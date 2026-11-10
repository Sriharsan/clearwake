"""Agent to agent batch: ten orders bought by the buyer agent, ten disputes opened by it, negotiated with the merchant agent.

The buyer agent (clearwake/buyer.py rule, clearwake/buyer_browser.py door) and the merchant agent (MerchantSwarm) never talk to
each other directly. They talk through the dispute: the buyer through the Resolution Center page, the merchant through PayPal's
Disputes API (send-message, make-offer). Every outcome is read back from the dispute record, never from what either agent says.

Two worlds share one negotiation loop:
  Rehearsal: RehearsalGateway (a local fake provider) plus the local stand-in page in tests/fixtures/resolution_center. Runs offline.
  Sandbox:   the real PayPal sandbox. Needs Sri's one time login in the persistent browser profile.
"""
from dataclasses import dataclass, field, replace
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import tempfile
import time
import uuid

from verdock_core.outcome import MISMATCH, PENDING, UNKNOWN, VERIFIED
from verdock_core.receipts import verify_log

from . import dispatch
from .buyer import price_verdict
from .buyer import BuyerAgent, DisputeRule, Mandate, check, check_draft, decide_offer, final_action, mandate_receipt, reason_key
from .buyer_browser import NeedsHuman, Recorder, ResolutionCenter, StepFailed, blocked, fixture_site, open_buyer_log, sandbox_site, visible
from .counter import Counter
from .models import Adapter
from .paypal import GatewayError, Offline, ProviderRefused, RehearsalGateway
from .swarm import MerchantSwarm

ROOT = Path(__file__).resolve().parent.parent
PHOTO = ROOT / "fixtures" / "dispatch" / "photos" / "test-photo-3-notebooks.jpg"
PHOTO_NOTE = "test photo, CC0, not a real parcel"
TRACKER = {"carrier": "UPS", "status": "SHIPPED"}
NOT_RECEIVED, NOT_AS_DESCRIBED = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
API_REASON = {"item_not_received": NOT_RECEIVED, "missing_items": NOT_RECEIVED, "not_as_described": NOT_AS_DESCRIBED, "unauthorised": "UNAUTHORISED"}
RULE = DisputeRule(accept_min_percent=80, accept_min_percent_not_as_described=80, counter_min_percent=40, max_counters=1)
MAX_ROUNDS = 5

# Outcome classes, as reported
SETTLED, EVIDENCE, BUYER_OWNER, MERCHANT_OWNER, PENDING_STATE, ERROR = (
    "settled_inquiry_no_fee", "evidence_sent", "escalated_to_buyer_owner", "escalated_to_merchant_owner", "pending", "error")


@dataclass(frozen=True)
class CaseSpec:
    n: int
    scenario: str            # what the case is, for the table
    reason: str              # item_not_received, missing_items or not_as_described
    product: str
    quantity: int
    ask_minor: int           # the refund the buyer asks for
    message: str
    tracked: bool = False    # the merchant adds UPS tracking
    proof: bool = False      # the merchant records dispatch proof (photo counted by SAM) at packing
    owner_approves: bool = False   # rehearsal only: the merchant owner approves the offer in the inbox


CASES = (   # case l: 4 item not received, 4 not as described, 2 unauthorised
    CaseSpec(1, "Item not received, tracking shows shipped", "item_not_received", "notebook-a5", 1, 900, "My notebook never arrived.", tracked=True),
    CaseSpec(2, "Item not received, no tracking, full amount", "item_not_received", "notebook-a5", 1, 900, "My notebook never arrived."),
    CaseSpec(3, "Item not received, no tracking, small amount", "item_not_received", "notebook-a5", 1, 300, "My notebook never arrived."),
    CaseSpec(4, "Item not received, no tracking, small amount", "item_not_received", "notebook-a5", 1, 200, "My notebook never arrived."),
    CaseSpec(5, "Not as described, small amount", "not_as_described", "notebook-a5", 1, 300, "The paper is not the grid I ordered."),
    CaseSpec(6, "Not as described, small amount", "not_as_described", "notebook-a5", 1, 150, "The cover is scratched."),
    CaseSpec(7, "Not as described, full amount, owner approves a partial offer", "not_as_described", "notebook-a5", 1, 900, "The cover is a different colour.", owner_approves=True),
    CaseSpec(8, "Not as described, small amount", "not_as_described", "notebook-a5", 1, 250, "The pages are a different size."),
    CaseSpec(9, "Unauthorised, signed mandate on record, full amount", "unauthorised", "notebook-a5", 1, 900, "I do not recognise this payment."),
    CaseSpec(10, "Unauthorised, signed mandate on record, small amount", "unauthorised", "notebook-a5", 1, 300, "I do not recognise this payment."),
)

CASES_DISPATCH = (
    CaseSpec(1, "Item not received, tracking shows shipped", "item_not_received", "notebook-a5", 1, 900, "My notebook never arrived.", tracked=True),
    CaseSpec(2, "Item not received, no tracking, full amount", "item_not_received", "notebook-a5", 1, 900, "My notebook never arrived."),
    CaseSpec(3, "Item not received, no tracking, small amount", "item_not_received", "notebook-a5", 1, 300, "My notebook never arrived."),
    CaseSpec(4, "Item not received, no tracking, small amount", "item_not_received", "notebook-a5", 1, 200, "My notebook never arrived."),
    CaseSpec(5, "Item missing, dispatch proof counted 3 of 3", "missing_items", "notebook-a5", 3, 900, "Only 2 of 3 notebooks arrived.", tracked=True, proof=True),
    CaseSpec(6, "Item missing, dispatch proof counted 3 of 3", "missing_items", "notebook-a5", 3, 900, "Only 2 of 3 notebooks arrived.", tracked=True, proof=True),
    CaseSpec(7, "Item missing, no dispatch proof, small amount", "missing_items", "notebook-a5", 3, 250, "Only 2 of 3 notebooks arrived."),
    CaseSpec(8, "Not as described, small amount", "not_as_described", "notebook-a5", 1, 300, "The paper is not the grid I ordered."),
    CaseSpec(9, "Not as described, full amount, owner approves a partial offer", "not_as_described", "notebook-a5", 1, 900, "The cover is a different colour.", owner_approves=True),
    CaseSpec(10, "Not as described, small amount", "not_as_described", "notebook-a5", 1, 150, "The cover is scratched."),
)

