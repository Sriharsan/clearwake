"""Ten orders, ten disputes, negotiated by the buyer agent and the merchant agent. Every outcome is read back from PayPal's record.

  python scripts/batch.py --local              All ten end to end offline (local provider + local stand-in page). Safe anywhere.
  python scripts/batch.py --sandbox                The real PayPal sandbox. Needs Sri's login first: python scripts/buyer_dispute.py --login
  python scripts/batch.py --sandbox --manual-buyer [--resume] [--manual-timeout 900]
                                                   No browser here: buyer browser actions are printed as JSON lines (approve link, open
                                                   dispute, accept, counter); PayPal is polled until each effect appears.
  python scripts/batch.py --sandbox --manual-buyer --plan
                                                   Creates the ten sandbox orders (no money moves yet) and prints, as JSON lines, the
                                                   approval link for each order and the dispute each will need. Then run with --resume.
  python scripts/batch.py --local --model ollama   Use the local model for both agents (default: scripted). --buyer-model sets the buyer alone.
  python scripts/batch.py --local --mix dispatch   The earlier mix with dispatch proof (missing items counted by a recorded SAM run)
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
    if ("--local" in argv) == ("--sandbox" in argv):
        print(__doc__)
        return 2
    backend = argv[argv.index("--model") + 1] if "--model" in argv else "scripted"
    adapter = Adapter(backend)
    buyer_adapter = Adapter(argv[argv.index("--buyer-model") + 1] if "--buyer-model" in argv else backend)
    cases = batch.CASES_DISPATCH if "--mix" in argv and argv[argv.index("--mix") + 1] == "dispatch" else batch.CASES
    if "--cases" in argv:
        wanted = {int(n) for n in argv[argv.index("--cases") + 1].split(",")}
        cases = tuple(c for c in cases if c.n in wanted)
    try:
        if "--plan" in argv:
            if "--sandbox" not in argv or "--manual-buyer" not in argv:
                print("--plan needs --sandbox --manual-buyer")
                return 2
            batch.plan_sandbox(cases)
            return 0
        if "--local" in argv:
            report = batch.run_local(adapter, cases, buyer_adapter=buyer_adapter)
        else:
            timeout = int(argv[argv.index("--manual-timeout") + 1]) if "--manual-timeout" in argv else 900
            report = batch.run_sandbox(adapter, cases, manual="--manual-buyer" in argv, resume="--resume" in argv, timeout_s=timeout, buyer_adapter=buyer_adapter)
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
          f"merchant model calls {s['model_calls']} ({s['merchant_model_ms']} ms, {s['scripted_decisions']} scripted) | buyer model calls {s['buyer_model_calls']} ({s['buyer_model_ms']} ms, {s['buyer_model_overrides']} overridden by the rule) | price reference used: yes, {report['price_reference']['calls']} calls ({report['price_reference']['source']}) | buyer log verifies {report['buyer_log']['verifies']}, merchant log verifies {report['merchant_log']['verifies']}")
    print("Stayed manual:"); [print("  -", m) for m in report["manual"]]
    print("Saved", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
