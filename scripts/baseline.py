"""Baseline versus Clearwake on the same seeded episodes, both acting on the same rehearsal PayPal layer.

  python scripts/baseline.py                         200 episodes, default seed
  python scripts/baseline.py --seed 7 --episodes 400  any multiple of 4

Runs an unguarded agent ("mock PayPal layer, unguarded agent") and Clearwake's real guarded code path through four injected
conditions in equal share, saves every episode to data/runs/baseline-<time>.json and prints the table. Exit code 1 if Clearwake
did worse than the baseline on any measure, in total or in any one condition.
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
    report = baseline.run(seed, count)
    path = baseline.save(report, ROOT / "data" / "runs")
    print(baseline.table_text(report))
    print("Saved", path.relative_to(ROOT))
    if report["clearwake_worse_on"]:
        print("\nClearwake did worse than the baseline on:")
        for condition, measure, base, guard in report["clearwake_worse_on"]:
            print(f"  {condition} / {measure}: baseline {base}, Clearwake {guard}")
        return 1
    print("\nClearwake did not do worse than the baseline on any measure.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