def money(minor):
    return f"{Decimal(minor) / 100:.2f}"


def buyer_mandate(owner="Buyer owner"):
    return Mandate(owner, 100000, 10000, ("clearwake-demo-store",), ("home", "stationery"), dispute_rule=RULE, max_over_market_percent=25)


def recorded_price(product, tolerance):
    """Rehearsal price reference: a recorded fixture (the catalogue price itself). No credits are used and nothing is called."""
    from .market import MarketCheck, _within
    return MarketCheck(product["price_minor"], "recorded.fixture", product["name"], None, _within(product["price_minor"], product["price_minor"], tolerance),
                       0, "recorded fixture", int(time.time() * 1000))


def live_price(product, tolerance):
    """Sandbox price reference through Channel3. Live calls are capped by CHANNEL3_MAX_CALLS (default 0: refused without a call, flagged)."""
    from .market import price_check
    return price_check(product["name"], product["price_minor"], "USD", tolerance)


# Reading the outcome back from PayPal's own record ----------------------------------------------------------------------------

def refund_seen(record):
    """The refund PayPal's dispute record shows, as minor units, or 0. Read from the record, not from either agent."""
    out = (record.get("dispute_outcome") or {}).get("amount_refunded") or {}
    if out.get("value"):
        return int(Decimal(out["value"]) * 100)
    for move in record.get("fund_movements", []) or []:
        if move.get("party") == "BUYER" and move.get("reason") == "DISPUTE_SETTLEMENT" and (move.get("amount") or {}).get("value"):
            return int(Decimal(move["amount"]["value"]) * 100)
    for refund in (record.get("refund_details") or {}).get("transactions", []) or []:
        if (refund.get("amount") or {}).get("value"):
            return int(Decimal(refund["amount"]["value"]) * 100)
    return 0


def model_stats(receipts_path, dispute_id):
    """Merchant model calls for one dispute from the merchant agent's signed receipts: {"calls", "ms", "scripted"}.

    Uses the per call receipts (clearwake.model.call) when they exist, otherwise any receipt that names a model."""
    new, old = {"calls": 0, "ms": 0, "scripted": 0, "seen": False}, {"calls": 0, "ms": 0, "scripted": 0}
    path = Path(receipts_path)
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            body = json.loads(line)
        except ValueError:
            continue
        params = body.get("params", {})
        if params.get("dispute") != dispute_id:
            continue
        if body.get("action_id") == "clearwake.model.call":
            new["seen"] = True
            if params.get("backend") == "scripted" or params.get("model") == "scripted":
                new["scripted"] += 1
            else:
                new["calls"] += 1
                new["ms"] += max(0, int(params.get("latency_ms", 0)))
        elif "model" in params:
            old["scripted" if params["model"] == "scripted" else "calls"] += 1
    return new if new["seen"] else old


def model_calls(receipts_path, dispute_id):
    stats = model_stats(receipts_path, dispute_id)
    return stats["calls"], stats["scripted"]


def classify(final, merchant_result, buyer_end, settled):
    """One outcome class per case, from PayPal's record and the end state of the negotiation."""
    if settled:
        return SETTLED
    if merchant_result is not None and merchant_result.state == "awaiting approval":
        return MERCHANT_OWNER
    if buyer_end == "escalated_owner":
        return EVIDENCE if (merchant_result and merchant_result.proposal.get("decided") == "fight_with_evidence") else BUYER_OWNER
    return PENDING_STATE


# Worlds -----------------------------------------------------------------------------------------------------------------------

