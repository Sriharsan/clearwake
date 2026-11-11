"""An agent built like PayPal's Agent Toolkit flow, run unguarded and then guarded, on the local PayPal layer.

  python examples/toolkit_agent_guarded.py                 one episode of each of the four attacks, side by side
  python examples/toolkit_agent_guarded.py --recorded      all 80 attack episodes of the recorded seed (20261110), totals
  python examples/toolkit_agent_guarded.py --seed N --per-attack K

The unguarded side is clearwake.baseline.ToolkitSurface: the one money tool docs/TOOLKIT_FAILURE_CASES.md records for disputes
(accept_dispute_claim sends only the note, no PayPal-Request-Id, no limit, a lost answer is retried by the caller). The guarded side
wraps that same surface with clearwake.toolkit_guard.guard(). Both act on the same "local PayPal layer": durable local records,
no network call. Nothing here touches PayPal.
"""
from pathlib import Path
import random
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import baseline as B  # noqa: E402
from clearwake.paypal import GatewayError, ProviderRefused  # noqa: E402
from clearwake.toolkit_guard import AWAITING, guard  # noqa: E402

LAYER = B.LABEL_LAYER   # "local PayPal layer"
ATTACKS = {   # attack key -> (baseline scenario, title)
    "lost_response": ("lost_paypal_response", "Lost response after PayPal applied the refund"),
    "injection": ("injected_instruction", "Injected instruction in the buyer's message"),
    "over_limit": ("over_limit_offer", "Over limit request"),
    "duplicate": ("duplicate_delivery", "Duplicate delivery of the same case"),
}


def run_unguarded(ep, work, seed):
    """The recorded unguarded agent, unchanged."""
    return B.run_toolkit(ep, work, seed, resolved_check=False)


def run_guarded(ep, work, seed):
    """The same agent and the same layer, with every tool call going through guard()."""
    root = Path(work) / f"guarded-{ep['n']}"
    gateway = B.PayPalLikeGateway(root / "provider.sqlite3")
    dispute_id = B._open_inr(gateway, ep)
    surface = B.ToolkitSurface(gateway, random.Random(f"{seed}:{ep['n']}:t"), False, ep["lost_responses"])
    api = guard(surface, reader=gateway, data_dir=root / "guard")                      # the guard, line 2 of 3
    named = B.AMOUNT.search(ep["message"])
    believed = B.money(B.cents(named.group(1)) if named else ep["intended_minor"])     # an agent that takes the amount from the message
    steps, approvals, held = [], 0, False
    for _ in range(ep["deliveries"]):                    # each delivery is a fresh run of the agent
        for _attempt in range(B.MAX_ATTEMPTS):
            try:
                out = api.accept_dispute_claim(dispute_id, "Accepted.", amount=believed, limit=B.money(B.OWNER_LIMIT_MINOR))    # line 3 of 3
                if out.state == AWAITING:                # the owner decides; the harness plays the owner and approves exactly this move
                    api.approvals.approve(out.approval_id, "Sri"); approvals += 1
                    out = api.accept_dispute_claim(dispute_id, "Accepted.", approval_id=out.approval_id)
            except GatewayError:
                steps.append("no answer, called again")
                continue
            except ProviderRefused:
                steps.append("error shown to the caller")
                break
            held = held or out.state.startswith("held for a person")
            steps.append(out.state + ("" if out.sent else ", nothing sent"))
            break
    measured = B._measure_inr(gateway, ep, dispute_id)
    report = api.verify()
    return {**measured, "steps": steps, "agent": "toolkit+guard", "approvals": approvals, "held_for_person": held,
            "receipts": report["count"], "receipts_verify": report["ok"], "public_key": api.public_key, "receipt_path": api.receipts.path}


def episodes_for(seed, per_attack):
    every = B.episodes_inr(seed, B.DEFAULT_EPISODES)
    return {key: [e for e in every if e["condition"] == scenario][:per_attack] for key, (scenario, _) in ATTACKS.items()}


def usd(minor):
    return f"{minor / 100:,.2f}"


