"""Buyer agent: picks a product for its owner and buys only inside the owner's spending mandate.

The model may only name a product id. The mandate check reads numbers and ids, never the model's text.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parent / "catalog.json"


def load_catalog(path=CATALOG):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["merchant"], data["currency"], {item["id"]: item for item in data["products"]}


@dataclass(frozen=True)
class Mandate:
    owner: str
    budget_minor: int
    per_item_cap_minor: int
    allowed_merchants: tuple
    allowed_categories: tuple
    currency: str = "USD"

    def __post_init__(self):
        if min(self.budget_minor, self.per_item_cap_minor) <= 0 or self.per_item_cap_minor > self.budget_minor:
            raise ValueError("A mandate needs a positive budget and a per item cap no higher than the budget.")


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
