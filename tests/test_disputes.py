"""PayPal dispute path (rehearsal provider shaped like the Disputes API): evidence, deadlines, policy, Checker."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest

from clearwake.buyer import Mandate, load_catalog, mandate_receipt
from clearwake.models import Adapter
from clearwake.paypal import RehearsalGateway
from clearwake.swarm import MerchantSwarm
from verdock_core.outcome import VERIFIED
from verdock_core.receipts import ReceiptLog, create_seed, load_seed, verify_log

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
TRACKERS = [{"number": "SYNTH1Z999AA10123456", "carrier": "UPS", "status": "SHIPPED"}]


def due(hours):
    return (NOW + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


class DisputeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.root = Path(self.folder.name)
        self.gateway = RehearsalGateway(self.root / "provider.sqlite3")
        self.swarm = MerchantSwarm(self.gateway, self.root / "merchant", Adapter("scripted"), clock=lambda: NOW)

    def tearDown(self):
        self.folder.cleanup()

    def test_i_item_not_received_submits_tracking_before_the_deadline(self):
        d = self.gateway.open_dispute("CAP-1", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "9.00", due(72), "Never arrived.")
        result = self.swarm.handle_dispute(d["dispute_id"], 900, "buyer-1", {"id": "ORDER-1"}, TRACKERS)
        self.assertEqual((result.action, result.state), ("provide_evidence", VERIFIED))
        sent = self.gateway.dispute(d["dispute_id"])["evidences"][0]
        self.assertEqual(sent["evidence_info"]["tracking_info"][0]["tracking_number"], "SYNTH1Z999AA10123456")

    def test_j_agent_order_disputed_as_unauthorised_attaches_the_mandate_receipt(self):
        seed = self.root / "buyer.seed"; create_seed(str(seed))
        buyer_log = ReceiptLog(str(self.root / "buyer.ndjson"), load_seed(str(seed)))
        _, _, products = load_catalog()
        mandate = Mandate("Synthetic shopper", 10200, 10200, ("clearwake-demo-store",), ("stationery",))
        receipt = mandate_receipt(buyer_log, mandate, products["notebook-a5"], "clearwake-demo-store", "ORDER-2")
        d = self.gateway.open_dispute("CAP-2", "UNAUTHORISED", "9.00", due(72), "I did not buy this.")
        result = self.swarm.handle_dispute(d["dispute_id"], 900, "buyer-2", {"id": "ORDER-2"}, [], receipt)
        self.assertEqual((result.action, result.state), ("provide_evidence", VERIFIED))
        notes = self.gateway.dispute(d["dispute_id"])["evidences"][0]["notes"]
        self.assertIn(receipt["digest"][:16], notes)
        self.assertTrue(verify_log(buyer_log.path, buyer_log.public_key)["ok"])

    def test_k_dispute_close_to_its_deadline_goes_to_the_inbox_with_the_countdown(self):
        d = self.gateway.open_dispute("CAP-3", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "9.00", due(5))
        result = self.swarm.handle_dispute(d["dispute_id"], 900, "buyer-3", {"id": "ORDER-3"}, TRACKERS)
        self.assertEqual(result.state, "awaiting approval"); self.assertEqual(result.proposal["deadline"]["state"], "soon")
        self.assertLess(result.proposal["deadline"]["seconds_left"], 6 * 3600)
        self.assertEqual(self.gateway.dispute(d["dispute_id"])["status"], "WAITING_FOR_SELLER_RESPONSE")  # nothing sent

    def test_small_claim_without_evidence_is_accepted_and_refunded_then_checked(self):
        d = self.gateway.open_dispute("CAP-4", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "1.50", due(72))
        result = self.swarm.handle_dispute(d["dispute_id"], 900, "buyer-4")
        self.assertEqual((result.action, result.state), ("accept_and_refund", VERIFIED))
        self.assertEqual(self.gateway.dispute(d["dispute_id"])["status"], "RESOLVED")

    def test_open_inquiry_is_answered_and_a_paypal_refusal_is_not_unknown(self):
        from clearwake.paypal import ProviderRefused
        d = self.gateway.open_dispute("CAP-6", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "5.00", due(72))
        self.gateway._update_dispute(d["dispute_id"], status="OPEN")  # real sandbox inquiries start OPEN
        refusing = self.gateway.provide_evidence
        self.gateway.provide_evidence = lambda *a: (_ for _ in ()).throw(ProviderRefused("PayPal refused it (422 UNPROCESSABLE_ENTITY X)."))
        refused = self.swarm.handle_dispute(d["dispute_id"], 2000, "buyer-6", {"id": "ORDER-6"}, TRACKERS)
        self.assertEqual(refused.state, "refused by PayPal"); self.assertIn("Nothing was applied", refused.detail)
        self.gateway.provide_evidence = refusing
        sent = self.swarm.handle_dispute(d["dispute_id"], 2000, "buyer-6", {"id": "ORDER-6"}, TRACKERS)
        self.assertEqual((sent.action, sent.state), ("provide_evidence", VERIFIED))

    def test_sandbox_helpers_pass_paypal_refusals_through_unchanged(self):
        from clearwake.paypal import ProviderRefused, SandboxGateway
        def send(request, timeout):
            if request.full_url.endswith("/token"): return {"access_token": "synthetic-token", "token_type": "Bearer", "expires_in": 3600}
            raise ProviderRefused("PayPal refused it (422 UNPROCESSABLE_ENTITY NOT_ALLOWED).")
        gateway = SandboxGateway("synthetic-client", "synthetic-secret", send=send)
        with self.assertRaises(ProviderRefused):
            gateway.provide_evidence("PP-D-1", [], "12345678-1234-4234-8234-123456789abc")
        with self.assertRaises(ProviderRefused):
            gateway.dispute("PP-D-1")

    def test_a_model_cannot_send_evidence_the_records_do_not_hold(self):
        liar = Adapter("ollama", "test-model", send=lambda u, p, h: {"choices": [{"message": {"content": json.dumps({"action": "provide_evidence"})}}]})
        swarm = MerchantSwarm(self.gateway, self.root / "liar", liar, clock=lambda: NOW)
        d = self.gateway.open_dispute("CAP-5", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "9.00", due(72))
        self.assertEqual(swarm.handle_dispute(d["dispute_id"], 900, "buyer-5", {"id": "ORDER-5"}, []).state, "awaiting approval")

    def test_l_batch_of_ten_disputes_in_parallel_is_counted_honestly(self):
        reasons = ["MERCHANDISE_OR_SERVICE_NOT_RECEIVED"] * 4 + ["MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"] * 4 + ["UNAUTHORISED"] * 2
        ids = [self.gateway.open_dispute(f"CAP-B{i}", r, "1.50" if "DESCRIBED" in r else "9.00", due(72))["dispute_id"] for i, r in enumerate(reasons)]
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda pair: self.swarm.handle_dispute(pair[1], 900, f"buyer-b{pair[0]}", {"id": f"ORDER-B{pair[0]}"},
                                                                           TRACKERS if "RECEIVED" in reasons[pair[0]] else []), enumerate(ids)))
        elapsed = time.perf_counter() - started
        counts = {key: sum(1 for r in results if (r.action, r.state) == key) for key in
                  {("provide_evidence", VERIFIED), ("accept_and_refund", VERIFIED), ("escalate", "awaiting approval")}}
        self.assertEqual(counts[("provide_evidence", VERIFIED)], 4)
        self.assertEqual(counts[("accept_and_refund", VERIFIED)], 4)
        self.assertEqual(counts[("escalate", "awaiting approval")], 2)
        self.assertLess(elapsed, 30)
        self.assertTrue(verify_log(self.swarm.receipts.path, self.swarm.receipts.public_key)["ok"])


if __name__ == "__main__":
    unittest.main()
