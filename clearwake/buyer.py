"""Buyer agent: picks a product for its owner and buys only inside the owner's spending mandate.

The model may only name a product id. The mandate check reads numbers and ids, never the model's text.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

CATALOG = Path(__file__).resolve().parent / "catalog.json"


def load_catalog(path=CATALOG):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["merchant"], data["currency"], {item["id"]: item for item in data["products"]}


ESCALATE_ON = ("merchant_evidence", "no_response", "counters_exhausted", "below_counter_floor", "offer_exceeds_request")
REASONS = ("item_not_received", "missing_items", "not_as_described", "unauthorised")
PAYPAL_REASONS = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "item_not_received", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "not_as_described",
                  "UNAUTHORISED": "unauthorised", "UNAUTHORIZED": "unauthorised"}


@dataclass(frozen=True)
class DisputeRule:
    """What the owner lets the buyer agent do when an order goes wrong. Signed into the mandate receipt.

    accept_min_percent: accept any refund offer at or above this share of the amount asked, for item_not_received and missing_items.
    accept_min_percent_not_as_described: the same for not_as_described.
    counter_min_percent: an offer below this share is not countered, it goes to the owner.
    max_counters: how many times the agent may ask for more before it hands the case to the owner.
    no_response_hours: waiting this long without a merchant reply escalates (if "no_response" is in escalate_on).
    escalate_on: the conditions that stop the agent and hand the case to its owner. Any other silence means wait.
    escalate_to_claim: whether the agent may press PayPal's own "escalate to claim". Off unless the owner turns it on.
    """
    accept_min_percent: int = 80
    accept_min_percent_not_as_described: int = 80
    counter_min_percent: int = 40
    max_counters: int = 1
    no_response_hours: int = 72
    escalate_on: tuple = ESCALATE_ON
    escalate_to_claim: bool = False

    def __post_init__(self):
        for name in ("accept_min_percent", "accept_min_percent_not_as_described", "counter_min_percent"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 100:
                raise ValueError(f"{name} must be a whole number from 1 to 100.")
        if self.counter_min_percent > min(self.accept_min_percent, self.accept_min_percent_not_as_described):
            raise ValueError("counter_min_percent cannot be above an accept threshold.")
        if type(self.max_counters) is not int or not 0 <= self.max_counters <= 3:
            raise ValueError("max_counters must be a whole number from 0 to 3.")
        if type(self.no_response_hours) is not int or not 1 <= self.no_response_hours <= 24 * 30:
            raise ValueError("no_response_hours must be between 1 and 720.")
        if not isinstance(self.escalate_on, tuple) or not self.escalate_on or set(self.escalate_on) - set(ESCALATE_ON):
            raise ValueError("escalate_on must be a non empty tuple of: " + ", ".join(ESCALATE_ON) + ".")
        if type(self.escalate_to_claim) is not bool:
            raise ValueError("escalate_to_claim must be true or false.")

    def accept_percent(self, reason):
        return self.accept_min_percent_not_as_described if reason == "not_as_described" else self.accept_min_percent

    def to_dict(self):
        return {"accept_min_percent": self.accept_min_percent, "accept_min_percent_not_as_described": self.accept_min_percent_not_as_described,
                "counter_min_percent": self.counter_min_percent, "max_counters": self.max_counters, "no_response_hours": self.no_response_hours,
                "escalate_on": list(self.escalate_on), "escalate_to_claim": self.escalate_to_claim}


@dataclass(frozen=True)
class Mandate:
    owner: str
    budget_minor: int
    per_item_cap_minor: int
    allowed_merchants: tuple
    allowed_categories: tuple
    currency: str = "USD"
    dispute_rule: DisputeRule | None = None

    def __post_init__(self):
        if min(self.budget_minor, self.per_item_cap_minor) <= 0 or self.per_item_cap_minor > self.budget_minor:
            raise ValueError("A mandate needs a positive budget and a per item cap no higher than the budget.")
        if self.dispute_rule is not None and not isinstance(self.dispute_rule, DisputeRule):
            raise ValueError("dispute_rule must be a DisputeRule.")


@dataclass(frozen=True)
class BuyerDecision:
    action: str            # accept, counter, escalate or wait
    code: str              # short machine readable reason
    detail: str            # one line for the receipt and the screen
    percent: int = -1      # offer as a whole percent of the amount asked, -1 when there is no offer
    counter_minor: int = 0  # the amount a counter asks for


def reason_key(value):
    """The buyer's reason key from a PayPal reason code or one of our own keys. Unknown reasons are refused."""
    key = PAYPAL_REASONS.get(value, value)
    if key not in REASONS:
        raise ValueError("The dispute reason must be one of: " + ", ".join(REASONS) + ".")
    return key