class Rehearsal:
    """Fake provider plus the local stand-in page. Offline. Every record is invented; nothing here is PayPal."""
    mode, label = "rehearsal", "rehearsal: local fake provider and a local stand-in page, offline, nothing is PayPal"
    price = staticmethod(recorded_price)
    price_source = "recorded fixture"

    def __init__(self, work, page, now=None):
        self.work, self.page, self.site = Path(work), page, fixture_site()
        self.gateway = RehearsalGateway(self.work / "provider.sqlite3")
        self.orders = {}

    def buy(self, spec, product, total_minor, run):
        order_id, capture_id = f"ORDER-REH-{run}-{spec.n:02d}", f"CAP-REH-{run}-{spec.n:02d}"
        self.orders[order_id] = capture_id
        if spec.tracked:
            self.trackers = {order_id: [{"number": f"SYNTH1Z{run.upper()}{spec.n:04d}", **TRACKER}]}
        self.page.evaluate("(t) => RC.transactions.push(t)", capture_id)
        return {"order_id": order_id, "capture_id": capture_id, "trackers": [{"number": f"SYNTH1Z{run.upper()}{spec.n:04d}", **TRACKER}] if spec.tracked else [],
                "how": "rehearsal order, no PayPal call"}

    def find_dispute(self, capture_id, page_id, reason, ask_minor, message):
        due = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat().replace("+00:00", "Z")
        return self.gateway.open_dispute(capture_id, API_REASON[reason], money(ask_minor), due, message, stage="INQUIRY")["dispute_id"]

    def after_merchant(self, api_id, page_id):
        """Carry the merchant's side of the dispute record onto the stand-in page, as PayPal's site would show it."""
        record = self.gateway.dispute(api_id)
        if record.get("offer") and record["status"] == "WAITING_FOR_SELLER_RESPONSE" and record.get("buyer_countered"):
            record = self.gateway._update_dispute(api_id, status="WAITING_FOR_BUYER_RESPONSE")   # a standing offer stays open after a counter
        sellers = [m["content"] for m in record.get("messages", []) if m.get("posted_by") == "SELLER"]
        offer = record.get("offer")
        patch = {"messages": sellers, "status": record["status"],
                 "offer": {"amount": offer["seller_offered_amount"]["value"], "currency": offer["seller_offered_amount"]["currency_code"]} if offer else None}
        self.page.evaluate("([id, patch]) => RC.merchantSync(id, patch)", [page_id, patch])

    def after_buyer(self, api_id, page_id, action):
        """Carry what the buyer pressed on the page into the fake provider's record."""
        if action == "accept":
            self.gateway.buyer_accepts_offer(api_id)
        elif action == "claim":
            self.gateway.buyer_escalates(api_id)
        elif action == "counter":
            text = [e for e in self.page.evaluate("RC.log") if e["type"] == "message" and e["id"] == page_id][-1]["text"]
            record = self.gateway.dispute(api_id)
            self.gateway._update_dispute(api_id, status="WAITING_FOR_SELLER_RESPONSE", buyer_countered=True,
                                         messages=record.get("messages", []) + [{"posted_by": "BUYER", "content": text}])

    def read(self, api_id):
        return self.gateway.dispute(api_id)

    def approve(self, swarm, result, spec):
        if spec.owner_approves and result.approval_id:
            swarm.approvals.approve(result.approval_id, "rehearsal owner")
            return result.approval_id
        return None


class Sandbox:
    """The real PayPal sandbox. The buyer approves orders and works the Resolution Center in the persistent browser profile."""
    mode, label = "sandbox", "real PayPal sandbox: sandbox buyer in a real browser, merchant agent on the Disputes API"
    price = staticmethod(live_price)
    price_source = "Channel3"

    def __init__(self, gateway, page, site=None, manual=None, state=None):
        self.gateway, self.page, self.site = gateway, page, site or sandbox_site()
        self.manual, self.state = manual, state if state is not None else {}

    def _created(self, n):
        def remember(order_id):   # an order that exists but is not yet approved is kept, so a resumed run does not buy twice
            self.state.setdefault("cases", {}).setdefault(str(n), {})["order_id"] = order_id
            if self.state.get("save"):
                self.state["save"]()
        return remember

    def buy(self, spec, product, total_minor, run):
        saved = self.state.get("cases", {}).get(str(spec.n))
        if saved and saved.get("capture_id"):   # resumed: the order is already paid, do not buy again
            return {**saved, "how": "resumed: order already captured in the PayPal sandbox"}
        approver = (lambda oid, url, status: self.manual.approve_order(oid, url, status)) if self.manual else None
        order_id, capture_id = create_and_pay(self.gateway, self.page, product, spec.quantity, total_minor, self.site, approver=approver,
                                              existing=(saved or {}).get("order_id"), on_created=self._created(spec.n))
        trackers = []
        if spec.tracked:
            number = f"SYNTH1Z{run.upper()}{spec.n:04d}"
            self.gateway.add_tracking(order_id, capture_id, number, "UPS", str(uuid.uuid4()))
            trackers = [{"number": number, **TRACKER}]
        bought = {"order_id": order_id, "capture_id": capture_id, "trackers": trackers,
                  "how": "real sandbox order approved in the buyer's browser, captured by the merchant gateway" if not self.manual
                  else "real sandbox order approved in the lead's browser (manual buyer mode), captured by the merchant gateway"}
        self.state.setdefault("cases", {})[str(spec.n)] = bought
        if self.manual and self.state.get("save"):
            self.state["save"]()
        return bought

    def find_dispute(self, capture_id, page_id, reason, ask_minor, message):
        """The id the Resolution Center shows is PayPal's dispute id. Read the list to be sure it is there for this payment."""
        for _ in range(12):
            try:
                if page_id:
                    record = self.gateway.dispute(page_id)
                    if capture_id in [t.get("seller_transaction_id") for t in record.get("disputed_transactions", [])]:
                        return page_id
            except (GatewayError, ProviderRefused):
                pass
            for item in self.gateway.disputes():
                if capture_id in [t.get("seller_transaction_id") for t in item.get("disputed_transactions", [])]:
                    return item["dispute_id"]
            time.sleep(5)
        raise LookupError("PayPal's dispute list does not show a dispute for this payment yet.")

    def after_merchant(self, api_id, page_id):
        return None

    def after_buyer(self, api_id, page_id, action):
        return None

    def read(self, api_id):
        return self.gateway.dispute(api_id)

    def approve(self, swarm, result, spec):
        return None   # the merchant owner's approval stays manual against the real sandbox


