"""Settling in conversation before escalation, the per dispute policy decision, and the network cut (offline hold)."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from urllib.error import URLError
from urllib.request import Request

from clearwake import paypal
from clearwake.models import Adapter
from clearwake.paypal import NetworkSwitch, Offline, RehearsalGateway
from clearwake.swarm import Case, MerchantSwarm
from verdock_core.outcome import MISMATCH, PENDING, VERIFIED
from verdock_core.queue import HELD
from verdock_core.receipts import verify_log

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
TRACKERS = [{"number": "SYNTH1Z999AA10123456", "carrier": "UPS", "status": "SHIPPED"}]
NOT_RECEIVED, NOT_AS_DESCRIBED = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"


def due(hours):
    return (NOW + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def model_says(action):
    return Adapter("ollama", "test-model", send=lambda u, p, h: {"choices": [{"message": {"content": json.dumps({"action": action})}}]})


class SettleTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.root = Path(self.folder.name)
        self.gateway = RehearsalGateway(self.root / "provider.sqlite3")
        self.swarm = MerchantSwarm(self.gateway, self.root / "merchant", Adapter("scripted"), clock=lambda: NOW)

    def tearDown(self):
        self.folder.cleanup()

    def refunds_at_provider(self):
        with closing(sqlite3.connect(self.gateway.path)) as db:
            return [row[0] for row in db.execute("SELECT refund_id FROM records")]

    def inquiry(self, capture, reason=NOT_AS_DESCRIBED, value="2.50", hours=240, message="The colour is wrong."):
        return self.gateway.open_dispute(capture, reason, value, due(hours), message, stage="INQUIRY")["dispute_id"]

    def test_n_settled_in_conversation_only_when_paypal_shows_it_resolved_as_an_inquiry(self):
        d = self.inquiry("CAP-N1")
        sent = self.swarm.handle_dispute(d, 2000, "buyer-n1")
        self.assertEqual((sent.action, sent.state), ("settle_by_offer", PENDING))  # offer made, buyer has not answered
        record = self.gateway.dispute(d)
        self.assertEqual(record["offer"]["seller_offered_amount"]["value"], "2.50")
        self.assertEqual([m["posted_by"] for m in record["messages"]], ["BUYER", "SELLER"])
        self.assertEqual(self.refunds_at_provider(), [])  # no money until the buyer accepts
        self.gateway.buyer_accepts_offer(d)
        settled = self.swarm.handle_dispute(d, 2000, "buyer-n1")
        self.assertEqual(settled.state, VERIFIED); self.assertIn("Settled, no fee", settled.detail)
        self.assertEqual(len(self.refunds_at_provider()), 1)
        self.assertEqual(len(self.refunds_at_provider()), len(set(self.refunds_at_provider())))
        self.assertTrue(verify_log(self.swarm.receipts.path, self.swarm.receipts.public_key)["ok"])

    def test_an_escalated_case_is_never_counted_as_settled(self):
        d = self.inquiry("CAP-N2")
        self.swarm.handle_dispute(d, 2000, "buyer-n2")
        self.gateway.buyer_escalates(d)
        result = self.swarm.settlement(d)
        self.assertEqual(result.state, MISMATCH); self.assertIn("became a claim", result.detail)

    def test_above_the_offer_limit_a_partial_offer_needs_the_owner(self):
        d = self.inquiry("CAP-N3", value="9.00")
        held = self.swarm.handle_dispute(d, 2000, "buyer-n3")
        self.assertEqual((held.state, held.proposal["offer"]), ("awaiting approval", "5.00"))
        self.assertNotIn("offer", self.gateway.dispute(d))
        self.swarm.approvals.approve(held.approval_id, "Sri")
        sent = self.swarm.handle_dispute(d, 2000, "buyer-n3", approval_id=held.approval_id)
        self.assertEqual(sent.state, PENDING)
        self.assertEqual(self.gateway.dispute(d)["offer"]["seller_offered_amount"]["value"], "5.00")

    def test_records_that_answer_the_reason_are_sent_as_a_message_not_an_offer(self):
        d = self.inquiry("CAP-N4", reason=NOT_RECEIVED, value="9.00", message="Never arrived.")
        result = self.swarm.handle_dispute(d, 2000, "buyer-n4", {"id": "ORDER-N4"}, TRACKERS)
        self.assertEqual((result.action, result.state), ("fight_with_evidence", VERIFIED))
        self.assertIn("SYNTH1Z999AA10123456", self.gateway.dispute(d)["messages"][-1]["content"])
        self.assertNotIn("offer", self.gateway.dispute(d))

    def test_the_policy_decides_and_the_model_proposal_is_only_shown(self):
        swarm = MerchantSwarm(self.gateway, self.root / "model", model_says("refund_within_limit"), clock=lambda: NOW)
        d = self.inquiry("CAP-N5")
        result = swarm.handle_dispute(d, 2000, "buyer-n5")
        self.assertEqual((result.proposal["proposed"], result.proposal["decided"], result.action), ("refund_within_limit", "settle_by_offer", "settle_by_offer"))
        greedy = MerchantSwarm(self.gateway, self.root / "greedy", model_says("settle_by_offer"), clock=lambda: NOW)
        near = self.inquiry("CAP-N6", hours=5)
        self.assertEqual(greedy.handle_dispute(near, 2000, "buyer-n6").state, "awaiting approval")  # deadline close: the owner decides
        self.assertNotIn("offer", self.gateway.dispute(near))

    def test_an_unauthorised_inquiry_without_a_mandate_goes_to_the_owner(self):
        d = self.inquiry("CAP-N7", reason="UNAUTHORISED")
        self.assertEqual(self.swarm.handle_dispute(d, 2000, "buyer-n7").state, "awaiting approval")


class OfferOrderTests(SettleTests):
    """Seen on the real sandbox: a seller message moves the case to waiting for the buyer, and an offer is refused after it."""

    def test_an_offer_after_a_seller_message_is_refused_the_way_paypal_refuses_it(self):
        from clearwake.paypal import ProviderRefused
        d = self.inquiry("CAP-N8")
        self.gateway.send_message(d, "Hello.", "12345678-1234-4234-8234-123456789abc")
        self.assertEqual(self.gateway.dispute(d)["status"], "WAITING_FOR_BUYER_RESPONSE")
        with self.assertRaisesRegex(ProviderRefused, "ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE"):
            self.gateway.make_offer(d, "Offer.", "2.50", "USD", "22345678-1234-4234-8234-123456789abc")

    def test_the_swarm_sends_the_offer_alone_and_its_note_is_the_only_seller_message(self):
        d = self.inquiry("CAP-N9")
        result = self.swarm.handle_dispute(d, 2000, "buyer-n9")
        self.assertEqual((result.proposal["decided"], result.state), ("settle_by_offer", PENDING))
        record = self.gateway.dispute(d)
        self.assertEqual([m["posted_by"] for m in record["messages"]], ["BUYER", "SELLER"])
        self.assertIn("2.50 USD", record["messages"][1]["content"]); self.assertEqual(record["offer"]["seller_offered_amount"]["value"], "2.50")

    def test_a_refused_offer_is_receipted_and_never_described_as_applied_and_it_frees_the_reservation(self):
        from clearwake.paypal import ProviderRefused
        d = self.inquiry("CAP-N10")
        real = self.gateway.make_offer
        self.gateway.make_offer = lambda *a: (_ for _ in ()).throw(ProviderRefused("PayPal refused it (422 ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE)."))
        result = self.swarm.handle_dispute(d, 2000, "buyer-n10")
        self.assertEqual(result.state, "refused by PayPal"); self.assertIn("was not applied", result.detail)
        lines = [json.loads(l) for l in Path(self.swarm.receipts.path).read_text(encoding="utf-8").splitlines()]
        refused = [l for l in lines if l["action_id"] == "clearwake.dispute.refused_by_paypal"][0]
        self.assertEqual((refused["params"]["action"], refused["success"]), ("make_offer", False))
        self.assertEqual([m["posted_by"] for m in self.gateway.dispute(d)["messages"]], ["BUYER"])   # nothing reached the buyer
        self.gateway.make_offer = real
        self.assertEqual(self.swarm.handle_dispute(d, 2000, "buyer-n10").state, PENDING)             # a later try is not blocked


class NetworkCutTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); root = Path(self.folder.name)
        self.provider = RehearsalGateway(root / "provider.sqlite3")
        self.network = NetworkSwitch(self.provider)
        self.swarm = MerchantSwarm(self.network, root / "merchant", Adapter("scripted"), clock=lambda: NOW)

    def tearDown(self):
        self.folder.cleanup()

    def refunds(self):
        with closing(sqlite3.connect(self.provider.path)) as db:
            return [row[0] for row in db.execute("SELECT refund_id FROM records")]

    def test_m_network_cut_mid_batch_holds_money_then_reconciles_first_and_never_duplicates(self):
        first = self.swarm.handle(Case("m1", "buyer complaint", "O", "CAP-M", 1800, "buyer-m1", 150, "NOT_AS_DESCRIBED"))
        self.assertEqual(first.state, VERIFIED)
        inquiry = self.provider.open_dispute("CAP-M2", NOT_AS_DESCRIBED, "2.50", due(240), "Wrong size.", stage="INQUIRY")["dispute_id"]
        self.network.cut = True                                                       # cable pulled mid batch
        refund = self.swarm.handle(Case("m2", "buyer complaint", "O", "CAP-M", 1800, "buyer-m2", 150, "NOT_AS_DESCRIBED"))
        offer = self.swarm.handle_dispute(inquiry, 2000, "buyer-m3")
        self.assertEqual((refund.state, offer.state), (HELD, HELD))
        self.assertEqual(len(self.refunds()), 1)                                       # nothing moved while offline
        self.assertNotIn("offer", self.provider.dispute(inquiry))
        self.assertEqual([r.state for r in self.swarm.resume_offline()], [HELD, HELD])  # still offline: still held
        self.network.cut = False                                                      # reconnect
        resumed = self.swarm.resume_offline()
        self.assertEqual([r.state for r in resumed], [VERIFIED, PENDING])
        self.assertEqual(len(self.refunds()), 2); self.assertEqual(self.swarm.queue.held(), [])
        self.assertEqual(self.swarm.resume_offline(), [])                               # a second resume sends nothing
        self.assertEqual(self.swarm.handle(Case("m2", "buyer complaint", "O", "CAP-M", 1800, "buyer-m2", 150, "NOT_AS_DESCRIBED")).state, VERIFIED)
        self.assertEqual(len(self.refunds()), 2)                                       # no duplicate after reconnect
        actions = [json.loads(line)["action_id"] for line in Path(self.swarm.receipts.path).read_text(encoding="utf-8").splitlines()]
        held_at = [i for i, a in enumerate(actions) if a == "clearwake.offline.held"]
        reconciled_at = [i for i, a in enumerate(actions) if a == "clearwake.offline.reconciled"]
        checked_after = [i for i, a in enumerate(actions) if a == "clearwake.refund.checked" and i > held_at[0]]
        self.assertEqual(len(held_at), 2); self.assertLess(reconciled_at[0], checked_after[0])  # PayPal read before anything resumed

    def test_nothing_shows_as_verified_while_offline(self):
        self.network.cut = True
        self.assertEqual(self.swarm.settlement("PP-D-REH-ANY").state, HELD)


class TransportTests(unittest.TestCase):
    def test_failures_before_the_request_leaves_are_offline_not_unknown(self):
        for reason in (ConnectionRefusedError(), socket.gaierror(), OSError("Tunnel connection failed: 403 Forbidden")):
            self.assertTrue(paypal.never_left(URLError(reason)))
        for error in (TimeoutError(), URLError(TimeoutError()), ConnectionResetError()):
            self.assertFalse(paypal.never_left(error))

    def test_egress_setting_is_one_host_and_port_and_ambient_proxies_are_ignored(self):
        import os
        saved = os.environ.get("CLEARWAKE_EGRESS")
        try:
            os.environ["CLEARWAKE_EGRESS"] = "egress:8080"
            self.assertEqual(paypal.egress_proxy(), {"https": "http://egress:8080"})
            os.environ["CLEARWAKE_EGRESS"] = "http://evil.example/"
            with self.assertRaises(paypal.GatewayError):
                paypal.egress_proxy()
            del os.environ["CLEARWAKE_EGRESS"]
            self.assertEqual(paypal.egress_proxy(), {})
        finally:
            if saved is not None:
                os.environ["CLEARWAKE_EGRESS"] = saved

    def test_settle_routes_are_allowed_and_buyer_routes_are_not(self):
        base = "https://api-m.sandbox.paypal.com/v1/customer/disputes/PP-D-1/"
        refused = []
        def fake_open(*args, **kwargs):
            raise ConnectionRefusedError()
        import urllib.request
        original = urllib.request.OpenerDirector.open
        urllib.request.OpenerDirector.open = lambda self, *a, **k: fake_open()
        try:
            for route in ("send-message", "make-offer"):
                with self.assertRaises((Offline, paypal.GatewayError)):
                    paypal.transport(Request(base + route, data=b"{}", method="POST"))
            for route in ("accept-offer", "escalate", "deny-offer"):
                try:
                    paypal.transport(Request(base + route, data=b"{}", method="POST"))
                except paypal.GatewayError as error:
                    refused.append(str(error))
        finally:
            urllib.request.OpenerDirector.open = original
        self.assertEqual(refused, ["Only reviewed PayPal sandbox routes are allowed."] * 3)


if __name__ == "__main__":
    unittest.main()
