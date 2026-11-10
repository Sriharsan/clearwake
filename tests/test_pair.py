"""Two signed logs, one story: the buyer log and the merchant log verified together."""
import json
from pathlib import Path
import tempfile
import unittest

from clearwake.pair import verify_pair, verify_report
from verdock_core.receipts import ReceiptLog, create_seed, load_seed, line_hash


def make_logs(folder, dispute="PP-R-1", merchant_dispute=None, outcome="settled_inquiry_no_fee", merchant_outcome=None, with_merchant_close=True):
    folder = Path(folder)
    logs = {}
    for name in ("buyer", "merchant"):
        create_seed(str(folder / f"{name}.seed"))
        logs[name] = ReceiptLog(str(folder / f"{name}.ndjson"), load_seed(str(folder / f"{name}.seed")))
    mandate = logs["buyer"].append("mandate:O1", "clearwake.buyer.mandate", {"order_id": "O1"}, True)
    digest = line_hash(mandate)
    logs["buyer"].append(f"{dispute}:open", "clearwake.buyer.open_dispute", {"dispute_id": dispute, "mandate_receipt": digest}, True)
    logs["buyer"].append(f"{dispute}:closed", "clearwake.buyer.case_closed", {"dispute_id": dispute, "outcome": outcome, "order_id": "O1", "mandate_receipt": digest}, True)
    if with_merchant_close:
        logs["merchant"].append("m:closed", "clearwake.batch.case_closed", {"dispute": merchant_dispute or dispute, "order": "O1", "outcome": merchant_outcome or outcome,
                                                                          "paypal_status": "RESOLVED"}, True)
    return logs


class PairTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.root = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def check(self, logs, **kw):
        return verify_pair(logs["buyer"].path, logs["buyer"].public_key, logs["merchant"].path, logs["merchant"].public_key, **kw)

    def test_both_logs_naming_the_same_dispute_pass(self):
        result = self.check(make_logs(self.root))
        self.assertTrue(result["ok"], result["failures"]); self.assertIn("PP-R-1", result["disputes"])

    def test_a_different_dispute_id_fails_with_the_exact_reason(self):
        result = self.check(make_logs(self.root, merchant_dispute="PP-R-2"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("PP-R-1" in f and "merchant log has no case_closed" in f for f in result["failures"]))
        self.assertTrue(any("PP-R-2" in f and "buyer log has no case_closed" in f for f in result["failures"]))

    def test_different_outcomes_fail(self):
        result = self.check(make_logs(self.root, merchant_outcome="escalated_to_merchant_owner"))
        self.assertTrue(any("different outcomes" in f for f in result["failures"]))

    def test_a_missing_merchant_receipt_fails(self):
        result = self.check(make_logs(self.root, with_merchant_close=False))
        self.assertFalse(result["ok"])

    def test_an_edited_receipt_breaks_that_log(self):
        logs = make_logs(self.root)
        path = Path(logs["merchant"].path)
        path.write_text(path.read_text(encoding="utf-8").replace("RESOLVED", "RESOLVEd"), encoding="utf-8")
        result = self.check(logs)
        self.assertFalse(result["ok"]); self.assertTrue(any(f.startswith("The merchant log does not verify") for f in result["failures"]))

    def test_a_missing_mandate_link_fails(self):
        logs = make_logs(self.root)
        logs["buyer"].append("x", "clearwake.buyer.read_thread", {"dispute_id": "PP-R-1", "mandate_receipt": "ab" * 32}, True)
        result = self.check(logs)
        self.assertTrue(any("mandate receipt that is not in the buyer log" in f for f in result["failures"]))

    def test_a_case_the_mandate_refused_has_no_dispute_and_still_passes(self):
        logs = make_logs(self.root)
        logs["buyer"].append("O7:closed", "clearwake.buyer.case_closed", {"dispute_id": "", "outcome": "handled_by_mandate", "order_id": "O7"}, True)
        result = self.check(logs)
        self.assertTrue(result["ok"], result["failures"]); self.assertEqual(result["no_dispute_cases"], 1)

    def test_the_script_prints_pass_and_the_exact_failure(self):
        import subprocess, sys
        logs = make_logs(self.root)
        script = Path(__file__).resolve().parent.parent / "scripts" / "verify_pair.py"
        args = [sys.executable, str(script), "--buyer", logs["buyer"].path, "--buyer-key", logs["buyer"].public_key,
                "--merchant", logs["merchant"].path, "--merchant-key", logs["merchant"].public_key]
        ok = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual((ok.returncode, ok.stdout.startswith("PASS")), (0, True))
        bad = subprocess.run(args + ["--dispute", "PP-R-9"], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1); self.assertIn("FAIL: Dispute PP-R-9", bad.stdout)


if __name__ == "__main__":
    unittest.main()
