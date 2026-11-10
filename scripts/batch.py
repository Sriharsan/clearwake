"""Ten orders, ten disputes, negotiated by the buyer agent and the merchant agent. Every outcome is read back from PayPal's record.

  python scripts/batch.py --rehearsal              All ten end to end offline (fake provider + local stand-in page). Safe anywhere.
  python scripts/batch.py --sandbox                The real PayPal sandbox. Needs Sri's login first: python scripts/buyer_dispute.py --login
  python scripts/batch.py --sandbox --manual-buyer [--resume] [--manual-timeout 900]
                                                   No browser here: buyer browser actions are printed as JSON lines (approve link, open
                                                   dispute, accept, counter); PayPal is polled until each effect appears.
  python scripts/batch.py --rehearsal --model ollama   Use the local model for the merchant agent (default: scripted)
  python scripts/batch.py --sandbox --cases 1,3    Only these case numbers

Writes data/runs/batch-<mode>-<time>.json and prints a table.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import batch  # noqa: E402
from clearwake.buyer_browser import NeedsHuman  # noqa: E402
from clearwake.models import Adapter  # noqa: E402


def main(argv):
    if ("--rehearsal" in argv) == ("--sandbox" in argv):
        print(__doc__)
        return 2
    adapter = Adapter(argv[argv.index("--model") + 1] if "--model" in argv else "scripted")
    cases = batch.CASES
    if "--cases" in argv:
        wanted = {int(n) for n in argv[argv.index("--cases") + 1].split(",")}
        cases = tuple(c for c in batch.CASES if c.n in wanted)
    try:
        if "--rehearsal" in argv:
            report = batch.run_rehearsal(adapter, cases)
        else:
            timeout = int(argv[argv.index("--manual-timeout") + 1]) if "--manual-timeout" in argv else 900
            report = batch.run_sandbox(adapter, cases, manual="--manual-buyer" in argv, resume="--resume" in argv, timeout_s=timeout)
    except NeedsHuman as stop:
        print("\nA person must do this step:", stop.why)
        for number, line in enumerate(stop.steps, 1):
            print(f"  {number}. {line}")
        return 3
    path = batch.save_report(report)
    print()
    print(batch.table(report["cases"]))
    s = report["summary"]
    print(f"\n{report['label']}\nsettled at INQUIRY with no fee {s[batch.SETTLED]} | evidence sent {s[batch.EVIDENCE]} | escalated to buyer owner {s[batch.BUYER_OWNER]} | "
          f"escalated to merchant owner {s[batch.MERCHANT_OWNER]} | pending {s[batch.PENDING_STATE]} | errors {s[batch.ERROR]}")
    print(f"refunds confirmed by PayPal's record {s['refunds_confirmed_by_paypal']} (USD {s['refunds_confirmed_total']}) | {s['seconds_per_case']} s per case | "
          f"model calls {s['model_calls']} ({s['scripted_decisions']} scripted decisions) | buyer log verifies {report['buyer_log']['verifies']}, merchant log verifies {report['merchant_log']['verifies']}")
    print("Stayed manual:"); [print("  -", m) for m in report["manual"]]
    print("Saved", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
