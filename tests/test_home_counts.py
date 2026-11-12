"""The home page and Control Room counts equal the run files: the batch file of 11 Nov plus the voice decisions file of 12 Nov.

10 claims: 5 resolved inside PayPal (4 at INQUIRY, case 4 at CHARGEBACK), 4 answered with proof, 0 waiting for the owner, 1 refused before filing.

The counts are read in a real browser from the page the visitor sees, and compared with a count made straight from data/runs/batch-sandbox-*.json.
"""
import functools
import http.server
import json
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "data" / "runs"


def newest_clean_batch():
    for path in sorted(RUNS.glob("batch-sandbox-*.json"), reverse=True):
        body = json.loads(path.read_text(encoding="utf-8"))
        if not any(c.get("outcome") == "error" for c in body.get("cases", [])):
            return path, body
    return None, None


def voice_cases():
    files = sorted(RUNS.glob("voice-decisions-*.json"))
    return {int(c["case"]): c for c in json.loads(files[-1].read_text(encoding="utf-8"))["cases"]} if files else {}


def counts_from(body):
    """Counted straight from the run files, with PayPal's record in the voice file deciding cases 4 and 9."""
    rows, voice = body["cases"], voice_cases()
    n = lambda test: sum(1 for r in rows if test(r))
    chargeback = 1 if voice.get(4, {}).get("paypal", {}).get("status") == "RESOLVED" else 0
    proof_now = 1 if voice.get(9, {}).get("paypal", {}).get("seller_proof_on_record") else 0
    owner = n(lambda r: r.get("outcome") == "escalated_to_merchant_owner") - chargeback - proof_now
    settled = n(lambda r: r.get("outcome") == "settled_inquiry_no_fee")
    return {"settled": settled, "resolved at chargeback": chargeback, "resolved": settled + chargeback,
            "answered with proof": n(lambda r: r.get("outcome") == "pending" and r.get("merchant_state") == "VERIFIED") + proof_now,
            "waiting for the owner": owner, "refused": n(lambda r: r.get("outcome") == "handled_by_mandate")}


@unittest.skipUnless(newest_clean_batch()[0], "needs data/runs (git ignored)")
class HomeCountsTests(unittest.TestCase):
    def test_counts_file_equals_the_batch_run_file(self):
        _, body = newest_clean_batch()
        written = json.loads((ROOT / "site" / "data" / "counts.json").read_text(encoding="utf-8"))
        want = counts_from(body)
        self.assertEqual(written["cases"], len(body["cases"]))
        self.assertEqual(written["settled"], want["settled"])
        self.assertEqual(written["answered_with_proof"], want["answered with proof"])
        self.assertEqual(written["waiting_for_owner"], want["waiting for the owner"])
        self.assertEqual(written["refused"], want["refused"])
        self.assertEqual(written["resolved_at_chargeback"], want["resolved at chargeback"])
        self.assertEqual(written["resolved"], want["resolved"])
        self.assertEqual((want["resolved"], want["settled"], want["resolved at chargeback"], want["answered with proof"], want["waiting for the owner"], want["refused"]), (5, 4, 1, 4, 0, 1))
        self.assertEqual(want["resolved"] + want["answered with proof"] + want["waiting for the owner"] + want["refused"], len(body["cases"]))

    def test_control_room_cards_and_tally_equal_the_run_files(self):
        _, body = newest_clean_batch()
        want = counts_from(body)
        cases = json.loads((ROOT / "site" / "data" / "cases.json").read_text(encoding="utf-8"))
        self.assertEqual(cases["counts"], {"settled": want["settled"], "resolved at chargeback": want["resolved at chargeback"], "answered with proof": want["answered with proof"],
                                           "waiting for owner": want["waiting for the owner"], "refused": want["refused"]})
        by = {c["n"]: c for c in cases["cases"]}
        voice = voice_cases()
        self.assertEqual(by[4]["paypal_status"], voice[4]["paypal"]["status"])
        self.assertEqual(by[4]["refund"]["id"], voice[4]["paypal"]["refund_id"])
        self.assertEqual(by[9]["paypal_status"], voice[9]["paypal"]["status"])
        self.assertEqual(by[7]["result"], "refused")
        self.assertEqual(by[7]["dispute"], "")

    def test_the_numbers_a_visitor_sees_on_the_home_page_equal_the_batch_run_file(self):
        from playwright.sync_api import sync_playwright
        _, body = newest_clean_batch()
        want = counts_from(body)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "site"))
        handler.log_message = lambda *a, **k: None
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html", wait_until="networkidle")
                page.wait_for_selector("#mp-nums:not([hidden])", timeout=15000)
                shown = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#mp-nums > div')].map(d => [d.querySelector('dt').textContent, Number(d.querySelector('dd').textContent)]))""")
                browser.close()
        finally:
            server.shutdown()
        self.assertEqual(shown, {"answered with proof": want["answered with proof"], "resolved inside PayPal": want["resolved"],
                                 "waiting for the owner": want["waiting for the owner"]})

    def test_the_control_room_tally_a_visitor_sees_equals_the_run_files(self):
        from playwright.sync_api import sync_playwright
        _, body = newest_clean_batch()
        want = counts_from(body)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "site"))
        handler.log_message = lambda *a, **k: None
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_address[1]}/control-room.html", wait_until="networkidle")
                page.wait_for_selector("#case-cards .case", timeout=15000)
                shown = page.evaluate("""() => Object.fromEntries(['t-settled', 't-chargeback', 't-review', 't-owner', 't-mandate'].map(i => [i, Number(document.getElementById(i).textContent)]))""")
                browser.close()
        finally:
            server.shutdown()
        self.assertEqual(shown, {"t-settled": want["settled"], "t-chargeback": want["resolved at chargeback"], "t-review": want["answered with proof"],
                                 "t-owner": want["waiting for the owner"], "t-mandate": want["refused"]})


if __name__ == "__main__":
    unittest.main()
