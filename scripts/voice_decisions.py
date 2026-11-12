"""The two spoken decisions, end to end: "Approve case 4" and "Don't pay case 9, send the proof".

  python scripts/voice_decisions.py --local            Both commands against the local provider, set to the same two states PayPal shows
                                                       (CASE 4 chargeback, CASE 9 inquiry). Prints a result table. Moves nothing at PayPal.
  python scripts/voice_decisions.py --real             Prints the plan and exits. Nothing is sent.
  python scripts/voice_decisions.py --real --yes-real  Runs against the PayPal sandbox and the two real dispute ids. Case 4 moves sandbox
                                                       money (USD 5.00 refund); case 9 moves none.
  --command "text"                                     Run one command instead of both (the words as speech to text would give them).
  --channel voice|typed  --stt NAME  --owner-voice NAME  --reply-voice NAME  --provider NAME     the source recorded in every receipt.
  --log-dir PATH                                       Where the signed receipts and records go (default data/voice-decisions/<mode>).
"""
from pathlib import Path
import argparse
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import envfile  # noqa: E402
from clearwake.decisions import CASES, COMMAND_4, COMMAND_9, DecisionRunner, mirror_local  # noqa: E402
from clearwake.paypal import LocalGateway, SandboxGateway  # noqa: E402
from verdock_core.receipts import verify_log  # noqa: E402

PLAN = f"""Plan for the real PayPal sandbox (nothing is sent without --yes-real):
  1. {COMMAND_4!r}
       dispute {CASES[4]['dispute']}, order {CASES[4]['order']}, USD 5.00, stage CHARGEBACK, status UNDER_REVIEW
       PayPal allows only accept_claim REFUND (make_offer is not allowed and is never called). Tracking is already on the order.
       Policy: accept_claim up to USD 5.00, owner approval above USD 2.00 (the spoken command is the approval, recorded).
       One accept-claim write with a stable PayPal-Request-Id, never retried. PayPal's dispute record is then read until RESOLVED,
       and the refund id, amount and any fee line are recorded as PayPal shows them. This moves USD 5.00 in the sandbox.
  2. {COMMAND_9!r}
       dispute {CASES[9]['dispute']}, order {CASES[9]['order']}, USD 9.00, stage INQUIRY, status WAITING_FOR_SELLER_RESPONSE
       No money moves. A sandbox test tracking number is added to the order (Add Tracking API), PROOF_OF_FULFILLMENT is sent with
       provide-evidence, and PayPal's record is read back. Refund, offer and accept_claim are refused in this command."""


def table(results):
    rows = [("command", "case", "ok", "PayPal shows", "writes", "receipts")]
    for r in results:
        rec = r["paypal_record"] or {}
        shows = f"{rec.get('status', '-')} / {rec.get('stage', '-')}"
        if r["case"] == 4:
            shows += f" / refund {rec.get('refund_amount') or '-'} {rec.get('refund_id') or ''}".rstrip()
        elif r["case"] == 9:
            shows += f" / proof {'seen' if rec.get('evidence_received') else 'not seen'}, money moved {'yes' if rec.get('money_moved') else 'no'}"
        writes = sum(1 for s in r["steps"] if s["state"] == "done" and s["step"] in ("accept claim", "tracking", "provide evidence"))
        rows.append((r["command"], str(r["case"] or "-"), "yes" if r["ok"] else "NO", shows, str(writes), str(len(r["receipts"]))))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--local", action="store_true")
    mode.add_argument("--real", action="store_true")
    ap.add_argument("--yes-real", action="store_true")
    ap.add_argument("--command", action="append")
    ap.add_argument("--channel", default="typed", choices=("voice", "typed"))
    ap.add_argument("--stt")
    ap.add_argument("--owner-voice")
    ap.add_argument("--reply-voice")
    ap.add_argument("--provider", default="scripts/voice_decisions.py")
    ap.add_argument("--log-dir")
    args = ap.parse_args(argv)
    commands = args.command or [COMMAND_4, COMMAND_9]
    source = {"channel": args.channel, "stt": args.stt, "owner_voice": args.owner_voice, "reply_voice": args.reply_voice, "provider": args.provider}
    if args.real and not args.yes_real:
        print(PLAN)
        return 0
    if args.real:
        envfile.load(ROOT / ".env")
        gateway = SandboxGateway.from_environment()
        log_dir = Path(args.log_dir) if args.log_dir else ROOT / "data" / "voice-decisions" / "real"
        label = "PayPal sandbox (real dispute ids)"
    else:
        folder = tempfile.TemporaryDirectory()
        log_dir = Path(args.log_dir) if args.log_dir else ROOT / "data" / "voice-decisions" / "local"
        gateway = mirror_local(LocalGateway(Path(folder.name) / "provider.sqlite3"))
        label = "local provider, set to the two states PayPal shows"
    runner = DecisionRunner(gateway, log_dir)
    if args.local:
        runner.poll_interval, runner.poll_total_wait = 0.01, 5.0   # the local provider answers at once; the real waits stay as set
    results = []
    for text in commands:
        result = runner.run(text, source)
        results.append(result)
        print(f"\n{text!r}: {'ok' if result['ok'] else 'stopped'}")
        if result["readback"]:
            print("  read back:", result["readback"])
        for s in result["steps"]:
            print(f"  {s['step']:<22} {s['state']:<9} {s['detail']}")
        if result["approval"]:
            a = result["approval"]
            print(f"  approval: {a['approved_by']}, level {a['level']}, limit {a['limit']}, rule: {a['rule']}")
        if result["stopped_reason"]:
            print("  stopped:", result["stopped_reason"])
    print(f"\nMode: {label}\n")
    print(table(results))
    report = verify_log(runner.swarm.receipts.path, runner.swarm.receipts.public_key)
    print(f"\nSigned receipts: {report.get('count')} in {runner.swarm.receipts.path}, verify offline: {'yes' if report.get('ok') else 'NO'}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
