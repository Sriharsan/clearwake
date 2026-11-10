"""Market price reference check (Channel3). Credits are the owner's: this script spends none unless --live is given AND CHANNEL3_MAX_CALLS allows it.

  python scripts/market_check.py --plan   Print the live queries that would be made and the credit cost. No network, no key needed.
  python scripts/market_check.py --live   Run them (one credit each, cached 24 h). Refuses while CHANNEL3_MAX_CALLS is 0 or too low.

Queries are the store catalog products at the catalog price. Results stay local; do not publish them.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import market  # noqa: E402


def queries():
    cat = json.loads((ROOT / "clearwake" / "catalog.json").read_text(encoding="utf-8"))
    cur = cat.get("currency", "USD")
    return [(p["name"], p["price_minor"], cur) for p in cat["products"]]


def main(argv):
    if "--plan" not in argv and "--live" not in argv:
        print(__doc__)
        return 2
    qs = queries()
    plan = market.plan([(q, c) for q, _, c in qs])
    for r in plan["queries"]:
        print(f"{'cached' if r['cached'] else 'live  '}  {r['credits']} credit  {r['query']} ({r['currency']})")
    print(f"total {plan['credits']} credits; cap {plan['cap']}, used this month {plan['used_this_month']}")
    if "--plan" in argv:
        print("dry run: nothing was called")
        return 0
    if plan["credits"] and not plan["allowed"]:
        print("refused: CHANNEL3_MAX_CALLS does not allow this many calls. Set it in .env to raise it.")
        return 1
    for q, price, cur in qs:
        c = market.price_check(q, price, cur, tolerance_percent=50)
        print(f"{q}: reference {c.reference_minor} {cur} (ours {price}), within 50 percent: {c.within_tolerance}, credits {c.credits_used}, {c.note}")
        if any(s in c.note for s in ("(401)", "(402)", "(429)")):
            print("stopped: the service refused; no more calls this run.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
