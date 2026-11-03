"""Add synthetic tracking to a sandbox order, as a merchant does when a parcel ships. A sandbox write, with test data only.

  python scripts/add_tracking.py ORDER_ID CAPTURE_ID [TRACKING_NUMBER] [CARRIER]

Needs the sandbox keys in .env. The default number is invented (SYNTH...), the default carrier is UPS. Reads the order back and prints
what PayPal now shows.
"""
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clearwake import envfile  # noqa: E402
from clearwake.paypal import GatewayError, ProviderRefused, SandboxGateway  # noqa: E402


def main():
    if not 3 <= len(sys.argv) <= 5:
        sys.exit(__doc__)
    order_id, capture_id = sys.argv[1], sys.argv[2]
    number = sys.argv[3] if len(sys.argv) > 3 else "SYNTH1Z999AA" + uuid.uuid4().hex[:8].upper()
    carrier = sys.argv[4] if len(sys.argv) > 4 else "UPS"
    envfile.load(Path(__file__).resolve().parent.parent / ".env")
    gateway = SandboxGateway.from_environment()
    try:
        gateway.add_tracking(order_id, capture_id, number, carrier, str(uuid.uuid4()))
        order = gateway.order(order_id)
    except (GatewayError, ProviderRefused, ValueError) as error:
        sys.exit(f"Not added: {error}")
    for unit in order.get("purchase_units", []):
        for tracker in unit.get("shipping", {}).get("trackers", []):
            print(f"PayPal shows tracker {tracker.get('id')} status {tracker.get('status')}")


if __name__ == "__main__":
    main()
