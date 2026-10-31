"""One-time PayPal SANDBOX setup: create an order, wait for the sandbox buyer to approve it, capture it.

The capture is the real sandbox payment that later refund checks draw against (USD 20.00, so up to
twenty USD 1.00 refunds). Credentials come only from the ignored .env and are never printed.
Usage: python scripts/sandbox_setup.py
"""
from pathlib import Path
from urllib.parse import urlsplit
import json
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import envfile  # noqa: E402
from clearwake.paypal import GatewayError, SandboxGateway  # noqa: E402

ENV = ROOT / ".env"
STATE = ROOT / "data" / "sandbox" / "setup-order.json"


# PayPal's published SANDBOX test card (developer.paypal.com/tools/sandbox/card-testing). It works only in the sandbox.
SANDBOX_TEST_VISA = "4012888888881881"


def card_setup(gateway):
    """No buyer login: pay the setup order with PayPal's published sandbox test card, then save the capture."""
    try:
        result = gateway.create_card_order("20.00", str(uuid.uuid4()), SANDBOX_TEST_VISA, "2030-12")
    except GatewayError:
        sys.exit("PayPal sandbox did not accept the test card order. Many sandbox merchants (for example India based ones) "
                 "are not enabled for direct card payments (PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING). Use the approval link "
                 "path instead: run without --test-card and log in as the sandbox personal account. Nothing was captured.")
    captures = [c for unit in result.get("purchase_units", []) for c in unit.get("payments", {}).get("captures", [])]
    if result.get("status") != "COMPLETED" or not captures or captures[0].get("status") != "COMPLETED":
        sys.exit(f"Sandbox test card order status {result.get('status')}, capture "
                 f"{captures[0].get('status') if captures else 'missing'}. Not saved.")
    capture = captures[0]
    envfile.set_value(ENV, "PAYPAL_SANDBOX_CAPTURE_ID", capture["id"])
    STATE.write_text(json.dumps({"order_id": result["id"], "capture_id": capture["id"], "captured": True, "method": "sandbox test card"}))
    print("SANDBOX order", result["id"], "paid with PayPal's published sandbox test card.")
    print("SANDBOX capture COMPLETED:", capture["id"], capture["amount"]["currency_code"], capture["amount"]["value"], "Saved as PAYPAL_SANDBOX_CAPTURE_ID in .env.")


def main():
    filled = envfile.load(ENV)
    missing = [name for name in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "CLEARWAKE_SANDBOX_ACK") if not filled[name]]
    if missing:
        sys.exit("Fill these names in clearwake/.env first: " + ", ".join(missing))
    gateway = SandboxGateway.from_environment()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if "--test-card" in sys.argv:
        return card_setup(gateway)
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    if state.get("order_id") and not state.get("captured"):
        try:
            gateway.order(state["order_id"])
        except GatewayError:
            # Unapproved sandbox orders expire after a few hours; start a fresh one rather than waiting forever.
            print("The previous sandbox order expired or is unavailable. Creating a new one.")
            state = {}
    if not state.get("order_id"):
        order = gateway.create_order("20.00", str(uuid.uuid4()), "http://127.0.0.1:8810/sandbox-approved")
        link = next((item["href"] for item in order.get("links", []) if item.get("rel") in ("payer-action", "approve")), "")
        if urlsplit(link).netloc != "www.sandbox.paypal.com":
            sys.exit("PayPal did not return a sandbox approval link. Nothing was captured.")
        state = {"order_id": order["id"], "approve": link}
        STATE.write_text(json.dumps(state))
    print("SANDBOX order:", state["order_id"])
    print("Open this link and approve with the sandbox PERSONAL test account (not your real PayPal):")
    print(" ", state["approve"])
    print("After approving, the browser may show a page that does not load. That is expected. Waiting up to 10 minutes...")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        status = gateway.order(state["order_id"]).get("status")
        if status == "APPROVED":
            break
        if status == "COMPLETED":
            sys.exit("This order was already captured. Delete data/sandbox/setup-order.json to start a new one.")
        time.sleep(5)
    else:
        sys.exit("Not approved within 10 minutes. Run this command again to keep waiting on the same order.")
    result = gateway.capture_order(state["order_id"], str(uuid.uuid4()))
    capture = result["purchase_units"][0]["payments"]["captures"][0]
    if capture.get("status") != "COMPLETED" or capture["amount"] != {"currency_code": "USD", "value": "20.00"}:
        sys.exit(f"Sandbox capture status is {capture.get('status')}. Not saved.")
    envfile.set_value(ENV, "PAYPAL_SANDBOX_CAPTURE_ID", capture["id"])
    STATE.write_text(json.dumps({**state, "capture_id": capture["id"], "captured": True}))
    print("SANDBOX capture COMPLETED:", capture["id"], "USD 20.00. Saved as PAYPAL_SANDBOX_CAPTURE_ID in .env.")


if __name__ == "__main__":
    main()
