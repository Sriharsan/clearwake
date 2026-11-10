"""The buyer agent buys one item through the PayPal sandbox, inside its signed mandate.

  python scripts/sandbox_buy.py "A5 dot grid notebook" [--quantity 1] [--manual-buyer]

Orders v2 create (merchant app, as scripts/sandbox_setup.py does), the buyer approves the checkout link, the merchant gateway captures.
Default: the approval happens in the persistent Playwright profile (python scripts/buyer_dispute.py --login first).
--manual-buyer: no browser here; the approval link is printed as a JSON line and PayPal is polled until it shows APPROVED.
The result is saved to data/sandbox/buys/<order>.json. Keys come only from .env and are never printed.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import envfile  # noqa: E402
from clearwake.batch import buyer_mandate, create_and_pay, money  # noqa: E402
from clearwake.buyer import BuyerAgent, check, mandate_receipt  # noqa: E402
from clearwake.buyer_browser import NeedsHuman, Recorder, open_buyer_log  # noqa: E402
from clearwake.models import Adapter  # noqa: E402
from clearwake.paypal import SandboxGateway  # noqa: E402


def main(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__)
        return 2
    quantity = int(argv[argv.index("--quantity") + 1]) if "--quantity" in argv else 1
    manual = "--manual-buyer" in argv
    envfile.load(ROOT / ".env")
    gateway = SandboxGateway.from_environment()
    mandate = buyer_mandate()
    agent = BuyerAgent(mandate, Adapter("scripted"))
    proposal, decision = agent.choose(argv[0])
    if decision.product is None:
        print("No product matches that request.")
        return 1
    product = decision.product
    priced = {**product, "price_minor": product["price_minor"] * quantity}
    verdict = check(mandate, agent.merchant["id"], agent.currency, priced, 0)
    print(f"{proposal.label} chose {product['id']} x{quantity}: {verdict.reason}")
    if not verdict.allowed:
        return 1
    log = open_buyer_log()
    rec = Recorder(log, "0" * 64, "paypal-sandbox via the lead's browser" if manual else "paypal-sandbox")
    try:
        if manual:
            from clearwake.buyer_manual import ManualBuyer
            door = ManualBuyer(gateway, rec, mandate.dispute_rule)
            order_id, capture_id = create_and_pay(gateway, None, product, quantity, priced["price_minor"], approver=door.approve_order)
        else:
            from playwright.sync_api import sync_playwright
            from clearwake.batch import has_login
            from clearwake.buyer_browser import PROFILE, ensure_signed_in, launch, sandbox_site
            if not has_login():
                raise NeedsHuman("There is no saved buyer login yet.", ["Run: python scripts/buyer_dispute.py --login"])
            with sync_playwright() as pw:
                context, page = launch(pw, PROFILE, headless=False)
                try:
                    ensure_signed_in(page, sandbox_site())
                    order_id, capture_id = create_and_pay(gateway, page, product, quantity, priced["price_minor"])
                finally:
                    context.close()
    except NeedsHuman as stop:
        print("A person must do this step:", stop.why)
        for number, line in enumerate(stop.steps, 1):
            print(f"  {number}. {line}")
        return 3
    receipt = mandate_receipt(log, mandate, priced, agent.merchant["id"], order_id)
    folder = ROOT / "data" / "sandbox" / "buys"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{order_id}.json").write_text(json.dumps({"order_id": order_id, "capture_id": capture_id, "product": product["id"], "quantity": quantity,
                                                         "paid": money(priced["price_minor"]), "mandate_receipt": receipt["digest"]}, indent=1), encoding="utf-8")
    print(f"SANDBOX order {order_id} captured {capture_id} USD {money(priced['price_minor'])}. Mandate receipt {receipt['digest'][:16]} signed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
