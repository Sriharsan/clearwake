"""Run the shared refund workroom. Default mode makes zero network calls."""
import argparse
import os
from pathlib import Path

from .console import Console
from .controller import RefundCase, RefundController
from .paypal import RehearsalGateway, SandboxGateway
from .server import ClearwakeServer


def main():
    import sys
    if "--phone" in sys.argv[1:]:   # phone voice mode, like Relayloom's phone alerts: a separate small server on the LAN address
        from .voice_phone import main as phone
        return phone([a for a in sys.argv[1:] if a != "--phone"])
    if "--voice-lan" in sys.argv[1:]:   # the phone microphone page over https on the private LAN: clearwake/voice_lan.py
        from .voice_lan import main as voice_lan
        return voice_lan([a for a in sys.argv[1:] if a != "--voice-lan"])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on. Anything but loopback is accepted only with CLEARWAKE_HOSTED=1 (hosted mode)")
    parser.add_argument("--port", type=int, default=None, help="Default 8810; in hosted mode the PORT variable the host provides")
    parser.add_argument("--database", type=Path, default=Path("data/clearwake.sqlite3"))
    parser.add_argument("--enable-paypal-sandbox", action="store_true", help="Explicitly enable sandbox-only network requests; never production")
    parser.add_argument("--enable-meta-synthetic", action="store_true", help="Separate opt-in for the upstream fixed synthetic AI fixture; may consume provider credits")
    parser.add_argument("--enable-local-ai", action="store_true", help="Explicitly use the reviewed local model for the fixed synthetic fixture")
    parser.add_argument("--console-model", choices=("scripted", "ollama"), default="scripted",
                        help="Agents in the /console rehearsal: scripted rules (default, no model calls) or a local Ollama model on loopback")
    parser.add_argument("--rehearsal-outcome", choices=("completed", "pending", "lost-response"), default="completed")
    args = parser.parse_args()
    hosted = os.environ.get("CLEARWAKE_HOSTED") == "1"
    if args.port is None:
        args.port = int(os.environ.get("PORT", "8810")) if hosted and os.environ.get("PORT", "").isdigit() else 8810
    if args.host not in ("127.0.0.1", "::1", "localhost") and not hosted:
        parser.error("--host beyond loopback needs CLEARWAKE_HOSTED=1 (hosted mode). Local runs stay on loopback.")
    if hosted and os.environ.get("CLEARWAKE_CONSOLE_MODEL") in ("scripted", "ollama") and args.console_model == "scripted":
        args.console_model = os.environ["CLEARWAKE_CONSOLE_MODEL"]  # real local-model calls only where the host has a model
    if args.enable_meta_synthetic and args.enable_local_ai:
        parser.error("Choose local AI or Meta, not both.")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and65535")
    try:
        if args.enable_paypal_sandbox:
            gateway = SandboxGateway.from_environment()
            case = RefundCase(capture=os.environ.get("PAYPAL_SANDBOX_CAPTURE_ID", ""), amount=os.environ.get("CLEARWAKE_REFUND_AMOUNT", "1.00"))
        else:
            gateway = RehearsalGateway(args.database.resolve().with_name("rehearsal-provider.sqlite3"), args.rehearsal_outcome)
            case = RefundCase()
        worker = None
        if args.enable_meta_synthetic:
            from relayloom.meta import MetaWorker
            worker = MetaWorker.from_environment()
        elif args.enable_local_ai:
            from .local_ai import LocalWorker
            worker = LocalWorker.from_environment()
        controller = RefundController(args.database, case=case, gateway=gateway, worker=worker)
        console = Console(args.database.resolve().parent / "console", args.console_model)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    server = ClearwakeServer((args.host, args.port), controller, console, hosted=hosted)
    print(f"Clearwake: http://127.0.0.1:{args.port}")
    print(f"Console:   http://127.0.0.1:{args.port}/console (local run on the local provider; agents: {console.adapter.label()})")
    print(f"Payments: {gateway.mode}. Specialists: {controller.mode}. No calls occur just by opening the page.")
    print("Loopback only. Use synthetic data. One immutable bounded capture per database.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close(); controller.close()


if __name__ == "__main__":
    main()
