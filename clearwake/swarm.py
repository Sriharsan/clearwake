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

from verdock_core.approvals import ApprovalStore
from verdock_core.invariants import Invariants
from verdock_core.outcome import MISMATCH, PENDING, UNKNOWN, VERIFIED, OutcomeLog, compare
from verdock_core.policy import decide, load_policy, policy_hash
from verdock_core.receipts import ReceiptLog, create_seed, load_seed
from verdock_core import Refused

from .paypal import GatewayError

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

    def receipt(self, step, action, params, success):
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

    def reconcile(self, case, known_refund_id):
        """Resolve an UNKNOWN from PayPal's own record of a known refund id. Reads only; never resends."""
        result = self.check(case, known_refund_id, {"proposed": "reconcile"})
        if result.state == VERIFIED and case.id in self.held:
            self.invariants.commit(self.held.pop(case.id))
        return result
