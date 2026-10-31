"""Evidence agent and deadline watch for PayPal disputes.

Evidence is built only from records Clearwake read (order, capture, trackers, signed mandate receipt).
Nothing is invented: every evidence item names the record it came from.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


@dataclass
class DisputeView:
    id: str
    status: str
    reason: str
    amount_minor: int
    currency: str
    due: datetime | None
    transactions: list
    raw: dict = field(repr=False, default_factory=dict)

    @classmethod
    def from_paypal(cls, data):
        money = data.get("dispute_amount") or {}
        value = Decimal(money.get("value", "0"))
        return cls(data["dispute_id"], data.get("status", ""), data.get("reason", ""), int(value * 100), money.get("currency_code", "USD"),
                   parse_time(data.get("seller_response_due_date")),
                   [t.get("seller_transaction_id") for t in data.get("disputed_transactions", []) if t.get("seller_transaction_id")], data)


def deadline(view, now=None, escalate_before_seconds=24 * 3600):
    """Countdown to seller_response_due_date. 'soon' escalates to the approval inbox before it lapses."""
    if view.due is None:
        return {"seconds_left": None, "state": "no deadline given"}
    left = int((view.due - (now or datetime.now(timezone.utc))).total_seconds())
    return {"seconds_left": left, "state": "lapsed" if left <= 0 else "soon" if left <= escalate_before_seconds else "ok"}


def evidence_pack(view, order=None, trackers=(), mandate_receipt=None):
    """Return (evidences for PayPal, sources shown on screen). Only facts read from records."""
    evidences, sources = [], []
    shipped = [t for t in trackers if t.get("status") in ("SHIPPED", "DELIVERED")]
    if shipped and "NOT_RECEIVED" in view.reason:
        evidences.append({"evidence_type": "PROOF_OF_FULFILLMENT",
                          "evidence_info": {"tracking_info": [{"carrier_name": t["carrier"], "tracking_number": t["number"]} for t in shipped]},
                          "notes": "Tracking from the PayPal order record."})
        sources += [f"PayPal order {order.get('id') if order else '?'} tracker {t['number']} ({t['status']})" for t in shipped]
    if mandate_receipt and view.reason in ("UNAUTHORISED", "UNAUTHORIZED", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"):
        evidences.append({"evidence_type": "OTHER", "notes": (
            f"Signed purchase mandate from the buyer's agent, linked to PayPal order {mandate_receipt['order_id']}: owner {mandate_receipt['owner']}, "
            f"item {mandate_receipt['item']}, price {mandate_receipt['price']}, cap {mandate_receipt['cap']}. Ed25519 receipt {mandate_receipt['digest'][:16]}..., "
            "verifiable offline with the buyer agent's public key.")[:2000]})
        sources.append(f"Mandate receipt {mandate_receipt['digest'][:16]} (verified offline before use)")
    return evidences, sources


def propose(view, evidences, refund_limit_minor, clock):
    """What the merchant side should do. The policy layer still decides; this is only the proposal."""
    if clock["state"] == "lapsed":
        return "escalate", "The response deadline has passed. A person must review it."
    if evidences:
        return ("escalate", "Evidence is ready but the deadline is close; a person approves sending it.") if clock["state"] == "soon" else (
            "provide_evidence", f"{len(evidences)} evidence item(s) from the record.")
    if view.amount_minor <= refund_limit_minor:
        return "accept_and_refund", "No evidence that answers this reason, and the amount is within the refund limit."
    return "escalate", "No evidence that answers this reason, and the amount is above the refund limit."


DECISIONS = ("settle_by_offer", "refund_within_limit", "fight_with_evidence", "escalate")
UNAUTHORISED = ("UNAUTHORISED", "UNAUTHORIZED")


def dispute_decision(policy, view, evidences, clock, inquiry):
    """The policy's decision for one dispute: (action, reason, amount_minor). The model's proposal never changes it.

    Fight only when the records answer the reason. Otherwise settle in conversation while the case is still an
    inquiry (no claim, so no PayPal dispute fee), up to the owner's offer limit, a partial offer above it.
    After escalation, refund within the claim limit. Everything else, and anything near its deadline, goes to the owner.
    """
    from verdock_core.policy import decide
    if clock["state"] in ("soon", "lapsed"):
        return "escalate", f"Deadline {clock['state']}: the owner decides.", 0
    if evidences:
        return "fight_with_evidence", f"{len(evidences)} record(s) answer this reason.", 0
    if view.reason in UNAUTHORISED:
        return "escalate", "Unauthorised with no signed mandate on record: the owner decides.", 0
    if inquiry:
        full = decide(policy, "make_offer", view.amount_minor, view.currency)
        if full.allowed:
            return "settle_by_offer", "Full refund offer within the owner's offer limit.", view.amount_minor
        limit = policy["operations"].get("make_offer", {}).get("max_amount_minor", 0)
        if full.reason == "above limit" and limit:
            return "settle_by_offer", f"Partial offer: the owner's offer limit is {limit / 100:.2f} {view.currency}.", limit
        return "escalate", f"Policy does not allow an offer ({full.reason}).", 0
    claim = decide(policy, "accept_claim", view.amount_minor, view.currency)
    if claim.allowed:
        return "refund_within_limit", "Refund within the owner's claim limit.", view.amount_minor
    return "escalate", f"Above the owner's refund limit ({claim.reason}).", 0
