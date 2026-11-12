"""Spoken decisions for the merchant agent: the decision layer under the voice layer.

The voice layer turns speech into text and calls DecisionRunner.run(text, source). Two commands exist:

  "Approve case 4"                    CHARGEBACK, PayPal allows only accept_claim REFUND. The signed policy lets the merchant agent refund
                                      up to USD 5.00 and asks for the owner's approval above USD 2.00; the owner's spoken command is that
                                      approval and is recorded. One accept_claim write with a stable PayPal-Request-Id, never a blind retry.
                                      PayPal's dispute record is then read until it shows RESOLVED, and the money movements are checked.
  "Don't pay case 9, send the proof"  INQUIRY, PayPal asks for PROOF_OF_FULFILLMENT. No money moves. Tracking goes on the order through the
                                      Add Tracking API, the proof goes through provide-evidence, and PayPal's record is read back.

Anything else is refused with a plain reason and no PayPal call is made. Every receipt written by a run carries the source of the command
(voice or typed, the speech to text provider and the voices) in its params, so each receipt shows how the command arrived.
Models never decide here: the parser, the policy file and the checks below do.
"""
from __future__ import annotations

import inspect
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from verdock_core import Refused
from verdock_core.outcome import MISMATCH, PENDING, UNKNOWN, VERIFIED, compare
from verdock_core.policy import decide

from .evidence import DisputeView, deadline
from .models import Adapter
from .paypal import GatewayError, Offline, ProviderRefused, amount as hard_cap
from .swarm import MerchantSwarm, money

POLICY = Path(__file__).resolve().parent.parent / "policy" / "voice-decisions.yaml"

# The two real sandbox disputes (read from PayPal and confirmed). Local runs mirror these same states.
CASES = {
    4: {"dispute": "PP-R-FEV-10198802", "order": "1VS14216L3023114Y", "capture": "1AK49667BE6254624", "stage": "CHARGEBACK"},
    9: {"dispute": "PP-R-ZZO-10198792", "order": "7HW302090M294554W", "capture": "4DR51838U3407841V", "stage": "INQUIRY"},
}
COMMAND_4, COMMAND_9 = "Approve case 4", "Don't pay case 9, send the proof"
CARRIER = "UPS"
TEST_LABEL = "sandbox test tracking value, not a real parcel"
SOURCE_KEYS = ("channel", "stt", "owner_voice", "reply_voice", "provider")


# ----- the command parser ------------------------------------------------------------------------------------------------------------

NUMBER_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "for": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9"}
CASE_REF = re.compile(r"\b(?:case|dispute|claim)\s*(?:number|no|num)?\s*(\d+|zero|one|two|three|four|five|six|seven|eight|nine"
                      r"|for(?!\s+(?:me|you|us|the|a|an|him|her|them|this|that|it|my|our)\b))\b")
APPROVE_WORDS = re.compile(r"\b(approve|approved|approving|accept|confirm|confirmed|proceed|go ahead|okay|ok|yes|pay|refund|settle)\b")
NEGATION = re.compile(r"\b(do not|never|cancel|stop|reject|decline|deny|no)\b")
NO_PAYMENT = re.compile(r"\b(do not|never|no)\s+(pay|payment|refund|refunds|money|offer|accept|settle|approve|send money|give money)\b")
PROOF_WORDS = re.compile(r"\b(proof|evidence|tracking|fulfilment|fulfillment|delivery)\b")
SEND_WORDS = re.compile(r"\b(send|submit|provide|give|share|attach|file|upload|add|show|use)\b")