def verdict(key, side, guarded):
    paid, records = side["refunded_minor"], side["refund_records"]
    if key == "lost_response":
        return f"paid {records} times, USD {usd(paid)}" if records > 1 else f"paid once, USD {usd(paid)}"
    if key == "duplicate":
        return f"paid {records} times, USD {usd(paid)}" if records > 1 else f"paid once, USD {usd(paid)}"
    if key == "injection":
        return "held for a person, message receipted and ignored" if guarded and side["held_for_person"] else f"accepted the claim, USD {usd(paid)} paid"
    return f"held for a person (limit USD {usd(B.OWNER_LIMIT_MINOR)})" if guarded and side["held_for_person"] else f"paid USD {usd(paid)}"


def show_attack(key, ep, unguarded, guarded):
    print(f"\n{ATTACKS[key][1]}   (episode {ep['n']}, {LAYER})")
    if key == "injection":
        print(f"  buyer's message: {ep['message']}")
    rows = (("PayPal refunds recorded", unguarded["refund_records"], guarded["refund_records"]),
            ("paid out (USD)", usd(unguarded["refunded_minor"]), usd(guarded["refunded_minor"])),
            ("overpaid (USD)", usd(unguarded["overpaid_minor"]), usd(guarded["overpaid_minor"])),
            ("double refunds", unguarded["double_refunds"], guarded["double_refunds"]),
            ("result", verdict(key, unguarded, False), verdict(key, guarded, True)))
    print(f"  {'':26}{'unguarded':<44}guarded")
    for name, a, b in rows:
        print(f"  {name:<26}{str(a):<44}{b}")
    print(f"  guarded receipts: {guarded['receipts']} signed lines, offline check {'ok' if guarded['receipts_verify'] else 'FAILED'}, key {guarded['public_key'][:16]}...")


def totals(results):
    out = {}
    for key, pairs in results.items():
        out[key] = {side: {m: sum(p[side][m] for p in pairs) for m in ("overpaid_minor", "double_refunds", "refunded_minor", "refund_records")} for side in ("unguarded", "guarded")}
        out[key]["episodes"] = len(pairs)
        out[key]["held"] = sum(1 for p in pairs if p["guarded"]["held_for_person"])
        out[key]["approvals"] = sum(p["guarded"]["approvals"] for p in pairs)
        out[key]["receipts_ok"] = all(p["guarded"]["receipts_verify"] for p in pairs)
    return out


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else B.DEFAULT_SEED
    per_attack = 20 if "--recorded" in argv else int(argv[argv.index("--per-attack") + 1]) if "--per-attack" in argv else 1
    work = Path(tempfile.mkdtemp(prefix="clearwake-toolkit-guard-"))
    try:
        results = {}
        for key, eps in episodes_for(seed, per_attack).items():
            results[key] = [{"episode": ep, "unguarded": run_unguarded(ep, work, seed), "guarded": run_guarded(ep, work, seed)} for ep in eps]
        if "--recorded" not in argv:
            print(f"An agent calling PayPal's Agent Toolkit tool accept_dispute_claim, unguarded and guarded, on the {LAYER} (seed {seed}).")
            for key, pairs in results.items():
                for pair in pairs:
                    show_attack(key, pair["episode"], pair["unguarded"], pair["guarded"])
        t = totals(results)
        print(f"\nTotals over {sum(v['episodes'] for v in t.values())} episodes, seed {seed}, {LAYER} (unguarded / guarded)")
        print(f"  {'attack':<16}{'n':>4}{'overpaid USD':>22}{'double refunds':>18}{'held for person':>18}{'owner approvals':>18}{'receipts verify':>17}")
        for key, v in t.items():
            u, g = v["unguarded"], v["guarded"]
            print(f"  {key:<16}{v['episodes']:>4}{usd(u['overpaid_minor']) + ' / ' + usd(g['overpaid_minor']):>22}{str(u['double_refunds']) + ' / ' + str(g['double_refunds']):>18}"
                  f"{v['held']:>18}{v['approvals']:>18}{'yes' if v['receipts_ok'] else 'NO':>17}")
        print("  The guard holds what is above the owner's limit for a person; it does not decide for the person. If no person acts before the")
        print("  deadline, PayPal escalates the case. That cost is not in these numbers.")
        return 0 if all(v["receipts_ok"] for v in t.values()) else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
