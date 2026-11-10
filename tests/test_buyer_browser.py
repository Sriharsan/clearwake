"""The Resolution Center driver, tested against a local stand-in page (tests/fixtures/resolution_center, TESTS ONLY).

This proves the driver logic. It does not prove PayPal's real pages: those are validated only by a real run."""
from pathlib import Path
import json
import tempfile
import unittest

from clearwake.buyer_browser import (NeedsHuman, Recorder, ResolutionCenter, StepFailed, detect_block_text, ensure_signed_in, fixture_site,
                                     is_signed_in, manual_steps, open_buyer_log, parse_thread)
from clearwake.buyer import DisputeRule
from verdock_core.receipts import verify_log

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


class ParseTests(unittest.TestCase):
    TEXT = """Dispute PP-R-FIX-0001
Status: Waiting for your response
You asked for USD 9.00
Conversation
You: Only 2 of 3 notebooks arrived.
Seller: We are sorry. We offer a refund of USD 3.00.
The seller offered you a refund of USD 3.00
Accept offer
"""

    def test_reads_status_messages_offer_and_request(self):
        t = parse_thread("PP-R-FIX-0001", self.TEXT, can_accept=True)
        self.assertEqual((t.status, t.offer_minor, t.requested_minor, t.currency), ("Waiting for your response", 300, 900, "USD"))
        self.assertEqual([who for who, _ in t.messages], ["buyer", "seller"])
        self.assertTrue(t.offer_open and not t.resolved)
        self.assertEqual(t.facts(), {"offer_minor": 300, "evidence": False, "replied": True})

    def test_an_offer_without_the_accept_button_is_not_open(self):
        t = parse_thread("X", self.TEXT, can_accept=False)
        self.assertFalse(t.offer_open); self.assertIsNone(t.facts()["offer_minor"]); self.assertTrue(t.facts()["evidence"])

    def test_resolved_and_escalated_and_dollar_amounts(self):
        self.assertTrue(parse_thread("X", "Status: Resolved\n").resolved)
        self.assertTrue(parse_thread("X", "Status: Escalated to a claim\n").escalated)
        self.assertEqual(parse_thread("X", "The merchant offered you a refund of $1,234.50\n").offer_minor, 123450)

    def test_challenge_words_are_detected(self):
        for text in ("Please complete the CAPTCHA", "Confirm you are not a robot", "Enter the code we texted you", "Security challenge"):
            self.assertTrue(detect_block_text(text), text)
        self.assertEqual(detect_block_text("Resolution Center. Your disputes."), "")

    def test_manual_steps_are_exact_and_never_ask_for_a_password_in_code(self):
        steps = manual_steps("login")
        self.assertIn("python scripts/buyer_dispute.py --login", steps[0])
        self.assertTrue(any("by hand" in s for s in steps))


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class DriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.root = Path(self.folder.name)
        self.page = self.browser.new_page()
        self.log = open_buyer_log(self.root / "buyer")
        self.rec = Recorder(self.log, "m" * 64, "fixture", self.root / "shots")

    def tearDown(self):
        self.page.close(); self.folder.cleanup()

    def centre(self, query="", attempts=2):
        site = fixture_site(query=query)
        self.page.goto(site.home_url)
        return ResolutionCenter(self.page, site, self.rec, attempts=attempts, timeout_ms=3000, pause_s=0.05)

    def test_signed_out_stops_with_the_login_command_and_types_nothing(self):
        rc = self.centre("?signedout=1")
        self.assertFalse(is_signed_in(self.page, rc.site))
        with self.assertRaises(NeedsHuman) as caught:
            ensure_signed_in(self.page, rc.site, timeout_s=1)
        self.assertIn("scripts/buyer_dispute.py --login", caught.exception.steps[0])
        self.assertEqual(self.page.locator("#pw").input_value(), "")   # nothing was typed into the password box

    def test_a_session_signed_in_by_hand_is_reused(self):
        rc = self.centre("?signedout=1")
        self.page.get_by_role("button", name="Log in").click()          # what Sri does in the real window
        self.assertTrue(ensure_signed_in(self.page, rc.site, timeout_s=2))

    def test_a_captcha_stops_every_step_and_is_receipted(self):
        rc = self.centre("?captcha=1")
        with self.assertRaises(NeedsHuman) as caught:
            rc.open_dispute("CAP-FIXTURE-1", "item_not_received", "It never came.")
        self.assertIn("never bypasses", str(caught.exception))
        last = json.loads(Path(self.log.path).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((last["action_id"], last["success"]), ("clearwake.buyer.open_dispute.blocked", False))

    def test_all_three_reasons_open_and_are_read_back(self):
        rc = self.centre()
        for reason, label in (("item_not_received", "item_not_received"), ("not_as_described", "not_as_described"), ("missing_items", "missing_items"), ("unauthorised", "unauthorised")):
            with self.subTest(reason=reason):
                opened = rc.open_dispute("CAP-FIXTURE-1", reason, f"Test message for {reason}.", amount="9.00")
                state = self.page.evaluate(f"RC.disputes['{opened['dispute_id']}']")
                self.assertEqual((state["reason"], state["requested"]), (label, "9.00"))
                self.assertEqual(state["messages"][0]["text"], f"Test message for {reason}.")
                self.assertTrue(opened["dispute_id"].startswith("PP-R-FIX-"))

    def test_open_then_read_offer_then_accept(self):
        rc = self.centre()
        did = rc.open_dispute("CAP-FIXTURE-1", "item_not_received", "Never arrived.", amount="3.00")["dispute_id"]
        self.assertFalse(rc.read_thread(did).seller_replied)
        self.page.evaluate("([id]) => RC.merchantSync(id, {messages: ['We offer a refund of USD 3.00.'], offer: {amount: '3.00', currency: 'USD'}, status: 'WAITING_FOR_BUYER_RESPONSE'})", [did])
        thread = rc.read_thread(did)
        self.assertEqual((thread.offer_minor, thread.requested_minor, thread.offer_open), (300, 300, True))
        done = rc.accept_offer(did)
        self.assertTrue(done.resolved)
        self.assertEqual(self.page.evaluate(f"RC.log.map(e => e.type)"), ["opened", "accepted"])

    def test_counter_sends_a_message_and_it_appears_in_the_thread(self):
        rc = self.centre()
        did = rc.open_dispute("CAP-FIXTURE-1", "not_as_described", "Wrong colour.", amount="9.00")["dispute_id"]
        rc.counter(did, "Could you raise the refund to USD 7.20?")
        self.assertIn(("buyer", "Could you raise the refund to USD 7.20?"), rc.read_thread(did).messages)

    def test_escalating_to_the_owner_presses_nothing_and_a_claim_needs_the_rule(self):
        rc = self.centre()
        did = rc.open_dispute("CAP-FIXTURE-1", "item_not_received", "Never arrived.", amount="9.00")["dispute_id"]
        rc.escalate(did, to="owner", why="merchant sent records")
        self.assertEqual(self.page.evaluate(f"RC.disputes['{did}'].status"), "WAITING_FOR_SELLER_RESPONSE")
        with self.assertRaises(PermissionError):
            rc.escalate(did, to="claim", rule=DisputeRule())
        self.assertEqual(self.page.evaluate(f"RC.disputes['{did}'].status"), "WAITING_FOR_SELLER_RESPONSE")
        rc.escalate(did, to="claim", rule=DisputeRule(escalate_to_claim=True))
        self.assertEqual(self.page.evaluate(f"RC.disputes['{did}'].status"), "ESCALATED")

    def test_every_step_writes_a_screenshot_and_a_receipt_linked_to_the_mandate(self):
        rc = self.centre()
        did = rc.open_dispute("CAP-FIXTURE-1", "item_not_received", "Never arrived.")["dispute_id"]
        rc.read_thread(did)
        lines = Path(self.log.path).read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 2)
        for line in lines:
            body = json.loads(line)
            self.assertEqual(body["params"]["mandate_receipt"], "m" * 64)
            self.assertEqual(body["params"]["source"], "fixture")
            self.assertTrue((self.root / "shots" / body["params"]["shot"]).is_file())
        self.assertTrue(verify_log(self.log.path, self.log.public_key)["ok"])

    def test_a_failing_step_is_retried_screenshotted_and_receipted_as_failed(self):
        rc = self.centre()
        with self.assertRaises(StepFailed):
            rc.open_dispute("CAP-NOT-LISTED", "item_not_received", "Never arrived.")
        failed = [json.loads(l) for l in Path(self.log.path).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(failed[-1]["action_id"], "clearwake.buyer.open_dispute.failed")
        self.assertFalse(failed[-1]["success"])
        self.assertGreaterEqual(len(list((self.root / "shots").glob("*failed*.png"))), 2)   # one per try
        self.assertTrue(verify_log(self.log.path, self.log.public_key)["ok"])

    def test_bad_input_is_refused_before_the_browser_moves(self):
        rc = self.centre()
        for args in (("CAP-FIXTURE-1", "something_else", "x"), ("bad id", "item_not_received", "x"), ("CAP-FIXTURE-1", "item_not_received", "  ")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                rc.open_dispute(*args)


if __name__ == "__main__":
    unittest.main()
