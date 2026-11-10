"""An agent using PayPal's Agent Toolkit directly versus Clearwake, on the same seeded episodes and the same local PayPal layer.

  python scripts/baseline.py                          200 item not received episodes, default seed
  python scripts/baseline.py --seed 7 --episodes 400  any multiple of 10
  python scripts/baseline.py --legacy                 the earlier four condition run (multiple of 4)

The toolkit side behaves as docs/TOOLKIT_FAILURE_CASES.md records. The Clearwake side is the real guarded code path. Every episode
is saved to data/runs/baseline-<time>.json and the table is printed. Exit code 1 if Clearwake did worse than the baseline on any
measure, in total or in any one scenario.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import baseline  # noqa: E402


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else baseline.DEFAULT_SEED
    count = int(argv[argv.index("--episodes") + 1]) if "--episodes" in argv else baseline.DEFAULT_EPISODES
    legacy = "--legacy" in argv
    report = baseline.run(seed, count) if legacy else baseline.run_inr(seed, count)
    path = baseline.save(report, ROOT / "data" / "runs")
    print(baseline.table_text(report) if legacy else baseline.table_text_inr(report))
    print("Saved", path.relative_to(ROOT))
    if report["clearwake_worse_on"]:
        print("\nClearwake did worse than the baseline on:")
        for condition, measure, base, guard, *rest in report["clearwake_worse_on"]:
            print(f"  {condition} / {measure}: baseline {base}, Clearwake {guard}")
        return 1
    print("\nClearwake did not do worse than the baseline on any measure.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