def order_payload(product, quantity, total_minor, return_url):
    unit = Decimal(product["price_minor"]) / 100
    total = f"{Decimal(total_minor) / 100:.2f}"
    if Decimal(total) != unit * quantity:
        raise ValueError("The order total must equal the unit price times the quantity.")
    return {"intent": "CAPTURE", "purchase_units": [{
        "reference_id": product["id"], "description": product["name"][:120],
        "amount": {"currency_code": "USD", "value": total, "breakdown": {"item_total": {"currency_code": "USD", "value": total}}},
        "items": [{"name": product["name"][:120], "sku": product["id"], "quantity": str(quantity), "category": "PHYSICAL_GOODS",
                   "unit_amount": {"currency_code": "USD", "value": f"{unit:.2f}"}}]}],
        "payment_source": {"paypal": {"experience_context": {"user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING",
                                                             "return_url": return_url, "cancel_url": return_url}}}}


def create_and_pay(gateway, page, product, quantity, total_minor, site=None, timeout_s=600, return_url="http://127.0.0.1:8842/sandbox-approved", approver=None, existing=None, on_created=None):
    """Orders v2 create (merchant app), the buyer approves in the persistent browser, the merchant gateway captures.

    Mirrors scripts/sandbox_setup.py. The approval page is a PayPal page: the agent clicks only the approve button; it types nothing.
    If the button cannot be found the window stays open for Sri to click it, and the order is polled until PayPal shows APPROVED."""
    if total_minor > 5000:
        raise ValueError("A sandbox batch order is capped at USD 50.00.")
    payload = order_payload(product, quantity, total_minor, return_url)
    gateway._access_token()
    order = gateway.order(existing) if existing else gateway._request("/v2/checkout/orders", payload, str(uuid.uuid4()))
    if on_created:
        on_created(order["id"])
    link = next((i["href"] for i in order.get("links", []) if i.get("rel") in ("payer-action", "approve")), "")
    if not link.startswith("https://www.sandbox.paypal.com/") and order.get("status") not in ("APPROVED", "COMPLETED"):
        raise GatewayError("PayPal did not return a sandbox approval link. Nothing was captured.")
    if approver is not None:   # manual buyer mode: someone else's browser approves; PayPal's record says when
        approver(order["id"], link, lambda: gateway.order(order["id"]).get("status"))
        if gateway.order(order["id"]).get("status") == "COMPLETED":
            capture = gateway.order(order["id"])["purchase_units"][0]["payments"]["captures"][0]
            return order["id"], capture["id"]
        result = gateway.capture_order(order["id"], str(uuid.uuid4()))
        capture = result["purchase_units"][0]["payments"]["captures"][0]
        if capture.get("status") != "COMPLETED":
            raise GatewayError(f"Capture status {capture.get('status')}.")
        return order["id"], capture["id"]
    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    end, clicked = time.monotonic() + timeout_s, 0
    while time.monotonic() < end:
        status = gateway.order(order["id"]).get("status")
        if status == "APPROVED":
            break
        if status == "COMPLETED":
            raise GatewayError("The order is already captured.")
        why = blocked(page)
        if why:
            raise NeedsHuman("PayPal shows a challenge (" + why + ") on the approval page. Approve the order by hand in the open window.",
                             ["Approve the sandbox order in the open browser window as the sandbox buyer.", "The batch continues by itself once PayPal shows it approved."])
        button = page.get_by_role("button", name=re.compile(r"^\s*(pay now|complete purchase|continue)\s*$", re.I))
        if clicked < 3 and visible(button):
            clicked += 1
            try:
                button.first.click(timeout=5000)
            except Exception:
                pass
        time.sleep(3)
    else:
        raise TimeoutError("PayPal did not show the order approved in time.")
    result = gateway.capture_order(order["id"], str(uuid.uuid4()))
    capture = result["purchase_units"][0]["payments"]["captures"][0]
    if capture.get("status") != "COMPLETED":
        raise GatewayError(f"Capture status {capture.get('status')}.")
    return order["id"], capture["id"]


