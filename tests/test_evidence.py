"""Evidence agent: only facts from records, and deadlines escalate before they lapse."""
from datetime import datetime, timedelta, timezone
import unittest

from clearwake.evidence import DisputeView, deadline, evidence_pack, propose

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def dispute(reason, value="9.00", due_in_hours=72):
    return DisputeView.from_paypal({"dispute_id": "PP-D-SYNTH", "status": "WAITING_FOR_SELLER_RESPONSE", "reason": reason,
        "dispute_amount": {"currency_code": "USD", "value": value},
        "seller_response_due_date": (NOW + timedelta(hours=due_in_hours)).isoformat().replace("+00:00", "Z"),
        "disputed_transactions": [{"seller_transaction_id": "CAPTURE1"}]})


TRACKER = [{"number": "SYNTH1Z999AA10123456", "carrier": "UPS", "status": "SHIPPED"}]
MANDATE = {"order_id": "ORDER1", "owner": "Test shopper", "item": "notebook-a5", "price": "USD 9.00", "cap": "USD 102.00", "digest": "ab" * 32}


class EvidenceTests(unittest.TestCase):
    def test_not_received_with_tracking_submits_tracking_from_the_record(self):
        view = dispute("MERCHANDISE_OR_SERVICE_NOT_RECEIVED")
        evidences, sources = evidence_pack(view, {"id": "ORDER1"}, TRACKER)
        self.assertEqual(evidences[0]["evidence_type"], "PROOF_OF_FULFILLMENT")
        self.assertEqual(evidences[0]["evidence_info"]["tracking_info"][0]["tracking_number"], "SYNTH1Z999AA10123456")
        self.assertTrue(sources and "tracker" in sources[0])
        self.assertEqual(propose(view, evidences, 500, deadline(view, NOW))[0], "provide_evidence")

    def test_no_record_means_no_evidence(self):
        view = dispute("MERCHANDISE_OR_SERVICE_NOT_RECEIVED")
        self.assertEqual(evidence_pack(view, {"id": "ORDER1"}, [])[0], [])
        self.assertEqual(evidence_pack(view, {"id": "ORDER1"}, [{"number": "X1", "carrier": "UPS", "status": "CANCELLED"}])[0], [])

    def test_unauthorised_agent_order_attaches_the_mandate_receipt(self):
        view = dispute("UNAUTHORISED")
        evidences, sources = evidence_pack(view, {"id": "ORDER1"}, [], MANDATE)
        self.assertEqual(evidences[0]["evidence_type"], "OTHER"); self.assertIn("ORDER1", evidences[0]["notes"])
        self.assertIn("Mandate receipt", sources[0])

    def test_deadline_states_and_escalation_before_lapse(self):
        for hours, state in ((72, "ok"), (6, "soon"), (-1, "lapsed")):
            self.assertEqual(deadline(dispute("MERCHANDISE_OR_SERVICE_NOT_RECEIVED", due_in_hours=hours), NOW)["state"], state)
        near = dispute("MERCHANDISE_OR_SERVICE_NOT_RECEIVED", due_in_hours=6)
        evidences, _ = evidence_pack(near, {"id": "ORDER1"}, TRACKER)
        self.assertEqual(propose(near, evidences, 500, deadline(near, NOW))[0], "escalate")
        lapsed = dispute("MERCHANDISE_OR_SERVICE_NOT_RECEIVED", due_in_hours=-1)
        self.assertEqual(propose(lapsed, [], 5000, deadline(lapsed, NOW))[0], "escalate")

    def test_refund_only_within_limit_when_there_is_no_evidence(self):
        small, large = dispute("MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "3.00"), dispute("MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "40.00")
        self.assertEqual(propose(small, [], 500, deadline(small, NOW))[0], "accept_and_refund")
        self.assertEqual(propose(large, [], 500, deadline(large, NOW))[0], "escalate")


if __name__ == "__main__":
    unittest.main()
