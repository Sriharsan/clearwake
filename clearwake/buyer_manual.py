"""Manual buyer mode: the same buyer agent, with a person or another agent's browser as its hands.

The buyer agent still decides everything (mandate, dispute rule). Where it needs a buyer browser action (approve the checkout link,
open the dispute, accept or counter an offer) it prints one JSON line describing the exact action, then polls PayPal's own records
until the effect appears. Nothing is counted as done until PayPal shows it. Every request and every confirmed effect is receipted
in the buyer log, labelled "buyer step performed through the lead's browser", exactly like the Playwright mode.

The class has the same methods as buyer_browser.ResolutionCenter, so the batch loop does not know which one it is driving.
"""
import json
import time

from .buyer_browser import NeedsHuman, Thread, minor, sandbox_site

LABEL = "buyer step performed through the lead's browser"
REASON_UI = {"item_not_received": "I didn't receive my item", "not_as_described": "My item is significantly not as described",
             "missing_items": "An item is missing from my order"}


def thread_from_record(dispute_id, record):
    """What the buyer agent reads, taken from PayPal's own dispute record instead of the page."""
    messages = [("seller" if str(m.get("posted_by", "")).upper() == "SELLER" else "buyer", str(m.get("content", ""))) for m in record.get("messages", []) or []]
    offer = (record.get("offer") or {}).get("seller_offered_amount") or {}
    status, stage = record.get("status", ""), record.get("dispute_life_cycle_stage", "")
    requested = (record.get("dispute_amount") or {}).get("value")
    thread = Thread(dispute_id, status=status, resolved=status == "RESOLVED", escalated=bool(stage) and stage != "INQUIRY", messages=messages,
                    offer_minor=minor(offer["value"]) if offer.get("value") else None, currency=offer.get("currency_code", "USD"),
                    requested_minor=minor(requested) if requested else None)
    thread.can_accept = thread.offer_minor is not None and status == "WAITING_FOR_BUYER_RESPONSE"
    thread.can_escalate = stage == "INQUIRY" and status != "RESOLVED"
    thread.text_sha256 = __import__("hashlib").sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    return thread