# The negotiation --------------------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, world, swarm, rc, rec, mandate, log, adapter_label, clock=time.perf_counter, counter=None, buyer_adapter=None, price_fn=None):
        self.price_fn = price_fn
        self.world, self.swarm, self.rc, self.rec, self.mandate, self.log = world, swarm, rc, rec, mandate, log
        self.buyer_adapter = buyer_adapter or Adapter("scripted")
        self.adapter_label, self.clock = adapter_label, clock
        self.counter = counter or Counter("recorded")
        self.catalog = BuyerAgent(mandate, Adapter("scripted"))   # catalog and the mandate check; the choice itself is scripted

    def ask_model(self, ctx, name, system, user, fields, scripted, row):
        """One buyer model call. Returns the proposal; the call is receipted with model, latency and prompt hash."""
        proposal = self.buyer_adapter.propose(system, user, fields, scripted)
        call = proposal.call or {}
        live = proposal.backend != "scripted"
        if live:
            row["buyer_model_calls"] = row.get("buyer_model_calls", 0) + 1
            row["buyer_model_ms"] = row.get("buyer_model_ms", 0) + max(0, int(call.get("latency_ms", 0)))
        else:
            row["buyer_scripted_decisions"] = row.get("buyer_scripted_decisions", 0) + 1
        return proposal, live

    def draft(self, ctx, spec, product, total, row):
        """The buyer agent drafts its dispute message. Code accepts it only if it states nothing but the amount asked."""
        what = {"item_not_received": "the item did not arrive", "missing_items": "part of the order is missing",
                "not_as_described": "the item is not as described", "unauthorised": "the owner does not recognise this payment"}[spec.reason]
        proposal, live = self.ask_model(
            ctx, "model_draft", "You write the first message of a PayPal dispute for a buyer. Be polite and factual in two or three sentences. "
            "State only the facts given. Do not invent amounts, dates, ids or promises. Do not add links.",
            f"Item: {product['name']}. Order total USD {money(total)}. Refund asked: USD {money(spec.ask_minor)}. Problem: {what}. Buyer's note: {spec.message}",
            ["message"], lambda: {"message": spec.message}, row)
        text = (proposal.value or {}).get("message")
        ok, problems = check_draft(text, spec.ask_minor)
        used = "model" if live and ok else "scripted rule" if not live else "fallback to the owner's note"
        message = text.strip() if live and ok else spec.message
        call = proposal.call or {}
        self.rec.step(None, ctx, "model_draft", {"model": proposal.model, "backend": proposal.backend, "latency_ms": call.get("latency_ms", -1),
                      "prompt_sha256": call.get("prompt_sha256", ""), "used": used, "problems": "; ".join(problems)[:200],
                      "message_sha256": hashlib.sha256(message.encode()).hexdigest()}, True)
        row["draft"] = {"model": proposal.model, "used": used, "message": message}
        return message

    def choose(self, ctx, spec, step, facts, row):
        """The rule decides what is allowed; a model may pick among the allowed actions (never a bolder one); code takes the final say."""
        proposal, live = self.ask_model(
            ctx, "model_decision", "You are a buyer's agent. The owner's rule already limits what you may do. Choose accept, counter or escalate. "
            "Choose escalate if anything looks wrong.",
            f"Asked USD {money(spec.ask_minor)}. Merchant offer: {('USD ' + money(facts['offer_minor'])) if facts['offer_minor'] is not None else 'none'}. "
            f"Merchant answered with records instead of an offer: {facts['evidence']}. The owner's rule says: {step.action} ({step.code}).",
            ["action"], lambda: {"action": step.action}, row)
        proposed = (proposal.value or {}).get("action") if live else step.action
        proposed = proposed if isinstance(proposed, str) else "none"
        final = final_action(step.action, proposed) if live else step.action
        call = proposal.call or {}
        self.rec.step(None, ctx, "model_decision", {"model": proposal.model, "backend": proposal.backend, "latency_ms": call.get("latency_ms", -1),
                      "prompt_sha256": call.get("prompt_sha256", ""), "proposed": proposed[:20], "rule_action": step.action, "final": final,
                      "overridden": bool(live and proposed != final), "rule_code": step.code}, True)
        row.setdefault("buyer_model", []).append({"proposed": proposed, "rule": step.action, "final": final, "model": proposal.model})
        return final

    def case(self, spec, run_id, spent_minor):
        started = self.clock()
        row = {"n": spec.n, "scenario": spec.scenario, "reason": spec.reason, "ask": money(spec.ask_minor), "steps": []}
        merchant_result, buyer_end, counters = None, "", 0
        try:
            product = self.catalog.products[spec.product]
            total = product["price_minor"] * spec.quantity
            priced = {**product, "price_minor": total}
            decision = check(self.mandate, self.catalog.merchant["id"], self.catalog.currency, priced, spent_minor)
            row["mandate"] = decision.reason
            if not decision.allowed:
                row.update(outcome=ERROR, detail="The mandate refused the purchase: " + decision.reason, seconds=round(self.clock() - started, 2), buyer_steps=0)
                return row
            mc = (self.price_fn or self.world.price)(product, self.mandate.max_over_market_percent)
            verdict = price_verdict(self.mandate, mc)
            row["price_reference"] = {**mc.to_receipt_params(), "verdict": verdict["action"], "why": verdict["reason"], "source": self.world.price_source}
            row["price_credits"] = mc.credits_used
            self.rec.step(None, f"case{spec.n}", "price_reference", {**{k: v for k, v in mc.to_receipt_params().items() if v is not None},
                                                                     "verdict": verdict["action"], "why": verdict["reason"][:200], "item": product["id"]}, verdict["action"] != "refuse")
            if verdict["action"] == "refuse":
                row.update(outcome=ERROR, detail="The mandate's price rule refused the purchase: " + verdict["reason"], seconds=round(self.clock() - started, 2), buyer_steps=0)
                return row
            bought = self.world.buy(spec, product, total, run_id)
            kept = getattr(self.world, "state", {}).get("cases", {}).get(str(spec.n), {})
            if not kept.get("mandate"):
                kept["mandate"] = mandate_receipt(self.log, self.mandate, priced, self.catalog.merchant["id"], bought["order_id"], price=mc)
            digest = kept["mandate_digest"] = kept["mandate"]["digest"]
            self.rec.mandate_digest = digest
            row.update(order_id=bought["order_id"], capture_id=bought["capture_id"], paid=money(total), mandate_receipt=digest[:16], bought_how=bought["how"])
            order = {"id": bought["order_id"], "items": [{"sku": spec.product, "quantity": spec.quantity}]}
            if spec.proof and not kept.get("dispatch_receipt"):   # the merchant packs: the photo is counted (a recorded real SAM run on the CC0 test photo) and signed
                made = dispatch.pack(self.swarm, self.counter, bought["order_id"], bought["capture_id"],
                                     {spec.product: {"ordered": spec.quantity, "prompt": "book"}}, [PHOTO], True, photo_note=PHOTO_NOTE)
                kept["dispatch_receipt"], kept["dispatch_counter"] = made["digest"][:16], made["counter"]
            if kept.get("dispatch_receipt"):
                row["dispatch_receipt"], row["dispatch_counter"] = kept["dispatch_receipt"], kept["dispatch_counter"]
            ctx = bought["order_id"]
            message = self.draft(ctx, spec, product, total, row)
            opened = self.rc.open_dispute(bought["capture_id"], spec.reason, message, amount=money(spec.ask_minor), context=ctx)
            page_id = opened["dispute_id"]
            api_id = self.world.find_dispute(bought["capture_id"], page_id, spec.reason, spec.ask_minor, spec.message)
            row.update(dispute_id=api_id, page_dispute_id=page_id)
            approval_id = None
            for _ in range(MAX_ROUNDS):
                merchant_result = self.swarm.handle_dispute(api_id, total, f"buyer-{run_id}-{spec.n}", order, bought["trackers"],
                                                         kept["mandate"] if spec.reason == "unauthorised" else None, approval_id)
                if merchant_result.state == "awaiting approval":
                    approval_id = self.world.approve(self.swarm, merchant_result, spec)
                    if approval_id:
                        row["steps"].append("merchant owner approved the offer (rehearsal)")
                        continue
                self.world.after_merchant(api_id, page_id)
                row["steps"].append(f"merchant: {merchant_result.proposal.get('decided') or merchant_result.action} -> {merchant_result.state}")
                thread = self.rc.read_thread(page_id, context=ctx)
                facts = thread.facts()
                step = decide_offer(self.mandate.dispute_rule, spec.reason, spec.ask_minor, facts["offer_minor"], facts["evidence"], facts["replied"], counters)
                taken = self.choose(ctx, spec, step, facts, row) if step.action in ("accept", "counter", "escalate", "wait") else step.action
                if taken != step.action:
                    step = replace(step, action=taken, code=step.code + "+model_cautious")
                self.rec.step(None, ctx, "decision", {"dispute_id": page_id, "action": step.action, "code": step.code, "percent": step.percent,
                                                      "offer_minor": facts["offer_minor"] if facts["offer_minor"] is not None else -1, "asked_minor": spec.ask_minor,
                                                      "counters_used": counters}, True)
                row["steps"].append(f"buyer: {step.action} ({step.code})")
                getattr(self.rc, "note_decision", lambda d: None)(step)
                if step.action == "accept":
                    self.rc.accept_offer(page_id, context=ctx)
                    self.world.after_buyer(api_id, page_id, "accept")
                    buyer_end = "accepted"
                    break
                if step.action == "counter":
                    self.rc.counter(page_id, f"Thank you for the offer. Could you raise the refund to USD {money(step.counter_minor)}?", context=ctx)
                    self.world.after_buyer(api_id, page_id, "counter")
                    counters += 1
                    continue
                if step.action == "escalate":
                    self.rc.escalate(page_id, "owner", why=step.code, context=ctx)
                    buyer_end = "escalated_owner"
                    break
                break   # wait: nothing more the buyer can do until the merchant acts
            # Every outcome is read back from PayPal's record
            final = self.world.read(api_id)
            settlement = self.swarm.settlement(api_id) if buyer_end == "accepted" else None
            settled = bool(settlement and settlement.state == VERIFIED)
            row.update(paypal_status=final.get("status"), paypal_stage=final.get("dispute_life_cycle_stage"),
                       paypal_outcome=(final.get("dispute_outcome") or {}).get("outcome_code", ""), refund_confirmed=money(refund_seen(final)) if settled else "0.00",
                       settlement=settlement.state if settlement else "", settlement_detail=settlement.detail if settlement else "",
                       merchant_state=merchant_result.state if merchant_result else "", merchant_decision=(merchant_result.proposal.get("decided") if merchant_result else ""),
                       buyer_end=buyer_end or "waiting", counters=counters)
            row["outcome"] = classify(final, merchant_result, buyer_end, settled)
            stats = model_stats(self.swarm.receipts.path, api_id)
            row.update(model_calls=stats["calls"], model_ms=stats["ms"], scripted_decisions=stats["scripted"])
        except NeedsHuman as stop:
            row.update(outcome=ERROR, detail="Stopped, a person must continue: " + stop.why, manual_steps=stop.steps)
        except (StepFailed, GatewayError, ProviderRefused, Offline, LookupError, TimeoutError, ValueError) as error:
            row.update(outcome=ERROR, detail=f"{type(error).__name__}: {str(error)[:200]}")
        row["seconds"] = round(self.clock() - started, 2)
        row["buyer_steps"] = sum(1 for s in self.rec.steps if s["context"] == row.get("order_id"))
        return row


