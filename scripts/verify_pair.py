"""Verify the buyer agent's log and the merchant agent's log together, offline. Prints PASS or the exact failure.

  python scripts/verify_pair.py data/runs/batch-sandbox-20261110-120000.json
  python scripts/verify_pair.py --buyer B.ndjson --buyer-key HEX --merchant M.ndjson --merchant-key HEX [--dispute ID]

Checks: each log verifies (signatures and hash chain), both name the same PayPal dispute id for every closed case with the same
outcome and order, and every buyer step carries the hash of a mandate receipt in the buyer log. Exit 0 on PASS, 1 on failure.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake.pair import verify_pair, verify_report  # noqa: E402


def main(argv):
    arg = lambda name: argv[argv.index(name) + 1] if name in argv else None
    if argv and not argv[0].startswith("--"):
        report_path = Path(argv[0])
        result = verify_report(json.loads(report_path.read_text(encoding="utf-8")), report_path.parent)
    elif arg("--buyer") and arg("--merchant") and arg("--buyer-key") and arg("--merchant-key"):
        result = verify_pair(arg("--buyer"), arg("--buyer-key"), arg("--merchant"), arg("--merchant-key"), arg("--dispute"))
    else:
        print(__doc__)
        return 2
    if result["ok"]:
        print(f"PASS: both logs verify and name the same dispute for {len(result['disputes'])} closed case(s)"
              + (f"; {result['no_dispute_cases']} case(s) handled by the buyer's mandate with no dispute opened" if result["no_dispute_cases"] else ""))
        for did, info in result["disputes"].items():
            print(f"  {did}  order {info['order']}  {info['outcome']}  PayPal {info['paypal_status']}")
        return 0
    for failure in result["failures"]:
        print("FAIL:", failure)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