class ManualBuyer:
    def __init__(self, gateway, recorder, rule, out=print, timeout_s=900, poll_s=5, sleep=time.sleep, clock=time.monotonic, home=None):
        self.gateway, self.rec, self.rule, self.out = gateway, recorder, rule, out
        self.timeout_s, self.poll_s, self.sleep, self.clock = timeout_s, poll_s, sleep, clock
        self.home = home or sandbox_site().home_url
        self.n, self.decision, self.site = 0, None, sandbox_site()

    def note_decision(self, decision):
        self.decision = {"action": decision.action, "code": decision.code, "detail": decision.detail, "percent": decision.percent}

    # plumbing
    def emit(self, context, action, **fields):
        self.n += 1
        line = {"n": self.n, "action": action, **fields, "dispute_rule": self.rule.to_dict(), "decision": self.decision, "performed_through": LABEL}
        self.out(json.dumps(line, ensure_ascii=False))
        self.rec.step(None, context, f"{action}.requested", {"action_n": self.n, "label": LABEL, **{k: v for k, v in fields.items() if k in ("order_id", "dispute_id", "reason", "url")}}, True)

    def wait(self, context, action, check, params):
        """Poll PayPal until check() returns a truthy effect. A timeout is receipted as failed and stops for a person."""
        end = self.clock() + self.timeout_s
        while True:
            try:
                effect = check()
            except Exception:   # a read that fails is not an effect; keep polling until the timeout
                effect = None
            if effect:
                self.rec.step(None, context, action, {**params, "effect_confirmed_by": "PayPal record", "label": LABEL}, True)
                return effect
            if self.clock() >= end:
                self.rec.step(None, context, f"{action}.timeout", {**params, "label": LABEL, "waited_s": self.timeout_s}, False)
                raise NeedsHuman(f"PayPal's record does not show the effect of '{action}' yet.",
                                 [f"Do the action printed above as the sandbox buyer.", "Then run the same command again with --resume."])
            self.sleep(self.poll_s)

    # steps
    def approve_order(self, order_id, url, status):
        """status() reads the order from PayPal. Already approved (a resumed run) prints nothing."""
        if status() in ("APPROVED", "COMPLETED"):
            return True
        self.emit(order_id, "approve_order", order_id=order_id, url=url, instruction="Open the link as the sandbox buyer and approve the payment.")
        return self.wait(order_id, "approve_order", lambda: status() in ("APPROVED", "COMPLETED"), {"order_id": order_id})

    def _find(self, capture_id):
        for item in self.gateway.disputes():
            if capture_id in [t.get("seller_transaction_id") for t in item.get("disputed_transactions", [])]:
                return item["dispute_id"]
        return None

    def open_dispute(self, transaction_id, reason, message, amount=None, context=None):
        context = context or transaction_id
        existing = self._find(transaction_id)
        if existing:   # resumed: the dispute is already there
            self.rec.step(None, context, "open_dispute", {"dispute_id": existing, "transaction": transaction_id, "reason": reason, "already_present": True, "label": LABEL}, True)
            return {"dispute_id": existing}
        self.emit(context, "open_dispute", order_id=context, transaction=transaction_id, url=self.home, reason=reason, reason_ui=REASON_UI[reason],
                  amount=str(amount) if amount is not None else "", message=message)
        found = self.wait(context, "open_dispute", lambda: self._find(transaction_id), {"transaction": transaction_id, "reason": reason})
        return {"dispute_id": found}

    def read_thread(self, dispute_id, context=None):
        thread = thread_from_record(dispute_id, self.gateway.dispute(dispute_id))
        self.rec.step(None, context or dispute_id, "read_thread", {"dispute_id": dispute_id, "status": thread.status[:60], "source": "PayPal dispute record",
                      "offer_minor": thread.offer_minor if thread.offer_minor is not None else -1, "seller_messages": sum(1 for w, _ in thread.messages if w == "seller")}, True)
        return thread

    def accept_offer(self, dispute_id, context=None):
        context = context or dispute_id
        if thread_from_record(dispute_id, self.gateway.dispute(dispute_id)).resolved:
            return True
        self.emit(context, "accept_offer", dispute_id=dispute_id, url=self.home, instruction="Open the dispute and click Accept offer.")

        def done():
            record = self.gateway.dispute(dispute_id)
            return record.get("status") in ("RESOLVED", "UNDER_REVIEW") or any(m.get("reason") == "DISPUTE_SETTLEMENT" for m in record.get("fund_movements", []) or [])
        return self.wait(context, "accept_offer", done, {"dispute_id": dispute_id})

    def counter(self, dispute_id, message, context=None):
        context = context or dispute_id
        before = sum(1 for w, _ in thread_from_record(dispute_id, self.gateway.dispute(dispute_id)).messages if w == "buyer")
        self.emit(context, "counter", dispute_id=dispute_id, url=self.home, message=message, instruction="Reply to the seller with exactly this message.")
        return self.wait(context, "counter", lambda: sum(1 for w, _ in thread_from_record(dispute_id, self.gateway.dispute(dispute_id)).messages if w == "buyer") > before,
                         {"dispute_id": dispute_id})

    def escalate(self, dispute_id, to="owner", rule=None, why="", context=None):
        """Handing the case to the owner needs no browser action: the receipt is the step. A claim needs the owner's rule and a browser action."""
        context = context or dispute_id
        if to == "owner":
            self.rec.step(None, context, "escalate_to_owner", {"dispute_id": dispute_id, "why": why[:200], "label": LABEL}, True)
            return True
        if rule is None or not getattr(rule, "escalate_to_claim", False):
            self.rec.step(None, context, "escalate_to_claim.refused", {"dispute_id": dispute_id}, False)
            raise PermissionError("The owner's dispute rule does not let the agent escalate to a claim.")
        self.emit(context, "escalate_to_claim", dispute_id=dispute_id, url=self.home)
        return self.wait(context, "escalate_to_claim", lambda: self.gateway.dispute(dispute_id).get("dispute_life_cycle_stage") not in ("INQUIRY", None), {"dispute_id": dispute_id})
