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
        self.assertEqual(value["label"], "rehearsal, invented records")
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
        self.assertEqual(self.request("GET", "/")[0], 200)  # the workroom still answers

    def test_reset_opens_a_new_folder_and_keeps_the_old_one(self):
        self.run_case("c")
        before = self.console.data
        status, value = self.post("/console/api/reset", {})
        self.assertEqual(status, 200)
        self.assertTrue(before.exists()); self.assertNotEqual(before, self.console.data)
        self.assertEqual(self.console.entries, [])


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
