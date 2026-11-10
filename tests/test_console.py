"""Console endpoints over real loopback HTTP: CSRF, the rehearsal cases, the inbox, reconcile and the verifier assets."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from clearwake.console import Console
from clearwake.controller import RefundController
from clearwake.server import ClearwakeServer
from verdock_core.receipts import verify_log


def no_network(*args, **kwargs):
    raise AssertionError("The console made a network call in rehearsal.")


class ConsoleHTTPTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.controller = RefundController(root / "http.sqlite3")
        self.console = Console(root / "console")
        self.server = ClearwakeServer(("127.0.0.1", 0), self.controller, self.console)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.guard = patch("urllib.request.OpenerDirector.open", no_network)
        self.guard.start()
        status, headers, raw = self.request("GET", "/console/api/session")
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertTrue(self.cookie.startswith("clearwake_console="))
        self.assertIn("HttpOnly; SameSite=Strict", headers["Set-Cookie"])
        self.csrf = json.loads(raw)["csrf"]

    def tearDown(self):
        self.guard.stop()
        self.server.shutdown(); self.server.server_close(); self.controller.close(); self.folder.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        connection.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse(); content = response.read()
        result = (response.status, dict(response.getheaders()), content); connection.close(); return result

    def post(self, path, body):
        status, _, raw = self.request("POST", path, body, {"Cookie": self.cookie, "X-Clearwake-CSRF": self.csrf})
        return status, json.loads(raw)

    def run_case(self, key):
        status, value = self.post("/console/api/case", {"case": key})
        self.assertEqual(status, 200, value)
        self.assertEqual(value["label"], "rehearsal data")
        return value["entries"]

    def test_mutations_need_the_console_csrf_token_and_same_origin(self):
        body = {"case": "c"}
        self.assertEqual(self.request("POST", "/console/api/case", body)[0], 403)
        self.assertEqual(self.request("POST", "/console/api/case", body, {"Cookie": self.cookie})[0], 403)
        self.assertEqual(self.request("POST", "/console/api/case", body, {"Cookie": self.cookie, "X-Clearwake-CSRF": "0" * 64})[0], 403)
        self.assertEqual(self.request("POST", "/console/api/case", body, {"X-Clearwake-CSRF": self.csrf})[0], 403)
        self.assertEqual(self.request("POST", "/console/api/case", body, {"Cookie": self.cookie, "X-Clearwake-CSRF": self.csrf,
                                                                         "Origin": "https://attacker.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/console/api/case", body, {"Cookie": self.cookie, "X-Clearwake-CSRF": self.csrf,
                                                                         "Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.request("POST", "/console/api/case", body, {"Cookie": self.cookie, "X-Clearwake-CSRF": self.csrf, "Host": "evil.test"})[0], 403)
        self.assertEqual(self.console.entries, [])
        self.assertEqual(self.post("/console/api/case", body)[0], 200)
        self.assertEqual(self.post("/console/api/case", {"case": "z"})[0], 400)
        self.assertEqual(self.post("/console/api/unknown", {})[0], 404)

    def test_refund_cases_reach_the_same_states_as_the_case_runner(self):
        self.assertEqual([e["state"] for e in self.run_case("c")], ["VERIFIED"])
        self.assertEqual([e["state"] for e in self.run_case("d")], ["awaiting approval"])
        e = self.run_case("e")
        self.assertEqual([x["state"] for x in e], ["UNKNOWN"])
        self.assertEqual([h["state"] for h in e[0]["history"]], ["UNKNOWN", "UNKNOWN"])  # the second attempt sends nothing
        self.assertEqual(sorted(x["state"] for x in self.run_case("f")), sorted(["VERIFIED", "VERIFIED", "refused"]))
        g = self.run_case("g")
        self.assertEqual([x["state"] for x in g], ["refused"])
        lines = [json.loads(line) for line in Path(self.console.swarm.receipts.path).read_text(encoding="utf-8").splitlines()]
        refusal = [line for line in lines if line["action_id"] == "clearwake.policy.refused" and line["params"]["case"] == g[0]["id"]]
        self.assertEqual(refusal[0]["params"]["limit_minor"], 500)

    def test_dispute_cases_reach_the_same_states_as_the_case_runner(self):
        self.assertEqual([(x["action"], x["state"]) for x in self.run_case("i")], [("provide_evidence", "VERIFIED")])
        j = self.run_case("j")
        self.assertEqual([(x["action"], x["state"]) for x in j], [("provide_evidence", "VERIFIED")])
        self.assertTrue(j[0]["receipt_ok"])
        self.assertTrue(any(s.startswith("Mandate receipt") for s in j[0]["sources"]))
        k = self.run_case("k")
        self.assertEqual([x["state"] for x in k], ["awaiting approval"])
        self.assertLess(k[0]["deadline"]["seconds_left"], 5 * 3600 + 1)
        batch = self.run_case("l")
        self.assertEqual(len(batch), 10)
        summary = {"evidenced": sum(x["action"] == "provide_evidence" and x["state"] == "VERIFIED" for x in batch),
                   "refunded": sum(x["action"] == "accept_and_refund" and x["state"] == "VERIFIED" for x in batch),
                   "escalated": sum(x["state"] == "awaiting approval" for x in batch)}
        self.assertEqual(sum(summary.values()), 10)

    def test_approve_then_rerun_reaches_verified(self):
        pending = self.run_case("d")[0]
        status, value = self.post("/console/api/approve", {"approval_id": pending["approval_id"], "approver": ""})
        self.assertEqual(status, 400)
        status, value = self.post("/console/api/approve", {"approval_id": pending["approval_id"], "approver": "Sri (approver)"})
        self.assertEqual(status, 200, value)
        self.assertEqual(value["state"], "VERIFIED")
        self.assertEqual(value["approver"], "Sri (approver)")
        self.assertEqual(self.post("/console/api/approve", {"approval_id": pending["approval_id"], "approver": "Sri (approver)"})[0], 409)
        _, _, raw = self.request("GET", "/console/api/state")
        state = json.loads(raw)
        self.assertEqual([a["status"] for a in state["inbox"]], ["CONSUMED"])
        self.assertIn("VERIFIED", [row["state"] for row in state["ledger"]["rows"]])

    def test_reconcile_settles_unknown_from_the_record_without_resending(self):
        e = self.run_case("e")[0]
        self.assertEqual(self.post("/console/api/reconcile", {"case_id": "nope"})[0], 404)
        status, value = self.post("/console/api/reconcile", {"case_id": e["id"]})
        self.assertEqual(status, 200, value)
        self.assertEqual(value["state"], "VERIFIED")
        self.assertEqual(self.post("/console/api/reconcile", {"case_id": e["id"]})[0], 409)
        _, _, raw = self.request("GET", "/console/api/state")
        self.assertEqual(json.loads(raw)["ledger"]["provider_refunds"], 1)

    def test_buyer_agent_signs_only_purchases_inside_the_mandate(self):
        status, bought = self.post("/console/api/buy", {"request": "A dot grid notebook for meeting notes"})
        self.assertEqual(status, 200)
        self.assertTrue(bought["allowed"]); self.assertEqual(bought["model"], "scripted, not AI")
        self.assertTrue(all(bought["checks"].values()))
        self.assertTrue(bought["receipt"]["log_ok"]); self.assertEqual(len(bought["receipt"]["digest"]), 64)
        status, refused = self.post("/console/api/buy", {"request": "Wireless headphones"})
        self.assertFalse(refused["allowed"]); self.assertIsNone(refused["receipt"])
        self.assertFalse(refused["checks"]["category allowed"])
        self.assertEqual(self.post("/console/api/buy", {"request": ""})[0], 400)
        _, _, raw = self.request("GET", "/console/api/state")
        mandate = json.loads(raw)["mandate"]
        self.assertEqual((mandate["budget"], mandate["spent"], mandate["remaining"]), ("102.00", "9.00", "93.00"))

    def test_receipt_logs_and_keys_verify(self):
        self.run_case("c"); self.post("/console/api/buy", {"request": "A stoneware mug"})
        _, headers, raw = self.request("GET", "/console/api/receipts")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        logs = json.loads(raw)["logs"]
        self.assertEqual([log["name"] for log in logs], ["merchant", "buyer"])
        for log in logs:
            report = verify_log(log["text"].splitlines(), log["public_key"])
            self.assertTrue(report["ok"], report); self.assertGreater(report["count"], 0)

    def test_console_and_verifier_assets_have_the_right_types(self):
        expected = {"/console": "text/html", "/console.js": "text/javascript", "/console-lib.js": "text/javascript",
                    "/console.css": "text/css", "/verdock/verify.js": "text/javascript"}
        for path, kind in expected.items():
            status, headers, content = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertEqual(headers["Content-Type"], kind + "; charset=utf-8", path)
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"]); self.assertTrue(content)
        _, _, verifier = self.request("GET", "/verdock/verify.js")
        self.assertIn(b"export async function verifyLog", verifier)
        _, _, page = self.request("GET", "/console")
        self.assertNotIn(b"<script>", page); self.assertNotIn(b" style=", page); self.assertNotIn(b"http", page.replace(b"http-equiv", b""))
        for path in ("/vendor/ag-grid/ag-grid.min.css", "/web/../clearwake/console.py", "/verdock/verify.test.mjs", "/console/api/nothing"):
            self.assertEqual(self.request("GET", path)[0], 404, path)
        status, headers, _ = self.request("GET", "/")  # the refund workroom is gone: / goes to the console
        self.assertEqual((status, headers["Location"]), (302, "/console"))
        for gone in ("/payment.js", "/payment.css"):
            self.assertEqual(self.request("GET", gone)[0], 404, gone)

    def test_only_the_console_page_lets_in_ag_grid_styles_by_nonce_and_fixed_hashes(self):
        import re
        status, headers, page = self.request("GET", "/console")
        nonce = re.search(rb'name="cw-style-nonce" content="([A-Za-z0-9_-]{24})"', page).group(1).decode()
        csp = headers["Content-Security-Policy"]
        self.assertIn(f"style-src 'self' 'nonce-{nonce}' 'sha256-", csp)
        self.assertNotIn("unsafe-inline", csp); self.assertNotIn("unsafe-hashes", csp)
        again = re.search(rb'content="([A-Za-z0-9_-]{24})"', self.request("GET", "/console")[2]).group(1).decode()
        self.assertNotEqual(nonce, again)  # a fresh nonce for every page
        status, headers, grid = self.request("GET", "/vendor/ag-grid-community.min.js")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/javascript; charset=utf-8"))
        self.assertIn(b"styleNonce", grid); self.assertNotIn("nonce-", headers["Content-Security-Policy"])
        self.assertNotIn("nonce-", self.request("GET", "/console.js")[1]["Content-Security-Policy"])

    def test_fonts_are_served_from_this_origin_and_the_policy_allows_them(self):
        status, headers, font = self.request("GET", "/fonts/Figtree-var.woff2")
        self.assertEqual((status, headers["Content-Type"]), (200, "font/woff2"))
        self.assertEqual(font[:4], b"wOF2")
        self.assertIn("font-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("font-src 'self' data:", self.request("GET", "/console")[1]["Content-Security-Policy"])  # AG Grid's icon font
        self.assertNotIn("data:", headers["Content-Security-Policy"])
        for gone in ("/fonts/Inter-400.woff2", "/fonts/../console.html", "/fonts/"):
            self.assertEqual(self.request("GET", gone)[0], 404, gone)

    def test_reset_opens_a_new_folder_and_keeps_the_old_one(self):
        self.run_case("c")
        before = self.console.data
        status, value = self.post("/console/api/reset", {})
        self.assertEqual(status, 200)
        self.assertTrue(before.exists()); self.assertNotEqual(before, self.console.data)
        self.assertEqual(self.console.entries, [])


    def test_dispute_ledger_rows_carry_the_stage_the_proposal_and_paypal_raw_record(self):
        self.run_case("n")
        _, _, raw = self.request("GET", "/console/api/state")
        row = json.loads(raw)["disputes"][0]
        self.assertEqual((row["stage"], row["paypal_status"], row["proposed"], row["decided"]), ("INQUIRY", "RESOLVED", "settle_by_offer", "settle_by_offer"))
        self.assertEqual(row["record"]["dispute_id"], row["dispute"])  # PayPal shaped record, as read from the gateway
        self.assertEqual(row["record"]["dispute_life_cycle_stage"], "INQUIRY")
        self.assertIn("seller_response_due_date", row["record"])
        self.assertTrue(row["due"])


class HostedTests(unittest.TestCase):
    """CLEARWAKE_HOSTED=1: reset wipes the demo folder only, and each address has a rate limit."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.controller = RefundController(root / "http.sqlite3")
        self.console = Console(root / "console")
        self.outside = root / "keep-me.txt"; self.outside.write_text("not the console's data", encoding="utf-8")
        self.now = [1000.0]
        self.server = ClearwakeServer(("127.0.0.1", 0), self.controller, self.console, hosted=True, clock=lambda: self.now[0])
        self.server.limiter.limits.update({"read": 4, "write": 3})
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.controller.close(); self.folder.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        connection.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse(); content = response.read()
        result = (response.status, dict(response.getheaders()), content); connection.close(); return result

    def session(self, ip="203.0.113.7"):
        status, headers, raw = self.request("GET", "/console/api/session", headers={"X-Forwarded-For": ip})
        self.assertEqual(status, 200, raw)
        self.assertIn("; Secure", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";", 1)[0], json.loads(raw)["csrf"]

    def post(self, cookie, csrf, path, body, ip="203.0.113.7"):
        status, headers, raw = self.request("POST", path, body, {"Cookie": cookie, "X-Clearwake-CSRF": csrf, "X-Forwarded-For": ip})
        return status, headers, json.loads(raw)

    def test_reset_wipes_every_run_folder_of_the_demo_and_nothing_outside_it(self):
        cookie, csrf = self.session()
        first = self.console.data
        self.assertEqual(self.post(cookie, csrf, "/console/api/case", {"case": "c"})[0], 200)
        (self.console.root / "run-20260101-000000-abcd").mkdir()
        (self.console.root / "notes").mkdir()
        status, _, value = self.post(cookie, csrf, "/console/api/reset", {})
        self.assertEqual(status, 200, value)
        self.assertTrue(value["wiped"]); self.assertEqual(value["removed_folders"], 2)
        self.assertFalse(first.exists()); self.assertTrue(self.console.data.exists())
        self.assertTrue((self.console.root / "notes").exists()); self.assertTrue(self.outside.exists())
        self.assertEqual(self.console.entries, [])

    def test_a_client_over_its_allowance_gets_429_with_retry_after_then_recovers(self):
        cookie, csrf = self.session()  # read 1
        for _ in range(3):
            self.assertEqual(self.post(cookie, csrf, "/console/api/buy", {"request": "A stoneware mug"})[0], 200)
        status, headers, value = self.post(cookie, csrf, "/console/api/buy", {"request": "A stoneware mug"})
        self.assertEqual(status, 429); self.assertIn("Too many requests", value["error"]); self.assertGreaterEqual(int(headers["Retry-After"]), 1)
        self.assertEqual(len(self.console.purchases), 3)  # the refused request ran nothing
        self.assertEqual(self.post(cookie, csrf, "/console/api/buy", {"request": "A stoneware mug"}, ip="198.51.100.9")[0], 200)  # another address has its own allowance
        self.now[0] += 61
        self.assertEqual(self.post(cookie, csrf, "/console/api/buy", {"request": "A stoneware mug"})[0], 200)

    def test_reads_are_limited_too_and_limits_do_not_apply_outside_hosted_mode(self):
        for _ in range(4):
            self.assertEqual(self.request("GET", "/console/api/state", headers={"X-Forwarded-For": "192.0.2.1"})[0], 200)
        self.assertEqual(self.request("GET", "/console/api/state", headers={"X-Forwarded-For": "192.0.2.1"})[0], 429)
        local = ClearwakeServer(("127.0.0.1", 0), self.controller, self.console, hosted=False)
        try:
            self.assertIsNone(local.limiter)
        finally:
            local.server_close()

    def test_other_hosts_are_refused_unless_named(self):
        self.assertEqual(self.request("GET", "/console/api/state", headers={"Host": "demo.example.test"})[0], 403)  # no allowed host configured: loopback only
        self.server.allowed_hosts = {"demo.example.test"}
        self.assertEqual(self.request("GET", "/console/api/state", headers={"Host": "demo.example.test"})[0], 200)
        self.assertEqual(self.request("GET", "/console/api/state", headers={"Host": "evil.test"})[0], 403)
        self.assertEqual(self.request("GET", "/console/api/state", headers={"Host": "demo.example.test", "Origin": "https://evil.test"})[0], 403)
        self.assertEqual(self.request("GET", "/console/api/state", headers={"Host": "demo.example.test", "Origin": "https://demo.example.test"})[0], 200)


class ConsoleRestartTests(unittest.TestCase):
    def test_entries_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Console(Path(folder))
            first.run_case("d")
            again = Console(Path(folder))
            self.assertEqual([e["state"] for e in again.entries], ["awaiting approval"])
            entry = again.approve(again.entries[0]["approval_id"], "Sri (approver)")
            self.assertEqual(entry["state"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
