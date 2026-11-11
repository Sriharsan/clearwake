"""The agent to agent batch: local end to end, the outcome classes, and the manual buyer mode against a stand-in sandbox."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clearwake import batch
from clearwake.buyer_browser import NeedsHuman
from clearwake.buyer_manual import thread_from_record
from clearwake.paypal import LocalGateway


def read_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


class LocalBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.report = batch.run_local(cases=batch.CASES_MIX_L, work=cls.work.name, scope_item_not_received=False)   # the earlier mix has other reasons
        cls.rows = {r["n"]: r for r in cls.report["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_all_ten_run_end_to_end_with_no_errors(self):
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(self.report["summary"][batch.ERROR], 0)
        self.assertEqual(self.report["mode"], "local")

    def test_the_outcome_mix(self):
        s = self.report["summary"]
        self.assertEqual((s[batch.SETTLED], s[batch.EVIDENCE], s[batch.BUYER_OWNER], s[batch.MERCHANT_OWNER]), (6, 3, 0, 1))   # under the batch merchant rule
        self.assertEqual({n for n, r in self.rows.items() if r["outcome"] == batch.SETTLED}, {3, 4, 5, 6, 7, 8})
        self.assertEqual({n for n, r in self.rows.items() if r["outcome"] == batch.EVIDENCE}, {1, 9, 10})
        reasons = sorted(r["reason"] for r in self.rows.values())
        self.assertEqual((reasons.count("item_not_received"), reasons.count("not_as_described"), reasons.count("unauthorised")), (4, 4, 2))

    def test_settled_means_paypals_record_says_resolved_at_inquiry_with_the_refund(self):
        for n in (3, 4, 5, 6, 7, 8):
            r = self.rows[n]
            self.assertEqual((r["paypal_status"], r["paypal_stage"], r["settlement"]), ("RESOLVED", "INQUIRY", "VERIFIED"))
            self.assertEqual(r["refund_confirmed"], r["ask"])
        self.assertEqual(self.report["summary"]["refunds_confirmed_total"], "21.00")

    def test_unsettled_cases_never_claim_a_refund(self):
        for n in (1, 2, 9, 10):
            self.assertEqual(self.rows[n]["refund_confirmed"], "0.00")
            self.assertNotEqual(self.rows[n]["paypal_status"], "RESOLVED")

    def test_unauthorised_cases_are_answered_with_the_signed_mandate_and_the_buyer_hands_them_to_its_owner(self):
        for n in (9, 10):
            self.assertEqual(self.rows[n]["merchant_decision"], "fight_with_evidence")
            self.assertEqual(self.rows[n]["buyer_end"], "escalated_owner")
            self.assertEqual(self.rows[n]["outcome"], batch.EVIDENCE)

    def test_the_rule_drives_the_buyer(self):
        self.assertEqual(self.rows[7]["counters"], 0)   # the merchant's batch rule offers the full USD 9.00 once the owner approves
        self.assertEqual(self.rows[3]["counters"], 0)   # 100% offer: accepted at once

    def test_both_logs_verify_and_every_buyer_step_carries_a_mandate_receipt_hash(self):
        self.assertTrue(self.report["buyer_log"]["verifies"])
        self.assertTrue(self.report["merchant_log"]["verifies"])
        lines = read_lines(Path(self.work.name) / "buyer" / "buyer-receipts.ndjson")
        self.assertEqual(sum(1 for l in lines if l["action_id"] == "clearwake.buyer.mandate"), 10)
        steps = [l for l in lines if l["action_id"] not in ("clearwake.buyer.mandate", "clearwake.buyer.price_reference")]
        self.assertGreater(len(steps), 30)
        digests = {l["params"]["mandate_receipt"] for l in steps}
        self.assertNotIn("0" * 64, digests)
        self.assertEqual(len(digests), 10)   # one mandate receipt per order

    def test_scripted_means_zero_model_calls_and_says_so(self):
        self.assertEqual(self.report["summary"]["model_calls"] + self.report["summary"]["buyer_model_calls"], 0)
        self.assertGreater(self.report["summary"]["scripted_decisions"], 0)
        self.assertIn("scripted", self.report["merchant_agent"])

    def test_the_table_has_a_row_per_case(self):
        self.assertEqual(len(batch.table(self.report["cases"]).splitlines()), 12)


class TenItemNotReceivedTests(unittest.TestCase):
    """The ten agent bought item not received cases, run on the local provider."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.report = batch.run_local(work=cls.work.name)
        cls.rows = {r["n"]: r for r in cls.report["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_every_case_is_item_not_received_and_nothing_errors(self):
        self.assertEqual(len(self.rows), 10)
        self.assertEqual({c.reason for c in batch.CASES}, {"item_not_received"})
        self.assertEqual(self.report["summary"][batch.ERROR], 0)

    def test_the_result_line_comes_from_the_rows(self):
        line = self.report["summary"]["result"]
        self.assertEqual((line["settled"], line["handed_to_person"], line["fees"], line["double_refunds"]), (5, 5, 0, 0))
        self.assertTrue(line["text"].startswith("5 of 10 settled by agents inside the limits, 5 correctly handed to a person, 0 fees, 0 double refunds, median "))
        self.assertEqual(batch.result_line(self.report["cases"]), line)

    def test_delivered_and_in_transit_are_answered_with_the_tracking_and_handed_on(self):
        for n in (1, 2):
            self.assertEqual((self.rows[n]["merchant_decision"], self.rows[n]["outcome"], self.rows[n]["refund_confirmed"]), ("fight_with_evidence", batch.EVIDENCE, "0.00"))

    def test_not_shipped_lost_and_second_not_shipped_settle_with_an_offer_sent_alone(self):
        for n in (3, 4, 10):
            r = self.rows[n]
            self.assertEqual((r["outcome"], r["paypal_status"], r["paypal_stage"], r["refund_confirmed"], r["offers_sent"]), (batch.SETTLED, "RESOLVED", "INQUIRY", "5.00", 1))

    def test_tracking_is_added_before_the_dispute_exists_and_receipted_by_the_merchant(self):
        lines = read_lines(Path(self.work.name) / "merchant" / "merchant-receipts.ndjson")
        added = {l["params"]["order"]: l for l in lines if l["action_id"] == "clearwake.merchant.tracking_added"}
        self.assertEqual({self.rows[n]["order_id"] for n in (1, 2, 4, 5)}, set(added))
        for n in (1, 2, 4, 5):
            tracking = added[self.rows[n]["order_id"]]
            opened = [l for l in lines if l["params"].get("dispute") == self.rows[n]["dispute_id"]][0]
            self.assertTrue(tracking["params"]["added_before_dispute"])
            self.assertLess(tracking["ts_ms"], opened["ts_ms"])
        self.assertEqual(added[self.rows[4]["order_id"]]["params"]["carrier_status"], "LOST")
        self.assertEqual(added[self.rows[1]["order_id"]]["params"]["carrier_status"], "DELIVERED")

    def test_two_of_three_uses_the_recorded_sam_count_and_the_merchant_answers_with_it(self):
        r = self.rows[5]
        self.assertIn("recorded", r["dispatch_counter"])
        self.assertEqual((r["merchant_decision"], r["outcome"]), ("fight_with_evidence", batch.EVIDENCE))

    def test_an_instruction_in_the_buyers_message_is_ignored_and_receipted(self):
        r = self.rows[6]
        self.assertEqual(r["injection"], {"followed": False, "offer": "5.00"})
        self.assertEqual(r["outcome"], batch.SETTLED)
        lines = read_lines(Path(self.work.name) / "merchant" / "merchant-receipts.ndjson")
        ignored = [l for l in lines if l["action_id"] == "clearwake.batch.injection_ignored"]
        self.assertEqual((len(ignored), ignored[0]["params"]["followed"], ignored[0]["success"]), (1, False, True))

    def test_a_claim_outside_the_mandate_opens_no_dispute_and_goes_to_the_person_with_the_evidence(self):
        r = self.rows[7]
        self.assertEqual((r["outcome"], r["dispute_id"], r["buyer_end"]), (batch.MANDATE_REFUSED, "", "handed_to_owner"))
        self.assertNotIn("page_dispute_id", r)
        lines = read_lines(Path(self.work.name) / "buyer" / "buyer-receipts.ndjson")
        names = [l["action_id"] for l in lines if r["order_id"] in l["step_id"]]
        self.assertIn("clearwake.buyer.claim_refused", names)
        self.assertIn("clearwake.buyer.handed_to_owner", names)
        self.assertNotIn("clearwake.buyer.open_dispute", names)
        handed = [l for l in lines if l["action_id"] == "clearwake.buyer.handed_to_owner"][0]["params"]
        self.assertEqual((handed["paid_minor"], handed["asked_minor"], handed["dispute_opened"]), (900, 2000, False))

    def test_a_lost_response_is_reconciled_from_paypal_and_the_offer_is_never_sent_twice(self):
        r = self.rows[8]
        self.assertEqual((r["reconciled"], r["offers_sent"], r["outcome"], r["refund_confirmed"]), (True, 1, batch.SETTLED, "5.00"))
        lines = read_lines(Path(self.work.name) / "merchant" / "merchant-receipts.ndjson")
        rec = [l for l in lines if l["action_id"] == "clearwake.batch.reconciled" and l["params"]["dispute"] == r["dispute_id"]]
        self.assertEqual((len(rec), rec[0]["params"]["resent"]), (1, False))

    def test_an_offer_above_the_merchants_limit_waits_for_the_merchant_owner(self):
        r = self.rows[9]
        self.assertEqual((r["outcome"], r["merchant_state"], r["refund_confirmed"], r["offers_sent"]), (batch.MERCHANT_OWNER, "awaiting approval", "0.00", 0))
        self.assertNotEqual(r["paypal_status"], "RESOLVED")

    def test_the_pair_of_logs_verifies_and_names_the_same_dispute_for_nine_cases(self):
        from clearwake.pair import verify_pair
        result = verify_pair(Path(self.work.name) / "buyer" / "buyer-receipts.ndjson", self.report["buyer_log"]["public_key"],
                             Path(self.work.name) / "merchant" / "merchant-receipts.ndjson", self.report["merchant_log"]["public_key"])
        self.assertEqual((result["ok"], len(result["disputes"]), result["no_dispute_cases"]), (True, 9, 1))
        self.assertEqual(set(result["disputes"]), {r["dispute_id"] for r in self.rows.values() if r["dispute_id"]})

    def test_the_merchants_rule_is_in_plain_words_and_in_the_policy_hash(self):
        self.assertIn("up to USD 5.00", self.report["merchant_rule"])
        self.assertTrue(self.report["merchant_rule_applied"])


class ScopeTests(unittest.TestCase):
    def test_every_other_reason_goes_to_the_owner_untouched(self):
        from clearwake.models import Adapter
        from clearwake.swarm import MerchantSwarm
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            gateway = LocalGateway(Path(d) / "p.sqlite3")
            swarm = MerchantSwarm(gateway, Path(d) / "m", Adapter("scripted"))
            swarm.only_item_not_received = True
            for reason in ("MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "UNAUTHORISED", "DUPLICATE_TRANSACTION"):
                dispute = gateway.open_dispute("CAP-" + reason[:5], reason, "3.00", "2030-01-01T00:00:00Z", "Something is wrong.", stage="INQUIRY")["dispute_id"]
                result = swarm.handle_dispute(dispute, 900, "buyer-x", {"id": "O"}, [{"number": "TRK123456", "carrier": "UPS", "status": "SHIPPED"}])
                record = gateway.dispute(dispute)
                self.assertEqual((result.state, result.action), ("awaiting approval", "escalate"))
                self.assertEqual((record["status"], len(record["messages"]), "offer" in record, "evidences" in record), ("WAITING_FOR_SELLER_RESPONSE", 1, False, False))
            lines = read_lines(swarm.receipts.path)
            self.assertEqual(sum(1 for l in lines if l["action_id"] == "clearwake.dispute.out_of_scope" and l["params"]["sent_anything"] is False), 3)

    def test_item_not_received_is_still_answered(self):
        from clearwake.models import Adapter
        from clearwake.swarm import MerchantSwarm
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            gateway = LocalGateway(Path(d) / "p.sqlite3")
            swarm = MerchantSwarm(gateway, Path(d) / "m", Adapter("scripted"))
            swarm.only_item_not_received = True
            dispute = gateway.open_dispute("CAP-NR", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "2.00", "2030-01-01T00:00:00Z", "Never came.", stage="INQUIRY")["dispute_id"]
            self.assertNotEqual(swarm.handle_dispute(dispute, 900, "buyer-y", {"id": "O"}, []).state, "awaiting approval")
            self.assertIn("offer", gateway.dispute(dispute))


class DispatchMixTests(unittest.TestCase):
    def test_missing_items_with_dispatch_proof_use_the_recorded_sam_count_and_the_merchant_fights(self):
        cases = tuple(c for c in batch.CASES_DISPATCH if c.n in (5, 7))
        report = batch.run_local(cases=cases)
        rows = {r["n"]: r for r in report["cases"]}
        self.assertIn("recorded", rows[5]["dispatch_counter"])
        self.assertEqual((rows[5]["merchant_decision"], rows[5]["buyer_end"], rows[5]["outcome"]), ("fight_with_evidence", "escalated_owner", batch.EVIDENCE))
        self.assertEqual(rows[7]["outcome"], batch.SETTLED)


class BuyerModelTests(unittest.TestCase):
    """The buyer agent makes model calls; code checks every one. A stub stands in for the model here, so these test the checks only."""

    @staticmethod
    def stub(draft, action):
        def send(url, payload, headers):
            keys = payload["messages"][0]["content"].rsplit("keys: ", 1)[1]
            body = {"message": draft} if keys.startswith("message") else {"choice": action}
            return {"choices": [{"message": {"content": json.dumps(body)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        return send

    def run_cases(self, numbers, draft, action):
        from clearwake.models import Adapter
        cases = tuple(c for c in batch.CASES_MIX_L if c.n in numbers)
        return batch.run_local(cases=cases, buyer_adapter=Adapter("ollama", "stub-model", send=self.stub(draft, action)))

    def test_a_good_draft_is_used_and_the_calls_are_counted_and_receipted(self):
        report = self.run_cases((3,), "My order has not arrived and I would like a refund of what is missing, please.", "accept")
        row = report["cases"][0]
        self.assertEqual((row["draft"]["used"], row["buyer_model_calls"], row["outcome"]), ("model", 2, batch.SETTLED))
        self.assertEqual(row["draft"]["message"], "My order has not arrived and I would like a refund of what is missing, please.")
        self.assertEqual(report["summary"]["buyer_model_calls"], 2)
        lines = read_lines(Path(report["work_dir"]) / "buyer" / "buyer-receipts.ndjson")
        calls = [l["params"] for l in lines if l["action_id"] in ("clearwake.buyer.model_draft", "clearwake.buyer.model_decision")]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c["model"] == "stub-model" and c["prompt_sha256"] for c in calls))

    def test_a_draft_with_a_wrong_amount_or_a_link_is_replaced_by_the_template(self):
        report = self.run_cases((3,), "Refund me 99.00 now, see http://example.com/pay", "accept")
        draft = report["cases"][0]["draft"]
        self.assertEqual(draft["used"], "template")
        self.assertIn(report["cases"][0]["order_id"], draft["message"])
        self.assertNotIn("99.00", draft["message"])

    def test_a_model_cannot_be_bolder_than_the_rule_but_may_be_more_careful(self):
        bold = self.run_cases((1,), "My order has not arrived and I would like a refund of what is missing, please.", "accept")   # the rule says escalate: records, no offer
        self.assertEqual((bold["cases"][0]["outcome"], bold["summary"]["buyer_model_overrides"]), (batch.EVIDENCE, 1))
        careful = self.run_cases((3,), "My order has not arrived and I would like a refund of what is missing, please.", "escalate")   # the rule says accept
        self.assertEqual(careful["cases"][0]["buyer_end"], "escalated_owner")
        self.assertNotEqual(careful["cases"][0]["outcome"], batch.SETTLED)

    def test_garbage_from_the_model_changes_nothing(self):
        report = self.run_cases((3,), "x", "give everything away")
        self.assertEqual(report["cases"][0]["outcome"], batch.SETTLED)   # not a permitted action: the rule's own action is taken


class PriceReferenceTests(unittest.TestCase):
    @staticmethod
    def fn(reference, within, note="ok"):
        from clearwake.market import MarketCheck
        return lambda product, tolerance: MarketCheck(reference, "shop.example" if reference else None, product["name"], None, within, 1 if reference else 0, note, 1)

    def run_one(self, price_fn):
        from clearwake.models import Adapter
        from playwright.sync_api import sync_playwright
        from clearwake.buyer_browser import fixture_site
        work = tempfile.mkdtemp(prefix="clearwake-price-")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(); page.goto(fixture_site().home_url)
                return batch.run_batch(batch.LocalRun(work, page), work, page, Adapter("scripted"), tuple(c for c in batch.CASES_MIX_L if c.n == 3), price_fn=price_fn), work
            finally:
                browser.close()

    def test_a_price_above_the_rule_is_refused_before_any_order(self):
        report, _ = self.run_one(self.fn(500, False))
        row = report["cases"][0]
        self.assertEqual(row["outcome"], batch.ERROR)
        self.assertIn("price rule refused", row["detail"])
        self.assertNotIn("order_id", row)
        self.assertEqual(report["summary"]["price_reference_refused"], 1)

    def test_no_reference_is_flagged_and_the_purchase_goes_on(self):
        report, work = self.run_one(self.fn(None, None, "refused: CHANNEL3_MAX_CALLS is 0, no live calls allowed"))
        row = report["cases"][0]
        self.assertEqual((row["price_reference"]["verdict"], row["outcome"]), ("flag", batch.SETTLED))
        self.assertEqual(report["summary"]["price_reference_flags"], 1)
        lines = read_lines(Path(work) / "buyer" / "buyer-receipts.ndjson")
        mandate = [l for l in lines if l["action_id"] == "clearwake.buyer.mandate"][0]
        self.assertEqual(mandate["params"]["price_reference"]["within_tolerance"], None)
        self.assertEqual(mandate["params"]["max_over_market_percent"], 25)

    def test_the_local_reference_is_a_recorded_fixture_that_uses_no_credits(self):
        report, _ = self.run_one(None)
        self.assertEqual(report["price_reference"], {"source": "recorded fixture", "used": True, "calls": 0})
        self.assertEqual(report["cases"][0]["price_reference"]["verdict"], "ok")


class PlanTests(unittest.TestCase):
    def test_the_plan_prints_one_approval_link_per_order_then_the_disputes_and_saves_the_orders(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            local_gw, printed = StandInSandbox(Path(d) / "p.sqlite3"), []
            lines = batch.plan_sandbox(cases=batch.CASES_MIX_L, work=Path(d) / "m", gateway=local_gw, out=printed.append)
            approve = [l for l in lines if l["action"] == "approve_order"]
            self.assertEqual(len(approve), 10)
            self.assertTrue(all(l["url"].startswith("https://www.sandbox.paypal.com/") for l in approve))
            self.assertEqual(len({l["order_id"] for l in approve}), 10)
            disputes = [l for l in lines if l["action"] == "open_dispute"]
            self.assertEqual(sorted(l["reason"] for l in disputes).count("unauthorised"), 2)
            self.assertEqual(len(printed), 21)
            self.assertIn("--resume", lines[-1]["command"])
            again = batch.plan_sandbox(cases=batch.CASES_MIX_L, work=Path(d) / "m", gateway=local_gw, out=lambda x: None)
            self.assertEqual(len(local_gw.orders), 10)   # a second plan creates no new orders
            self.assertEqual([l["order_id"] for l in again if l["action"] == "approve_order"], [l["order_id"] for l in approve])


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


class StandInSandbox:
    """Stands in for the PayPal sandbox in the manual mode tests: the local provider's disputes plus orders. Tests only."""
    mode = "paypal-sandbox"

    def __init__(self, path):
        self.inner, self.orders, self.n = LocalGateway(path), {}, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _access_token(self):
        return "t"

    def _request(self, path, payload, request_id):
        self.n += 1
        oid = f"LOCALORDER{self.n}"
        self.orders[oid] = {"status": "CREATED"}
        return self.order(oid)

    def order(self, oid):
        status = self.orders[oid]["status"]
        out = {"id": oid, "status": status, "links": [{"rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={oid}"}]}
        if status == "COMPLETED":
            out["purchase_units"] = [{"payments": {"captures": [{"id": "CAP" + oid, "status": "COMPLETED"}]},
                                      "shipping": {"trackers": self.orders[oid].get("trackers", [])}}]
        return out

    def capture_order(self, oid, request_id):
        self.orders[oid]["status"] = "COMPLETED"
        return self.order(oid)

    def add_tracking(self, order_id, capture_id, number, carrier, request_id):
        self.orders[order_id].setdefault("trackers", []).append({"id": f"{capture_id}-{number}", "status": "SHIPPED"})
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
            local_gw, printed = StandInSandbox(Path(d) / "p.sqlite3"), []
            cases = tuple(c for c in batch.CASES_MIX_L if c.n in (3, 7))
            report = batch.run_sandbox(cases=cases, manual=True, work=Path(d) / "manual", timeout_s=2, out=lambda l: local_gw.hands(l, printed), gateway=local_gw, poll_s=0)
            rows = {r["n"]: r for r in report["cases"]}
            self.assertEqual(rows[3]["outcome"], batch.SETTLED)
            self.assertEqual([a["action"] for a in printed[:3]], ["approve_order", "open_dispute", "accept_offer"])
            opened = printed[1]
            self.assertEqual((opened["reason"], opened["dispute_rule"]["accept_min_percent"]), ("item_not_received", 80))
            self.assertIn(opened["order_id"], opened["message"])
            self.assertIn("lead's browser", opened["performed_through"])
            self.assertEqual(printed[2]["decision"]["action"], "accept")
            lines = read_lines(Path(d) / "manual" / "buyer" / "buyer-receipts.ndjson")
            names = [l["action_id"] for l in lines]
            for needed in ("clearwake.buyer.approve_order.requested", "clearwake.buyer.approve_order", "clearwake.buyer.open_dispute", "clearwake.buyer.accept_offer"):
                self.assertIn(needed, names)
            self.assertTrue(all("lead's browser" in l["params"]["source"] for l in lines if l["action_id"] != "clearwake.buyer.mandate"))
            self.assertTrue(report["buyer_log"]["verifies"])
            self.assertEqual(rows[7]["outcome"], batch.MERCHANT_OWNER)   # the merchant owner's approval stays manual against the sandbox

    def test_a_missing_effect_times_out_receipted_and_stops_for_a_person_then_resume_continues(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            local_gw, work = StandInSandbox(Path(d) / "p.sqlite3"), Path(d) / "manual"
            cases = tuple(c for c in batch.CASES_MIX_L if c.n == 3)
            report = batch.run_sandbox(cases=cases, manual=True, work=work, timeout_s=0, out=lambda line: None, gateway=local_gw, poll_s=0)
            row = report["cases"][0]
            self.assertEqual(row["outcome"], batch.ERROR)
            self.assertIn("approve_order", row["detail"])
            self.assertTrue(row["manual_steps"])
            names = [l["action_id"] for l in read_lines(work / "buyer" / "buyer-receipts.ndjson")]
            self.assertIn("clearwake.buyer.approve_order.timeout", names)
            local_gw.orders["LOCALORDER1"]["status"] = "APPROVED"   # the person approved meanwhile
            again = batch.run_sandbox(cases=cases, manual=True, resume=True, work=work, timeout_s=2, out=local_gw.hands, gateway=local_gw, poll_s=0)
            self.assertEqual(again["cases"][0]["outcome"], batch.SETTLED)
            self.assertEqual(len(local_gw.orders), 1)   # resumed on the same order, no second purchase

    def test_the_ten_cases_in_manual_mode_print_the_buyer_actions_add_tracking_first_and_hand_the_rest_on(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            local_gw, printed = StandInSandbox(Path(d) / "p.sqlite3"), []
            report = batch.run_sandbox(manual=True, work=Path(d) / "manual", timeout_s=2, out=lambda l: local_gw.hands(l, printed), gateway=local_gw, poll_s=0)
            rows = {r["n"]: r for r in report["cases"]}
            self.assertEqual(report["summary"][batch.ERROR], 0, [r.get("detail") for r in report["cases"]])
            self.assertEqual([a["action"] for a in printed].count("open_dispute"), 9)   # case 7 opens none
            self.assertNotIn(rows[7]["order_id"], [a.get("order_id") for a in printed if a["action"] == "open_dispute"])
            self.assertEqual(rows[7]["outcome"], batch.MANDATE_REFUSED)
            self.assertEqual({n for n, r in rows.items() if r["outcome"] == batch.SETTLED}, {3, 4, 6, 8, 10})
            for n in (1, 2, 4, 5):   # tracking was added to the PayPal order before the dispute was asked for
                self.assertEqual(len(local_gw.orders[rows[n]["order_id"]]["trackers"]), 1)
            self.assertTrue(all(a["performed_through"].endswith("lead's browser") for a in printed))
            self.assertIn("settled by agents inside the limits", report["summary"]["result"]["text"])

    def test_a_counter_is_printed_then_confirmed_from_the_dispute_record(self):
        from clearwake.batch import RULE
        from clearwake.buyer_browser import Recorder, open_buyer_log
        from clearwake.buyer_manual import ManualBuyer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            local_gw, printed = StandInSandbox(Path(d) / "p.sqlite3"), []
            dispute = local_gw.inner.open_dispute("CAP-X", batch.NOT_RECEIVED, "9.00", "2030-01-01T00:00:00Z", "Never arrived.", stage="INQUIRY")["dispute_id"]
            rec = Recorder(open_buyer_log(Path(d) / "b"), "a" * 64, "paypal-sandbox via the lead's browser", Path(d) / "s")
            door = ManualBuyer(local_gw, rec, RULE, out=lambda l: local_gw.hands(l, printed), timeout_s=2, poll_s=0)
            self.assertTrue(door.counter(dispute, "Could you raise the refund to USD 7.20?"))
            self.assertEqual((printed[0]["action"], printed[0]["message"]), ("counter", "Could you raise the refund to USD 7.20?"))
            self.assertEqual(door.read_thread(dispute).messages[-1], ("buyer", "Could you raise the refund to USD 7.20?"))


if __name__ == "__main__":
    unittest.main()
