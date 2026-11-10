"""The agent to agent batch: rehearsal end to end, the outcome classes, and the manual buyer mode against a fake sandbox."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clearwake import batch
from clearwake.buyer_browser import NeedsHuman
from clearwake.buyer_manual import thread_from_record
from clearwake.paypal import RehearsalGateway


def read_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


class RehearsalBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.report = batch.run_rehearsal(work=cls.work.name)
        cls.rows = {r["n"]: r for r in cls.report["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_all_ten_run_end_to_end_with_no_errors(self):
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(self.report["summary"][batch.ERROR], 0)
        self.assertEqual(self.report["mode"], "rehearsal")

    def test_the_outcome_mix(self):
        s = self.report["summary"]
        self.assertEqual((s[batch.SETTLED], s[batch.EVIDENCE], s[batch.BUYER_OWNER], s[batch.MERCHANT_OWNER]), (5, 3, 1, 1))
        self.assertEqual({n for n, r in self.rows.items() if r["outcome"] == batch.SETTLED}, {3, 4, 7, 8, 10})

    def test_settled_means_paypals_record_says_resolved_at_inquiry_with_the_refund(self):
        for n in (3, 4, 7, 8, 10):
            r = self.rows[n]
            self.assertEqual((r["paypal_status"], r["paypal_stage"], r["settlement"]), ("RESOLVED", "INQUIRY", "VERIFIED"))
            self.assertEqual(r["refund_confirmed"], r["ask"])
        self.assertEqual(self.report["summary"]["refunds_confirmed_total"], "12.00")

    def test_unsettled_cases_never_claim_a_refund(self):
        for n in (1, 2, 5, 6, 9):
            self.assertEqual(self.rows[n]["refund_confirmed"], "0.00")
            self.assertNotEqual(self.rows[n]["paypal_status"], "RESOLVED")

    def test_dispatch_proof_cases_use_the_recorded_sam_count_and_the_merchant_fights(self):
        for n in (5, 6):
            self.assertIn("recorded", self.rows[n]["dispatch_counter"])
            self.assertEqual(self.rows[n]["merchant_decision"], "fight_with_evidence")
            self.assertEqual(self.rows[n]["buyer_end"], "escalated_owner")

    def test_the_rule_drives_the_buyer(self):
        self.assertEqual(self.rows[9]["counters"], 1)   # 55% offer: one counter, then the owner
        self.assertEqual(self.rows[3]["counters"], 0)   # 100% offer: accepted at once

    def test_both_logs_verify_and_every_buyer_step_carries_a_mandate_receipt_hash(self):
        self.assertTrue(self.report["buyer_log"]["verifies"])
        self.assertTrue(self.report["merchant_log"]["verifies"])
        lines = read_lines(Path(self.work.name) / "buyer" / "buyer-receipts.ndjson")
        self.assertEqual(sum(1 for l in lines if l["action_id"] == "clearwake.buyer.mandate"), 10)
        steps = [l for l in lines if l["action_id"] != "clearwake.buyer.mandate"]
        self.assertGreater(len(steps), 30)
        digests = {l["params"]["mandate_receipt"] for l in steps}
        self.assertNotIn("0" * 64, digests)
        self.assertEqual(len(digests), 10)   # one mandate receipt per order

    def test_scripted_means_zero_model_calls_and_says_so(self):
        self.assertEqual(self.report["summary"]["model_calls"], 0)
        self.assertGreater(self.report["summary"]["scripted_decisions"], 0)
        self.assertIn("scripted", self.report["merchant_agent"])

    def test_the_table_has_a_row_per_case(self):
        self.assertEqual(len(batch.table(self.report["cases"]).splitlines()), 12)


class HelperTests(unittest.TestCase):
    def test_order_payload_checks_the_total(self):
        product = {"id": "notebook-a5", "name": "A5 dot grid notebook", "price_minor": 900}
        payload = batch.order_payload(product, 3, 2700, "http://127.0.0.1:8842/x")
        self.assertEqual(payload["purchase_units"][0]["amount"]["value"], "27.00")
        with self.assertRaises(ValueError):
            batch.order_payload(product, 3, 2600, "http://127.0.0.1:8842/x")

    def test_refund_seen_reads_the_record_not_the_agents(self):
        self.assertEqual(batch.refund_seen({"dispute_outcome": {"amount_refunded": {"value": "3.00"}}}), 300)
        self.assertEqual(batch.refund_seen({"fund_movements": [{"party": "BUYER", "reason": "DISPUTE_SETTLEMENT", "amount": {"value": "2.50"}}]}), 250)
        self.assertEqual(batch.refund_seen({"status": "RESOLVED"}), 0)

    def test_model_calls_count_only_non_scripted_models(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            path = Path(d) / "r.ndjson"
            path.write_text("\n".join(json.dumps({"params": {"dispute": "D1", "model": m}}) for m in ("scripted", "qwen3", "qwen3")) + "\n", encoding="utf-8")
            self.assertEqual(batch.model_calls(path, "D1"), (2, 1))
            self.assertEqual(batch.model_calls(path, "D2"), (0, 0))

    def test_sandbox_without_a_saved_login_stops_with_the_login_command(self):
        with mock.patch.object(batch, "has_login", return_value=False):
            with self.assertRaises(NeedsHuman) as caught:
                batch.run_sandbox(gateway=object())
        self.assertIn("buyer_dispute.py --login", caught.exception.steps[0])

    def test_thread_from_a_paypal_record(self):
        record = {"status": "WAITING_FOR_BUYER_RESPONSE", "dispute_life_cycle_stage": "INQUIRY", "dispute_amount": {"value": "9.00"},
                  "messages": [{"posted_by": "BUYER", "content": "x"}, {"posted_by": "SELLER", "content": "y"}],
                  "offer": {"seller_offered_amount": {"currency_code": "USD", "value": "5.00"}}}
        t = thread_from_record("D", record)
        self.assertEqual((t.offer_minor, t.requested_minor, t.can_accept, t.resolved), (500, 900, True, False))
        self.assertEqual(t.facts()["offer_minor"], 500)


class FakeSandbox:
    """Stands in for the PayPal sandbox in the manual mode tests: the rehearsal provider's disputes plus orders. Tests only."""
    mode = "paypal-sandbox"

    def __init__(self, path):
        self.inner, self.orders, self.n = RehearsalGateway(path), {}, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _access_token(self):
        return "t"

    def _request(self, path, payload, request_id):
        self.n += 1
        oid = f"FAKEORDER{self.n}"
        self.orders[oid] = {"status": "CREATED"}
        return self.order(oid)

    def order(self, oid):
        status = self.orders[oid]["status"]
        out = {"id": oid, "status": status, "links": [{"rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={oid}"}]}
        if status == "COMPLETED":
            out["purchase_units"] = [{"payments": {"captures": [{"id": "CAP" + oid, "status": "COMPLETED"}]}}]
        return out

    def capture_order(self, oid, request_id):
        self.orders[oid]["status"] = "COMPLETED"
        return self.order(oid)

    def add_tracking(self, *args):
        return {}

    def hands(self, line, printed=None):
        """Plays the lead's browser: does what the printed action says."""
        a = json.loads(line)
        if printed is not None:
            printed.append(a)
        if a["action"] == "approve_order":
            self.orders[a["order_id"]]["status"] = "APPROVED"
        elif a["action"] == "open_dispute":
            self.inner.open_dispute("CAP" + a["order_id"], batch.API_REASON[a["reason"]], a["amount"], "2030-01-01T00:00:00Z", a["message"], stage="INQUIRY")
        elif a["action"] == "accept_offer":
            self.inner.buyer_accepts_offer(a["dispute_id"])
        elif a["action"] == "counter":
            body = self.inner.dispute(a["dispute_id"])
            self.inner._update_dispute(a["dispute_id"], status="WAITING_FOR_SELLER_RESPONSE", buyer_countered=True,
                                       messages=body["messages"] + [{"posted_by": "BUYER", "content": a["message"]}])


