"""Run the four demo cases against the rehearsal gateway and print PASS or FAIL.

Rehearsal only: synthetic records, fake provider, zero network or model calls.
Each case uses its own temporary database, like the separate demo databases.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clearwake.controller import RefundCase, RefundController  # noqa: E402
from clearwake.paypal import RehearsalGateway  # noqa: E402
from relayloom.controller import Rejected  # noqa: E402


class Case:
    def __init__(self, folder, outcome):
        self.gateway = RehearsalGateway(Path(folder) / "rehearsal-provider.sqlite3", outcome)
        self.controller = RefundController(Path(folder) / "case.sqlite3", gateway=self.gateway)
        self.owner = self.controller.create({"name": "Synthetic refund review", "display_name": "Owner", "brief": "Review a fictional refund policy."})

    def action(self, name, **body):
        return self.controller.mutate(self.owner, self.controller.session(self.owner)["csrf"], name, body)

    def state(self):
        return self.controller.snapshot(self.owner)

    def grant(self):
        revision = self.state()["room"]["revision"]
        self.action("run", revision=revision)
        deadline = time.monotonic() + 10
        while not all(row["state"] in ("COMPLETE", "REUSED") for row in self.state()["tasks"]):
            if time.monotonic() > deadline:
                raise RuntimeError("specialists did not settle")
            time.sleep(.05)
        self.action("permission", revision=revision, publish=True)
        self.action("publish", revision=revision)
        self.action("refund-grant", revision=revision, grant_id=self.state()["payment"]["grant"]["id"], allow=True, **self.controller.case.fields())
        state = self.state()
        return {"revision": revision, "grant_id": state["payment"]["grant"]["id"], **self.controller.case.fields()}

    def operation(self):
        return self.state()["payment"]["operation"]

    def provider_records(self):
        with closing(sqlite3.connect(self.gateway.path)) as db:
            return db.execute("SELECT refund_id FROM records").fetchall()

    def close(self):
        self.controller.close()


def under_limit(case):
    body = case.grant()
    case.action("refund", **body)
    sent = case.operation()
    case.action("reconcile", revision=body["revision"], operation_id=sent["id"], refund_id=sent["provider_id"])
    final = case.operation()
    return sent["state"] == "AWAITING_VERIFICATION" and final["state"] == "VERIFIED" and len(case.provider_records()) == 1, \
        f"sent {sent['state']}, after provider record check {final['state']}"


def lost_response(case):
    body = case.grant()
    try:
        case.action("refund", **body)
    except Rejected:
        pass
    held = case.operation()["state"]
    again = case.action("refund", **body)
    return held == "UNKNOWN" and again.get("replayed") is True and len(case.provider_records()) == 1, \
        f"state {held}, second send replayed={again.get('replayed')}, provider records {len(case.provider_records())}"


def reconcile_unknown(case):
    body = case.grant()
    try:
        case.action("refund", **body)
    except Rejected:
        pass
    before = case.operation()
    # The operator reads the known refund ID from the synthetic provider's own record.
    refund_id = case.provider_records()[0][0]
    case.action("reconcile", revision=body["revision"], operation_id=before["id"], refund_id=refund_id)
    after = case.operation()["state"]
    return before["state"] == "UNKNOWN" and after == "VERIFIED" and len(case.provider_records()) == 1, \
        f"{before['state']} resolved to {after} with no second refund"


def over_limit(case):
    try:
        RefundCase(amount="6.00")
        configured = "accepted"
    except ValueError:
        configured = "refused"
    body = case.grant()
    try:
        case.action("refund", **{**body, "amount": "6.00"})
        sent = "accepted"
    except Rejected:
        sent = "refused"
    untouched = case.operation() is None and not case.provider_records()
    return configured == "refused" and sent == "refused" and untouched, \
        f"USD 6.00 case {configured}, USD 6.00 send {sent}, nothing reserved or sent={untouched}"


CASES = [
    ("1. Refund under the limit is sent and checked against the record", "completed", under_limit),
    ("2. Lost provider response goes to UNKNOWN and is not retried", "lost-response", lost_response),
    ("3. Reconciliation resolves UNKNOWN to its true state", "lost-response", reconcile_unknown),
    ("4. Over limit refund is refused before any money moves", "completed", over_limit),
]


def main():
    print("Clearwake demo check. REHEARSAL ONLY: fake provider, synthetic records, no network.")
    failed = 0
    for title, outcome, check in CASES:
        with tempfile.TemporaryDirectory() as folder:
            case = Case(folder, outcome)
            try:
                ok, detail = check(case)
            except Exception as error:  # report, do not hide, an unexpected failure
                ok, detail = False, f"{type(error).__name__}: {error}"
            finally:
                case.close()
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {title}  ({detail})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
