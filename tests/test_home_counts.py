"""The home page counts equal the real batch run file: 3 answered with proof, 4 settled, 2 waiting for the owner.

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


def counts_from(body):
    rows = body["cases"]
    n = lambda test: sum(1 for r in rows if test(r))
    return {"settled": n(lambda r: r.get("outcome") == "settled_inquiry_no_fee"),
            "answered with proof": n(lambda r: r.get("outcome") == "pending" and r.get("merchant_state") == "VERIFIED"),
            "waiting for the owner": n(lambda r: r.get("outcome") == "escalated_to_merchant_owner"),
            "refused": n(lambda r: r.get("outcome") == "handled_by_mandate")}


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
        self.assertEqual((want["answered with proof"], want["settled"], want["waiting for the owner"], want["refused"]), (3, 4, 2, 1))

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
        self.assertEqual(shown, {"answered with proof": want["answered with proof"], "settled with the refund": want["settled"],
                                 "waiting for the owner": want["waiting for the owner"]})


if __name__ == "__main__":
    unittest.main()