def normalize(text):
    """Lower case, no punctuation, 'don't' as 'do not', number words as digits where a case number is meant."""
    text = str(text or "").lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"\bdon'?t\b", "do not", text)
    text = re.sub(r"\b(can|won|wouldn|shouldn|didn|isn)'?t\b", r"\1 not", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def cases_named(clean):
    return sorted({int(NUMBER_WORDS.get(m, m)) for m in CASE_REF.findall(clean)})


def parse_command(text):
    """(name, case, reason). name is 'approve_case_4', 'proof_case_9' or None with a plain reason. Reads only the words, never decides money."""
    clean = normalize(text)
    if not clean:
        return {"name": None, "case": None, "normalized": clean, "reason": "No command was heard. Nothing ran."}
    named = cases_named(clean)
    plain = "I act on two spoken commands only: Approve case 4, and Don't pay case 9, send the proof. Nothing ran."
    if not named:
        return {"name": None, "case": None, "normalized": clean, "reason": "No case number was heard. " + plain}
    if len(named) > 1:
        return {"name": None, "case": None, "normalized": clean, "reason": "Two cases were named in one command. Say one case at a time. Nothing ran."}
    case = named[0]
    rest = CASE_REF.sub(" ", clean)   # the words around the case reference ("case no 4" must not read as a no)
    if case == 4:
        if NEGATION.search(rest):
            return {"name": None, "case": 4, "normalized": clean, "reason": "Case 4 was heard with a no, so nothing was approved. Nothing ran."}
        if not APPROVE_WORDS.search(rest):
            return {"name": None, "case": 4, "normalized": clean, "reason": "Case 4 needs the word approve. Nothing ran."}
        return {"name": "approve_case_4", "case": 4, "normalized": clean, "reason": ""}
    if case == 9:
        if not NO_PAYMENT.search(rest):
            return {"name": None, "case": 9, "normalized": clean,
                    "reason": "Case 9 only has the command that pays nothing and sends the proof. Say: Don't pay case 9, send the proof. Nothing ran."}
        if not PROOF_WORDS.search(rest) or not SEND_WORDS.search(rest):
            return {"name": None, "case": 9, "normalized": clean, "reason": "Case 9 needs both: do not pay, and send the proof. Nothing ran."}
        return {"name": "proof_case_9", "case": 9, "normalized": clean, "reason": ""}
    return {"name": None, "case": case, "normalized": clean, "reason": f"Case {case} is not one of the two cases I act on. " + plain}


# ----- helpers -----------------------------------------------------------------------------------------------------------------------

class RealClock:
    def monotonic(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)

    def utcnow(self):
        return datetime.now(timezone.utc)


def clean(value, depth=0):
    """Receipt-safe data: no floats, bounded strings, plain containers."""
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return value[:2000]
    if depth > 6:
        return str(value)[:200]
    if isinstance(value, dict):
        return {str(k)[:80]: clean(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(v, depth + 1) for v in list(value)[:60]]
    return str(value)[:200]


def normalize_source(source):
    source = source if isinstance(source, dict) else {}
    result = {key: (clean(source.get(key)) if isinstance(source.get(key), (str, int, bool, type(None))) else str(source.get(key))[:200]) for key in SOURCE_KEYS}
    return result


def amount_text(record, key="dispute_amount"):
    value = (record.get(key) or {}).get("value")
    return value if isinstance(value, str) else None


def movements(record):
    """What PayPal's record shows about money: the fund movement lines, the refund id and amount, and any fee line, exactly as shown."""
    lines = [m for key in ("fund_movements", "money_movements") for m in (record.get(key) or []) if isinstance(m, dict)]
    transactions = (record.get("refund_details") or {}).get("transactions") or []
    refund = transactions[0] if transactions and isinstance(transactions[0], dict) else {}
    paid = refund.get("amount") or (record.get("dispute_outcome") or {}).get("amount_refunded") or {}
    fees = [m for m in lines if "FEE" in f"{m.get('reason', '')} {m.get('type', '')}".upper() or any("fee" in str(k).lower() for k in m)]

    def text(m):
        a = m.get("amount") or {}
        return " ".join(str(x) for x in (m.get("party"), m.get("type"), m.get("reason"), a.get("currency_code"), a.get("value")) if x)
    return {"lines": lines, "lines_text": [text(m) for m in lines], "refund_id": str(refund.get("id") or ""), "refund_amount": str(paid.get("value") or ""),
            "refund_currency": str(paid.get("currency_code") or ""), "fees": fees,
            "settled": [m for m in lines if m.get("reason") == "DISPUTE_SETTLEMENT"]}


def sandbox_tracking_number(order_id, n):
    """The number the batch gave its tracked orders: SYNTH1Z, the last six characters of the order id, the case number in two digits."""
    return f"SYNTH1Z{order_id[-6:].upper()}{n:02d}"


def trackers_of(order):
    return [t for unit in order.get("purchase_units", []) for t in ((unit.get("shipping") or {}).get("trackers") or [])]


def capture_of(order, fallback=""):
    for unit in order.get("purchase_units", []):
        for capture in ((unit.get("payments") or {}).get("captures") or []):
            if capture.get("id"):
                return capture["id"]
    return fallback


class Stop(Exception):
    """A run ends here with a plain reason. Nothing further is sent."""


class _Ctx:
    def __init__(self, source):
        self.source, self.steps, self.receipts = source, [], []
        self.approval, self.record, self.readback = {}, {}, ""


# ----- the runner --------------------------------------------------------------------------------------------------------------------

class DecisionRunner:
    poll_interval = 2.0       # seconds before the second read; it grows by half each time, to at most 10 seconds
    poll_max_reads = 12       # reads of PayPal's dispute record after the write, at most
    poll_total_wait = 60.0    # seconds of waiting in all, at most

    def __init__(self, gateway, log_dir, policy_path=None, clock=None, cases=None, agent="clearwake-merchant"):
        self.gateway, self.clock = gateway, clock or RealClock()
        self.cases = cases or CASES
        self.swarm = MerchantSwarm(gateway, log_dir, Adapter("scripted"), policy_path or POLICY, agent=agent, clock=self._utcnow)
        self.policy, self.log_dir = self.swarm.policy, Path(log_dir)
        self._busy = threading.Lock()

    # clocks: a test clock may offer only some of these
    def _utcnow(self):
        return self.clock.utcnow() if hasattr(self.clock, "utcnow") else datetime.now(timezone.utc)

    def _monotonic(self):
        return self.clock.monotonic() if hasattr(self.clock, "monotonic") else time.monotonic()

    def _sleep(self, seconds):
        (self.clock.sleep if hasattr(self.clock, "sleep") else time.sleep)(seconds)

    # recording
    def step(self, ctx, step, state, detail):
        ctx.steps.append({"step": step, "state": state, "detail": str(detail)})

    def receipt(self, ctx, step_id, action, params, success=True):
        line = self.swarm.receipt(step_id, action, {**clean(params), "source": ctx.source}, success)
        with open(self.swarm.receipts.path, "rb") as handle:
            number = handle.read().count(b"\n")
        ctx.receipts.append({"action_id": action, "line": number, "log": str(self.swarm.receipts.path), "step": step_id, "success": success})
        return line

    def result(self, ctx, ok, command, action, case, dispute, stopped=""):
        return {"ok": ok, "command": command, "action": action, "case": case, "dispute": dispute, "steps": ctx.steps, "receipts": ctx.receipts,
                "paypal_record": ctx.record, "approval": ctx.approval, "stopped_reason": stopped, "readback": ctx.readback}

    # entry point
    def run(self, command_text, source):
        source = normalize_source(source)
        ctx = _Ctx(source)
        if source["channel"] not in ("voice", "typed"):
            self.step(ctx, "source", "refused", "The source channel must be voice or typed. Nothing ran and nothing was recorded.")
            return self.result(ctx, False, str(command_text or "")[:200], "none", None, "", "The source channel must be voice or typed.")
        with self._busy:
            parsed = parse_command(command_text)
            self.step(ctx, "heard", "done", f"Heard: {str(command_text or '')[:200]!r} over {source['channel']}")
            if not parsed["name"]:
                self.step(ctx, "parse", "refused", parsed["reason"])
                self.receipt(ctx, "command:refused", "clearwake.voice.command_refused",
                             {"heard": str(command_text or "")[:300], "normalized": parsed["normalized"], "reason": parsed["reason"], "pay_pal_calls": 0}, False)
                return self.result(ctx, False, str(command_text or "")[:200], "none", parsed["case"], "", parsed["reason"])
            case = parsed["case"]
            canonical = COMMAND_4 if case == 4 else COMMAND_9
            ids = self.cases[case]
            self.step(ctx, "parse", "done", f"Understood as {canonical!r} for case {case} (dispute {ids['dispute']}).")
            self.receipt(ctx, f"{ids['dispute']}:command", "clearwake.voice.command", {"heard": str(command_text or "")[:300], "command": canonical, "case": case,
                         "dispute": ids["dispute"], "policy": str(self.swarm.policy_hash)}, True)
            if not self.swarm.invariants.lock(f"voice:{ids['dispute']}", "voice-decisions", ttl_seconds=300):
                self.step(ctx, "lock", "refused", "Another agent holds this dispute. No second action.")
                return self.result(ctx, False, canonical, "none", case, ids["dispute"], "Another agent holds this dispute.")
            try:
                return (self._case4 if case == 4 else self._case9)(ctx, canonical, ids)
            except Stop as stop:
                self.step(ctx, "stopped", "stopped", str(stop))
                self.receipt(ctx, f"{ids['dispute']}:stopped", "clearwake.decision.stopped", {"case": case, "reason": str(stop)}, False)
                return self.result(ctx, False, canonical, "stopped", case, ids["dispute"], str(stop))
            except Exception as error:   # never a traceback to the voice layer, and never text that could hold a secret
                reason = f"Stopped on an unexpected {type(error).__name__}. Nothing further was sent."
                self.step(ctx, "stopped", "stopped", reason)
                self.receipt(ctx, f"{ids['dispute']}:stopped", "clearwake.decision.stopped", {"case": case, "reason": reason}, False)
                return self.result(ctx, False, canonical, "stopped", case, ids["dispute"], reason)
            finally:
                self.swarm.invariants.unlock(f"voice:{ids['dispute']}", "voice-decisions")

    # reads (GET only)
    def read_dispute(self, dispute_id):
        try:
            return self.gateway.dispute(dispute_id), ""
        except Offline:
            return None, "offline: the request did not leave this network"
        except (ProviderRefused, GatewayError) as error:
            return None, str(error)[:200]

    def read_order(self, order_id):
        try:
            return self.gateway.order(order_id), ""
        except Offline:
            return None, "offline: the request did not leave this network"
        except (ProviderRefused, GatewayError) as error:
            return None, str(error)[:200]

    def refuse_by_policy(self, ctx, case, operation, amount_minor, why):
        """A refund or an offer asked for inside a command that forbids it: the policy and the command both refuse it, and it is receipted."""
        decision = decide(self.policy, operation, amount_minor, "USD")
        reason = f"{why} (policy: {decision.reason}, level {decision.level})" if not decision.allowed else why
        self.step(ctx, f"policy {operation}", "refused", f"{operation} is refused: {reason}.")
        self.receipt(ctx, f"{self.cases[case]['dispute']}:{operation}-refused", "clearwake.policy.refused",
                     {"case": case, "operation": operation, "amount_minor": amount_minor, "level": str(decision.level), "reason": reason, "called": False}, False)

    def poll(self, ctx, case, dispute_id, done, label, max_reads=None):
        """Read PayPal's dispute record until done(record) is true. Every read is recorded. Bounded in reads and in waiting."""
        max_reads = max_reads or self.poll_max_reads
        waited, interval, record = 0.0, self.poll_interval, None
        for n in range(1, max_reads + 1):
            record, error = self.read_dispute(dispute_id)
            if record is None:
                self.step(ctx, f"{label} read {n}", "unread", f"Could not read PayPal's record ({error}).")
                self.receipt(ctx, f"{dispute_id}:read:{n}", "clearwake.dispute.read", {"case": case, "n": n, "readable": False, "error": error}, False)
            else:
                self.step(ctx, f"{label} read {n}", "read", f"PayPal shows {record.get('status')} at stage {record.get('dispute_life_cycle_stage')}.")
                self.receipt(ctx, f"{dispute_id}:read:{n}", "clearwake.dispute.read", {"case": case, "n": n, "readable": True, "status": record.get("status") or "",
                             "stage": record.get("dispute_life_cycle_stage") or ""}, True)
                if done(record):
                    return record, n, waited
            if n == max_reads or waited + interval > self.poll_total_wait:
                return record, n, waited
            self._sleep(interval)
            waited += interval
            interval = min(interval * 1.5, 10.0)
        return record, max_reads, waited

    def approval_record(self, ctx, decision, operation, amount_minor, subject, rule, approval_id=""):
        record = {"approval_id": approval_id, "required": decision.needs_approval, "approved": True, "approver": "owner",
                  "approved_by": "owner, by voice" if ctx.source["channel"] == "voice" else "owner, typed", "operation": operation, "subject": subject, "amount_minor": amount_minor,
                  "currency": "USD", "limit_minor": decision.limit_minor if decision.limit_minor is not None else 0,
                  "limit": f"USD {money(decision.limit_minor or 0)}", "level": str(decision.level), "rule": rule, "source": ctx.source,
                  "policy_hash": self.swarm.policy_hash}
        ctx.approval = record
        return record

    # ----- case 4: accept the claim and refund -----------------------------------------------------------------------------------
    def _case4(self, ctx, canonical, ids):
        dispute_id, order_id = ids["dispute"], ids["order"]
        swarm, op_id = self.swarm, f"dispute:{dispute_id}"
        record, error = self.read_dispute(dispute_id)
        if record is None:
            raise Stop(f"PayPal's record could not be read ({error}). Nothing was sent.")
        view = DisputeView.from_paypal(record)
        options = record.get("allowed_response_options") or {}
        claim_types = (options.get("accept_claim") or {}).get("accept_claim_types") or []
        stage, status = record.get("dispute_life_cycle_stage"), record.get("status")
        self.step(ctx, "read dispute", "read", f"PayPal shows {status} at stage {stage}, reason {view.reason}, amount {record.get('dispute_amount', {}).get('currency_code')} "
                  f"{amount_text(record)}. Allowed answers: accept_claim {','.join(claim_types) or 'none'}; make_offer {'listed' if 'make_offer' in options else 'not allowed'}.")
        resolved = status == "RESOLVED"
        if not resolved:
            if stage != ids["stage"]:
                raise Stop(f"PayPal shows stage {stage}, not {ids['stage']}. Nothing was sent.")
            if "REFUND" not in claim_types:
                raise Stop("PayPal does not list accept_claim REFUND for this dispute now. Nothing was sent.")
        value = amount_text(record)
        try:
            hard_cap(value)
        except (ValueError, TypeError):
            raise Stop(f"The disputed amount {value} is outside the hard cap of USD 5.00. Nothing was sent.") from None
        minor = int(Decimal(value) * 100)
        currency = (record.get("dispute_amount") or {}).get("currency_code", "USD")
        order, order_error = self.read_order(order_id)
        trackers = trackers_of(order) if order else []
        if trackers:
            first = trackers[0]
            self.step(ctx, "read order", "read", f"Order {order_id} already carries tracking {str(first.get('id', '')).split('-', 1)[-1]} "
                      f"(PayPal tracker status {first.get('status')}). No tracking step is needed.")
        else:
            self.step(ctx, "read order", "read" if order else "unread", f"Order {order_id}: " + ("no tracking on it." if order else f"could not be read ({order_error})."))
        ctx.readback = (f"Approve case 4: accept the claim and refund {currency} {value} from the merchant on dispute {dispute_id}, a chargeback under review. "
                        "No offer is made, because PayPal does not allow one here. The buyer needs no step.")
        self.step(ctx, "read back", "done", ctx.readback)
        self.receipt(ctx, f"{dispute_id}:readback", "clearwake.decision.readback", {"case": 4, "readback": ctx.readback, "make_offer": "not allowed by PayPal, never called",
                     "buyer_step": "none needed"}, True)
        self.step(ctx, "buyer side", "info", "The buyer needs no accept step: the buyer opened the chargeback, and PayPal closes it when the seller accepts the claim.")
        self.refuse_by_policy(ctx, 4, "make_offer", minor, "PayPal does not list make_offer for a chargeback and this command never offers")
        decision = decide(self.policy, "accept_claim", minor, currency)
        if not decision.allowed:
            self.step(ctx, "policy accept_claim", "refused", f"Policy refused: {decision.reason}.")
            self.receipt(ctx, f"{dispute_id}:refused", "clearwake.policy.refused", {"case": 4, "operation": "accept_claim", "amount_minor": minor,
                         "reason": decision.reason, "level": str(decision.level)}, False)
            raise Stop(f"Policy refused accept_claim of {currency} {value}: {decision.reason}. Nothing was sent.")
        rule = (f"accept_claim at level {decision.level}: limit USD {money(decision.limit_minor or 0)}"
                + (f", owner approval above USD {money(self.policy['operations']['accept_claim'].get('approval_above_minor', 0))}" if decision.needs_approval else ""))
        self.step(ctx, "policy accept_claim", "done", f"Allowed: {decision.reason}. {rule}.")
        approval_id = ""
        if decision.needs_approval:
            approval_id = swarm.approvals.request("accept_claim", f"accept the claim and refund {value} {currency}", dispute_id, minor, currency, decision.limit_minor,
                                                  swarm.agent, 3600)
            self.receipt(ctx, f"{dispute_id}:approval-request", "clearwake.approval.requested", {"case": 4, "approval": approval_id, "amount_minor": minor,
                         "rule": rule}, True)
            swarm.approvals.approve(approval_id, "owner")
            self.approval_record(ctx, decision, "accept_claim", minor, dispute_id, rule, approval_id)
            self.receipt(ctx, f"{dispute_id}:approval", "clearwake.approval.granted", {"case": 4, "approval": approval_id, "approver": "owner",
                         "via": ctx.source["channel"], "limit_minor": decision.limit_minor, "level": str(decision.level), "rule": rule}, True)
            try:
                swarm.approvals.require(approval_id, "accept_claim", dispute_id, minor, currency)
            except Refused as refused:
                raise Stop(f"The approval was not valid ({refused}). Nothing was sent.") from None
            swarm.approvals.consume(approval_id)
            self.receipt(ctx, f"{dispute_id}:approval-used", "clearwake.approval.used", {"case": 4, "approval": approval_id, "approver": "owner"}, True)
            self.step(ctx, "approval", "done", f"Approved by the {ctx.approval['approved_by']}: {rule}. Recorded as approval {approval_id[:8]}.")
        else:
            self.approval_record(ctx, decision, "accept_claim", minor, dispute_id, rule)
            self.step(ctx, "approval", "done", "Within limits: no approval needed. The owner's spoken command is recorded.")
        # the one write
        prior = swarm.outcomes.latest(op_id)
        try:
            swarm.outcomes.expect(op_id, {"status": "RESOLVED", "amount": value, "currency": currency}, ["status", "amount", "currency"])
        except Refused:
            pass   # the expectation from an earlier run stays
        if resolved:
            self.step(ctx, "accept claim", "skipped", "PayPal already shows RESOLVED. Nothing is written again.")
        elif prior in (UNKNOWN, PENDING, VERIFIED):
            self.step(ctx, "accept claim", "skipped", f"This dispute was already answered once ({prior}). It is never written twice: PayPal's record is read instead.")
        else:
            self.send_accept(ctx, dispute_id, minor, value, currency, op_id, decision)
        # read PayPal's record until it shows RESOLVED, then check the money
        final, reads, waited = self.poll(ctx, 4, dispute_id, lambda r: r.get("status") == "RESOLVED", "dispute")
        return self.finish4(ctx, canonical, ids, final, reads, waited, value, currency, op_id)

    def send_accept(self, ctx, dispute_id, minor, value, currency, op_id, decision):
        swarm = self.swarm
        capture = self.cases[4]["capture"]
        gross = (self.read_dispute_gross(dispute_id) or minor)
        try:
            reservation = swarm.invariants.reserve(f"capture:{capture}", gross, minor, "chargeback-buyer", self._utcnow().date().isoformat(),
                                                   swarm.policy.get("caps", {}).get("per_customer_per_day_minor"))
        except Refused as refused:
            self.receipt(ctx, f"{dispute_id}:invariant", "clearwake.invariant.refused", {"case": 4, "reason": str(refused)[:200]}, False)
            raise Stop(f"Swarm limit: {refused}. Nothing was sent.") from None
        request_id = swarm.invariants.request_id(f"voice:accept_claim:{dispute_id}")
        note = f"Refund of {value} {currency} accepted by the merchant on the owner's spoken approval."
        params = inspect.signature(self.gateway.accept_claim).parameters
        extra = {k: v for k, v in (("claim_type", "REFUND"), ("claim_reason", "LOST_IN_MAIL")) if k in params}
        self.receipt(ctx, f"{dispute_id}:accept-claim:sending", "clearwake.dispute.accept_claim_sending", {"case": 4, "request_id": request_id,
                     "claim_type": "REFUND", "amount": value, "currency": currency, "retry": "never"}, True)
        try:
            self.gateway.accept_claim(dispute_id, note, value, currency, request_id, **extra)
        except Offline:
            swarm.invariants.release(reservation)
            self.step(ctx, "accept claim", "held", "Offline: the request did not leave this network. Nothing was sent.")
            raise Stop("Offline: the request did not leave this network. Nothing was sent and the same request id is kept.") from None
        except ProviderRefused as refused:
            swarm.invariants.release(reservation)
            self.receipt(ctx, f"{dispute_id}:accept-claim:refused", "clearwake.dispute.refused_by_paypal", {"case": 4, "reason": str(refused)[:200]}, False)
            raise Stop(f"{refused} Nothing was applied.") from None
        except GatewayError:
            # The write may have taken effect. The reservation and the request id stay. It is never sent again: PayPal's record is read.
            swarm.outcomes.record(op_id, UNKNOWN)
            swarm.held[op_id] = reservation
            self.step(ctx, "accept claim", "unknown", "The answer was lost. It may have taken effect, so it is not sent again: PayPal's record is read instead.")
            self.receipt(ctx, f"{dispute_id}:accept-claim:unknown", "clearwake.dispute.accept_claim_unknown", {"case": 4, "request_id": request_id,
                         "resent": False}, False)
            return
        swarm.invariants.commit(reservation)
        swarm.outcomes.record(op_id, PENDING, {"sent": "accept_claim", "request_id": request_id})
        self.step(ctx, "accept claim", "done", f"accept_claim REFUND sent once for {currency} {value} with PayPal-Request-Id {request_id}. No retry.")
        self.receipt(ctx, f"{dispute_id}:accept-claim", "clearwake.dispute.accept_claim_sent", {"case": 4, "request_id": request_id, "claim_type": "REFUND",
                     "amount": value, "currency": currency, "writes": 1}, True)

    def read_dispute_gross(self, dispute_id):
        """The capture total from the dispute's own transaction, in minor units, for the capture cap."""
        record, _ = self.read_dispute(dispute_id)
        try:
            return int(Decimal(record["disputed_transactions"][0]["gross_amount"]["value"]) * 100)
        except (TypeError, KeyError, IndexError, InvalidOperation):
            return None

    def finish4(self, ctx, canonical, ids, final, reads, waited, value, currency, op_id):
        dispute_id = ids["dispute"]
        status = (final or {}).get("status")
        outcome = ((final or {}).get("dispute_outcome") or {}).get("outcome_code", "")
        moves = movements(final or {})
        refund_read = {}
        if moves["refund_id"]:
            try:
                refund_read = self.gateway.refund_record(moves["refund_id"])
            except (Offline, ProviderRefused, GatewayError, ValueError) as error:
                refund_read = {"unread": str(error)[:120]}
        ctx.record = {"dispute_id": dispute_id, "status": status or "", "stage": (final or {}).get("dispute_life_cycle_stage") or "", "outcome": outcome,
                      "reads": reads, "waited_seconds": int(waited), "refund_id": moves["refund_id"], "refund_amount": moves["refund_amount"],
                      "refund_currency": moves["refund_currency"], "refund_record": {k: refund_read.get(k) for k in ("status", "amount") if k in refund_read} or refund_read,
                      "fund_movements": moves["lines_text"], "fees": moves["fees"]}
        if final is None or status != "RESOLVED":
            state = UNKNOWN if final is None else PENDING
            reason = (f"PayPal still shows {status or 'nothing readable'} after {reads} reads over {int(waited)} seconds. The claim was not sent again."
                      if final is not None else f"PayPal's record could not be read in {reads} tries. The claim was not sent again.")
            self.step(ctx, "check", state.lower(), reason)
            self.receipt(ctx, f"{dispute_id}:check", "clearwake.dispute.checked", {"case": 4, "state": state, "status": status or "", "reads": reads}, False)
            raise Stop(reason)
        fee_text = "; ".join(json.dumps(f, sort_keys=True) for f in moves["fees"]) or "no fee line shown by PayPal"
        self.step(ctx, "money", "read", f"Refund id {moves['refund_id'] or 'not shown'}, amount {moves['refund_currency']} {moves['refund_amount'] or 'not shown'}. "
                  f"Fund movements: {'; '.join(moves['lines_text']) or 'none shown'}. Fee lines: {fee_text}.")
        observed = {"status": status, "amount": moves["refund_amount"], "currency": moves["refund_currency"] or currency}
        state = compare({"status": "RESOLVED", "amount": value, "currency": currency}, observed, ["status", "amount", "currency"])
        if state == VERIFIED and refund_read.get("status") not in (None, "COMPLETED", "PENDING") and "unread" not in refund_read:
            state = MISMATCH
        if state == VERIFIED and "SELLER" in outcome.upper():
            state = MISMATCH
        try:
            self.swarm.outcomes.record(op_id, state, observed)
        except Refused:
            state = UNKNOWN
        ctx.record["state"] = state
        self.step(ctx, "check", state.lower(), f"PayPal shows {status} ({outcome or 'no outcome code'}) and a refund of {observed['currency']} {observed['amount'] or 'not shown'}: "
                  + {VERIFIED: "this matches the approved refund.", MISMATCH: "this does not match the approved refund.",
                     UNKNOWN: "the refund amount is not shown, so it is not counted.", PENDING: "pending."}[state])
        self.receipt(ctx, f"{dispute_id}:check", "clearwake.dispute.checked", {"case": 4, "state": state, "status": status, "outcome": outcome,
                     "refund_id": moves["refund_id"], "refund_amount": moves["refund_amount"], "refund_currency": moves["refund_currency"],
                     "fund_movements": moves["lines_text"], "fees": moves["fees"], "reads": reads}, state == VERIFIED)
        if state != VERIFIED:
            raise Stop(f"PayPal's record shows {status} but the refund does not check out ({state}).")
        return self.result(ctx, True, canonical, "accept_claim REFUND", 4, dispute_id)

    # ----- case 9: no money, add tracking, send the proof ------------------------------------------------------------------------
    def _case9(self, ctx, canonical, ids):
        dispute_id, order_id = ids["dispute"], ids["order"]
        swarm, op_id = self.swarm, f"dispute:{dispute_id}"
        record, error = self.read_dispute(dispute_id)
        if record is None:
            raise Stop(f"PayPal's record could not be read ({error}). Nothing was sent.")
        view = DisputeView.from_paypal(record)
        options = record.get("allowed_response_options") or {}
        stage, status = record.get("dispute_life_cycle_stage"), record.get("status")
        requested = any(e.get("evidence_type") == "PROOF_OF_FULFILLMENT" and e.get("source") == "REQUESTED_FROM_SELLER" for e in record.get("evidences", []) or [])
        clock = deadline(view, self._utcnow())
        self.step(ctx, "read dispute", "read", f"PayPal shows {status} at stage {stage}, reason {view.reason}, amount {(record.get('dispute_amount') or {}).get('currency_code')} "
                  f"{amount_text(record)}, seller response due {record.get('seller_response_due_date') or 'not given'} ({clock['state']}). PayPal "
                  f"{'requests' if requested else 'does not list a request for'} PROOF_OF_FULFILLMENT. Offered to the seller, not used: "
                  f"{', '.join(k for k in ('accept_claim', 'make_offer') if k in options) or 'nothing'}.")
        if stage != ids["stage"] or status not in ("WAITING_FOR_SELLER_RESPONSE", "OPEN", "UNDER_REVIEW", "WAITING_FOR_BUYER_RESPONSE"):
            raise Stop(f"PayPal shows {status} at stage {stage}, which does not take the proof now. Nothing was sent.")
        if clock["state"] == "lapsed":
            raise Stop("The seller response date has passed. A person decides. Nothing was sent.")
        order, order_error = self.read_order(order_id)
        if order is None:
            raise Stop(f"The order could not be read ({order_error}). Nothing was sent.")
        capture = capture_of(order, ids["capture"])
        existing = trackers_of(order)
        number = str(existing[0].get("id", "")).split("-", 1)[-1] if existing else sandbox_tracking_number(order_id, 9)
        how = "already on the PayPal order" if existing else "added through the Add Tracking API"
        ctx.readback = (f"Don't pay case 9, send the proof: no money moves. Tracking {number} with {CARRIER} ({TEST_LABEL}) goes on order {order_id}, then the proof of "
                        f"fulfillment goes to dispute {dispute_id}, then PayPal's record is read back. No refund and no offer.")
        self.step(ctx, "read order", "read", f"Order {order_id} shows {len(existing)} tracker(s); capture {capture}.")
        self.step(ctx, "read back", "done", ctx.readback)
        self.receipt(ctx, f"{dispute_id}:readback", "clearwake.decision.readback", {"case": 9, "readback": ctx.readback, "money_moves": False,
                     "tracking_number": number, "tracking_label": TEST_LABEL}, True)
        for operation in ("refund", "make_offer", "accept_claim"):
            self.refuse_by_policy(ctx, 9, operation, int(Decimal(amount_text(record) or "0") * 100), "no money moves in this command")
        tracking_rule = decide(swarm.policy, "add_tracking", 0)
        evidence_rule = decide(swarm.policy, "provide_evidence", 0)
        for name, rule in (("add_tracking", tracking_rule), ("provide_evidence", evidence_rule)):
            if not rule.allowed:
                self.receipt(ctx, f"{dispute_id}:refused", "clearwake.policy.refused", {"case": 9, "operation": name, "reason": rule.reason}, False)
                raise Stop(f"Policy does not allow {name} ({rule.reason}). Nothing was sent.")
        rule_text = (f"add_tracking and provide_evidence at level {evidence_rule.level}, no money; refund, make_offer and accept_claim refused in this command")
        self.approval_record(ctx, evidence_rule, "provide_evidence", 0, dispute_id, rule_text)
        ctx.approval["required"] = False
        self.step(ctx, "policy", "done", f"Allowed: {rule_text}. The owner's spoken command is recorded as the approval.")
        self.receipt(ctx, f"{dispute_id}:approval", "clearwake.approval.recorded", {"case": 9, "approver": "owner", "via": ctx.source["channel"], "required": False,
                     "level": str(evidence_rule.level), "limit_minor": 0, "rule": rule_text}, True)
        seen_tracker = any(str(t.get("id", "")).endswith("-" + number) for t in existing)
        # tracking
        if seen_tracker:
            self.step(ctx, "tracking", "skipped", f"Tracking {number} is already on the order. Nothing is added twice.")
        else:
            request_id = swarm.invariants.request_id(f"voice:add_tracking:{order_id}")
            try:
                self.gateway.add_tracking(order_id, capture, number, CARRIER, request_id)
            except Offline:
                raise Stop("Offline: the request did not leave this network. Nothing was sent.") from None
            except ProviderRefused as refused:
                self.receipt(ctx, f"{order_id}:tracking-refused", "clearwake.dispute.refused_by_paypal", {"case": 9, "action": "add_tracking", "reason": str(refused)[:200]}, False)
                raise Stop(f"{refused} Nothing was applied.") from None
            except GatewayError:
                self.step(ctx, "tracking", "unknown", "The answer was lost. It is not sent again: the order is read instead.")
                self.receipt(ctx, f"{order_id}:tracking-unknown", "clearwake.merchant.tracking_unknown", {"case": 9, "request_id": request_id, "resent": False}, False)
            else:
                self.step(ctx, "tracking", "done", f"Add Tracking sent once: {number} with {CARRIER}, a {TEST_LABEL}.")
        after, _ = self.read_order(order_id)
        placed = [t for t in trackers_of(after or {}) if str(t.get("id", "")).endswith("-" + number)]
        if not placed:
            raise Stop("PayPal's order does not show the tracking yet, so the proof is not sent.")
        if not seen_tracker:
            self.receipt(ctx, f"{order_id}:tracking", "clearwake.merchant.tracking_added", {"case": 9, "order": order_id, "capture": capture, "tracking_number": number,
                         "carrier": CARRIER, "label": TEST_LABEL, "paypal_tracker": placed[0].get("id"), "paypal_tracker_status": placed[0].get("status") or ""}, True)
        self.step(ctx, "tracking check", "read", f"PayPal's order shows tracker {placed[0].get('id')} with status {placed[0].get('status')} ({how}).")
        # evidence
        def sent(rec):
            return any(e.get("evidence_type") == "PROOF_OF_FULFILLMENT" and e.get("source") == "SUBMITTED_BY_SELLER" and number in json.dumps(e)
                       for e in (rec or {}).get("evidences", []) or [])
        if sent(record):
            self.step(ctx, "provide evidence", "skipped", "PayPal already holds this proof. Nothing is sent twice.")
        else:
            evidences = [{"evidence_type": "PROOF_OF_FULFILLMENT", "evidence_info": {"tracking_info": [{"carrier_name": CARRIER, "tracking_number": number}]},
                          "notes": (f"Proof of fulfillment: tracking number {number} with {CARRIER} is on PayPal order {order_id}. "
                                    f"This is a {TEST_LABEL}, used in the PayPal sandbox.")}]
            request_id = swarm.invariants.request_id(f"voice:provide_evidence:{dispute_id}")
            try:
                self.gateway.provide_evidence(dispute_id, evidences, request_id)
            except Offline:
                raise Stop("Offline: the request did not leave this network. The proof was not sent.") from None
            except ProviderRefused as refused:
                self.receipt(ctx, f"{dispute_id}:evidence-refused", "clearwake.dispute.refused_by_paypal", {"case": 9, "action": "provide_evidence",
                             "reason": str(refused)[:200]}, False)
                raise Stop(f"{refused} Nothing was applied.") from None
            except GatewayError:
                swarm.outcomes.record(op_id, UNKNOWN)
                self.step(ctx, "provide evidence", "unknown", "The answer was lost. The proof is not sent again: PayPal's record is read instead.")
                self.receipt(ctx, f"{dispute_id}:evidence-unknown", "clearwake.dispute.evidence_unknown", {"case": 9, "request_id": request_id, "resent": False}, False)
            else:
                self.step(ctx, "provide evidence", "done", f"PROOF_OF_FULFILLMENT sent once with tracking {number} and a plain note (PayPal-Request-Id {request_id}). No retry.")
                self.receipt(ctx, f"{dispute_id}:evidence", "clearwake.dispute.evidence_sent", {"case": 9, "request_id": request_id, "evidence_type": "PROOF_OF_FULFILLMENT",
                             "tracking_number": number, "carrier": CARRIER, "label": TEST_LABEL, "writes": 1}, True)
        final, reads, waited = self.poll(ctx, 9, dispute_id, sent, "dispute", max_reads=min(self.poll_max_reads, 4))
        return self.finish9(ctx, canonical, ids, final, reads, waited, number, sent, op_id, record)

    def finish9(self, ctx, canonical, ids, final, reads, waited, number, sent, op_id, before):
        dispute_id = ids["dispute"]
        if final is None:
            raise Stop(f"PayPal's record could not be read in {reads} tries. Nothing further was sent.")
        received = sent(final)
        moves = movements(final)
        moved = bool(moves["refund_id"]) or bool(moves["settled"]) or bool((final.get("dispute_outcome") or {}).get("amount_refunded"))
        held = [e for e in final.get("evidences", []) or [] if e.get("source") == "SUBMITTED_BY_SELLER"]
        ctx.record = {"dispute_id": dispute_id, "status": final.get("status") or "", "stage": final.get("dispute_life_cycle_stage") or "",
                      "outcome": (final.get("dispute_outcome") or {}).get("outcome_code", ""), "evidence_received": received, "tracking_number": number,
                      "evidence_held": [{"evidence_type": e.get("evidence_type"), "source": e.get("source")} for e in held], "reads": reads,
                      "money_moved": moved, "fund_movements": moves["lines_text"]}
        state = VERIFIED if received and not moved else MISMATCH if moved else UNKNOWN
        if state == VERIFIED:
            self.swarm.outcomes.record(op_id, PENDING, {"proof": "seen"})
        ctx.record["state"] = state
        self.step(ctx, "check", state.lower(), f"PayPal shows {final.get('status')} at stage {final.get('dispute_life_cycle_stage')}; the proof "
                  f"{'is on its record' if received else 'is not on its record yet'}; money moved: {'yes' if moved else 'no'}.")
        self.receipt(ctx, f"{dispute_id}:check", "clearwake.dispute.checked", {"case": 9, "state": state, "status": final.get("status") or "",
                     "stage": final.get("dispute_life_cycle_stage") or "", "evidence_received": received, "money_moved": moved, "reads": reads}, state == VERIFIED)
        if state != VERIFIED:
            raise Stop("PayPal's record does not show the proof yet. It was not sent again." if not moved else "Money moved, which this command never allows.")
        return self.result(ctx, True, canonical, "add tracking and provide evidence", 9, dispute_id)


# ----- the two states, held in a local provider ------------------------------------------------------------------------------------

def spoken_reply(result):
    """The sentence Clearwake speaks after a decision: short, plain, only what PayPal's record showed. At most 400 characters."""
    if not result.get("ok"):
        why = str(result.get("stopped_reason") or "I cannot do that").strip().rstrip(".")
        if "still shows" in why:     # the write went once and PayPal has not caught up: say so, and that nothing was resent
            return f"The refund was sent once. {why}. I read PayPal's record again, I never send it twice."[:400]
        return f"I did not run that. {why}. Nothing was sent to PayPal."[:400]
    record = result.get("paypal_record") or {}
    shows = f"PayPal reads {record.get('status', 'no status')} at {record.get('stage', 'no stage')}"
    if result.get("case") == 4:
        refund = record.get("refund_amount") or record.get("amount") or "5.00"
        return f"Approved by the owner. One refund of {refund} dollars was accepted, no offer was sent. {shows}."[:400]
    if result.get("case") == 9:
        return f"No money moves. Tracking and proof are sent. {shows}."[:400]
    return f"Done. {shows}."[:400]


class VoiceDecisionRunner(DecisionRunner):
    """The runner the console attaches: same decisions, plus the sentence the voice speaks."""

    def run(self, command_text, source):
        if not parse_command(command_text)["name"]:
            return {"ok": False, "case": None, "text": ""}     # not one of the two commands: the plain words rules flow answers it
        result = super().run(command_text, source)
        return {**result, "text": spoken_reply(result)}


def mirror_local(gateway, now=None, fee_lines=(), resolve_after_reads=2):
    """Seed a LocalGateway with the two real states: CASE 4 (chargeback under review, accept_claim REFUND only, tracking on the order)
    and CASE 9 (inquiry waiting for the seller, PROOF_OF_FULFILLMENT requested, an order with no tracking, offer allowed)."""
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat().replace("+00:00", "Z")
    c4, c9 = CASES[4], CASES[9]
    gateway.seed_order(c4["order"], c4["capture"], "9.00", trackers=("SYNTH1Z23114Y04",))
    gateway.seed_order(c9["order"], c9["capture"], "9.00")

    def transaction(case, buyer):
        return {"buyer_transaction_id": buyer, "seller_transaction_id": case["capture"], "transaction_status": "HELD",
                "gross_amount": {"currency_code": "USD", "value": "9.00"}, "items": [{"item_id": "notebook-a5", "item_quantity": "1",
                "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "item_type": "PRODUCT"}]}
    gateway.seed_dispute({
        "dispute_id": c4["dispute"], "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "status": "UNDER_REVIEW", "dispute_state": "UNDER_PAYPAL_REVIEW",
        "dispute_life_cycle_stage": "CHARGEBACK", "dispute_amount": {"currency_code": "USD", "value": "5.00"},
        "disputed_transactions": [transaction(c4, "6UN613850R1361927")],
        "fund_movements": [{"party": "SELLER", "amount": {"currency_code": "USD", "value": "5.00"}, "type": "DEBIT", "reason": "HOLD_PLACED"}],
        "evidences": [{"evidence_type": "CREATE", "source": "SUBMITTED_BY_BUYER", "dispute_life_cycle_stage": "INQUIRY"}],
        "offer": {"buyer_requested_amount": {"currency_code": "USD", "value": "5.00"}},
        "refund_details": {"allowed_refund_amount": {"currency_code": "USD", "value": "5.00"}},
        "allowed_response_options": {"accept_claim": {"accept_claim_types": ["REFUND"]}},
        "_resolve_after_reads": resolve_after_reads, "_fee_lines": list(fee_lines)})
    gateway.seed_dispute({
        "dispute_id": c9["dispute"], "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "status": "WAITING_FOR_SELLER_RESPONSE", "dispute_state": "REQUIRED_ACTION",
        "dispute_life_cycle_stage": "INQUIRY", "dispute_amount": {"currency_code": "USD", "value": "9.00"},
        "disputed_transactions": [transaction(c9, "4AF56699NH6668541")],
        "fund_movements": [{"party": "SELLER", "amount": {"currency_code": "USD", "value": "8.23"}, "type": "DEBIT", "reason": "HOLD_PLACED"}],
        "messages": [{"posted_by": "BUYER", "content": "Order not received. Request refund for the affected amount."}],
        "evidences": [{"evidence_type": "CREATE", "source": "SUBMITTED_BY_BUYER", "dispute_life_cycle_stage": "INQUIRY"},
                      {"evidence_type": "PROOF_OF_FULFILLMENT", "source": "REQUESTED_FROM_SELLER", "date": stamp}],
        "seller_response_due_date": (now + timedelta(days=19)).isoformat().replace("+00:00", "Z"),
        "offer": {"buyer_requested_amount": {"currency_code": "USD", "value": "9.00"}},
        "refund_details": {"allowed_refund_amount": {"currency_code": "USD", "value": "9.00"}},
        "allowed_response_options": {"accept_claim": {"accept_claim_types": ["PARTIAL_REFUND", "REFUND"]}, "make_offer": {"offer_types": ["REFUND"]}}})
    return gateway
