"""Channel3 market reference: credit discipline and outcomes, all with a fake transport. No test makes a live call."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clearwake import market

KEY = "test-key-not-real-123"
BODY = {"products": [
    {"title": "Stone Mug", "brand_name": "Acme", "offers": [{"domain": "a.example", "price": {"price": 10.0, "currency": "USD"}}]},
    {"title": "Stone Mug 2", "offers": [{"domain": "b.example", "price": {"price": 14.0, "currency": "USD"}}, {"domain": "c.example", "price": {"price": 9.0, "currency": "GBP"}}]},
    {"title": "Stone Mug 3", "offers": [{"domain": "d.example", "price": {"price": 12.0, "currency": "USD"}}]}]}


class Fake:
    def __init__(self, status=200, body=BODY, exc=None):
        self.calls, self.status, self.body, self.exc = [], status, body, exc

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, dict(headers), body))
        if self.exc:
            raise self.exc
        return self.status, self.body


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.usage = Path(self.tmp.name) / "usage.json"
        self.patch = mock.patch.dict(os.environ, {"CHANNEL3_API_KEY": KEY, "CHANNEL3_MAX_CALLS": "5"})
        self.patch.start()
        self.load = mock.patch.object(market, "_load_key_vars", lambda *a, **k: None)
        self.load.start()
        self.live = mock.patch.object(market, "_urllib_transport", side_effect=AssertionError("live call"))
        self.live.start()

    def tearDown(self):
        self.live.stop(); self.load.stop(); self.patch.stop(); self.tmp.cleanup()

    def check(self, fake, q="Stoneware mug", price=1200, tol=None):
        return market.price_check(q, price, "USD", tol, transport=fake, usage_path=self.usage)

    def test_default_cap_zero_refuses_without_calling(self):
        with mock.patch.dict(os.environ, {"CHANNEL3_MAX_CALLS": "0"}):
            f = Fake()
            c = self.check(f)
        self.assertEqual(f.calls, [])
        self.assertEqual(c.credits_used, 0)
        self.assertIsNone(c.reference_minor)
        self.assertTrue(c.note.startswith("refused"))
        self.assertFalse(self.usage.exists())

    def test_unset_cap_means_zero(self):
        env = {k: v for k, v in os.environ.items() if k != "CHANNEL3_MAX_CALLS"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(market.max_calls(), 0)

    def test_reference_is_median_in_currency_and_within_tolerance(self):
        f = Fake()
        c = self.check(f, price=1300, tol=20)
        self.assertEqual(c.reference_minor, 1200)  # median of 10, 12, 14; the GBP offer is ignored
        self.assertEqual(c.credits_used, 1)
        self.assertTrue(c.within_tolerance)
        self.assertEqual(f.calls[0][0], market.URL)
        self.assertEqual(f.calls[0][1]["x-api-key"], KEY)
        self.assertEqual(f.calls[0][2]["limit"], market.LIMIT)

    def test_far_above_reference_is_outside_tolerance(self):
        self.assertFalse(self.check(Fake(), price=2400, tol=50).within_tolerance)

    def test_no_tolerance_gives_none(self):
        self.assertIsNone(self.check(Fake()).within_tolerance)

    def test_cache_prevents_second_charge(self):
        f = Fake()
        self.check(f)
        c = self.check(f, q="  stoneware MUG ")
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(c.credits_used, 0)
        self.assertEqual(c.note, "cached")
        self.assertEqual(c.reference_minor, 1200)
        self.assertEqual(market.calls_this_month(self.usage), 1)

    def test_cache_expires_after_24h(self):
        f = Fake()
        self.check(f)
        data = json.loads(self.usage.read_text())
        k = next(iter(data["cache"]))
        data["cache"][k]["ts_ms"] -= 25 * 3600 * 1000
        self.usage.write_text(json.dumps(data))
        self.check(f)
        self.assertEqual(len(f.calls), 2)

    def test_hard_cap_stops_calls(self):
        with mock.patch.dict(os.environ, {"CHANNEL3_MAX_CALLS": "2"}):
            f = Fake()
            for q in ("a", "b", "c"):
                c = self.check(f, q=q)
        self.assertEqual(len(f.calls), 2)
        self.assertIn("cap reached", c.note)
        self.assertEqual(c.credits_used, 0)

    def test_missing_key_refuses(self):
        with mock.patch.dict(os.environ, {"CHANNEL3_API_KEY": ""}):
            f = Fake()
            c = self.check(f)
        self.assertEqual(f.calls, [])
        self.assertTrue(c.note.startswith("refused"))

    def test_service_errors_are_not_retried_and_counted_once(self):
        for status in (401, 402, 429, 500, 503):
            f = Fake(status=status, body={})
            path = Path(self.tmp.name) / f"u{status}.json"
            c = market.price_check("x", 100, transport=f, usage_path=path)
            self.assertEqual(len(f.calls), 1, status)
            self.assertIsNone(c.reference_minor)
            self.assertEqual(c.credits_used, 1)
            self.assertIn(str(status), c.note)
            self.assertIsNone(c.within_tolerance)
            self.assertEqual(market.calls_this_month(path), 1)

    def test_timeout_is_not_retried(self):
        f = Fake(exc=TimeoutError())
        c = self.check(f)
        self.assertEqual(len(f.calls), 1)
        self.assertIn("timeout", c.note)
        self.assertEqual(market.calls_this_month(self.usage), 1)

    def test_empty_result_is_cached_and_free_next_time(self):
        f = Fake(body={"products": []})
        self.assertIsNone(self.check(f).reference_minor)
        self.check(f)
        self.assertEqual(len(f.calls), 1)

    def test_key_never_appears_in_results_or_usage_file(self):
        c = self.check(Fake(status=401, body={}))
        c2 = self.check(Fake(), q="other")
        for text in (json.dumps(c.to_receipt_params()), json.dumps(c2.to_receipt_params()), c.note, self.usage.read_text()):
            self.assertNotIn(KEY, text)

    def test_receipt_params_are_compact(self):
        p = self.check(Fake(), tol=10).to_receipt_params()
        self.assertEqual(set(p), {"reference_minor", "currency", "source_domain", "within_tolerance", "credits_used", "note", "title", "brand"})
        self.assertLess(len(json.dumps(p)), 400)

    def test_plan_makes_no_call_and_counts_credits(self):
        f = Fake()
        self.check(f, q="cached one")
        p = market.plan([("cached one", "USD"), ("new one", "USD")], usage_path=self.usage)
        self.assertEqual(p["credits"], 1)
        self.assertEqual(len(f.calls), 1)
        self.assertEqual([r["cached"] for r in p["queries"]], [True, False])


if __name__ == "__main__":
    unittest.main()