class ManualBuyerTests(unittest.TestCase):
    def test_manual_mode_prints_actions_polls_paypal_and_receipts_each_effect(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            fake, printed = FakeSandbox(Path(d) / "p.sqlite3"), []
            cases = tuple(c for c in batch.CASES if c.n in (3, 9))
            report = batch.run_sandbox(cases=cases, manual=True, work=Path(d) / "manual", timeout_s=2, out=lambda l: fake.hands(l, printed), gateway=fake, poll_s=0)
            rows = {r["n"]: r for r in report["cases"]}
            self.assertEqual(rows[3]["outcome"], batch.SETTLED)
            self.assertEqual([a["action"] for a in printed[:3]], ["approve_order", "open_dispute", "accept_offer"])
            opened = printed[1]
            self.assertEqual((opened["reason"], opened["message"], opened["dispute_rule"]["accept_min_percent"]), ("item_not_received", "My notebook never arrived.", 80))
            self.assertIn("lead's browser", opened["performed_through"])
            self.assertEqual(printed[2]["decision"]["action"], "accept")
            lines = read_lines(Path(d) / "manual" / "buyer" / "buyer-receipts.ndjson")
            names = [l["action_id"] for l in lines]
            for needed in ("clearwake.buyer.approve_order.requested", "clearwake.buyer.approve_order", "clearwake.buyer.open_dispute", "clearwake.buyer.accept_offer"):
                self.assertIn(needed, names)
            self.assertTrue(all("lead's browser" in l["params"]["source"] for l in lines if l["action_id"] != "clearwake.buyer.mandate"))
            self.assertTrue(report["buyer_log"]["verifies"])
            self.assertEqual(rows[9]["outcome"], batch.MERCHANT_OWNER)   # the merchant owner's approval stays manual against the sandbox

    def test_a_missing_effect_times_out_receipted_and_stops_for_a_person_then_resume_continues(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            fake, work = FakeSandbox(Path(d) / "p.sqlite3"), Path(d) / "manual"
            cases = tuple(c for c in batch.CASES if c.n == 3)
            report = batch.run_sandbox(cases=cases, manual=True, work=work, timeout_s=0, out=lambda line: None, gateway=fake, poll_s=0)
            row = report["cases"][0]
            self.assertEqual(row["outcome"], batch.ERROR)
            self.assertIn("approve_order", row["detail"])
            self.assertTrue(row["manual_steps"])
            names = [l["action_id"] for l in read_lines(work / "buyer" / "buyer-receipts.ndjson")]
            self.assertIn("clearwake.buyer.approve_order.timeout", names)
            fake.orders["FAKEORDER1"]["status"] = "APPROVED"   # the person approved meanwhile
            again = batch.run_sandbox(cases=cases, manual=True, resume=True, work=work, timeout_s=2, out=fake.hands, gateway=fake, poll_s=0)
            self.assertEqual(again["cases"][0]["outcome"], batch.SETTLED)
            self.assertEqual(len(fake.orders), 1)   # resumed on the same order, no second purchase

    def test_a_counter_is_printed_then_confirmed_from_the_dispute_record(self):
        from clearwake.batch import RULE
        from clearwake.buyer_browser import Recorder, open_buyer_log
        from clearwake.buyer_manual import ManualBuyer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            fake, printed = FakeSandbox(Path(d) / "p.sqlite3"), []
            dispute = fake.inner.open_dispute("CAP-X", batch.NOT_RECEIVED, "9.00", "2030-01-01T00:00:00Z", "Never arrived.", stage="INQUIRY")["dispute_id"]
            rec = Recorder(open_buyer_log(Path(d) / "b"), "a" * 64, "paypal-sandbox via the lead's browser", Path(d) / "s")
            door = ManualBuyer(fake, rec, RULE, out=lambda l: fake.hands(l, printed), timeout_s=2, poll_s=0)
            self.assertTrue(door.counter(dispute, "Could you raise the refund to USD 7.20?"))
            self.assertEqual((printed[0]["action"], printed[0]["message"]), ("counter", "Could you raise the refund to USD 7.20?"))
            self.assertEqual(door.read_thread(dispute).messages[-1], ("buyer", "Could you raise the refund to USD 7.20?"))


if __name__ == "__main__":
    unittest.main()
