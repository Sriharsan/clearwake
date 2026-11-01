"""Read one sandbox dispute from PayPal and print what PayPal's own record says. Read only: it sends nothing.

Usage: python scripts/show_dispute.py PP-R-SLI-10195419
Needs the sandbox keys in .env. It prints the dispute, never a key.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clearwake import envfile  # noqa: E402
from clearwake.paypal import GatewayError, ProviderRefused, SandboxGateway  # noqa: E402


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    envfile.load(Path(__file__).resolve().parent.parent / ".env")
    try:
        record = SandboxGateway.from_environment().dispute(sys.argv[1])
    except (GatewayError, ProviderRefused, ValueError) as error:
        sys.exit(f"Could not read the dispute: {error}")
    amount = record.get("dispute_amount") or {}
    print(f"PayPal sandbox record for {record.get('dispute_id')} (read just now)")
    print(f"  reason  {record.get('reason')}")
    print(f"  amount  {amount.get('currency_code')} {amount.get('value')}")
    print(f"  stage   {record.get('dispute_life_cycle_stage')}   status {record.get('status')}")
    for note in record.get("supporting_info", []):
        print(f"  note    {note.get('source')} at {note.get('provided_time')}")
        print(f"          {note.get('notes')}")
    if not record.get("supporting_info"):
        print("  no supporting info from the seller")


if __name__ == "__main__":
    main()