def summarise(rows):
    count = lambda name: sum(1 for r in rows if r.get("outcome") == name)
    done = [r for r in rows if r.get("seconds") is not None]
    refunds = sum(int(Decimal(r.get("refund_confirmed", "0")) * 100) for r in rows)
    return {"cases": len(rows), SETTLED: count(SETTLED), EVIDENCE: count(EVIDENCE), BUYER_OWNER: count(BUYER_OWNER),
            MERCHANT_OWNER: count(MERCHANT_OWNER), PENDING_STATE: count(PENDING_STATE), ERROR: count(ERROR),
            "refunds_confirmed_by_paypal": sum(1 for r in rows if r.get("settlement") == VERIFIED and refund_seen_ok(r)),
            "refunds_confirmed_total": money(refunds),
            "seconds_total": round(sum(r["seconds"] for r in done), 2), "seconds_per_case": round(sum(r["seconds"] for r in done) / len(done), 2) if done else 0,
            "model_calls": sum(r.get("model_calls", 0) for r in rows), "scripted_decisions": sum(r.get("scripted_decisions", 0) for r in rows),
            "merchant_model_ms": sum(r.get("model_ms", 0) for r in rows),
            "buyer_model_calls": sum(r.get("buyer_model_calls", 0) for r in rows), "buyer_model_ms": sum(r.get("buyer_model_ms", 0) for r in rows),
            "buyer_scripted_decisions": sum(r.get("buyer_scripted_decisions", 0) for r in rows),
            "price_reference_calls": sum(r.get("price_credits", 0) for r in rows), "price_reference_flags": sum(1 for r in rows if r.get("price_reference", {}).get("verdict") == "flag"),
            "price_reference_refused": sum(1 for r in rows if r.get("price_reference", {}).get("verdict") == "refuse"),
            "buyer_model_overrides": sum(1 for r in rows for m in r.get("buyer_model", []) if m["proposed"] != m["final"])}


