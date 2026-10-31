"""Fee leak gauge: PayPal's dispute rate rule, computed only from records Clearwake read.

PayPal's rule (Help Center article help350): the dispute rate is the disputed amount of item not received and
not as described claims over net sales for the previous 3 calendar months. A seller with more than 100 sales
transactions in that time and a dispute rate of 1.5% or more pays the High Volume Dispute Fee. No dispute fee
is charged when a case is resolved directly between seller and buyer and not escalated to a claim.
The Standard fee is also not charged on claims below twice the Standard fee or on unauthorised transactions,
so a settled case only counts as a fee avoided when PayPal's rule would otherwise have charged it.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

RULE_SOURCE = ("PayPal Help Center, help350 (UK edition; the US edition was not reachable on 31 Oct 2026)",
               "https://history.paypal.com/uk/cshelp/article/how-is-the-dispute-rate-calculated-and-how-do-i-avoid-being-charged-a-dispute-fee-help350")
FEE_SOURCE = ("PayPal Merchant Fees, United States, last updated 1 Oct 2026", "https://www.paypal.com/us/business/paypal-business-fees")
STANDARD_FEE_MINOR, HIGH_VOLUME_FEE_MINOR = 1500, 3000   # USD, from FEE_SOURCE; checked 31 Oct 2026
RATE_LINE = Decimal("0.015")
SALES_LINE = 100
COUNTED_REASONS = ("MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED")


@dataclass
class Gauge:
    sales: int
    net_sales_minor: int
    counted_disputes: int
    disputed_minor: int
    rate: Decimal | None              # None when there were no sales to divide by
    high_volume: bool
    settled_before_escalation: int    # PayPal shows RESOLVED at the INQUIRY stage
    escalated: int                    # PayPal shows a stage after INQUIRY
    fee_avoided_minor: int            # only for settled cases, at the fee tier PayPal's rule would have charged
    window: tuple

    def as_dict(self):
        return {"sales": self.sales, "net_sales": f"{self.net_sales_minor / 100:.2f}", "counted_disputes": self.counted_disputes,
                "disputed": f"{self.disputed_minor / 100:.2f}", "rate_percent": None if self.rate is None else f"{self.rate * 100:.2f}",
                "rate_line_percent": "1.50", "sales_line": SALES_LINE, "high_volume": self.high_volume,
                "settled_before_escalation": self.settled_before_escalation, "escalated": self.escalated,
                "fee_avoided": f"{self.fee_avoided_minor / 100:.2f}", "currency": "USD", "window": list(self.window),
                "rule_source": RULE_SOURCE, "fee_source": FEE_SOURCE}


def _minor(money):
    return int(Decimal((money or {}).get("value", "0")) * 100)


def _when(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def gauge(sales, disputes, now=None):
    """sales: [{"amount": {"value", "currency_code"}, "time": iso}], disputes: PayPal dispute records as read.

    Window: the previous 3 calendar months plus the current month to date, so a demo run on fresh records counts."""
    now = now or datetime.now(timezone.utc)
    start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)).replace(day=1)
    start = (start - timedelta(days=1)).replace(day=1)
    start = (start - timedelta(days=1)).replace(day=1)
    inside = lambda t: t is None or start <= t <= now
    counted_sales = [s for s in sales if inside(_when(s.get("time")))]
    net = sum(_minor(s.get("amount")) for s in counted_sales)
    counted = [d for d in disputes if d.get("reason") in COUNTED_REASONS and inside(_when(d.get("create_time")))]
    disputed = sum(_minor(d.get("dispute_amount")) for d in counted)
    rate = (Decimal(disputed) / Decimal(net)) if net else None
    high_volume = len(counted_sales) > SALES_LINE and rate is not None and rate >= RATE_LINE
    settled = [d for d in disputes if d.get("status") == "RESOLVED" and d.get("dispute_life_cycle_stage") == "INQUIRY"]
    escalated = [d for d in disputes if d.get("dispute_life_cycle_stage") not in (None, "INQUIRY")]
    return Gauge(len(counted_sales), net, len(counted), disputed, rate, high_volume, len(settled), len(escalated),
                 sum(fee_if_escalated(d, high_volume) for d in settled), (start.date().isoformat(), now.date().isoformat()))


def fee_if_escalated(dispute, high_volume):
    """The fee PayPal's rule would have charged had this case become a claim. 0 when an exemption applies."""
    if dispute.get("reason") in ("UNAUTHORISED", "UNAUTHORIZED"):
        return 0
    if high_volume:
        return HIGH_VOLUME_FEE_MINOR
    return STANDARD_FEE_MINOR if _minor(dispute.get("dispute_amount")) >= 2 * STANDARD_FEE_MINOR else 0
