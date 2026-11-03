"""Merchant swarm on the shared verdock-core engine.

Intake reads the case, Evidence gathers records, Decider proposes, the policy decides, an independent
Checker reads PayPal's record after every money movement. Signed receipts record each step.
Swarm invariants: one agent per case (lock), total refunded per capture never above the capture,
a per customer per day cap, and one stable PayPal-Request-Id per action across any retry.
Offline: an action the egress gateway could not send is held as "held, offline" with its request id.
On reconnect PayPal's record is read first, then the action resumes with the same request id.
"""
from dataclasses import asdict, dataclass, field
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import threading

from verdock_core.approvals import ApprovalStore
from verdock_core.invariants import Invariants
from verdock_core.outcome import MISMATCH, PENDING, UNKNOWN, VERIFIED, OutcomeLog, compare
from verdock_core.policy import decide, load_policy, policy_hash
from verdock_core.queue import HELD, RESUMED, HeldQueue
from verdock_core.receipts import ReceiptLog, create_seed, load_seed
from verdock_core import Refused

from . import dispatch as proof
from .paypal import GatewayError, Offline, ProviderRefused

POLICY = Path(__file__).resolve().parent.parent / "policy" / "merchant.yaml"


def money(minor):
    return f"{Decimal(minor) / 100:.2f}"


@dataclass
class Case:
    id: str                 # complaint or PayPal dispute id
    kind: str               # "buyer complaint" or "PayPal dispute"
    order_id: str
    capture_id: str
    capture_minor: int
    customer_id: str
    amount_minor: int       # what the buyer asks for
    reason: str
    message: str = ""       # free text from the buyer; never decides anything


@dataclass
class Result:
    case_id: str
    action: str
    state: str              # done, awaiting approval, refused, busy, VERIFIED, MISMATCH, UNKNOWN, PENDING
    detail: str
    refund_id: str | None = None
    approval_id: str | None = None
    proposal: dict = field(default_factory=dict)


