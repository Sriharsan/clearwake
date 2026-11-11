"""A drop-in guard between an agent and PayPal's Agent Toolkit tools.

    from clearwake.toolkit_guard import guard
    api = guard(paypal_tools, reader=paypal_reader)         # wrap the tools the agent already calls
    api.accept_dispute_claim(dispute_id, note)               # same call, now guarded

What it does, for the one money returning tool the toolkit documents (accept_dispute_claim):

  1. Reads PayPal's record of the dispute first. The amount comes from that record and the signed policy, never from the agent's
     arguments and never from message text. An amount or target the agent passes that differs is ignored and receipted.
  2. Refuses an amount above the policy limit and holds it for a person. Between the approval threshold and the limit it asks a person.
  3. Gives every money move one request id derived from the hash of its payload (tool, target, amount, currency), keeps a durable
     ledger, and reads PayPal's record before any retry. A retry after a lost response, or the same case delivered again, sends nothing
     when the record shows the claim already accepted.
  4. Reads buyer and merchant text with the same order-giving pattern check Clearwake uses (clearwake/guard.py). A hit is receipted;
     it changes nothing, because nothing in the text is ever used as an amount or a target.
  5. Writes a signed, hash chained receipt for every call, in the same format as Clearwake's own (verdock_core.receipts), so the run
     verifies offline.

It reuses the rules of clearwake/swarm.py: verdock_core policy (decide), invariants (caps, locks), outcome log, approvals and receipts,
and clearwake.guard for the text check. It is not a PayPal product, and it covers what docs/TOOLKIT_FAILURE_CASES.md documents.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import threading
import uuid

from verdock_core import Refused
from verdock_core.approvals import ApprovalStore
from verdock_core.invariants import Invariants
from verdock_core.outcome import MISMATCH, PENDING, UNKNOWN, VERIFIED, OutcomeLog
from verdock_core.policy import decide, load_policy, policy_hash
from verdock_core.receipts import ReceiptLog, create_seed, load_seed, verify_log

from . import guard as checks
from .paypal import Offline, ProviderRefused
from .swarm import POLICY, money

# Toolkit tool name -> the policy operation that limits it. Only the money returning tool the failure page documents.
MONEY_MOVING = {"accept_dispute_claim": "accept_claim"}
HELD, REFUSED, AWAITING, DONE_ELSEWHERE, BUSY, OFFLINE = ("held for a person", "refused", "awaiting approval", "already resolved", "busy", "held, offline")
SAFE_NOTE = "Accepted within the merchant's limit."


@dataclass
class Outcome:
    """What one guarded call did. sent is True only when this call sent a request to PayPal."""
    state: str
    detail: str
    sent: bool = False
    amount_minor: int = 0
    currency: str = "USD"
    request_id: str = ""
    approval_id: str | None = None
    signals: list = field(default_factory=list)
    receipt: str = ""

    def __str__(self):
        return f"{self.state}: {self.detail}"


def payload_hash(tool, target, amount_minor, currency):
    """The identity of a money move: tool, target, amount, currency. Free text (the note) is not part of it, so a retry whose
    wording the model changed is still the same move."""
    body = json.dumps({"tool": tool, "target": target, "amount_minor": amount_minor, "currency": currency}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def request_id_for(digest):
    """One stable PayPal-Request-Id per payload hash: the same on every retry, in every process."""
    return str(uuid.UUID(digest[:32]))


def _minor(value):
    """Minor units of a PayPal amount ("5.00" or {"value": "5.00", ...}); -1 when it cannot be read."""
    try:
        text = value.get("value") if isinstance(value, dict) else value
        return checks.minor(str(text).strip()) if text not in (None, "") else -1
    except (ValueError, AttributeError):
        return -1


def _accepts(function, name):
    try:
        params = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


class ToolkitGuard:
    def __init__(self, tool, policy=None, receipts=None, reader=None, data_dir=None, agent="clearwake-toolkit-guard", clock=None):
        self.tool, self.agent = tool, agent
        data = Path(data_dir or ".clearwake-toolkit-guard"); data.mkdir(parents=True, exist_ok=True)
        self.policy = policy if isinstance(policy, dict) else load_policy(policy or POLICY)
        self.policy_hash = policy_hash(self.policy)
        self.approvals = ApprovalStore(str(data / "approvals.sqlite3"))
        self.invariants = Invariants(str(data / "invariants.sqlite3"))
        self.outcomes = OutcomeLog(str(data / "outcomes.sqlite3"))
        if isinstance(receipts, ReceiptLog):
            self.receipts = receipts
        else:
            path = Path(receipts) if receipts else data / "toolkit-receipts.ndjson"
            seed = path.with_suffix(".seed")
            if not seed.exists():
                create_seed(str(seed))
            self.receipts = ReceiptLog(str(path), load_seed(str(seed)))
        self.public_key = self.receipts.public_key
        self.clock = clock
        self._read, self._read_capture = self._reader(reader)
        self._reservations = {}
        self._writer = threading.Lock()

    # reading PayPal's record -------------------------------------------------------------------------------------------------
    def _reader(self, reader):
        source = reader if reader is not None else self.tool
        if hasattr(source, "dispute"):
            return source.dispute, getattr(source, "capture", None)
        if reader is not None and callable(reader):
            return reader, None
        run = getattr(self.tool, "run", None) or (self.tool if callable(self.tool) else None)
        if run is None:
            raise TypeError("Give guard() a reader: a function dispute_id -> PayPal's dispute record, or an object with .dispute().")

        def read(dispute_id):   # the toolkit's own read tool; the reply may be JSON text
            out = run("get_dispute", {"dispute_id": dispute_id})
            return json.loads(out) if isinstance(out, (str, bytes)) else out
        return read, None

    # receipts ---------------------------------------------------------------------------------------------------------------
    def receipt(self, step, action, params, success):
        with self._writer:   # one writer per chain
            return self.receipts.append(step, action, {**params, "policy_hash": self.policy_hash}, success, actor={"agent": self.agent, "user": "merchant"})

    def verify(self):
        """Verify this run's receipt log offline against its own public key (the trust anchor)."""
        return verify_log(self.receipts.path, self.public_key)

    # the guarded tool -------------------------------------------------------------------------------------------------------
    def accept_dispute_claim(self, dispute_id, note="", approval_id=None, customer_id=None, **claimed):
        """Guarded accept_dispute_claim. Any other keyword (amount, limit, ...) is what the agent believes; it is receipted and ignored."""
        tool = "accept_dispute_claim"
        step = f"toolkit:{dispute_id}"
        try:
            record = self._read(dispute_id)
            if not isinstance(record, dict) or record.get("dispute_id", dispute_id) != dispute_id:
                raise ValueError("record does not belong to this target")
            amount_minor = _minor(record.get("dispute_amount"))
            currency = (record.get("dispute_amount") or {}).get("currency_code", "")
            if amount_minor < 0 or not currency:
                raise ValueError("no readable amount")
        except Exception as error:
            return self._end(step, tool, dispute_id, 0, "USD", "", REFUSED, f"Could not read PayPal's record ({type(error).__name__}). Nothing was sent.", [], -1, False)
        digest = payload_hash(tool, dispute_id, amount_minor, currency)
        request_id, op = request_id_for(digest), f"toolkit:{digest}"
        said = _minor(claimed.get("amount"))
        text = " ".join([str(note or "")] + [m.get("content", "") for m in record.get("messages", []) or [] if isinstance(m, dict)])[:2000]
        signals = checks.injection_signals(text)
        if signals:   # data, not orders: receipted, and nothing else changes
            self.receipt(f"{step}:injection", "clearwake.model.injection_attempt", {"dispute": dispute_id, "signals": signals, "text_sha256": checks.digest(text),
                         "effect": "none: the amount comes from PayPal's record and the policy"}, True)
        if not self.invariants.lock(op, self.agent, ttl_seconds=300):
            return self._end(step, tool, dispute_id, amount_minor, currency, request_id, BUSY, "Another call holds this move. Nothing was sent.", signals, said, False)
        try:
            return self._guarded(step, tool, dispute_id, note, record, amount_minor, currency, digest, request_id, op, said, signals, approval_id, customer_id)
        finally:
            self.invariants.unlock(op, self.agent)

    def _guarded(self, step, tool, dispute_id, note, record, amount_minor, currency, digest, request_id, op, said, signals, approval_id, customer_id):
        end = lambda state, detail, sent=False, approval=None: self._end(step, tool, dispute_id, amount_minor, currency, request_id, state, detail, signals, said, sent, approval)
        history = self.outcomes.history(op)
        latest = history[-1]["state"] if history else None
        if record.get("status") == "RESOLVED":   # PayPal's record says it is applied: nothing to send, whoever applied it
            if latest in (UNKNOWN, PENDING):
                self.outcomes.record(op, VERIFIED, {"status": "RESOLVED"})
                self._settle_reservation(op, history, commit=True)
                return end(VERIFIED, "PayPal's record shows the claim accepted. Nothing was sent again.")
            if latest == VERIFIED:
                return end(VERIFIED, "Already done: PayPal's record shows the claim accepted. Nothing was sent again.")
            return end(DONE_ELSEWHERE, "PayPal's record already shows this dispute resolved. Nothing was sent.")
        if latest in (VERIFIED, PENDING, MISMATCH):   # our ledger says it was sent and PayPal's record does not agree: a person looks
            return end(HELD, f"The ledger shows this move sent, PayPal's record shows {record.get('status')}. A person checks. Nothing was sent.")
        retry = latest == UNKNOWN   # read PayPal's record first (done above); it shows the earlier call did not apply, so the same request id may go again
        decision = decide(self.policy, MONEY_MOVING[tool], amount_minor, currency)
        if not decision.allowed:
            self.receipt(f"{step}:refused", "clearwake.policy.refused", {"dispute": dispute_id, "amount_minor": amount_minor, "limit_minor": decision.limit_minor or 0, "reason": decision.reason}, False)
            self.receipt(f"{step}:held", "clearwake.guard.held_for_person", {"dispute": dispute_id, "amount_minor": amount_minor, "sent_anything": False}, True)
            limit = f" (limit {money(decision.limit_minor)} {currency})" if decision.limit_minor is not None else ""
            return end(HELD, f"Policy refused: {decision.reason}{limit}. Held for a person; nothing was sent to PayPal.")
        if decision.needs_approval and not retry:   # a retry repeats the move a person already approved (same payload hash)
            if approval_id is None:
                approval_id = self.approvals.request(MONEY_MOVING[tool], f"accept claim and refund {money(amount_minor)} {currency}", dispute_id, amount_minor, currency,
                                                     decision.limit_minor, self.agent, 3600)
                self.receipt(f"{step}:approval-request", "clearwake.approval.requested", {"dispute": dispute_id, "approval": approval_id, "amount_minor": amount_minor}, True)
                return end(AWAITING, "Above the approval threshold. A person decides; nothing was sent.", approval=approval_id)
            try:
                approved = self.approvals.require(approval_id, MONEY_MOVING[tool], dispute_id, amount_minor, currency)
            except Refused as error:
                return end(REFUSED, f"Approval not valid: {error}", approval=approval_id)
            self.approvals.consume(approval_id)
            self.receipt(f"{step}:approval-used", "clearwake.approval.used", {"dispute": dispute_id, "approval": approval_id, "approver": approved["approver"]}, True)
        reservation = None
        if not retry:   # a retry keeps the reservation of the first attempt
            try:
                reservation = self._reserve(record, amount_minor, currency, customer_id, dispute_id)
            except Refused as error:
                self.receipt(f"{step}:invariant", "clearwake.invariant.refused", {"dispute": dispute_id, "amount_minor": amount_minor, "reason": str(error)[:200]}, False)
                return end(REFUSED, f"Swarm limit: {error}. Nothing was sent.")
        try:
            self.outcomes.expect(op, {"status": "RESOLVED"}, ["status"])
        except Refused:
            pass   # set once per move; a retry reuses it
        send_note = SAFE_NOTE if signals else (note or SAFE_NOTE)
        try:
            self._send(tool, dispute_id, send_note, request_id)
        except Offline:
            self._release(reservation)
            return end(OFFLINE, "Network down. Nothing was sent; it can be called again.")
        except ProviderRefused as refused:
            self._release(reservation)
            self.receipt(f"{step}:refused-by-paypal", "clearwake.dispute.refused_by_paypal", {"dispute": dispute_id, "reason": str(refused)[:200]}, False)
            return end("refused by PayPal", f"{refused} Nothing was applied.")
        except Exception as error:   # the request may have taken effect: keep the ledger and the request id, then raise it to the agent as before
            observed = {"reservation": reservation} if reservation else (history[-1]["observed"] if history and history[-1]["observed"] else None)
            self.outcomes.record(op, UNKNOWN, observed)
            if reservation:
                self._reservations[op] = reservation
            self.receipt(f"{step}:unknown", "clearwake.refund.unknown", {"dispute": dispute_id, "request_id": request_id, "amount_minor": amount_minor, "error": type(error).__name__}, False)
            self._end(step, tool, dispute_id, amount_minor, currency, request_id, UNKNOWN, f"No answer ({type(error).__name__}). Held as UNKNOWN; the next call reads PayPal's record first.", signals, said, True)
            raise
        return self._check(op, dispute_id, step, amount_minor, currency, request_id, signals, said, reservation or self._reserved(op, history), end)

    def _check(self, op, dispute_id, step, amount_minor, currency, request_id, signals, said, reservation, end):
        """Independent read of PayPal's record after the send. Only a matching record is VERIFIED."""
        try:
            after = self._read(dispute_id)
            paid = (after.get("dispute_outcome") or {}).get("amount_refunded")
            refunded = _minor(paid) if paid else amount_minor
            observed = {"status": after.get("status")}
            state = VERIFIED if after.get("status") == "RESOLVED" and refunded == amount_minor else MISMATCH
        except Exception:
            observed, state = None, UNKNOWN
        self.outcomes.record(op, state, observed)
        self.receipt(f"{step}:check", "clearwake.refund.checked", {"dispute": dispute_id, "state": state, "amount_minor": amount_minor}, state == VERIFIED)
        if state == VERIFIED:
            self._release_or_commit(reservation, commit=True)
        return end(state, {VERIFIED: "Matches PayPal's record: the claim shows RESOLVED for the amount.", MISMATCH: "PayPal's record does not match. A person checks.",
                           UNKNOWN: "No readable record yet."}[state], sent=True)

    def reconcile(self, dispute_id):
        """Reads PayPal's record for a move held as UNKNOWN and settles it. Reads only; never sends."""
        record = self._read(dispute_id)
        digest = payload_hash("accept_dispute_claim", dispute_id, _minor(record.get("dispute_amount")), (record.get("dispute_amount") or {}).get("currency_code", ""))
        op, history = f"toolkit:{digest}", self.outcomes.history(f"toolkit:{digest}")
        if history and history[-1]["state"] == UNKNOWN and record.get("status") == "RESOLVED":
            self.outcomes.record(op, VERIFIED, {"status": "RESOLVED"})
            self._settle_reservation(op, history, commit=True)
            self.receipt(f"toolkit:{dispute_id}:reconciled", "clearwake.refund.checked", {"dispute": dispute_id, "state": VERIFIED, "amount_minor": _minor(record["dispute_amount"])}, True)
            return VERIFIED
        return history[-1]["state"] if history else None

    # helpers ----------------------------------------------------------------------------------------------------------------
    def _send(self, tool, dispute_id, note, request_id):
        function = getattr(self.tool, tool, None)
        if function is not None:
            extra = {"request_id": request_id} if _accepts(function, "request_id") else {}
            return function(dispute_id, note, **extra)
        run = getattr(self.tool, "run", None) or self.tool
        return run(tool, {"dispute_id": dispute_id, "note": note})

    def _reserve(self, record, amount_minor, currency, customer_id, dispute_id):
        capture = ((record.get("disputed_transactions") or [{}])[0]).get("seller_transaction_id", "")
        if not capture or self._read_capture is None:
            return None   # no capture total to hold the move against; the policy limit still applies
        total = _minor((self._read_capture(capture) or {}).get("amount"))
        if total < 0:
            return None
        cap = self.policy.get("caps", {}).get("per_customer_per_day_minor") if customer_id else None
        day = (self.clock() if self.clock else datetime.now(timezone.utc)).date().isoformat()
        return self.invariants.reserve(f"capture:{capture}", total, amount_minor, customer_id or "unknown", day, cap)

    def _reserved(self, op, history):
        return self._reservations.get(op) or next((h["observed"]["reservation"] for h in reversed(history) if h.get("observed") and "reservation" in h["observed"]), None)

    def _settle_reservation(self, op, history, commit):
        self._release_or_commit(self._reserved(op, history), commit)

    def _release_or_commit(self, reservation, commit):
        if not reservation:
            return
        try:
            (self.invariants.commit if commit else self.invariants.release)(reservation)
        except Refused:
            pass

    def _release(self, reservation):
        self._release_or_commit(reservation, commit=False)

    def _end(self, step, tool, dispute_id, amount_minor, currency, request_id, state, detail, signals, said, sent, approval=None):
        line = self.receipt(f"{step}:call", "clearwake.toolkit.call", {"tool": tool, "dispute": dispute_id, "amount_minor": amount_minor, "currency": currency,
                            "amount_source": "paypal record", "claimed_amount_minor": said, "request_id": request_id, "state": state, "sent": sent,
                            "injection_signals": signals}, state in (VERIFIED, AWAITING, DONE_ELSEWHERE))
        return Outcome(state, detail, sent, amount_minor, currency, request_id, approval, list(signals), line)

    # the rest of the toolkit passes through untouched --------------------------------------------------------------------------
    def run(self, name, params=None):
        """PayPalAPI.run style entry: the money returning tool is guarded, every other tool is passed through."""
        params = dict(params or {})
        if name in MONEY_MOVING:
            return getattr(self, name)(**params)
        return self.tool.run(name, params)

    __call__ = run

    def __getattr__(self, name):
        if name.startswith("_") or name in ("tool",):
            raise AttributeError(name)
        return getattr(self.tool, name)


def guard(tools_or_callable, policy=None, receipts=None, reader=None, data_dir=None, **options):
    """Wrap PayPal Agent Toolkit tools (an object with accept_dispute_claim, a PayPalAPI-style object with run(), or a callable
    (name, params)). reader reads PayPal's record: a function dispute_id -> record, or an object with .dispute() and optionally
    .capture(). policy: path or loaded policy (default policy/merchant.yaml, its hash is in every receipt). receipts: a path or a
    ReceiptLog (default: a signed log in data_dir)."""
    return ToolkitGuard(tools_or_callable, policy=policy, receipts=receipts, reader=reader, data_dir=data_dir, **options)
