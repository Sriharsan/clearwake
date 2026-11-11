"""Run the four cases against the real PayPal SANDBOX and print PASS or FAIL for each.

Needs clearwake/.env with the sandbox keys and PAYPAL_SANDBOX_CAPTURE_ID from scripts/sandbox_setup.py.
Each run sends two real USD 1.00 sandbox refunds (cases a and b) against that USD 20.00 capture.
Credentials are never printed. Usage: python scripts/check_sandbox.py [--local-ai]
"""
from pathlib import Path
import json
import os
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))

from clearwake import envfile  # noqa: E402
from clearwake.controller import RefundCase  # noqa: E402
from clearwake.paypal import GatewayError, SandboxGateway  # noqa: E402
from relayloom.controller import Rejected  # noqa: E402
from check_run import Case  # noqa: E402


class CountingGateway:
    """The real sandbox gateway, counting refund POSTs. With lose_response, the real refund is sent and
    its response is withheld from Clearwake (an injected fault in sandbox); the response is kept as the
    operator's view of the merchant record, standing in for a lookup in the sandbox dashboard."""
    mode = "paypal-sandbox"

    def __init__(self, real, lose_response=False):
        self.real, self.lose_response, self.refund_posts, self.operator_view = real, lose_response, 0, None
        self.client_id = real.client_id

    def capture(self, capture_id):
        return self.real.capture(capture_id)

    def refund(self, *args):
        self.refund_posts += 1
        result = self.real.refund(*args)
        if self.lose_response:
            self.operator_view = result
            raise GatewayError("Injected fault in sandbox: the real refund was sent but its response was withheld.")
        return result

    def refund_record(self, refund_id):
        return self.real.refund_record(refund_id)


def local_ai_worker():
    from clearwake.local_ai import LocalWorker, MODEL
    tags = json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5))
    os.environ.setdefault("CLEARWAKE_LOCAL_AI_ACK", "I_CONFIRM_LOCAL_SYNTHETIC")
    os.environ.setdefault("CLEARWAKE_LOCAL_MODEL_DIGEST", next(m["digest"] for m in tags["models"] if m["name"] == MODEL))
    os.environ.setdefault("CLEARWAKE_LOCAL_LEDGER", str(ROOT / "data" / "sandbox" / "local-ai-ledger.sqlite3"))
    return LocalWorker.from_environment()


def under_limit(case, gateway):
    body = case.grant()
    case.action("refund", **body)
    sent = case.operation()
    case.action("reconcile", revision=body["revision"], operation_id=sent["id"], refund_id=sent["provider_id"])
    final = case.operation()
    return sent["state"] == "AWAITING_VERIFICATION" and final["state"] == "VERIFIED" and gateway.refund_posts == 1, \
        f"sandbox refund {sent['provider_id']}: {sent['state']}, then {final['state']} after reading the sandbox refund record"


def lost_response(case, gateway):
    body = case.grant()
    try:
        case.action("refund", **body)
    except Rejected:
        pass
    held = case.operation()["state"]
    again = case.action("refund", **body)
    return held == "UNKNOWN" and again.get("replayed") is True and gateway.refund_posts == 1, \
        f"injected fault in sandbox: state {held}, second send replayed={again.get('replayed')}, sandbox refund POSTs={gateway.refund_posts}"


def reconcile_unknown(case, gateway):
    before = case.operation()
    refund_id = (gateway.operator_view or {}).get("id")
    case.action("reconcile", revision=case.state()["room"]["revision"], operation_id=before["id"], refund_id=refund_id)
    after = case.operation()["state"]
    return before["state"] == "UNKNOWN" and after == "VERIFIED" and gateway.refund_posts == 1, \
        f"read sandbox refund {refund_id}: {before['state']} resolved to {after}, no second POST"


def over_limit(case, gateway):
    try:
        RefundCase(capture=case.controller.case.capture, amount="6.00"); configured = "accepted"
    except ValueError:
        configured = "refused"
    body = case.grant()
    try:
        case.action("refund", **{**body, "amount": "6.00"}); sent = "accepted"
    except Rejected:
        sent = "refused"
    return configured == "refused" and sent == "refused" and case.operation() is None and gateway.refund_posts == 0, \
        f"USD 6.00 case {configured}, USD 6.00 send {sent}, sandbox refund POSTs={gateway.refund_posts}"


def main():
    filled = envfile.load(ROOT / ".env")
    missing = [n for n in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "CLEARWAKE_SANDBOX_ACK", "PAYPAL_SANDBOX_CAPTURE_ID") if not filled[n]]
    if missing:
        sys.exit("Missing in clearwake/.env: " + ", ".join(missing) + ". Run scripts/sandbox_setup.py after adding the keys.")
    real = SandboxGateway.from_environment()
    refund_case = RefundCase(capture=os.environ["PAYPAL_SANDBOX_CAPTURE_ID"], amount="1.00")
    worker = local_ai_worker() if "--local-ai" in sys.argv else None
    print("Clearwake check against the PayPal SANDBOX (api-m.sandbox.paypal.com). Specialists:",
          "local AI (qwen2.5-coder:3b)" if worker else "deterministic")
    results, failed = [], 0
    with tempfile.TemporaryDirectory() as folder:
        steps = [("a. Refund under the limit, checked against the sandbox record", under_limit, CountingGateway(real), "a"),
                 ("b. Lost response goes to UNKNOWN, no blind retry", lost_response, CountingGateway(real, lose_response=True), "bc"),
                 ("c. Reconciliation resolves UNKNOWN from the sandbox record", reconcile_unknown, None, "bc"),
                 ("d. Over limit refund refused before any money moves", over_limit, CountingGateway(real), "d")]
        cases = {}
        for title, check, gateway, key in steps:
            if key not in cases:
                cases[key] = (Case(Path(folder) / key, None, gateway=gateway, case=refund_case, worker=worker), gateway)
            case, gateway = cases[key]
            try:
                ok, detail = check(case, gateway)
            except Exception as error:  # report the failure, never the credentials
                ok, detail = False, f"{type(error).__name__}: {str(error)[:200]}"
            failed += not ok
            results.append((ok, title, detail))
            print(f"{'PASS' if ok else 'FAIL'}  {title}  ({detail})", flush=True)
        for case, _ in cases.values():
            case.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
