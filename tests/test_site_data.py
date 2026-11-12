"""The public site's ledger data and its copies of shared files."""
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
spec = importlib.util.spec_from_file_location("build_site_data", ROOT / "scripts" / "build_site_data.py")
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


RUNS = (ROOT / "data" / "runs").is_dir() and any((ROOT / "data" / "runs").glob("baseline-*.json"))
needs_runs = unittest.skipUnless(RUNS, "the run files under data/runs are not committed: they exist on the machine that made the runs")


class SiteDataTests(unittest.TestCase):
    @needs_runs
    def test_ledger_rows_are_the_recorded_sandbox_cases_with_proposals_read_from_receipts(self):
        rows = builder.build()["rows"]
        self.assertEqual(sorted({r["case"] for r in rows}), ["c", "d", "e", "i", "m1", "m2", "m3", "n", "o"])
        self.assertEqual(len({r["dispute"] for r in rows}), len(rows))
        by = {r["case"]: r for r in rows}
        self.assertEqual((by["n"]["proposed"], by["n"]["stage"], by["n"]["paypal_status"]), ("settle_by_offer", "INQUIRY", "RESOLVED"))
        self.assertEqual((by["o"]["proposed"], by["o"]["model"]), ("fight_with_evidence", "scripted, not AI"))
        self.assertEqual(by["i"]["stage"], "CHARGEBACK")
        self.assertEqual(by["c"]["proposed"], "")  # no published receipt holds a proposal for c: the column shows a dash
        self.assertTrue(all(r["mode"] == "real sandbox" and isinstance(r["record"], dict) and r["record"] for r in rows))
        written = json.loads((SITE / "data" / "ledger.json").read_text(encoding="utf-8"))["rows"]
        self.assertEqual(written, rows)  # run scripts/build_site_data.py after a change
        self.assertIn("ledger.json", json.loads((SITE / "data" / "manifest.json").read_text(encoding="utf-8"))["files"])

    @needs_runs
    def test_totals_come_from_the_run_files_and_a_local_batch_stays_out_of_the_public_set(self):
        t = json.loads((SITE / "data" / "totals.json").read_text(encoding="utf-8"))
        self.assertTrue(t["public"]); self.assertLessEqual(len(t["public"]), 6)
        for n in t["public"] + t["local"]:
            self.assertTrue(n["value"] and n["label"] and n["source"])
        self.assertFalse([n for n in t["public"] if "batch-local" in n["source"]])
        self.assertEqual(t, builder.totals(builder.build()["rows"]))  # run scripts/build_site_data.py after a new run file

    @needs_runs
    def test_cases_json_has_one_card_per_case_in_the_five_result_words(self):
        d = json.loads((SITE / "data" / "cases.json").read_text(encoding="utf-8"))
        self.assertEqual([c["n"] for c in d["cases"]], list(range(1, 11)))
        self.assertEqual(set(c["result"] for c in d["cases"]), set(builder.VOCAB) - {"waiting for owner"})  # cases 4 and 9 were decided by voice on 12 Nov: none waits now
        self.assertEqual(d["verified_means"], builder.VERIFIED_MEANS)
        self.assertEqual(d["waiting"], [])
        self.assertEqual(d["cost"]["merchant_calls"] + d["cost"]["buyer_calls"], 24)
        self.assertEqual(d["cost"]["cost_per_call_usd"], "0.00")
        self.assertEqual(d, builder.cases_data())  # run scripts/build_site_data.py after a new run file

    def test_a_local_batch_is_never_published_and_a_sandbox_batch_becomes_rows(self):
        case = {"n": 1, "reason": "item_not_received", "ask": "9.00", "paypal_stage": "INQUIRY", "paypal_status": "RESOLVED", "outcome": "settled_inquiry_no_fee",
                "merchant_decision": "settle_by_offer", "merchant_state": "VERIFIED", "refund_confirmed": "3.00", "dispute_id": "PP-R-ABC-1", "steps": ["buyer: accept"]}
        batch = {"kind": "buyer-seller batch", "mode": "sandbox", "finished": "2026-11-11T10:00:00+00:00", "cases": [case, dict(case, n=2, outcome="evidence_sent", refund_confirmed="0.00", dispute_id="PP-R-ABC-2")]}
        self.assertIsNone(builder.from_batch(dict(batch, mode="local"), "batch-x"))
        rows = builder.from_batch(batch, "batch-x")["rows"]
        self.assertEqual([(r["result"], r["settled_before_escalation"], r["refunded"]) for r in rows], [("settled", True, True), ("evidence", False, False)])
        self.assertEqual(rows[0]["stage"], "INQUIRY"); self.assertIn("USD 3.00", rows[0]["outcome"])

    def test_the_site_copy_of_the_shared_ledger_helpers_matches_the_console_copy(self):
        self.assertEqual((SITE / "ledger-lib.js").read_bytes(), (ROOT / "web" / "console-lib.js").read_bytes())

    def test_vercel_policy_stays_strict_except_the_exact_style_hashes_on_the_control_room(self):
        rules = {r["source"]: {h["key"]: h["value"] for h in r["headers"]} for r in json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))["headers"]}
        strict, room = rules["/((?!control-room).*)"]["Content-Security-Policy"], rules["/control-room"]["Content-Security-Policy"]
        self.assertNotIn("sha256", strict); self.assertNotIn("data:", strict)
        for csp in (strict, room):
            self.assertNotIn("unsafe", csp); self.assertNotIn("nonce", csp); self.assertIn("default-src 'none'", csp); self.assertIn("script-src 'self';", csp)
        hashes = re.findall(r"'sha256-[A-Za-z0-9+/=]{44}'", room)
        self.assertGreaterEqual(len(hashes), 14); self.assertEqual(len(hashes), len(set(hashes)))
        self.assertIn("style-src 'self' 'sha256-", room)
        self.assertIn("font-src 'self' data:", room)  # AG Grid's icon font is a data: URI
        self.assertNotIn("data:", room.split("font-src")[0])  # no data: for scripts, styles or images

    def test_ag_grid_is_the_licensed_unchanged_vendor_build(self):
        self.assertEqual((SITE / "vendor" / "ag-grid-community-35.3.1.min.js").read_bytes(), (ROOT / "web" / "vendor" / "ag-grid-community-35.3.1.min.js").read_bytes())
        self.assertIn("MIT", (SITE / "vendor" / "ag-grid-community-LICENSE.txt").read_text(encoding="utf-8"))

    def test_no_page_still_carries_the_old_repeated_badges_or_the_giant_one(self):
        for page in ("index.html", "control-room.html", "developers.html"):
            html = (SITE / page).read_text(encoding="utf-8")
            self.assertNotRegex(html, r'class="tag (real|local)"', page)
            self.assertNotIn("local</span>", html, page)
        home = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("bignum", home); self.assertNotIn("Local, not PayPal", home)
        self.assertEqual(len(re.findall(r"Real PayPal sandbox, test money", home)), 1)


if __name__ == "__main__":
    unittest.main()
