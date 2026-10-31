"""Fee leak gauge: PayPal's dispute rate rule from records read, and fee avoided only where the rule would charge."""
from datetime import datetime, timezone
import unittest

from clearwake.fees import gauge

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


def sale(value, time="2026-10-15T10:00:00Z"):
    return {"amount": {"value": value, "currency_code": "USD"}, "time": time}


def dispute(value, reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED", status="WAITING_FOR_SELLER_RESPONSE", stage="INQUIRY", time="2026-10-20T10:00:00Z"):
    return {"dispute_amount": {"value": value, "currency_code": "USD"}, "reason": reason, "status": status,
            "dispute_life_cycle_stage": stage, "create_time": time}


class FeeGaugeTests(unittest.TestCase):
    def test_rate_counts_only_not_received_and_not_as_described_in_the_window(self):
        g = gauge([sale("100.00")] * 10 + [sale("500.00", "2026-05-01T00:00:00Z")],
                  [dispute("10.00"), dispute("10.00", "UNAUTHORISED"), dispute("10.00", time="2026-06-01T00:00:00Z")], NOW)
        self.assertEqual((g.sales, g.net_sales_minor, g.counted_disputes, g.disputed_minor), (10, 100000, 1, 1000))
        self.assertEqual(g.as_dict()["rate_percent"], "1.00"); self.assertFalse(g.high_volume)

    def test_high_volume_needs_more_than_100_sales_and_a_rate_of_at_least_one_and_a_half_percent(self):
        sales = [sale("10.00")] * 101
        self.assertTrue(gauge(sales, [dispute("15.15")], NOW).high_volume)       # 15.15 / 1010.00 = 1.5%
        self.assertFalse(gauge(sales, [dispute("15.00")], NOW).high_volume)
        self.assertFalse(gauge(sales[:100], [dispute("50.00")], NOW).high_volume)  # exactly 100 sales is not more than 100

    def test_fee_avoided_counts_only_cases_settled_as_an_inquiry_that_the_rule_would_have_charged(self):
        settled = lambda v, r="MERCHANDISE_OR_SERVICE_NOT_RECEIVED": dispute(v, r, "RESOLVED", "INQUIRY")
        g = gauge([sale("100.00")] * 3, [settled("40.00"), settled("2.50"), settled("40.00", "UNAUTHORISED"),
                                         dispute("40.00", status="RESOLVED", stage="CHARGEBACK")], NOW)
        self.assertEqual((g.settled_before_escalation, g.escalated, g.fee_avoided_minor), (3, 1, 1500))
        self.assertIsNone(gauge([], [], NOW).rate)


if __name__ == "__main__":
    unittest.main()
