"""Offline integration tests: real reused controller, durable DB and fake provider."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from clearwake.controller import RefundCase, RefundController
from clearwake.paypal import BASE, GatewayError, RehearsalGateway, SandboxGateway, transport
from clearwake.server import ClearwakeServer, core_script, workroom_page
from relayloom.controller import Rejected, digest


def specialist(role, intent, dependencies):
    output = {"summary": "A concise synthetic specialist response."}
    if role == "product":
        output.update(audience=intent["audience"], brief=intent["brief"])
    else:
        output["refund_days"] = intent["refund_days"]
        if role == "engineering":
            output["boundary"] = "draft-only"
        else:
            output.update(audience=intent["audience"], dependencies={key: digest(value) for key, value in dependencies.items()})
    return output


class RefundTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "workroom.sqlite3"
        self.gateway = RehearsalGateway(Path(self.folder.name) / "provider.sqlite3")
        self.controller = RefundController(self.path, gateway=self.gateway, worker=specialist)
        self.owner = self.controller.create({"name": "Synthetic refund review", "display_name": "Owner", "brief": "Review a fictional refund policy."})
        self.csrf = self.controller.session(self.owner)["csrf"]

    def tearDown(self):
        self.controller.close(); self.folder.cleanup()

    def action(self, name, token=None, **body):
        token = token or self.owner
        return self.controller.mutate(token, self.controller.session(token).get("csrf", ""), name, body)

    def ready(self):
        revision = self.controller.snapshot(self.owner)["room"]["revision"]
        self.action("run", revision=revision)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = self.controller.snapshot(self.owner)
            if all(row["state"] in ("COMPLETE", "REUSED") for row in state["tasks"]):
                break
            time.sleep(.01)
        else:
            self.fail("specialists did not settle")
        self.action("permission", revision=revision, publish=True)
        self.action("publish", revision=revision)
        return revision

    def grant(self):
        revision = self.ready()
        existing = self.controller.snapshot(self.owner)["payment"]["grant"]["id"]
        self.action("refund-grant", revision=revision, grant_id=existing, allow=True, **self.controller.case.fields())
        return self.refund_body()

    def refund_body(self):
        state = self.controller.snapshot(self.owner)
        return {"revision": state["room"]["revision"], "grant_id": state["payment"]["grant"]["id"], **self.controller.case.fields()}

    def operation(self):
        return self.controller.snapshot(self.owner)["payment"]["operation"]

    def join(self, role):
        invite = self.action("invites", role=role)["invite"]
        return self.controller.join({"invite": invite, "display_name": role.title()})

    def test_default_has_zero_network_calls_and_artifact_is_not_payment_permission(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden")):
            self.ready()
            with self.assertRaises(Rejected):
                self.action("refund", revision=1, grant_id=None, **self.controller.case.fields())
        self.assertIsNone(self.operation())
        self.assertEqual(self.controller.snapshot(self.owner)["metrics"]["model_calls"], 0)

    def test_complete_plan_separate_grant_one_effect_and_provider_read(self):
        body = self.grant()
        self.action("refund", **body)
        operation = self.operation()
        self.assertEqual(operation["state"], "AWAITING_VERIFICATION")
        self.assertEqual(self.action("refund", **body)["replayed"], True)
        self.action("reconcile", revision=1, operation_id=operation["id"], refund_id=operation["provider_id"])
        self.assertEqual(self.operation()["state"], "VERIFIED")
        with closing(sqlite3.connect(self.gateway.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM records").fetchone()[0], 1)

    def test_owner_only_grant_send_revoke_and_reconcile(self):
        body = self.grant()
        for role in ("editor", "viewer"):
            token = self.join(role)
            for action, values in [("refund-grant", {**body, "allow": False}), ("refund", body), ("reconcile", {"revision": 1, "operation_id": "unknown", "refund_id": "X"})]:
                with self.assertRaises(Rejected):
                    self.action(action, token=token, **values)
        self.assertIsNone(self.operation())

    def test_exact_case_schema_and_bounded_amount(self):
        body = self.grant()
        for key, bad in [("capture", "OTHER"), ("amount", "2.00"), ("amount", 1), ("currency", "EUR")]:
            with self.assertRaises(Rejected):
                self.action("refund", **{**body, key: bad})
        for value in ("5.01", "0.00", "-1.00", "NaN", "1", 1, True):
            with self.assertRaises(ValueError):
                RefundCase(amount=value)
        self.assertIsNone(self.operation())

    def test_expired_revoked_and_stale_grants_refuse_before_post(self):
        body = self.grant()
        self.action("refund-grant", revision=1, grant_id=body["grant_id"], allow=False)
        with self.assertRaises(Rejected): self.action("refund", **body)
        self.assertEqual(self.controller.snapshot(self.owner)["payment"]["grant"]["status"], "REVOKED")
        self.assertTrue(any(row["type"] == "refund_revoked" for row in self.controller.snapshot(self.owner)["events"]))
        self.action("refund-grant", revision=1, grant_id=body["grant_id"], allow=True, **self.controller.case.fields())
        body = self.refund_body()
        with self.controller.db() as db: db.execute("UPDATE cw_grants SET expires=0")
        with self.assertRaises(Rejected): self.action("refund", **body)
        self.action("intent", revision=1, brief="A revised synthetic goal", audience="Members", refund_days=14)
        with self.assertRaises(Rejected): self.action("refund", **body)
        self.assertIsNone(self.operation())

    def test_grant_compare_and_swap_refuses_changed_identity(self):
        body = self.grant()
        with self.assertRaises(Rejected):
            self.action("refund-grant", revision=1, grant_id=None, allow=False)
        self.assertEqual(self.controller.snapshot(self.owner)["payment"]["grant"]["status"], "ACTIVE")
        with self.assertRaises(Rejected):
            self.action("refund", **{**body, "grant_id": "old-grant"})

    def test_revoke_while_capture_read_is_waiting_stops_final_dispatch(self):
        body = self.grant(); started, release = threading.Event(), threading.Event()
        original_capture, original_refund = self.gateway.capture, self.gateway.refund
        posts = []
        def capture(identifier):
            started.set(); release.wait(3); return original_capture(identifier)
        def refund(*args):
            posts.append(args); return original_refund(*args)
        self.gateway.capture, self.gateway.refund = capture, refund
        with ThreadPoolExecutor(max_workers=2) as pool:
            request = pool.submit(self.action, "refund", **body)
            self.assertTrue(started.wait(2))
            self.action("refund-grant", revision=1, grant_id=body["grant_id"], allow=False)
            release.set()
            with self.assertRaises(Rejected): request.result()
        self.assertEqual(posts, [])
        self.assertEqual(self.operation()["state"], "BLOCKED")

    def test_intent_change_while_preflight_waits_stops_dispatch(self):
        body = self.grant(); started, release = threading.Event(), threading.Event()
        capture = self.gateway.capture
        self.gateway.capture = lambda identifier: (started.set(), release.wait(3), capture(identifier))[2]
        with ThreadPoolExecutor(max_workers=2) as pool:
            request = pool.submit(self.action, "refund", **body); self.assertTrue(started.wait(2))
            self.action("intent", revision=1, brief="Changed direction", audience="Members", refund_days=7)
            release.set()
            with self.assertRaises(Rejected): request.result()
        self.assertEqual(self.operation()["state"], "BLOCKED")
        with closing(sqlite3.connect(self.gateway.path)) as db, db: self.assertEqual(db.execute("SELECT count(*) FROM records").fetchone()[0], 0)

    def test_parallel_duplicate_requests_send_once(self):
        body = self.grant()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.action("refund", **body), range(6)))
        self.assertTrue(all(value["ok"] for value in results))
        with closing(sqlite3.connect(self.gateway.path)) as db, db: self.assertEqual(db.execute("SELECT count(*) FROM records").fetchone()[0], 1)

    def test_unknown_timeout_survives_restart_no_second_post_and_explicit_known_record(self):
        body = self.grant(); self.gateway.outcome = "lost-response"
        self.action("refund", **body); before = self.operation()
        self.assertEqual(before["state"], "UNKNOWN")
        with closing(sqlite3.connect(self.gateway.path)) as db, db: refund_id = db.execute("SELECT refund_id FROM records").fetchone()[0]
        self.controller.close()
        self.controller = RefundController(self.path, gateway=self.gateway, worker=specialist)
        self.assertEqual(self.operation()["request_id"], before["request_id"])
        self.assertEqual(self.operation()["state"], "UNKNOWN")
        self.assertTrue(self.action("refund", **body)["replayed"])
        self.action("refund-grant", revision=1, grant_id=body["grant_id"], allow=False)
        self.action("reconcile", revision=1, operation_id=before["id"], refund_id=refund_id)
        self.assertEqual(self.operation()["state"], "VERIFIED")
        with closing(sqlite3.connect(self.gateway.path)) as db, db: self.assertEqual(db.execute("SELECT count(*) FROM records").fetchone()[0], 1)

    def test_crashed_reserved_operation_becomes_unknown_and_cannot_replay(self):
        body = self.grant(); self.action("refund", **body)
        with self.controller.db() as db: db.execute("UPDATE cw_refunds SET state='RESERVED'")
        self.controller.close(); self.controller = RefundController(self.path, gateway=self.gateway, worker=specialist)
        self.assertEqual(self.operation()["state"], "UNKNOWN")
        self.assertTrue(self.action("refund", **body)["replayed"])

    def test_pending_record_only_verifies_after_explicit_completed_read(self):
        body = self.grant(); self.gateway.outcome = "pending"; self.action("refund", **body)
        op = self.operation()
        self.action("reconcile", revision=1, operation_id=op["id"], refund_id=op["provider_id"])
        self.assertEqual(self.operation()["state"], "PENDING")
        with closing(sqlite3.connect(self.gateway.path)) as db, db:
            stored = json.loads(db.execute("SELECT body FROM records").fetchone()[0]); stored["status"] = "COMPLETED"
            db.execute("UPDATE records SET body=?", (json.dumps(stored),))
        self.action("reconcile", revision=1, operation_id=op["id"])
        self.assertEqual(self.operation()["state"], "VERIFIED")

    def test_provider_mismatches_fail_closed_and_identity_cannot_be_swapped(self):
        body = self.grant(); self.action("refund", **body); op = self.operation()
        original = self.gateway.refund_record(op["provider_id"])
        for field, bad in [("amount", {"value": "2.00", "currency_code": "USD"}), ("custom_id", "different-request"), ("links", []), ("status", "APPROVED"), ("id", "OTHER-ID")]:
            altered = deepcopy(original); altered[field] = bad
            self.gateway.refund_record = lambda _, result=altered: result
            with self.assertRaises(Rejected): self.action("reconcile", revision=1, operation_id=op["id"], refund_id=op["provider_id"])
            self.assertEqual(self.operation()["state"], "AWAITING_VERIFICATION")
        with self.assertRaises(Rejected): self.action("reconcile", revision=1, operation_id=op["id"], refund_id="OTHER-ID")

    def test_current_capture_mismatch_never_posts(self):
        body = self.grant()
        self.gateway.capture = lambda _: {"id": "OTHER", "status": "COMPLETED", "amount": {"value": "10.00", "currency_code": "USD"}}
        self.gateway.refund = lambda *args: self.fail("refund must not be called")
        with self.assertRaises(Rejected): self.action("refund", **body)
        self.assertEqual(self.operation()["state"], "BLOCKED")

    def test_partially_refunded_capture_still_passes_preflight_but_other_statuses_do_not(self):
        body = self.grant()
        for status in ("PENDING", "REFUNDED", "DECLINED"):
            self.gateway.capture = lambda _, s=status: {"id": "DEMO-CAPTURE-0001", "status": s, "amount": {"value": "10.00", "currency_code": "USD"}}
            with self.assertRaises(Rejected): self.action("refund", **body)
            with self.controller.db() as db:
                db.execute("DELETE FROM cw_refunds")
        self.gateway.capture = lambda _: {"id": "DEMO-CAPTURE-0001", "status": "PARTIALLY_REFUNDED", "amount": {"value": "10.00", "currency_code": "USD"}}
        self.action("refund", **body)
        self.assertEqual(self.operation()["state"], "AWAITING_VERIFICATION")

    def test_session_revocation_while_preflight_waits_stops_dispatch(self):
        body = self.grant(); started, release = threading.Event(), threading.Event()
        capture = self.gateway.capture
        self.gateway.capture = lambda identifier: (started.set(), release.wait(3), capture(identifier))[2]
        with ThreadPoolExecutor(max_workers=2) as pool:
            request = pool.submit(self.action, "refund", **body); self.assertTrue(started.wait(2))
            self.action("logout"); release.set()
            with self.assertRaises(Rejected): request.result()
        with self.controller.db() as db:
            self.assertEqual(db.execute("SELECT state FROM cw_refunds").fetchone()[0], "BLOCKED")
        with closing(sqlite3.connect(self.gateway.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM records").fetchone()[0], 0)

    def test_previously_verified_receipt_cannot_regress_on_older_pending_read(self):
        self.action("refund", **self.grant()); operation = self.operation()
        self.action("reconcile", revision=1, operation_id=operation["id"])
        receipt = self.gateway.refund_record(operation["provider_id"]); receipt["status"] = "PENDING"
        self.gateway.refund_record = lambda _: receipt
        with self.assertRaises(Rejected): self.action("reconcile", revision=1, operation_id=operation["id"])
        self.assertEqual(self.operation()["state"], "VERIFIED")

    def test_cross_room_has_no_payment_record_or_second_effect(self):
        self.action("refund", **self.grant()); op = self.operation()
        other = self.controller.create({"name": "Another room", "display_name": "Other", "brief": "Different synthetic goal"})
        self.assertIsNone(self.controller.snapshot(other)["payment"]["operation"])
        with self.assertRaises(Rejected): self.action("reconcile", token=other, revision=1, operation_id=op["id"], refund_id=op["provider_id"])

    def test_changed_persistent_case_is_rejected(self):
        self.controller.close()
        with self.assertRaises(ValueError): RefundController(self.path, case=RefundCase(amount="2.00"), gateway=self.gateway, worker=specialist)


class TransportTests(unittest.TestCase):
    def test_sandbox_oauth_capture_refund_record_shapes_with_fake_http(self):
        calls = []
        def send(request, timeout):
            calls.append(request)
            self.assertEqual(timeout, 15)
            if request.full_url.endswith("/token"): return {"access_token": "synthetic-token", "token_type": "Bearer", "expires_in": 3600}
            return {"id": "synthetic-response"}
        gateway = SandboxGateway("synthetic-client", "synthetic-secret", send=send)
        gateway.capture("CAPTURE1")
        gateway.refund("CAPTURE1", "1.00", "USD", "12345678-1234-4234-8234-123456789abc")
        gateway.refund_record("REFUND1")
        self.assertEqual(len(calls), 4)
        refund = calls[2]
        self.assertEqual(refund.full_url, BASE + "/v2/payments/captures/CAPTURE1/refund")
        self.assertEqual(refund.get_header("Paypal-request-id"), "12345678-1234-4234-8234-123456789abc")
        self.assertEqual(json.loads(refund.data)["custom_id"], "12345678-1234-4234-8234-123456789abc")
        self.assertEqual(json.loads(refund.data)["amount"], {"value": "1.00", "currency_code": "USD"})

    def test_setup_order_and_capture_use_only_sandbox_routes(self):
        calls = []
        def send(request, timeout):
            calls.append(request)
            if request.full_url.endswith("/token"): return {"access_token": "synthetic-token", "token_type": "Bearer", "expires_in": 3600}
            return {"id": "ORDER1"}
        gateway = SandboxGateway("synthetic-client", "synthetic-secret", send=send)
        request_id = "12345678-1234-4234-8234-123456789abc"
        gateway.create_order("20.00", request_id, "http://127.0.0.1:8810/sandbox-approved")
        gateway.order("ORDER1")
        gateway.capture_order("ORDER1", request_id)
        self.assertEqual([c.full_url for c in calls[1:]], [BASE + "/v2/checkout/orders", BASE + "/v2/checkout/orders/ORDER1",
                                                           BASE + "/v2/checkout/orders/ORDER1/capture"])
        self.assertEqual(json.loads(calls[1].data)["purchase_units"][0]["amount"], {"currency_code": "USD", "value": "20.00"})
        for bad in (("50.01", request_id, "http://127.0.0.1:8810/x"), ("20.00", "not-a-uuid", "http://127.0.0.1:8810/x"),
                    ("20.00", request_id, "https://example.invalid/return")):
            with self.assertRaises(ValueError): gateway.create_order(*bad)
        from urllib.request import Request
        with self.assertRaises(GatewayError): transport(Request("https://api-m.paypal.com/v2/checkout/orders"))
        gateway.create_card_order("20.00", request_id, "4012888888881881", "2030-12")
        self.assertEqual(json.loads(calls[-1].data)["payment_source"]["card"]["expiry"], "2030-12")
        for bad in (("20.00", request_id, "4012-8888", "2030-12"), ("20.00", request_id, "4012888888881881", "12/30"), ("60.00", request_id, "4012888888881881", "2030-12")):
            with self.assertRaises(ValueError): gateway.create_card_order(*bad)

    def test_production_destination_and_identifier_injection_are_refused(self):
        from urllib.request import Request
        with self.assertRaises(ValueError): SandboxGateway("x", "y", base="https://api-m.paypal.com")
        with self.assertRaises(GatewayError): transport(Request("https://api-m.paypal.com/v1/oauth2/token"))
        gateway = SandboxGateway("x", "y", send=lambda *args: self.fail("no request should be sent"))
        for capture in ("../refunds/OTHER", "X?secret=1", "X\r\nHeader: value", "https://example.invalid"):
            with self.assertRaises(ValueError): gateway.capture(capture)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.controller = RefundController(Path(self.folder.name) / "http.sqlite3", worker=specialist)
        self.server = ClearwakeServer(("127.0.0.1", 0), self.controller)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.controller.close(); self.folder.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse(); content = response.read()
        result = (response.status, dict(response.getheaders()), content); connection.close(); return result

    def test_real_http_auth_csrf_same_origin_and_extension_assets(self):
        self.assertEqual(self.request("GET", "/api/state")[0], 401)
        status, headers, _ = self.request("POST", "/api/rooms", {"name": "HTTP synthetic", "display_name": "Owner", "brief": "A synthetic refund"})
        self.assertEqual(status, 201); cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertTrue(cookie.startswith("clearwake_session="))
        self.assertIn("HttpOnly; SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(self.request("GET", "/api/state", headers={"Cookie": cookie.replace("clearwake_session=", "relayloom_session=")})[0], 401)
        status, _, raw = self.request("GET", "/api/session", headers={"Cookie": cookie}); csrf = json.loads(raw)["csrf"]
        body = {"revision": 1, "grant_id": None, "allow": True, **self.controller.case.fields()}
        self.assertEqual(self.request("POST", "/api/refund-grant", body, {"Cookie": cookie})[0], 403)
        self.assertEqual(self.request("POST", "/api/refund-grant", body, {"Cookie": cookie, "X-Relayloom-CSRF": csrf, "Origin": "https://attacker.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/api/refund-grant", body, {"Cookie": cookie, "X-Relayloom-CSRF": csrf})[0], 409)
        for asset in ("/", "/app.js", "/style.css", "/payment.js", "/payment.css"):
            status, headers, content = self.request("GET", asset)
            self.assertEqual(status, 200, asset); self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"]); self.assertTrue(content)
        self.assertIn(b"Clearwake", workroom_page()); self.assertIn(b"clearwake:state", core_script())
        self.assertIn(b"Local AI configured", core_script())
        self.assertEqual(self.request("GET", "/../README.md")[0], 404)


if __name__ == "__main__":
    unittest.main()