def decide_offer(rule, reason, requested_minor, offer_minor=None, evidence=False, replied=False, counters_used=0, hours_waiting=0):
    """Pure decision: accept, counter, escalate or wait, from what the merchant did. No text, no model.

    offer_minor: the refund the merchant offered, or None. evidence: the merchant answered with records instead of an offer.
    replied: the merchant wrote anything. Whatever the merchant writes can only be one of these facts."""
    if not isinstance(rule, DisputeRule):
        raise ValueError("The mandate has no dispute rule: the agent may not negotiate.")
    reason = reason_key(reason)
    if type(requested_minor) is not int or requested_minor <= 0:
        raise ValueError("The amount asked must be a positive whole number of minor units.")
    if offer_minor is not None and (type(offer_minor) is not int or offer_minor < 0):
        raise ValueError("The offer must be a whole number of minor units.")

    def stop(code, detail, percent=-1):
        return BuyerDecision("escalate" if code in rule.escalate_on else "wait", code, detail, percent)

    if offer_minor is None:
        if evidence or replied:
            return stop("merchant_evidence", "The merchant answered with records and no offer: the owner decides.")
        if hours_waiting >= rule.no_response_hours:
            return stop("no_response", f"No merchant reply for {hours_waiting} hours: the owner decides.")
        return BuyerDecision("wait", "no_reply_yet", "No merchant reply yet.")
    percent = offer_minor * 100 // requested_minor
    if offer_minor > requested_minor:
        return stop("offer_exceeds_request", "The offer is above the amount asked: the owner decides.", percent)
    need = rule.accept_percent(reason)
    if offer_minor * 100 >= need * requested_minor:
        return BuyerDecision("accept", "offer_meets_rule", f"Offer is {percent}% of the amount asked; the owner's rule accepts {need}% or more.", percent)
    if offer_minor * 100 < rule.counter_min_percent * requested_minor:
        return stop("below_counter_floor", f"Offer is {percent}%, below the {rule.counter_min_percent}% the agent may counter.", percent)
    if counters_used < rule.max_counters:
        target = min(requested_minor, -(-requested_minor * need // 100))
        return BuyerDecision("counter", "ask_for_more", f"Offer is {percent}%; asking for {need}% ({target} minor units).", percent, target)
    return stop("counters_exhausted", f"Offer is {percent}% after {counters_used} counter(s); the owner decides.", percent)


@dataclass
class MandateDecision:
    allowed: bool
    reason: str
    product: dict | None = None
    checks: dict = field(default_factory=dict)


def check(mandate, merchant_id, currency, product, spent_minor):
    """Every rule must pass. Returns which ones did, so the screen and the receipt can show them."""
    if product is None:
        return MandateDecision(False, "No product in this store matches the request.")
    checks = {
        "merchant allowed": merchant_id in mandate.allowed_merchants,
        "category allowed": product["category"] in mandate.allowed_categories,
        "currency matches": currency == mandate.currency,
        "under per item cap": product["price_minor"] <= mandate.per_item_cap_minor,
        "inside remaining budget": spent_minor + product["price_minor"] <= mandate.budget_minor,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return MandateDecision(not failed, "Inside the mandate." if not failed else "Refused: " + ", ".join(failed) + ".", product, checks)


def mandate_receipt(log, mandate, product, merchant_id, order_id, ts_ms=None):
    """Signed record of authenticated purchase intent: the owner's mandate, the item, and the PayPal order it paid for.

    Written to the buyer's own receipt log with the buyer agent's key. Returns what the merchant's Evidence agent attaches."""
    from verdock_core.receipts import line_hash
    params = {"order_id": order_id, "merchant": merchant_id, "item": product["id"], "price_minor": product["price_minor"],
              "currency": mandate.currency, "budget_minor": mandate.budget_minor, "per_item_cap_minor": mandate.per_item_cap_minor,
              "allowed_categories": list(mandate.allowed_categories),
              "dispute_rule": mandate.dispute_rule.to_dict() if mandate.dispute_rule else "none"}
    line = log.append(f"mandate:{order_id}", "clearwake.buyer.mandate", params, True, actor={"agent": "clearwake-buyer", "user": mandate.owner}, ts_ms=ts_ms)
    return {"order_id": order_id, "owner": mandate.owner, "item": product["id"], "price": f"{mandate.currency} {product['price_minor'] / 100:.2f}",
            "cap": f"{mandate.currency} {mandate.per_item_cap_minor / 100:.2f}", "digest": line_hash(line), "line": line, "public_key": log.public_key}


# What a model may do with the buyer's decision. The rule's action is the ceiling: a model may be more cautious, never bolder.
PERMITTED = {"accept": ("accept", "escalate"), "counter": ("counter", "escalate"), "escalate": ("escalate",), "wait": ("wait",)}
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def final_action(rule_action, proposed):
    """The action that is taken: the model's proposal only if the owner's rule permits it, otherwise the rule's own action."""
    return proposed if proposed in PERMITTED[rule_action] else rule_action


def check_draft(text, asked_minor, limit=500):
    """Code check on a model's dispute message. Returns (ok, problems). It may state only the amount asked, no links, no addresses."""
    problems = []
    if not isinstance(text, str) or not 10 <= len(text.strip()) <= limit:
        return False, [f"the message must be 10 to {limit} characters"]
    if re.search(r"https?://|www\.|@|\bPP-[A-Z]-", text, re.I):
        problems.append("it contains a link, an address or an id")
    allowed = {f"{asked_minor / 100:.2f}", str(asked_minor // 100) if asked_minor % 100 == 0 else "x"}
    for number in NUMBER.findall(text):
        if number.replace(",", ".").rstrip("0").rstrip(".") not in {a.rstrip("0").rstrip(".") for a in allowed} | {"1", "2", "3"}:
            problems.append(f"it states the number {number}, which is not the amount asked")
    return not problems, problems


class BuyerAgent:
    def __init__(self, mandate, adapter, catalog_path=CATALOG):
        self.mandate, self.adapter = mandate, adapter
        self.merchant, self.currency, self.products = load_catalog(catalog_path)

    def choose(self, request, spent_minor=0):
        listing = "\n".join(f"{p['id']}: {p['name']} ({p['category']}, {p['price_minor'] / 100:.2f} {self.currency})" for p in self.products.values())

        def scripted():  # deterministic rule: first product whose name words appear in the request
            words = set(request.lower().split())
            hit = next((p for p in self.products.values() if words & set(p["name"].lower().split())), None)
            return {"product_id": hit["id"] if hit else ""}

        proposal = self.adapter.propose(
            "You are a shopping agent. Pick the one product id from the list that best matches the owner's request, or an empty string.",
            f"Store {self.merchant['name']} lists:\n{listing}\n\nOwner's request: {request}", ["product_id"], scripted)
        product = self.products.get((proposal.value or {}).get("product_id", ""))
        return proposal, check(self.mandate, self.merchant["id"], self.currency, product, spent_minor)