class MerchantSwarm:
    def __init__(self, gateway, data_dir, adapter, policy_path=POLICY, agent="clearwake-merchant", clock=None):
        data = Path(data_dir); data.mkdir(parents=True, exist_ok=True)
        self.data = data
        self.gateway, self.adapter, self.agent = gateway, adapter, agent
        self.policy = load_policy(policy_path); self.policy_hash = policy_hash(self.policy)
        self.approvals = ApprovalStore(str(data / "approvals.sqlite3"))
        self.invariants = Invariants(str(data / "invariants.sqlite3"))
        self.outcomes = OutcomeLog(str(data / "outcomes.sqlite3"))
        self.queue = HeldQueue(str(data / "held.sqlite3"))
        seed_path = data / "merchant.seed"
        if not seed_path.exists():
            create_seed(str(seed_path))
        self.receipts = ReceiptLog(str(data / "merchant-receipts.ndjson"), load_seed(str(seed_path)))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.held = {}  # UNKNOWN refunds keep their capture reservation until reconciled
        self._writer = threading.Lock()

    def receipt(self, step, action, params, success):
        with self._writer:  # one writer per chain: parallel agents must not fork it
            return self.receipts.append(step, action, {**params, "policy_hash": self.policy_hash}, success,
                                    actor={"agent": self.agent, "user": "merchant"})

    def propose(self, case):
        """Decider agent proposal. The text of the message can only pick among actions; amounts come from the case."""
        def scripted():
            return {"action": "refund" if case.amount_minor else "provide_evidence"}
        proposal = self.adapter.propose(
            "You resolve a refund request for a small online merchant. Choose refund, provide_evidence or escalate.",
            f"Reason: {case.reason}. Buyer message: {case.message[:500]}", ["action"], scripted)
        action = (proposal.value or {}).get("action")
        return (action if action in ("refund", "provide_evidence", "escalate") else "escalate"), proposal

    def handle(self, case, approval_id=None, owner="swarm-1"):
        if not self.invariants.lock(f"case:{case.id}", owner, ttl_seconds=300):
            return Result(case.id, "none", "busy", "Another agent holds this case. No second action.")
        try:
            latest = self.outcomes.latest(case.id)
            if latest in (UNKNOWN, VERIFIED, PENDING):
                return Result(case.id, "none", latest,"This case already has a refund on record. Nothing is sent again; reconcile instead.")
            action, proposal = self.propose(case)
            shown = {"backend": proposal.label, "proposed": action}
            self.receipt(f"{case.id}:proposal", "clearwake.decider.proposal", {"case": case.id, "kind": case.kind, "proposed": action, "model": proposal.model}, True)
            if action != "refund":
                return Result(case.id, action, "escalated" if action == "escalate" else "done", "No money moves on this path.", proposal=shown)
            decision = decide(self.policy, "refund", case.amount_minor, "USD")
            if not decision.allowed:
                self.receipt(f"{case.id}:refused", "clearwake.policy.refused", {"case": case.id, "amount_minor": case.amount_minor, "limit_minor": decision.limit_minor, "reason": decision.reason}, False)
                return Result(case.id, "refund", "refused", f"Policy refused: {decision.reason} (limit {money(decision.limit_minor or 0)} USD).", proposal=shown)
            if decision.needs_approval:
                if approval_id is None:
                    approval_id = self.approvals.request("refund", f"refund {money(case.amount_minor)} USD", case.id, case.amount_minor, "USD",
                                                         decision.limit_minor, owner, ttl_seconds=3600)
                    self.receipt(f"{case.id}:approval-request", "clearwake.approval.requested", {"case": case.id, "approval": approval_id, "amount_minor": case.amount_minor}, True)
                    return Result(case.id, "refund", "awaiting approval", "Above the approval threshold. Waiting in the inbox.", approval_id=approval_id, proposal=shown)
                try:
                    record = self.approvals.require(approval_id, "refund", case.id, case.amount_minor, "USD")
                except Refused as error:
                    return Result(case.id, "refund", "refused", f"Approval not valid: {error}", approval_id=approval_id, proposal=shown)
                self.approvals.consume(approval_id)
                self.receipt(f"{case.id}:approval-used", "clearwake.approval.used", {"case": case.id, "approval": approval_id, "approver": record["approver"]}, True)
            return self.execute(case, shown, approval_id)
        finally:
            self.invariants.unlock(f"case:{case.id}", owner)

    def execute(self, case, shown, approval_id=None):
        try:  # preflight: read the capture before any money moves (this also prepares sandbox authentication)
            capture = self.gateway.capture(case.capture_id)
            if capture.get("status") not in ("COMPLETED", "PARTIALLY_REFUNDED"):
                raise GatewayError(f"capture status {capture.get('status')}")
        except Offline:
            return self.hold(f"refund:{case.id}", "refund", self.invariants.request_id(f"refund:{case.id}"),
                             {"case": asdict(case), "approval_id": approval_id}, case.id, shown)
        except GatewayError as error:
            self.receipt(f"{case.id}:preflight", "clearwake.refund.blocked", {"case": case.id, "reason": "capture preflight failed"}, False)
            return Result(case.id, "refund", "refused", f"Capture preflight failed ({error}). Nothing was sent.", approval_id=approval_id, proposal=shown)
        day = self.clock().date().isoformat()
        try:
            reservation = self.invariants.reserve(f"capture:{case.capture_id}", case.capture_minor, case.amount_minor, case.customer_id, day,
                                                  self.policy.get("caps", {}).get("per_customer_per_day_minor"))
        except Refused as error:
            self.receipt(f"{case.id}:invariant", "clearwake.invariant.refused", {"case": case.id, "amount_minor": case.amount_minor, "reason": str(error)[:200]}, False)
            return Result(case.id, "refund", "refused", f"Swarm limit: {error}", approval_id=approval_id, proposal=shown)
        request_id = self.invariants.request_id(f"refund:{case.id}")
        expected = {"amount": money(case.amount_minor), "currency": "USD", "status": "COMPLETED"}
        self.outcomes.expect(case.id, expected, ["amount", "currency", "status"], status_field="status", pending_values=("PENDING",))
        try:
            response = self.gateway.refund(case.capture_id, money(case.amount_minor), "USD", request_id)
        except Offline:  # the gateway refused the tunnel: nothing reached PayPal
            self.invariants.release(reservation)
            return self.hold(f"refund:{case.id}", "refund", request_id, {"case": asdict(case), "approval_id": approval_id}, case.id, shown)
        except GatewayError:
            # The request may have taken effect. Keep the reservation and the request id. Never resend.
            self.outcomes.record(case.id, UNKNOWN)
            self.held[case.id] = reservation
            self.receipt(f"{case.id}:unknown", "clearwake.refund.unknown", {"case": case.id, "request_id": request_id, "amount_minor": case.amount_minor}, False)
            return Result(case.id, "refund", UNKNOWN, "Response lost. Held as UNKNOWN; reconcile from PayPal's record.", approval_id=approval_id, proposal=shown)
        self.invariants.commit(reservation)
        return self.check(case, response.get("id"), shown, approval_id)

    def check(self, case, refund_id, shown, approval_id=None):
        """Independent read of PayPal's refund record. Only a matching record is VERIFIED."""
        try:
            record = self.gateway.refund_record(refund_id)
            observed = {"amount": record["amount"]["value"], "currency": record["amount"]["currency_code"], "status": record["status"]}
        except (GatewayError, KeyError, TypeError):
            observed = None
        state = compare({"amount": money(case.amount_minor), "currency": "USD", "status": "COMPLETED"}, observed,
                        ["amount", "currency", "status"], status_field="status", pending_values=("PENDING",))
        self.outcomes.record(case.id, state, observed)
        self.receipt(f"{case.id}:check", "clearwake.refund.checked", {"case": case.id, "refund": refund_id or "", "state": state,
                     "amount_minor": case.amount_minor}, state == VERIFIED)
        return Result(case.id, "refund", state, {VERIFIED: "Matches PayPal's refund record.", MISMATCH: "PayPal's record does not match. Escalated.",
                      PENDING: "PayPal shows it pending.", UNKNOWN: "No readable record yet."}[state], refund_id, approval_id, shown)

    def _proof(self, view, order, trackers):
        """Dispatch proof for this dispute's order, checked against what the buyer says arrived. None when there is nothing to check.

        The buyer's message is read only as a claim to check. It never decides an amount or an action."""
        claim = proof.buyer_claim(view.raw)
        found = proof.assess(self, order, trackers, claim)
        if found is not None:
            self.receipt(f"{view.id}:dispatch-checked", "clearwake.dispute.dispatch_checked", {
                "dispute": view.id, "order": (order or {}).get("id", ""), "claimed_received": claim["received"] if claim else -1,
                "claimed_of": claim["of"] if claim else -1, "strong": found.strong,
                "receipt": found.record["digest"] if found.record else "", "summary": found.summary[:300]}, found.strong)
        return found

    def handle_dispute(self, dispute_id, capture_minor, customer_id, order=None, trackers=(), mandate_receipt=None,
                       approval_id=None, owner="swarm-1"):
        """A real PayPal dispute (or its rehearsal twin): Intake, Evidence, Decider, policy, Checker. Deadlines escalate."""
        from .evidence import DisputeView, deadline, evidence_pack, propose as rule
        args = {"dispute_id": dispute_id, "capture_minor": capture_minor, "customer_id": customer_id, "order": order,
                "trackers": list(trackers), "mandate_receipt": mandate_receipt, "approval_id": approval_id}
        if not self.invariants.lock(f"dispute:{dispute_id}", owner, ttl_seconds=300):
            return Result(dispute_id, "none", "busy", "Another agent holds this dispute.")
        try:
            try:
                view = DisputeView.from_paypal(self.gateway.dispute(dispute_id))                   # Intake
            except Offline:
                return self.hold(f"dispute:{dispute_id}", "dispute", "", args, dispute_id, {})
            offered = {link.get("rel") for link in view.raw.get("links", []) if isinstance(link, dict)}
            if view.status == "UNDER_REVIEW" and "provide_supporting_info" in offered:
                return self.supporting_info(view, order, trackers, mandate_receipt)
            if view.raw.get("dispute_life_cycle_stage") == "INQUIRY":
                return self.inquiry(view, args)
            if view.status not in ("WAITING_FOR_SELLER_RESPONSE", "OPEN"):
                return Result(dispute_id, "none", "done", f"PayPal shows {view.status}; nothing to answer.")
            clock = deadline(view, self.clock())
            dispatch_found = self._proof(view, order, trackers)
            evidences, sources = evidence_pack(view, order, trackers, mandate_receipt, dispatch_found)  # Evidence
            limit = self.policy["operations"]["accept_claim"].get("approval_above_minor", 0)

            def scripted():
                return {"action": rule(view, evidences, limit, clock)[0]}
            proposal = self.adapter.propose(                                                           # Decider
                "You answer a PayPal dispute for a small merchant. Choose provide_evidence, accept_and_refund or escalate.",
                f"Reason {view.reason}, amount {money(view.amount_minor)} {view.currency}, evidence items {len(evidences)}, "
                f"deadline {clock['state']}.", ["action"], scripted)
            action = (proposal.value or {}).get("action")
            action = action if action in ("provide_evidence", "accept_and_refund", "escalate") else "escalate"
            if action == "provide_evidence" and not evidences:
                action = "escalate"  # a model may not claim evidence that the records do not hold
            shown = {"backend": proposal.label, "proposed": action, "deadline": clock, "sources": sources,
                     "dispatch": dispatch_found.summary if dispatch_found else None, "claim": dispatch_found.claim if dispatch_found else None}
            self.receipt(f"{dispute_id}:proposal", "clearwake.dispute.proposal", {"dispute": dispute_id, "reason": view.reason,
                         "proposed": action, "evidence_items": len(evidences), "deadline_state": clock["state"], "model": proposal.model}, True)
            # An escalation asks a person to approve one exact next step; an approved one lets the swarm take only that step.
            planned = "provide_evidence" if evidences else "accept_and_refund"
            approved = False
            record = self.approvals.get(approval_id) if approval_id else None
            if record and record["operation"].startswith("dispute_"):
                try:
                    self.approvals.require(approval_id, f"dispute_{planned}", dispute_id, view.amount_minor, view.currency)
                except Refused as error:
                    return Result(dispute_id, planned, "refused", f"Approval not valid: {error}", approval_id=approval_id, proposal=shown)
                self.approvals.consume(approval_id)
                self.receipt(f"{dispute_id}:approval-used", "clearwake.approval.used", {"dispute": dispute_id, "approval": approval_id,
                             "approver": record["approver"], "step": planned}, True)
                action, approved = planned, True
            if clock["state"] in ("soon", "lapsed") and approval_id is None:
                action = "escalate"
            if action == "escalate":
                step = "send the evidence from PayPal's record" if evidences else f"accept and refund {money(view.amount_minor)} {view.currency}"
                approval_id = self.approvals.request(f"dispute_{planned}", f"answer dispute {dispute_id} ({view.reason}): {step}", dispute_id,
                                                     view.amount_minor, view.currency, self.policy["operations"]["accept_claim"]["max_amount_minor"], owner, 3600)
                self.receipt(f"{dispute_id}:escalated", "clearwake.dispute.escalated", {"dispute": dispute_id, "approval": approval_id,
                             "seconds_left": clock["seconds_left"] if clock["seconds_left"] is not None else -1}, True)
                return Result(dispute_id, "escalate", "awaiting approval", f"Escalated to the inbox. Deadline: {clock['state']}.",
                              approval_id=approval_id, proposal=shown)
            request_id = self.invariants.request_id(f"dispute:{dispute_id}:{action}")
            if action == "provide_evidence":
                if not decide(self.policy, "provide_evidence", 0).allowed:
                    return Result(dispute_id, action, "refused", "Policy does not allow sending evidence.", proposal=shown)
                files = dispatch_found.documents if dispatch_found and dispatch_found.strong else ()
                try:
                    self.gateway.provide_evidence(dispute_id, evidences, request_id, files)
                except Offline:
                    return self.hold(f"dispute:{dispute_id}", "dispute", request_id, args, dispute_id, shown)
                except ProviderRefused as refused:
                    self.receipt(f"{dispute_id}:evidence-refused", "clearwake.dispute.refused_by_paypal", {"dispute": dispute_id, "reason": str(refused)[:200]}, False)
                    return Result(dispute_id, action, "refused by PayPal", f"{refused} Nothing was applied.", proposal=shown)
                except GatewayError:
                    self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN)
                    return Result(dispute_id, action, UNKNOWN, "Evidence response lost. Read the dispute before doing anything else.", proposal=shown)
                note = dispatch_found.record["digest"][:16] if dispatch_found and dispatch_found.strong else None
                return self.check_dispute(dispute_id, action, ("UNDER_REVIEW", "WAITING_FOR_BUYER_RESPONSE", "RESOLVED"), shown, expect_note=note)
            decision = decide(self.policy, "accept_claim", view.amount_minor, view.currency)            # accept_and_refund
            if not decision.allowed:
                return Result(dispute_id, action, "refused", f"Policy refused: {decision.reason}.", proposal=shown)
            if decision.needs_approval and approval_id is None and not approved:
                approval_id = self.approvals.request("accept_claim", f"accept and refund {money(view.amount_minor)}", dispute_id, view.amount_minor,
                                                     view.currency, decision.limit_minor, owner, 3600)
                return Result(dispute_id, action, "awaiting approval", "Above the approval threshold.", approval_id=approval_id, proposal=shown)
            if decision.needs_approval and not approved:
                try:
                    self.approvals.require(approval_id, "accept_claim", dispute_id, view.amount_minor, view.currency)
                except Refused as error:
                    return Result(dispute_id, action, "refused", f"Approval not valid: {error}", approval_id=approval_id, proposal=shown)
                self.approvals.consume(approval_id)
            capture = view.transactions[0] if view.transactions else ""
            try:
                reservation = self.invariants.reserve(f"capture:{capture}", capture_minor, view.amount_minor, customer_id,
                                                      self.clock().date().isoformat(), self.policy.get("caps", {}).get("per_customer_per_day_minor"))
            except Refused as error:
                return Result(dispute_id, action, "refused", f"Swarm limit: {error}", proposal=shown)
            try:
                self.gateway.accept_claim(dispute_id, "Refund within the merchant's limit.", money(view.amount_minor), view.currency, request_id)
            except Offline:
                self.invariants.release(reservation)
                return self.hold(f"dispute:{dispute_id}", "dispute", request_id, args, dispute_id, shown)
            except GatewayError:
                self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN); self.held[f"dispute:{dispute_id}"] = reservation
                return Result(dispute_id, action, UNKNOWN, "Response lost. Held; read the dispute before anything else.", approval_id=approval_id, proposal=shown)
            self.invariants.commit(reservation)
            return self.check_dispute(dispute_id, action, ("RESOLVED",), shown, approval_id)
        finally:
            self.invariants.unlock(f"dispute:{dispute_id}", owner)

    def inquiry(self, view, args):
        """Settle in conversation while PayPal still calls it an inquiry: no claim yet, so no PayPal dispute fee.

        The policy decides (settle by offer, fight with the records, or escalate); the model's proposal is only shown.
        Messages and offers go through PayPal's Disputes API. Only PayPal's record can mark a case settled."""
        from .evidence import DECISIONS, deadline, dispute_decision, evidence_pack
        dispute_id = view.id
        if view.status in ("WAITING_FOR_BUYER_RESPONSE", "RESOLVED"):
            return self.settlement(dispute_id)
        if view.status not in ("WAITING_FOR_SELLER_RESPONSE", "OPEN"):
            return Result(dispute_id, "none", "done", f"PayPal shows {view.status}; nothing to answer.")
        clock = deadline(view, self.clock())
        dispatch_found = self._proof(view, args["order"], args["trackers"])
        evidences, sources = evidence_pack(view, args["order"], args["trackers"], args["mandate_receipt"], dispatch_found)
        decided, why, offer_minor = dispute_decision(self.policy, view, evidences, clock, inquiry=True)
        buyer = " ".join(m.get("content", "") for m in view.raw.get("messages", []) or [] if m.get("posted_by") == "BUYER")[:300]
        proposal = self.adapter.propose(
            "You help a small merchant settle a PayPal dispute that is still an inquiry, before it becomes a claim. "
            "Choose settle_by_offer, refund_within_limit, fight_with_evidence or escalate.",
            f"Reason {view.reason}, amount {money(view.amount_minor)} {view.currency}, evidence items {len(evidences)}, "
            f"deadline {clock['state']}. Buyer wrote: {buyer}", ["action"], lambda: {"action": decided})
        proposed = (proposal.value or {}).get("action")
        proposed = proposed if proposed in DECISIONS else "no usable proposal"
        shown = {"backend": proposal.label, "proposed": proposed, "decided": decided, "why": why, "deadline": clock,
                 "sources": sources, "stage": "INQUIRY", "offer": money(offer_minor) if offer_minor else None,
                 "dispatch": dispatch_found.summary if dispatch_found else None, "claim": dispatch_found.claim if dispatch_found else None}
        self.receipt(f"{dispute_id}:decision", "clearwake.dispute.decision", {"dispute": dispute_id, "stage": "INQUIRY", "proposed": proposed,
                     "decided": decided, "offer_minor": offer_minor, "model": proposal.model}, True)
        offered = {link.get("rel") for link in view.raw.get("links", []) if isinstance(link, dict)}
        if decided == "fight_with_evidence" and "provide_evidence" in offered and dispatch_found is not None and dispatch_found.strong:
            return self.inquiry_evidence(view, args, evidences, dispatch_found, shown)   # PayPal offers provide-evidence on this inquiry
        if decided == "fight_with_evidence":
            message = ("Thank you for reaching out. Here is what our PayPal records show: " + "; ".join(sources) + ". "
                       + " ".join(e.get("notes", "") for e in evidences))[:2000]
            request_id = self.invariants.request_id(f"dispute:{dispute_id}:message")
            try:
                self.gateway.send_message(dispute_id, message, request_id)
            except Offline:
                return self.hold(f"dispute:{dispute_id}", "dispute", request_id, args, dispute_id, shown)
            except ProviderRefused as refused:
                return Result(dispute_id, decided, "refused by PayPal", f"{refused} Nothing was applied.", proposal=shown)
            except GatewayError:
                self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN)
                return Result(dispute_id, decided, UNKNOWN, "Message response lost. Read the dispute before anything else.", proposal=shown)
            try:
                after = self.gateway.dispute(dispute_id)
            except (GatewayError, ProviderRefused, Offline):
                after = {}
            seen = any(m.get("posted_by") == "SELLER" and message[:60] in m.get("content", "") for m in after.get("messages", []) or [])
            self.receipt(f"{dispute_id}:message-check", "clearwake.dispute.message_checked", {"dispute": dispute_id, "seen": seen}, seen)
            return Result(dispute_id, decided, VERIFIED if seen else UNKNOWN, "PayPal's dispute record shows the message with the facts." if seen
                          else "Sent, but PayPal's record does not show the message yet. Not counted as verified.", proposal=shown)
        if decided == "escalate":
            approval_id = self.approvals.request("dispute_inquiry", f"decide inquiry {dispute_id} ({view.reason}): {why}", dispute_id,
                                                 view.amount_minor, view.currency, self.policy["operations"]["make_offer"]["max_amount_minor"], "swarm-1", 3600)
            self.receipt(f"{dispute_id}:escalated", "clearwake.dispute.escalated", {"dispute": dispute_id, "approval": approval_id,
                         "seconds_left": clock["seconds_left"] if clock["seconds_left"] is not None else -1}, True)
            return Result(dispute_id, "escalate", "awaiting approval", f"Escalated to the owner. {why}", approval_id=approval_id, proposal=shown)
        decision = decide(self.policy, "make_offer", offer_minor, view.currency)                       # settle_by_offer
        approval_id = args.get("approval_id")
        if decision.needs_approval and approval_id is None:
            approval_id = self.approvals.request("make_offer", f"offer {money(offer_minor)} {view.currency} to settle {dispute_id}", dispute_id,
                                                 offer_minor, view.currency, decision.limit_minor, "swarm-1", 3600)
            return Result(dispute_id, decided, "awaiting approval", "Offer above the owner's approval threshold.", approval_id=approval_id, proposal=shown)
        if decision.needs_approval:
            try:
                self.approvals.require(approval_id, "make_offer", dispute_id, offer_minor, view.currency)
            except Refused as error:
                return Result(dispute_id, decided, "refused", f"Approval not valid: {error}", approval_id=approval_id, proposal=shown)
            self.approvals.consume(approval_id)
        capture = view.transactions[0] if view.transactions else ""
        try:  # an offer counts against the capture and the daily cap from the moment it is made
            reservation = self.invariants.reserve(f"capture:{capture}", args["capture_minor"], offer_minor, args["customer_id"],
                                                  self.clock().date().isoformat(), self.policy.get("caps", {}).get("per_customer_per_day_minor"))
        except Refused as error:
            return Result(dispute_id, decided, "refused", f"Swarm limit: {error}", proposal=shown)
        note = (f"We are sorry about this order. To settle it now, we offer a refund of {money(offer_minor)} {view.currency}"
                + (" (full amount)." if offer_minor >= view.amount_minor else "."))
        offer_id = self.invariants.request_id(f"dispute:{dispute_id}:offer")
        try:
            self.gateway.send_message(dispute_id, note, self.invariants.request_id(f"dispute:{dispute_id}:message"))
            self.gateway.make_offer(dispute_id, note, money(offer_minor), view.currency, offer_id)
        except Offline:
            self.invariants.release(reservation)
            return self.hold(f"dispute:{dispute_id}", "dispute", offer_id, args, dispute_id, shown)
        except ProviderRefused as refused:
            self.invariants.release(reservation)
            return Result(dispute_id, decided, "refused by PayPal", f"{refused} Nothing was applied.", proposal=shown)
        except GatewayError:
            self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN); self.held[f"dispute:{dispute_id}"] = reservation
            return Result(dispute_id, decided, UNKNOWN, "Offer response lost. Held; read the dispute before anything else.", proposal=shown)
        self.invariants.commit(reservation)
        self.receipt(f"{dispute_id}:offer", "clearwake.dispute.offer_sent", {"dispute": dispute_id, "offer_minor": offer_minor, "currency": view.currency}, True)
        return self.settlement(dispute_id, shown)

    def inquiry_evidence(self, view, args, evidences, dispatch_found, shown):
        """Send the dispatch proof (with the photo) through provide-evidence while the case is still an inquiry.

        Only PayPal's own record can confirm it: the dispute is read back and the proof counts as sent only when its receipt digest
        appears in an evidence note PayPal now holds."""
        dispute_id = view.id
        if not decide(self.policy, "provide_evidence", 0).allowed:
            return Result(dispute_id, "provide_evidence", "refused", "Policy does not allow sending evidence.", proposal=shown)
        request_id = self.invariants.request_id(f"dispute:{dispute_id}:provide_evidence:" + hashlib.sha256(json.dumps(evidences, sort_keys=True).encode()).hexdigest()[:12])
        try:
            self.gateway.provide_evidence(dispute_id, evidences, request_id, dispatch_found.documents)
        except Offline:
            return self.hold(f"dispute:{dispute_id}", "dispute", request_id, args, dispute_id, shown)
        except ProviderRefused as refused:
            self.receipt(f"{dispute_id}:evidence-refused", "clearwake.dispute.refused_by_paypal", {"dispute": dispute_id, "reason": str(refused)[:200]}, False)
            return Result(dispute_id, "provide_evidence", "refused by PayPal", f"{refused} Nothing was applied.", proposal=shown)
        except GatewayError:
            self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN)
            return Result(dispute_id, "provide_evidence", UNKNOWN, "Evidence response lost. Read the dispute before doing anything else.", proposal=shown)
        note = dispatch_found.record["digest"][:16]
        try:
            record = self.gateway.dispute(dispute_id)
        except (GatewayError, ProviderRefused, Offline):
            record = {}
        seen = any(note in str(e.get("notes", "")) for e in record.get("evidences", []) or [])
        self.receipt(f"{dispute_id}:evidence-check", "clearwake.dispute.evidence_checked", {"dispute": dispute_id, "status": record.get("status") or "",
                     "stage": record.get("dispute_life_cycle_stage") or "", "dispatch_evidence_seen": seen}, seen)
        return Result(dispute_id, "provide_evidence", VERIFIED if seen else UNKNOWN,
                      f"PayPal's record shows the dispatch proof ({record.get('status')}, {record.get('dispute_life_cycle_stage')})." if seen
                      else "Sent, but PayPal's record does not show the dispatch proof yet. Not counted as verified.", proposal=shown)

    def settlement(self, dispute_id, shown=None):
        """Checker for settling in conversation. "Settled, no fee" only when PayPal shows RESOLVED while still an INQUIRY."""
        try:
            record = self.gateway.dispute(dispute_id)
        except Offline:
            return Result(dispute_id, "settle_by_offer", HELD, "Cannot read PayPal while offline. Nothing is counted as settled.", proposal=shown or {})
        except (GatewayError, ProviderRefused):
            return Result(dispute_id, "settle_by_offer", UNKNOWN, "Could not read the dispute. Nothing is counted as settled.", proposal=shown or {})
        status, stage = record.get("status"), record.get("dispute_life_cycle_stage")
        outcome = (record.get("dispute_outcome") or {}).get("outcome_code", "")
        if status == "RESOLVED" and stage == "INQUIRY":
            state, detail = VERIFIED, f"Settled, no fee: PayPal shows RESOLVED ({outcome or 'no outcome code'}) at the INQUIRY stage, never a claim."
        elif stage == "INQUIRY":
            state, detail = PENDING, f"Offer sent. PayPal shows {status}; waiting for the buyer."
        else:
            state, detail = MISMATCH, f"PayPal shows stage {stage} ({status}): the case became a claim. Not counted as settled."
        self.receipt(f"{dispute_id}:settlement", "clearwake.dispute.settlement", {"dispute": dispute_id, "status": status or "", "stage": stage or "",
                     "outcome": outcome, "state": state}, state == VERIFIED)
        return Result(dispute_id, "settle_by_offer", state, detail, proposal=shown or {"stage": stage})

    def hold(self, key, operation, request_id, params, case_id, shown):
        """The network is down. Hold the action with its request id; nothing moves until PayPal can be read again."""
        entry = self.queue.hold(key, operation, request_id, params)
        self.receipt(f"{key}:held", "clearwake.offline.held", {"key": key, "operation": operation, "request_id": entry["request_id"]}, False)
        return Result(case_id, operation, HELD, "Network down: held, offline. Nothing was sent. It resumes after PayPal's record is read.", proposal=shown)

    def resume_offline(self):
        """After reconnect: for each held action read PayPal's record first, then resume it with the same request id."""
        results = []
        for entry in self.queue.held():
            params = entry["params"]
            case_id = params["case"]["id"] if entry["operation"] == "refund" else params["dispute_id"]
            try:
                record = self.gateway.capture(params["case"]["capture_id"]) if entry["operation"] == "refund" else self.gateway.dispute(case_id)
            except Offline:
                results.append(Result(case_id, entry["operation"], HELD, "Still offline. Still held."))
                continue
            except (GatewayError, ProviderRefused):
                results.append(Result(case_id, entry["operation"], HELD, "PayPal's record could not be read. Still held."))
                continue
            self.receipt(f"{entry['key']}:reconciled", "clearwake.offline.reconciled", {"key": entry["key"], "provider_status": str(record.get("status", ""))}, True)
            if entry["operation"] == "refund":
                result = self.handle(Case(**params["case"]), approval_id=params.get("approval_id"))
            else:
                result = self.handle_dispute(**params)
            if result.state != HELD:
                self.queue.close(entry["key"], RESUMED, f"PayPal record read first ({record.get('status', '')}), then {result.state}")
            results.append(result)
        return results

    def supporting_info(self, view, order, trackers, mandate_receipt):
        """PayPal is reviewing and only offers supporting info: send record facts as notes, then read them back."""
        from .evidence import evidence_pack
        evidences, sources = evidence_pack(view, order, trackers, mandate_receipt)
        shown = {"backend": "rule: PayPal offers only provide_supporting_info", "proposed": "provide_supporting_info", "sources": sources}
        if not evidences or not decide(self.policy, "provide_evidence", 0).allowed:
            return Result(view.id, "escalate", "awaiting approval", "Under review with nothing from the record to add. A person decides.", proposal=shown)
        notes = "Facts from the merchant's PayPal records: " + "; ".join(sources) + ". " + " ".join(e.get("notes", "") for e in evidences)
        request_id = self.invariants.request_id(f"dispute:{view.id}:supporting_info")
        try:
            self.gateway.provide_supporting_info(view.id, notes, request_id)
        except ProviderRefused as refused:
            return Result(view.id, "provide_supporting_info", "refused by PayPal", f"{refused} Nothing was applied.", proposal=shown)
        except GatewayError:
            self.outcomes.record(f"dispute:{view.id}", UNKNOWN)
            return Result(view.id, "provide_supporting_info", UNKNOWN, "Response lost. Read the dispute before anything else.", proposal=shown)
        try:
            after = self.gateway.dispute(view.id)
        except (GatewayError, ProviderRefused):
            after = {}
        seen = any(any(t.get("number", "") in str(info) for t in trackers) for info in after.get("supporting_info", []))
        state = VERIFIED if seen else UNKNOWN
        self.receipt(f"{view.id}:supporting-info", "clearwake.dispute.supporting_info", {"dispute": view.id, "items": len(sources), "state": state}, seen)
        return Result(view.id, "provide_supporting_info", state, "PayPal's dispute record now shows the tracking note." if seen
                      else "Sent, but PayPal's dispute record does not show it yet. Not counted as verified.", proposal=shown)

    def check_dispute(self, dispute_id, action, good_statuses, shown, approval_id=None, expect_note=None):
        """Checker: read the dispute back from PayPal. Only the expected status counts as verified.

        expect_note is the start of the dispatch receipt digest: when evidence was sent, the read back says whether PayPal's record shows it."""
        try:
            record = self.gateway.dispute(dispute_id)
            status = record.get("status")
        except (GatewayError, Offline):
            record, status = {}, None
        state = VERIFIED if status in good_statuses else UNKNOWN if status is None else MISMATCH
        if state == UNKNOWN:
            self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN)
        seen = expect_note is not None and any(expect_note in str(e.get("notes", "")) for e in record.get("evidences", []) or [])
        self.receipt(f"{dispute_id}:check", "clearwake.dispute.checked", {"dispute": dispute_id, "action": action, "status": status or "", "state": state,
                     **({"dispatch_evidence_seen": seen} if expect_note is not None else {})}, state == VERIFIED)
        detail = f"PayPal now shows {status}." if status else "Could not read the dispute."
        if expect_note is not None and status:
            detail += " PayPal's record shows the dispatch proof." if seen else " PayPal's record does not show the dispatch proof text yet."
        return Result(dispute_id, action, state, detail, approval_id=approval_id, proposal=shown)

    def reconcile(self, case, known_refund_id):
        """Resolve an UNKNOWN from PayPal's own record of a known refund id. Reads only; never resends."""
        result = self.check(case, known_refund_id, {"proposed": "reconcile"})
        if result.state == VERIFIED and case.id in self.held:
            self.invariants.commit(self.held.pop(case.id))
        return result