def refund_seen_ok(row):
    return Decimal(row.get("refund_confirmed", "0")) > 0


def table(rows):
    head = ("#", "Scenario", "Ask", "Merchant", "Buyer", "PayPal record", "Outcome", "Sec", "Model calls (merchant+buyer)")
    body = [(str(r["n"]), r["scenario"][:44], r["ask"], (r.get("merchant_decision") or r.get("merchant_state") or "-")[:20], r.get("buyer_end", "-"),
             f"{r.get('paypal_status', '-')}/{r.get('paypal_stage', '-')}", r.get("outcome", "-"), str(r.get("seconds", "-")), f"{r.get('model_calls', 0)}+{r.get('buyer_model_calls', 0)}") for r in rows]
    widths = [max(len(head[i]), *(len(b[i]) for b in body)) for i in range(len(head))]
    fmt = lambda cols: "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    return "\n".join([fmt(head), fmt(["-" * w for w in widths]), *(fmt(b) for b in body)])


MANUAL = {
    "rehearsal": ["Nothing real was touched: every record is invented by the local fake provider and the stand-in page.",
                  "Case 7: the merchant owner's approval of the partial offer is simulated (named 'rehearsal owner' in the receipt)."],
    "sandbox": ["Sri logs in to the sandbox buyer account once, by hand, in the persistent browser window (python scripts/buyer_dispute.py --login).",
                "The merchant owner's approval of any offer above the approval threshold stays manual: those cases are reported as escalated to the merchant owner.",
                "Cases the buyer agent hands to its owner (merchant answered with records, or an offer below the rule) stay open until the owner decides.",
                "Any CAPTCHA or verification prompt PayPal shows stops the agent; a person continues by hand."]}


def verify(path, key):
    return bool(Path(path).is_file() and verify_log(str(path), key)["ok"])


def run_batch(world, work, page, adapter, cases=CASES, mandate=None, clock=time.perf_counter, source=None, counter=None, door=None, buyer_adapter=None, price_fn=None):
    """Run the cases in order. Returns the report dictionary (written to data/runs/ by scripts/batch.py)."""
    work = Path(work)
    mandate = mandate or buyer_mandate()
    log = open_buyer_log(work / "buyer")
    rec = Recorder(log, "0" * 64, source or world.mode, work / "shots")
    rc = door(rec) if door else ResolutionCenter(page, world.site if hasattr(world, "site") else fixture_site(), rec)
    swarm = MerchantSwarm(world.gateway, work / "merchant", adapter)
    runner = Run(world, swarm, rc, rec, mandate, log, adapter.label(), clock, counter, buyer_adapter, price_fn)
    run_id = uuid.uuid4().hex[:6]
    started = datetime.now(timezone.utc)
    rows, spent = [], 0
    for spec in cases:
        row = runner.case(spec, run_id, spent)
        if row.get("paid"):
            spent += int(Decimal(row["paid"]) * 100)
        rows.append(row)
        print(f"case {spec.n:2d}  {row.get('outcome'):28}  {row['seconds']}s  {row.get('detail', '')}", flush=True)
        if row.get("manual_steps"):
            break   # a challenge or a missing login: stop the batch, never push through
    return {"kind": "buyer-seller batch", "mode": world.mode, "label": world.label, "started": started.isoformat(), "finished": datetime.now(timezone.utc).isoformat(),
            "price_reference": {"source": world.price_source, "used": True, "calls": sum(r.get("price_credits", 0) for r in rows)},
            "merchant_agent": adapter.label(), "buyer_agent": (buyer_adapter or Adapter("scripted")).label() + "; the owner's dispute rule (clearwake/buyer.py decide_offer) sets what it may do",
            "buyer_rule": mandate.dispute_rule.to_dict(), "cases": rows, "summary": summarise(rows), "manual": MANUAL[world.mode], "run_id": run_id,
            "buyer_log": {"path": str(Path(log.path).relative_to(ROOT)) if Path(log.path).is_relative_to(ROOT) else "buyer-receipts.ndjson", "public_key": log.public_key,
                          "verifies": verify(log.path, log.public_key), "receipts": len(Path(log.path).read_text(encoding="utf-8").splitlines())},
            "merchant_log": {"public_key": swarm.receipts.public_key, "verifies": verify(swarm.receipts.path, swarm.receipts.public_key)},
            "work_dir": str(work)}


def run_rehearsal(adapter=None, cases=CASES, work=None, headless=True, buyer_adapter=None):
    """All cases end to end offline: fake provider plus the local stand-in page. Used by scripts/batch.py and the tests."""
    from playwright.sync_api import sync_playwright
    adapter = adapter or Adapter("scripted")
    work = Path(work or tempfile.mkdtemp(prefix="clearwake-batch-"))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.goto(fixture_site().home_url)
            return run_batch(Rehearsal(work, page), work, page, adapter, cases, buyer_adapter=buyer_adapter)
        finally:
            browser.close()


def has_login():
    from .buyer_browser import PROFILE
    return (Path(PROFILE) / ".clearwake-login-ok").is_file()


