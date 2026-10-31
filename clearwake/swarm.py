"""Merchant swarm on the shared verdock-core engine.

Intake reads the case, Evidence gathers records, Decider proposes, the policy decides, an independent
Checker reads PayPal's record after every money movement. Signed receipts record each step.
Swarm invariants: one agent per case (lock), total refunded per capture never above the capture,
a per customer per day cap, and one stable PayPal-Request-Id per action across any retry.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import threading

from verdock_core.approvals import ApprovalStore
from verdock_core.invariants import Invariants
from verdock_core.outcome import MISMATCH, PENDING, UNKNOWN, VERIFIED, OutcomeLog, compare
from verdock_core.policy import decide, load_policy, policy_hash
from verdock_core.receipts import ReceiptLog, create_seed, load_seed
from verdock_core import Refused

from .paypal import GatewayError, ProviderRefused

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
        self.gateway, self.adapter, self.agent = gateway, adapter, agent
        self.policy = load_policy(policy_path); self.policy_hash = policy_hash(self.policy)
        self.approvals = ApprovalStore(str(data / "approvals.sqlite3"))
        self.invariants = Invariants(str(data / "invariants.sqlite3"))
        self.outcomes = OutcomeLog(str(data / "outcomes.sqlite3"))
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

    def handle_dispute(self, dispute_id, capture_minor, customer_id, order=None, trackers=(), mandate_receipt=None,
                       approval_id=None, owner="swarm-1"):
        """A real PayPal dispute (or its rehearsal twin): Intake, Evidence, Decider, policy, Checker. Deadlines escalate."""
        from .evidence import DisputeView, deadline, evidence_pack, propose as rule
        if not self.invariants.lock(f"dispute:{dispute_id}", owner, ttl_seconds=300):
            return Result(dispute_id, "none", "busy", "Another agent holds this dispute.")
        try:
            view = DisputeView.from_paypal(self.gateway.dispute(dispute_id))                       # Intake
            if view.status not in ("WAITING_FOR_SELLER_RESPONSE", "OPEN"):
                return Result(dispute_id, "none", "done", f"PayPal shows {view.status}; nothing to answer.")
            clock = deadline(view, self.clock())
            evidences, sources = evidence_pack(view, order, trackers, mandate_receipt)              # Evidence
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
            shown = {"backend": proposal.label, "proposed": action, "deadline": clock, "sources": sources}
            self.receipt(f"{dispute_id}:proposal", "clearwake.dispute.proposal", {"dispute": dispute_id, "reason": view.reason,
                         "proposed": action, "evidence_items": len(evidences), "deadline_state": clock["state"], "model": proposal.model}, True)
            if clock["state"] in ("soon", "lapsed") and approval_id is None:
                action = "escalate"
            if action == "escalate":
                approval_id = self.approvals.request("dispute", f"answer dispute {dispute_id} ({view.reason})", dispute_id, view.amount_minor,
                                                     view.currency, self.policy["operations"]["accept_claim"]["max_amount_minor"], owner, 3600)
                self.receipt(f"{dispute_id}:escalated", "clearwake.dispute.escalated", {"dispute": dispute_id, "approval": approval_id,
                             "seconds_left": clock["seconds_left"] if clock["seconds_left"] is not None else -1}, True)
                return Result(dispute_id, "escalate", "awaiting approval", f"Escalated to the inbox. Deadline: {clock['state']}.",
                              approval_id=approval_id, proposal=shown)
            request_id = self.invariants.request_id(f"dispute:{dispute_id}:{action}")
            if action == "provide_evidence":
                if not decide(self.policy, "provide_evidence", 0).allowed:
                    return Result(dispute_id, action, "refused", "Policy does not allow sending evidence.", proposal=shown)
                try:
                    self.gateway.provide_evidence(dispute_id, evidences, request_id)
                except ProviderRefused as refused:
                    self.receipt(f"{dispute_id}:evidence-refused", "clearwake.dispute.refused_by_paypal", {"dispute": dispute_id, "reason": str(refused)[:200]}, False)
                    return Result(dispute_id, action, "refused by PayPal", f"{refused} Nothing was applied.", proposal=shown)
                except GatewayError:
                    self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN)
                    return Result(dispute_id, action, UNKNOWN, "Evidence response lost. Read the dispute before doing anything else.", proposal=shown)
                return self.check_dispute(dispute_id, action, ("UNDER_REVIEW", "WAITING_FOR_BUYER_RESPONSE", "RESOLVED"), shown)
            decision = decide(self.policy, "accept_claim", view.amount_minor, view.currency)            # accept_and_refund
            if not decision.allowed:
                return Result(dispute_id, action, "refused", f"Policy refused: {decision.reason}.", proposal=shown)
            if decision.needs_approval and approval_id is None:
                approval_id = self.approvals.request("accept_claim", f"accept and refund {money(view.amount_minor)}", dispute_id, view.amount_minor,
                                                     view.currency, decision.limit_minor, owner, 3600)
                return Result(dispute_id, action, "awaiting approval", "Above the approval threshold.", approval_id=approval_id, proposal=shown)
            if decision.needs_approval:
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
            except GatewayError:
                self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN); self.held[f"dispute:{dispute_id}"] = reservation
                return Result(dispute_id, action, UNKNOWN, "Response lost. Held; read the dispute before anything else.", approval_id=approval_id, proposal=shown)
            self.invariants.commit(reservation)
            return self.check_dispute(dispute_id, action, ("RESOLVED",), shown, approval_id)
        finally:
            self.invariants.unlock(f"dispute:{dispute_id}", owner)

    def check_dispute(self, dispute_id, action, good_statuses, shown, approval_id=None):
        """Checker: read the dispute back from PayPal. Only the expected status counts as verified."""
        try:
            status = self.gateway.dispute(dispute_id).get("status")
        except GatewayError:
            status = None
        state = VERIFIED if status in good_statuses else UNKNOWN if status is None else MISMATCH
        if state == UNKNOWN:
            self.outcomes.record(f"dispute:{dispute_id}", UNKNOWN)
        self.receipt(f"{dispute_id}:check", "clearwake.dispute.checked", {"dispute": dispute_id, "action": action, "status": status or "", "state": state}, state == VERIFIED)
        return Result(dispute_id, action, state, f"PayPal now shows {status}." if status else "Could not read the dispute.", approval_id=approval_id, proposal=shown)

    def reconcile(self, case, known_refund_id):
        """Resolve an UNKNOWN from PayPal's own record of a known refund id. Reads only; never resends."""
        result = self.check(case, known_refund_id, {"proposed": "reconcile"})
        if result.state == VERIFIED and case.id in self.held:
            self.invariants.commit(self.held.pop(case.id))
        return result
