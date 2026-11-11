"""The owner's dispute rule: validated, signed into the mandate receipt, and applied by pure functions."""
import json
from pathlib import Path
import tempfile
import unittest

from clearwake.buyer import BuyerDecision, DisputeRule, Mandate, decide_offer, load_catalog, mandate_receipt, reason_key
from verdock_core.receipts import ReceiptLog, create_seed, load_seed, verify_log

RULE = DisputeRule(accept_min_percent=80, counter_min_percent=40, max_counters=1)


def decide(offer, requested=1000, reason="item_not_received", **kw):
    return decide_offer(RULE, reason, requested, offer, **kw)


class RuleValidationTests(unittest.TestCase):
    def test_defaults_and_bounds(self):
        self.assertEqual(DisputeRule().accept_min_percent, 80)
        for bad in ({"accept_min_percent": 0}, {"accept_min_percent": 101}, {"accept_min_percent": 80.5}, {"accept_min_percent": True},
                    {"counter_min_percent": 90}, {"max_counters": 4}, {"max_counters": -1}, {"no_response_hours": 0},
                    {"escalate_on": ()}, {"escalate_on": ("nonsense",)}, {"escalate_on": ["no_response"]}, {"escalate_to_claim": "yes"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                DisputeRule(**bad)

    def test_the_mandate_only_takes_a_real_rule(self):
        with self.assertRaises(ValueError):
            Mandate("o", 1000, 1000, ("m",), ("c",), dispute_rule={"accept_min_percent": 10})
        self.assertIsNone(Mandate("o", 1000, 1000, ("m",), ("c",)).dispute_rule)

    def test_no_rule_means_no_negotiation(self):
        with self.assertRaises(ValueError):
            decide_offer(None, "item_not_received", 1000, 900)

    def test_reasons_map_from_paypal_codes_and_unknown_ones_are_refused(self):
        self.assertEqual(reason_key("MERCHANDISE_OR_SERVICE_NOT_RECEIVED"), "item_not_received")
        self.assertEqual(reason_key("MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"), "not_as_described")
        self.assertEqual(reason_key("missing_items"), "missing_items")
        self.assertEqual(reason_key("UNAUTHORISED"), "unauthorised")
        with self.assertRaises(ValueError):
            reason_key("SOMETHING_ELSE")


class DecisionTests(unittest.TestCase):
    def test_accepts_at_or_above_the_threshold_exactly(self):
        self.assertEqual(decide(800).action, "accept")      # exactly 80%
        self.assertEqual(decide(1000).action, "accept")
        self.assertNotEqual(decide(799).action, "accept")   # 79.9% is below

    def test_missing_items_use_the_same_threshold_as_not_received(self):
        self.assertEqual(decide(800, reason="missing_items").action, "accept")
        self.assertEqual(decide(700, reason="missing_items").action, "counter")

    def test_not_as_described_has_its_own_threshold(self):
        rule = DisputeRule(accept_min_percent=80, accept_min_percent_not_as_described=60)
        self.assertEqual(decide_offer(rule, "not_as_described", 1000, 600).action, "accept")
        self.assertEqual(decide_offer(rule, "item_not_received", 1000, 600).action, "counter")

    def test_a_counter_asks_for_the_accept_threshold_rounded_up_never_above_the_request(self):
        got = decide(555, requested=999)
        self.assertEqual((got.action, got.counter_minor), ("counter", 800))   # ceil(999 * 0.8) = 800
        self.assertLessEqual(decide(500, requested=1).counter_minor if decide(500, requested=1).action == "counter" else 0, 1)

    def test_counters_are_limited_then_the_owner_decides(self):
        first = decide(550, counters_used=0)
        again = decide(550, counters_used=1)
        self.assertEqual((first.action, again.action, again.code), ("counter", "escalate", "counters_exhausted"))
        self.assertEqual(decide_offer(DisputeRule(max_counters=0), "item_not_received", 1000, 550).action, "escalate")

    def test_an_offer_below_the_counter_floor_goes_to_the_owner(self):
        self.assertEqual((decide(399).action, decide(399).code), ("escalate", "below_counter_floor"))
        self.assertEqual(decide(400).action, "counter")

    def test_an_offer_above_the_request_is_not_taken_blindly(self):
        self.assertEqual((decide(1001).action, decide(1001).code), ("escalate", "offer_exceeds_request"))

    def test_records_without_an_offer_escalate_and_silence_waits_until_the_limit(self):
        self.assertEqual(decide(None, evidence=True).code, "merchant_evidence")
        self.assertEqual(decide(None, replied=True).action, "escalate")
        self.assertEqual(decide(None).action, "wait")
        self.assertEqual(decide(None, hours_waiting=71).action, "wait")
        self.assertEqual((decide(None, hours_waiting=72).action, decide(None, hours_waiting=72).code), ("escalate", "no_response"))

    def test_a_condition_the_owner_left_out_waits_instead_of_escalating(self):
        rule = DisputeRule(escalate_on=("counters_exhausted",))
        self.assertEqual(decide_offer(rule, "item_not_received", 1000, None, replied=True).action, "wait")
        self.assertEqual(decide_offer(rule, "item_not_received", 1000, 550, counters_used=1).action, "escalate")

    def test_bad_numbers_are_refused(self):
        for requested, offer in ((0, 100), (-5, 100), (10.5, 5), (1000, -1), (1000, 99.9), (True, 5)):
            with self.subTest(requested=requested, offer=offer), self.assertRaises(ValueError):
                decide_offer(RULE, "item_not_received", requested, offer)

    def test_wording_cannot_change_a_decision(self):
        # the function takes numbers and flags only: no text reaches it
        a = decide(500, evidence=False)
        self.assertIsInstance(a, BuyerDecision)
        self.assertEqual(a, decide(500, evidence=False))

    def test_every_percentage_boundary(self):
        for requested in (100, 333, 999, 1000, 4500):
            for offer in range(0, requested + 1, max(1, requested // 50)):
                got = decide_offer(RULE, "item_not_received", requested, offer)
                if offer * 100 >= 80 * requested:
                    self.assertEqual(got.action, "accept", (requested, offer))
                elif offer * 100 < 40 * requested:
                    self.assertEqual(got.action, "escalate", (requested, offer))
                else:
                    self.assertEqual(got.action, "counter", (requested, offer))


class ClaimRuleTests(unittest.TestCase):
    def test_a_claim_is_allowed_only_for_an_order_the_agent_placed_up_to_its_amount(self):
        from clearwake.buyer import claim_allowed
        mandate = Mandate("o", 10000, 10000, ("m",), ("c",), dispute_rule=RULE)
        self.assertTrue(claim_allowed(mandate, 900, 900)[0])
        self.assertTrue(claim_allowed(mandate, 300, 900)[0])
        ok, why = claim_allowed(mandate, 2000, 900)
        self.assertFalse(ok); self.assertIn("more than the 9.00", why)
        self.assertFalse(claim_allowed(mandate, 500, 900, placed_by_agent=False)[0])
        self.assertFalse(claim_allowed(Mandate("o", 10000, 10000, ("m",), ("c",)), 500, 900)[0])
        for bad in ((0, 900), (-1, 900), (500, 0), (5.5, 900)):
            self.assertFalse(claim_allowed(mandate, *bad)[0])


class ModelCheckTests(unittest.TestCase):
    def test_the_model_may_only_pick_among_actions_the_rule_permits(self):
        from clearwake.buyer import final_action
        self.assertEqual(final_action("accept", "accept"), "accept")
        self.assertEqual(final_action("accept", "escalate"), "escalate")      # more careful is allowed
        self.assertEqual(final_action("escalate", "accept"), "escalate")      # bolder is not
        self.assertEqual(final_action("counter", "accept"), "counter")
        self.assertEqual(final_action("wait", "escalate"), "wait")
        self.assertEqual(final_action("accept", "give it all away"), "accept")

    def test_a_drafted_message_may_state_only_the_amount_asked_and_no_links(self):
        from clearwake.buyer import check_draft
        self.assertTrue(check_draft("My notebook never arrived. I would like 9.00 USD back.", 900)[0])
        self.assertFalse(check_draft("Please send 12.00 USD.", 900)[0])
        self.assertFalse(check_draft("See https://example.com for details of the order.", 900)[0])
        self.assertFalse(check_draft("short", 900)[0])
        self.assertFalse(check_draft("x" * 600, 900)[0])
        self.assertFalse(check_draft(None, 900)[0])


class PriceRuleTests(unittest.TestCase):
    @staticmethod
    def check(reference, within, note="ok"):
        from clearwake.market import MarketCheck
        return MarketCheck(reference, "shop.example" if reference else None, "Item", None, within, 0, note, 1)

    def test_the_price_rule_is_validated(self):
        for bad in (-1, 1001, 10.5, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Mandate("o", 1000, 1000, ("m",), ("c",), max_over_market_percent=bad)
        self.assertEqual(Mandate("o", 1000, 1000, ("m",), ("c",), max_over_market_percent=25).max_over_market_percent, 25)

    def test_ok_flag_and_refuse(self):
        from clearwake.buyer import price_verdict
        rule = Mandate("o", 1000, 1000, ("m",), ("c",), max_over_market_percent=25)
        self.assertEqual(price_verdict(rule, self.check(900, True))["action"], "ok")
        self.assertEqual(price_verdict(rule, self.check(500, False))["action"], "refuse")
        self.assertEqual(price_verdict(rule, self.check(None, None, "refused: cap"))["action"], "flag")
        self.assertEqual(price_verdict(rule, None)["action"], "flag")
        self.assertEqual(price_verdict(Mandate("o", 1000, 1000, ("m",), ("c",)), self.check(500, False))["action"], "ok")   # no rule, no check

    def test_the_reference_and_the_rule_are_signed_into_the_mandate_receipt(self):
        _, _, products = load_catalog()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            seed = Path(folder) / "b.seed"; create_seed(str(seed))
            log = ReceiptLog(str(Path(folder) / "b.ndjson"), load_seed(str(seed)))
            mandate = Mandate("Owner", 10200, 10200, ("clearwake-sandbox-store",), ("stationery",), max_over_market_percent=25)
            receipt = mandate_receipt(log, mandate, products["notebook-a5"], "clearwake-sandbox-store", "ORDER-P-1", price=self.check(900, True))
            params = json.loads(receipt["line"])["params"]
            self.assertEqual((params["max_over_market_percent"], params["price_reference"]["reference_minor"], params["price_reference"]["within_tolerance"]), (25, 900, True))
            self.assertTrue(verify_log([receipt["line"]], receipt["public_key"])["ok"])


class SignedRuleTests(unittest.TestCase):
    def test_the_rule_is_in_the_signed_mandate_receipt_and_an_edit_breaks_it(self):
        _, _, products = load_catalog()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            seed = Path(folder) / "b.seed"; create_seed(str(seed))
            log = ReceiptLog(str(Path(folder) / "b.ndjson"), load_seed(str(seed)))
            mandate = Mandate("Owner", 10200, 10200, ("clearwake-sandbox-store",), ("stationery",), dispute_rule=RULE)
            receipt = mandate_receipt(log, mandate, products["notebook-a5"], "clearwake-sandbox-store", "ORDER-RULE-1")
            body = json.loads(receipt["line"])
            self.assertEqual(body["params"]["dispute_rule"]["accept_min_percent"], 80)
            self.assertEqual(body["params"]["dispute_rule"]["max_counters"], 1)
            self.assertTrue(verify_log([receipt["line"]], receipt["public_key"])["ok"])
            edited = receipt["line"].replace('"accept_min_percent":80', '"accept_min_percent":10')
            self.assertNotEqual(edited, receipt["line"])
            self.assertFalse(verify_log([edited], receipt["public_key"])["ok"])

    def test_a_mandate_without_a_rule_says_so_in_the_receipt(self):
        _, _, products = load_catalog()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            seed = Path(folder) / "b.seed"; create_seed(str(seed))
            log = ReceiptLog(str(Path(folder) / "b.ndjson"), load_seed(str(seed)))
            receipt = mandate_receipt(log, Mandate("Owner", 10200, 10200, ("m",), ("stationery",)), products["notebook-a5"], "m", "ORDER-RULE-2")
            self.assertEqual(json.loads(receipt["line"])["params"]["dispute_rule"], "none")


if __name__ == "__main__":
    unittest.main()