def run_sandbox(adapter=None, cases=CASES, work=None, manual=False, resume=False, timeout_s=900, out=print, gateway=None, poll_s=5, buyer_adapter=None):
    """The real PayPal sandbox.

    Playwright mode needs the saved login in data/buyer-profile (python scripts/buyer_dispute.py --login).
    manual=True needs no browser here: buyer browser actions are printed as JSON lines and PayPal is polled for their effect."""
    from . import envfile
    from .paypal import SandboxGateway
    if gateway is None:
        envfile.load(ROOT / ".env")
        gateway = SandboxGateway.from_environment()
    adapter = adapter or Adapter("scripted")
    if manual:
        from .buyer_manual import ManualBuyer
        work = Path(work or ROOT / "data" / "buyer" / "manual-batch")
        state_path = work / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if resume and state_path.is_file() else {}
        if not resume and work.exists() and any(work.iterdir()):
            work.rename(work.with_name(work.name + "-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
        work.mkdir(parents=True, exist_ok=True)
        holder = {}
        state["save"] = lambda: state_path.write_text(json.dumps({k: v for k, v in state.items() if k != "save"}, indent=1), encoding="utf-8")
        world = Sandbox(gateway, None, manual=None, state=state)
        door = lambda rec: holder.setdefault("door", ManualBuyer(gateway, rec, buyer_mandate().dispute_rule, out=out, timeout_s=timeout_s, poll_s=poll_s))
        world.manual = None
        # the manual door needs the recorder, which run_batch creates: build the world's approver lazily
        class Lazy:
            def approve_order(self, *a):
                return holder["door"].approve_order(*a)
        world.manual = Lazy()
        report = run_batch(world, work, None, adapter, cases, source="paypal-sandbox via the lead's browser", door=door, buyer_adapter=buyer_adapter)
        state["save"]()
        report["label"] += " (manual buyer mode: buyer browser steps performed through the lead's browser, effects confirmed from PayPal's records)"
        report["manual"] = MANUAL["sandbox"][1:] + ["Every buyer browser step (approve the checkout link, open the dispute, accept or counter) was performed through the lead's browser; PayPal's record confirmed each effect."]
        return report
    from playwright.sync_api import sync_playwright
    from .buyer_browser import PROFILE, ensure_signed_in, launch
    if not has_login():
        raise NeedsHuman("There is no saved buyer login yet.", ["Run: python scripts/buyer_dispute.py --login", "Log in by hand as the sandbox buyer, then run this again."])
    work = Path(work or ROOT / "data" / "buyer" / f"batch-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    with sync_playwright() as pw:
        context, page = launch(pw, PROFILE, headless=False)
        try:
            ensure_signed_in(page, sandbox_site())
            return run_batch(Sandbox(gateway, page), work, page, adapter, cases, buyer_adapter=buyer_adapter)
        finally:
            context.close()


def plan_sandbox(cases=CASES, work=None, gateway=None, out=print):
    """Create the sandbox orders for the batch (no money moves until the buyer approves) and print what the buyer's browser must do.

    One JSON line per lead action: the checkout approval link of every order first, then the dispute each order will need.
    The orders are saved, so the real run (--resume) buys nothing twice."""
    from . import envfile
    from .buyer_manual import LABEL, REASON_UI
    from .paypal import SandboxGateway
    if gateway is None:
        envfile.load(ROOT / ".env")
        gateway = SandboxGateway.from_environment()
    mandate = buyer_mandate()
    catalog = BuyerAgent(mandate, Adapter("scripted"))
    work = Path(work or ROOT / "data" / "buyer" / "manual-batch")
    work.mkdir(parents=True, exist_ok=True)
    state_path = work / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    lines, spent = [], 0
    gateway._access_token()
    for spec in cases:
        product = catalog.products[spec.product]
        total = product["price_minor"] * spec.quantity
        verdict = check(mandate, catalog.merchant["id"], catalog.currency, {**product, "price_minor": total}, spent)
        if not verdict.allowed:
            raise ValueError(f"Case {spec.n}: the mandate refuses the purchase: {verdict.reason}")
        spent += total
        saved = state.setdefault("cases", {}).setdefault(str(spec.n), {})
        if not saved.get("order_id"):
            order = gateway._request("/v2/checkout/orders", order_payload(product, spec.quantity, total, "http://127.0.0.1:8842/sandbox-approved"), str(uuid.uuid4()))
            saved["order_id"] = order["id"]
            saved["approve_url"] = next((i["href"] for i in order.get("links", []) if i.get("rel") in ("payer-action", "approve")), "")
            state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        lines.append({"phase": "approve", "case": spec.n, "action": "approve_order", "order_id": saved["order_id"], "url": saved.get("approve_url", ""),
                      "amount": f"USD {money(total)}", "mandate_check": verdict.reason, "performed_through": LABEL,
                      "instruction": "Open the link as the sandbox buyer and approve the payment."})
    for spec in cases:
        lines.append({"phase": "dispute", "case": spec.n, "action": "open_dispute", "order_id": state["cases"][str(spec.n)]["order_id"], "reason": spec.reason,
                      "reason_ui": REASON_UI[spec.reason], "amount": money(spec.ask_minor), "planned": True, "performed_through": LABEL,
                      "message": "drafted by the buyer agent's model at run time; the owner's note if the model's draft fails the code check: " + spec.message,
                      "dispute_rule": mandate.dispute_rule.to_dict()})
    lines.append({"phase": "next", "action": "run", "command": "python scripts/batch.py --sandbox --manual-buyer --resume --model ollama",
                  "note": "Approve the ten links first. The run captures each order, asks for each dispute in turn and polls PayPal for every effect."})
    for line in lines:
        out(json.dumps(line, ensure_ascii=False))
    return lines


def save_report(report, folder=None):
    folder = Path(folder or ROOT / "data" / "runs")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"batch-{report['mode']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return path
