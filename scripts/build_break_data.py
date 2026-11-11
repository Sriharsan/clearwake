"""Build site/data/break.json for the 'Break it' page (site/break.html) from the newest recorded 200 episode run.

  python scripts/build_break_data.py

Reads the newest data/runs/baseline-*.json of the item not received mix (seed 20261110, 200 episodes). For each of the four attacks
(lost response, injected instruction, over limit request, duplicate delivery) it copies five recorded episodes: the episode's
parameters and what the agent using PayPal's Agent Toolkit directly did (recorded, copied as it is). It then replays the SAME
episode through the drop-in guard (clearwake/toolkit_guard.py) on the local PayPal layer, which gives the guarded outcome and
a signed receipt chain that the page verifies in the browser. Nothing here touches PayPal or the network.

As a check, the unguarded side is run again here and must equal the recorded one, episode by episode; the script stops if it does not.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import baseline as B  # noqa: E402

OUT = ROOT / "site" / "data" / "break.json"
PER_ATTACK = 5
COMPARE = ("refund_records", "refunded_minor", "overpaid_minor", "double_refunds", "steps")
TITLES = {"lost_response": "Lost response after PayPal applied the refund", "injection": "Injected instruction in the buyer's message",
          "over_limit": "Over limit request", "duplicate": "Duplicate delivery"}


def load_example():
    spec = importlib.util.spec_from_file_location("toolkit_agent_guarded", ROOT / "examples" / "toolkit_agent_guarded.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def newest_run():
    for path in sorted((ROOT / "data" / "runs").glob("baseline-*.json"), reverse=True):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("mix") == "item_not_received":
            return path, report
    raise SystemExit("No item not received baseline run found in data/runs.")


def side(measured, text):
    return {"refund_records": measured["refund_records"], "refunded_minor": measured["refunded_minor"], "overpaid_minor": measured["overpaid_minor"],
            "double_refunds": measured["double_refunds"], "steps": measured["steps"], "result": text}


def main():
    path, report = newest_run()
    example = load_example()
    seed = report["seed"]
    by_n = {r["episode"]["n"]: r for r in report["results"]}
    work = Path(tempfile.mkdtemp(prefix="clearwake-break-"))
    try:
        attacks, sums = {}, {}
        for key, (scenario, _) in example.ATTACKS.items():
            every = [e for e in B.episodes_inr(seed, report["episodes"]) if e["condition"] == scenario]
            shown, totals = [], {"episodes": 0, "unguarded_overpaid_minor": 0, "guarded_overpaid_minor": 0, "unguarded_double_refunds": 0,
                                 "guarded_double_refunds": 0, "held_for_person": 0, "unguarded_paid_minor": 0, "guarded_paid_minor": 0}
            for index, ep in enumerate(every):
                recorded = by_n[ep["n"]]
                if recorded["episode"] != ep:
                    raise SystemExit(f"Episode {ep['n']} in {path.name} differs from the seeded episode: rerun scripts/baseline.py first.")
                unguarded = example.run_unguarded(ep, work, seed)
                for field in COMPARE:
                    if unguarded[field] != recorded["unguarded"][field]:
                        raise SystemExit(f"Episode {ep['n']}: the unguarded run now gives {field} {unguarded[field]!r}, the record has {recorded['unguarded'][field]!r}.")
                guarded = example.run_guarded(ep, work, seed)
                totals["episodes"] += 1
                totals["unguarded_overpaid_minor"] += recorded["unguarded"]["overpaid_minor"]; totals["guarded_overpaid_minor"] += guarded["overpaid_minor"]
                totals["unguarded_double_refunds"] += recorded["unguarded"]["double_refunds"]; totals["guarded_double_refunds"] += guarded["double_refunds"]
                totals["unguarded_paid_minor"] += recorded["unguarded"]["refunded_minor"]; totals["guarded_paid_minor"] += guarded["refunded_minor"]
                totals["held_for_person"] += 1 if guarded["held_for_person"] else 0
                if index >= PER_ATTACK:
                    continue
                lines = Path(guarded["receipt_path"]).read_text(encoding="utf-8").splitlines()
                shown.append({
                    "episode": {k: ep[k] for k in ("n", "amount_minor", "message", "deliveries", "lost_responses")},
                    "unguarded": {"source": "recorded", **side(recorded["unguarded"], example.verdict(key, recorded["unguarded"], False))},
                    "guarded": {"source": "replayed on the same episode", **side(guarded, example.verdict(key, guarded, True)), "held_for_person": guarded["held_for_person"],
                                "approvals": guarded["approvals"], "public_key": guarded["public_key"], "receipt_lines": lines, "verified_in_python": guarded["receipts_verify"]},
                    "clearwake_recorded": {"matches_intent": recorded["guarded"]["matches_intent"], "refunded_minor": recorded["guarded"]["refunded_minor"], "steps": recorded["guarded"]["steps"]},
                })
            attacks[key] = {"title": TITLES[key], "scenario": scenario, "episodes_in_run": totals["episodes"], "shown": shown, "totals": totals}
            sums[key] = totals
        total = {k: sum(v[k] for v in sums.values()) for k in next(iter(sums.values()))}
        data = {"label": f"recorded from the {report['episodes']} episode run, seed {seed}", "seed": seed, "episodes": report["episodes"], "source_file": path.relative_to(ROOT).as_posix(),
                "layer": B.LABEL_LAYER, "owner_limit_minor": report["owner_limit_minor"], "capture_minor": report["capture_minor"],
                "toolkit_source": report["toolkit_source"], "totals": total, "attacks": attacks}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} from {path.name}: {total['episodes']} attack episodes, unguarded overpaid USD {total['unguarded_overpaid_minor'] / 100:.2f}, "
          f"guarded USD {total['guarded_overpaid_minor'] / 100:.2f}; double refunds {total['unguarded_double_refunds']} / {total['guarded_double_refunds']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
