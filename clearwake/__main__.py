"""Run the shared refund workroom. Default mode makes zero network calls."""
import argparse
import os
from pathlib import Path

from .console import Console
from .controller import RefundCase, RefundController, archive_legacy_database
from .paypal import LocalGateway, SandboxGateway
from .server import ClearwakeServer


PHONE_HELP = "\n".join((
    "Phone voice mode (say the rules out loud, ask what happened, approve inside the signed policy):",
    "  python -m clearwake --phone [--tls]    a separate small server on your Wi-Fi with a token link and a QR code",
    "  python -m clearwake --voice-lan        the microphone page over https on the private LAN (see docs/VOICE.md)"))


def main():
    import sys
    if "--phone" in sys.argv[1:]:   # phone voice mode, like Relayloom's phone alerts: a separate small server on the LAN address
        from .voice_phone import main as phone
        return phone([a for a in sys.argv[1:] if a != "--phone"])
    if "--voice-lan" in sys.argv[1:]:   # the phone microphone page over https on the private LAN: clearwake/voice_lan.py
        from .voice_lan import main as voice_lan
        return voice_lan([a for a in sys.argv[1:] if a != "--voice-lan"])
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, epilog=PHONE_HELP)
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on. Anything but loopback is accepted only with CLEARWAKE_HOSTED=1 (hosted mode)")
    parser.add_argument("--port", type=int, default=None, help="Default 8810; in hosted mode the PORT variable the host provides")
    parser.add_argument("--database", type=Path, default=Path("data/clearwake.sqlite3"))
    parser.add_argument("--enable-paypal-sandbox", action="store_true", help="Explicitly enable sandbox-only network requests; never production")
    parser.add_argument("--enable-meta-test-data", action="store_true", help="Separate opt-in for the upstream fixed test AI fixture; may consume provider credits")
    parser.add_argument("--enable-local-ai", action="store_true", help="Explicitly use the reviewed local model for the fixed test fixture")
    parser.add_argument("--voice-decisions", choices=("off", "local", "sandbox"), default="off",
                        help="Attach the voice decision runner (Approve case 4, Don't pay case 9, send the proof): on the local provider, or on the real PayPal sandbox")
    parser.add_argument("--console-model", choices=("scripted", "ollama"), default="scripted",
                        help="Agents in the /console local: scripted rules (default, no model calls) or a local Ollama model on loopback")
    parser.add_argument("--local-outcome", choices=("completed", "pending", "lost-response"), default="completed")
    args = parser.parse_args()
    hosted = os.environ.get("CLEARWAKE_HOSTED") == "1"
    if args.port is None:
        args.port = int(os.environ.get("PORT", "8810")) if hosted and os.environ.get("PORT", "").isdigit() else 8810
    if args.host not in ("127.0.0.1", "::1", "localhost") and not hosted:
        parser.error("--host beyond loopback needs CLEARWAKE_HOSTED=1 (hosted mode). Local runs stay on loopback.")
    if hosted and os.environ.get("CLEARWAKE_CONSOLE_MODEL") in ("scripted", "ollama") and args.console_model == "scripted":
        args.console_model = os.environ["CLEARWAKE_CONSOLE_MODEL"]  # real local-model calls only where the host has a model
    if args.enable_meta_test_data and args.enable_local_ai:
        parser.error("Choose local AI or Meta, not both.")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and65535")
    try:
        if args.enable_paypal_sandbox:
            gateway = SandboxGateway.from_environment()
            case = RefundCase(capture=os.environ.get("PAYPAL_SANDBOX_CAPTURE_ID", ""), amount=os.environ.get("CLEARWAKE_REFUND_AMOUNT", "1.00"))
        else:
            gateway = LocalGateway(args.database.resolve().with_name("local-provider.sqlite3"), args.local_outcome)
            case = RefundCase()
        worker = None
        if args.enable_meta_test_data:
            from relayloom.meta import MetaWorker
            worker = MetaWorker.from_environment()
        elif args.enable_local_ai:
            from .local_ai import LocalWorker
            worker = LocalWorker.from_environment()
        for kept in archive_legacy_database(args.database):
            print("Kept the earlier local database aside as", kept)
        controller = RefundController(args.database, case=case, gateway=gateway, worker=worker)
        console = Console(args.database.resolve().parent / "console", args.console_model)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.voice_decisions != "off" and not hosted:
        from .decisions import VoiceDecisionRunner, mirror_local
        from . import envfile
        envfile.load(Path(__file__).resolve().parent.parent / ".env")
        decision_gateway = SandboxGateway.from_environment() if args.voice_decisions == "sandbox" else mirror_local(LocalGateway(args.database.resolve().with_name("voice-local-provider.sqlite3"), "completed"))
        decision_runner = VoiceDecisionRunner(decision_gateway, args.database.resolve().parent / "voice-decisions" / args.voice_decisions)
    server = ClearwakeServer((args.host, args.port), controller, console, hosted=hosted)
    if args.voice_decisions != "off" and not hosted:
        server.decision_runner = decision_runner
        print(f"Voice decisions: {args.voice_decisions}")
    print(f"Clearwake: http://127.0.0.1:{args.port}")
    print(f"Console:   http://127.0.0.1:{args.port}/console (local run on the local provider; agents: {console.adapter.label()})")
    print(f"Payments: {gateway.mode}. Specialists: {controller.mode}. No calls occur just by opening the page.")
    print("Loopback only. Use test data. One immutable bounded capture per database.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close(); controller.close()


if __name__ == "__main__":
    main()
