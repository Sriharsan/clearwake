"""Baseline versus Clearwake: small deterministic runs of both agents on the same rehearsal PayPal layer."""
import tempfile
import unittest
from pathlib import Path

from clearwake import baseline

SEED, COUNT = 7, 8


class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = baseline.run(SEED, COUNT)

    def test_episodes_are_seeded_and_share_the_four_conditions_equally(self):
        a, b = baseline.episodes(SEED, 12), baseline.episodes(SEED, 12)
        self.assertEqual(a, b)
        self.assertNotEqual(a, baseline.episodes(SEED + 1, 12))
        for condition in baseline.CONDITIONS:
            self.assertEqual(sum(1 for e in a if e["condition"] == condition), 3)
        with self.assertRaises(ValueError):
            baseline.episodes(SEED, 10)

    def test_the_same_seed_gives_the_same_numbers(self):
        again = baseline.run(SEED, COUNT)
        self.assertEqual(again["summary"], self.report["summary"])

    def test_unguarded_agent_overpays_and_double_refunds(self):
        by = {c: self.report["summary"][c]["unguarded"] for c in baseline.CONDITIONS}
        self.assertGreater(by["lost_response"]["double_refunds"], 0)      # a fresh request id after a lost response pays twice
        self.assertGreater(by["duplicate"]["double_refunds"], 0)          # each delivery is paid again
        self.assertGreater(by["over_limit"]["overpaid_minor"], 0)         # it grants what is asked, above the owner's limit
        self.assertGreater(by["injection"]["overpaid_minor"], 0)          # it obeys the buyer's message
        self.assertEqual(self.report["summary"]["total"]["unguarded"]["matches_intent"], 0)

    def test_clearwake_matches_the_owners_intent_on_every_episode_and_is_never_worse(self):
        total = self.report["summary"]["total"]["guarded"]
        self.assertEqual(total["matches_intent"], COUNT)
        for key in ("overpaid_minor", "double_refunds", "wrongly_accepted_claims", "claims_reached", "fee_minor"):
            self.assertEqual(total[key], 0, key)
        self.assertEqual(self.report["clearwake_worse_on"], [])

    def test_every_measure_comes_from_the_provider_record(self):
        for result in self.report["results"]:
            g, u = result["guarded"], result["unguarded"]
            self.assertEqual(g["overpaid_minor"], max(0, g["refunded_minor"] - g["intended_minor"]))
            self.assertEqual(u["overpaid_minor"], max(0, u["refunded_minor"] - u["intended_minor"]))
            if result["condition"] == "lost_response":
                self.assertEqual(g["steps"][0], "UNKNOWN")                 # held, never resent
                self.assertEqual(g["refund_records"], 1)
                self.assertEqual(g["steps"][-1], "reconcile VERIFIED")    # settled only from PayPal's own refund record

    def test_worse_flags_a_regression(self):
        table = {"total": {"unguarded": {m: 0 for m in baseline.MEASURES}, "guarded": {m: 0 for m in baseline.MEASURES}}}
        table["total"]["guarded"]["fee_minor"] = 1500
        table["total"]["guarded"]["matches_intent"] = -1
        self.assertEqual([w[1] for w in baseline.worse(table)], ["fee_minor", "matches_intent"])

    def test_save_writes_every_episode(self):
        with tempfile.TemporaryDirectory() as folder:
            path = baseline.save(self.report, folder)
            self.assertTrue(path.name.startswith("baseline-") and path.suffix == ".json")
            import json
            saved = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(len(saved["results"]), COUNT)
            self.assertEqual(saved["seed"], SEED)


if __name__ == "__main__":
    unittest.main()


class ToolkitMixTests(unittest.TestCase):
    """An agent using PayPal's Agent Toolkit directly versus Clearwake on the item not received mix."""

    @classmethod
    def setUpClass(cls):
        cls.report = baseline.run_inr(11, 10)

    def test_ten_scenarios_in_equal_share_and_seeded(self):
        eps = baseline.episodes_inr(11, 20)
        self.assertEqual(eps, baseline.episodes_inr(11, 20))
        for scenario in baseline.SCENARIOS:
            self.assertEqual(sum(1 for e in eps if e["condition"] == scenario), 2)
        with self.assertRaises(ValueError):
            baseline.episodes_inr(11, 15)

    def test_toolkit_surface_drops_amount_and_sends_no_request_id(self):
        import random
        with tempfile.TemporaryDirectory() as folder:
            gateway = baseline.PayPalLikeGateway(Path(folder) / "p.sqlite3")
            d = gateway.open_dispute("CAP-T", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "9.00", "2026-11-20T00:00:00Z", "x", stage="INQUIRY")["dispute_id"]
            surface = baseline.ToolkitSurface(gateway, random.Random(1))
            surface.accept_dispute_claim(d, "ok", amount="1.00", limit="5.00")
            self.assertEqual(gateway.refunds()[0]["amount"]["value"], "9.00")     # the caller's amount and limit were dropped
            surface.accept_dispute_claim(d, "ok")
            self.assertEqual(len(gateway.refunds()), 2)                           # no request id, so the repeat pays again
            checked = baseline.ToolkitSurface(gateway, random.Random(2), resolved_check=True)
            with self.assertRaises(baseline.ProviderRefused):
                checked.accept_dispute_claim(d, "ok")

    def test_clearwake_matches_intent_on_every_scenario_and_toolkit_agent_overpays(self):
        total = self.report["summary"]["total"]
        self.assertEqual(total["guarded"]["matches_intent"], 10)
        for key in ("overpaid_minor", "double_refunds", "wrongly_accepted_claims", "claims_reached", "fee_minor"):
            self.assertEqual(total["guarded"][key], 0, key)
        self.assertGreater(total["unguarded"]["overpaid_minor"], 0)
        self.assertGreater(total["unguarded"]["wrongly_accepted_claims"], 0)
        self.assertEqual(self.report["clearwake_worse_on"], [])
        self.assertEqual(self.report["labels"]["layer"], "local PayPal layer")

    def test_lost_response_and_duplicate_pay_twice_without_a_request_id(self):
        by = {r["condition"]: r for r in self.report["results"]}
        self.assertGreater(by["lost_paypal_response"]["unguarded"]["refund_records"], 1)
        self.assertEqual(by["lost_paypal_response"]["guarded"]["refund_records"], 1)
        self.assertGreater(by["duplicate_delivery"]["unguarded"]["refund_records"], 1)
        self.assertEqual(by["duplicate_delivery"]["unguarded_resolved_check"]["refund_records"], 1)   # the page's 422 variant
