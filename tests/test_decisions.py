"""The two spoken decisions on the merchant agent: parsing, each command end to end on the local provider, no blind retry,
no make_offer for case 4, no money for case 9, the source in every receipt, the approval record, receipts that verify offline."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from clearwake.decisions import CASES, COMMAND_4, COMMAND_9, DecisionRunner, mirror_local, movements, normalize, parse_command, sandbox_tracking_number
from clearwake.paypal import GatewayError, LocalGateway, SandboxGateway
from verdock_core.receipts import verify_log

BASE = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
VOICE = {"channel": "voice", "stt": "sarvam-saaras", "owner_voice": "owner-voice-1", "reply_voice": "reply-voice-1", "provider": "sarvam"}
C4, C9 = CASES[4], CASES[9]


class FakeClock:
    """Sleeps move the clock and nothing else: a polling wait of a minute costs no time."""
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds

    def utcnow(self):
        return BASE + timedelta(seconds=self.t)


class Spy:
    """Wraps a gateway and records every call by name, so a test can say which calls never happened."""
    def __init__(self, gateway):
        self.gateway, self.calls = gateway, []

    def __getattr__(self, name):
        value = getattr(self.gateway, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return value(*args, **kwargs)
        return call

    def names(self):
        return [name for name, _, _ in self.calls]

    def count(self, name):
        return self.names().count(name)


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.local = LocalGateway(self.root / "provider.sqlite3")
        self.clock = FakeClock()

    def tearDown(self):
        self.folder.cleanup()

    def runner(self, resolve_after_reads=2, fee_lines=(), outcome="completed"):
        mirror_local(self.local, now=BASE, fee_lines=fee_lines, resolve_after_reads=resolve_after_reads)
        self.local.outcome = outcome
        self.spy = Spy(self.local)
        return DecisionRunner(self.spy, self.root / "log", clock=self.clock)

    def lines(self, runner):
        return [json.loads(line) for line in Path(runner.swarm.receipts.path).read_text(encoding="utf-8").splitlines() if line.strip()]

    def assert_signed(self, runner):
        report = verify_log(runner.swarm.receipts.path, runner.swarm.receipts.public_key)
        self.assertTrue(report["ok"], report)

    def provider_refunds(self):
        with closing(sqlite3.connect(self.local.path)) as db:
            return db.execute("SELECT refund_id FROM records").fetchall()

    def steps(self, result, name):
        return [s for s in result["steps"] if s["step"] == name]


class ParsingTests(unittest.TestCase):
    def test_case_4_variants(self):
        for text in ("Approve case 4", "approve case four", "APPROVE CASE 4.", "Approve case, four!", "okay approve case number 4", "Approve case for",
                     "yes, approve case 4 please", "Approve  case-4"):
            self.assertEqual(parse_command(text)["name"], "approve_case_4", text)

    def test_case_9_variants(self):
        for text in ("Don't pay case 9, send the proof", "dont pay case nine send the proof", "Do not pay case 9. Send the proof.", "don’t pay case 9, send proof",
                     "Do not refund case 9 and submit the evidence", "send the proof for case 9, do not pay", "Don't pay case number 9, send the tracking proof"):
            self.assertEqual(parse_command(text)["name"], "proof_case_9", text)

    def test_everything_else_is_refused_with_a_plain_reason(self):
        for text in ("", "   ", "Approve case 9", "Pay case 9", "Don't pay case 9", "Send the proof", "Approve case 5", "Approve case 40", "Do not approve case 4",
                     "Approve case 4 and case 9", "Reject case 4", "what is the weather", "refund everyone", "case 4"):
            parsed = parse_command(text)
            self.assertIsNone(parsed["name"], text)
            self.assertTrue(parsed["reason"].endswith("Nothing ran.") or "Nothing ran" in parsed["reason"], text)

    def test_normalize_handles_contractions_and_punctuation(self):
        self.assertEqual(normalize("Don’t pay, CASE 9!"), "do not pay case 9")
        self.assertEqual(normalize("dont"), "do not")
        self.assertEqual(normalize("a dot"), "a dot")


class CaseFourTests(Base):
    def test_accept_claim_refund_end_to_end_with_one_write_and_no_offer(self):
        runner = self.runner()
        result = runner.run("Approve case 4", VOICE)
        self.assertTrue(result["ok"], result["stopped_reason"])
        self.assertEqual((result["command"], result["action"], result["case"], result["dispute"]), (COMMAND_4, "accept_claim REFUND", 4, C4["dispute"]))
        self.assertEqual(self.spy.count("accept_claim"), 1)
        self.assertEqual(self.spy.count("make_offer"), 0)            # PayPal does not allow it for this chargeback; never called
        self.assertEqual(self.spy.count("refund"), 0)
        self.assertEqual(self.spy.count("send_message"), 0)
        name, args, kwargs = [c for c in self.spy.calls if c[0] == "accept_claim"][0]
        self.assertEqual((args[0], args[2], args[3]), (C4["dispute"], "5.00", "USD"))
        record = result["paypal_record"]
        self.assertEqual((record["status"], record["stage"], record["outcome"]), ("RESOLVED", "CHARGEBACK", "RESOLVED_BUYER_FAVOUR"))
        self.assertEqual((record["refund_amount"], record["refund_currency"]), ("5.00", "USD"))
        self.assertTrue(record["refund_id"])
        self.assertEqual(record["fees"], [])
        self.assertTrue(any("no accept step" in s["detail"] for s in self.steps(result, "buyer side")))
        self.assertTrue(any("not allowed" in s["detail"] for s in self.steps(result, "read dispute")))
        self.assertEqual(len(self.provider_refunds()), 1)
        self.assert_signed(runner)

    def test_the_readback_comes_first_and_names_the_decision(self):
        runner = self.runner()
        result = runner.run("Approve case 4", VOICE)
        self.assertTrue(result["readback"].startswith("Approve case 4: accept the claim and refund USD 5.00"))
        self.assertIn("No offer is made", result["readback"])
        names = [s["step"] for s in result["steps"]]
        self.assertLess(names.index("read back"), names.index("accept claim"))

    def test_the_owner_approval_is_recorded_above_the_two_dollar_line(self):
        runner = self.runner()
        result = runner.run("Approve case 4", VOICE)
        approval = result["approval"]
        self.assertEqual((approval["approver"], approval["approved_by"], approval["required"]), ("owner", "owner, by voice", True))
        self.assertEqual((approval["level"], approval["limit_minor"], approval["limit"]), ("Execute within Limits", 500, "USD 5.00"))
        self.assertIn("owner approval above USD 2.00", approval["rule"])
        self.assertEqual(approval["source"], VOICE)
        stored = runner.swarm.approvals.get(approval["approval_id"])
        self.assertEqual((stored["status"], stored["approver"], stored["requested_by"], stored["amount_minor"]), ("consumed", "owner", "clearwake-merchant", 500))
        actions = [r["action_id"] for r in result["receipts"]]
        for needed in ("clearwake.approval.requested", "clearwake.approval.granted", "clearwake.approval.used"):
            self.assertIn(needed, actions)

    def test_every_receipt_carries_the_source_and_receipts_verify(self):
        runner = self.runner()
        result = runner.run("Approve case 4", VOICE)
        lines = self.lines(runner)
        self.assertEqual(len(lines), len(result["receipts"]))
        for line in lines:
            self.assertEqual(line["params"]["source"], VOICE, line["action_id"])
            self.assertIn("policy_hash", line["params"])
        for i, row in enumerate(result["receipts"], 1):          # the line number is the receipt's place in the log
            self.assertEqual(row["line"], i)
            self.assertEqual(lines[row["line"] - 1]["action_id"], row["action_id"])
        self.assert_signed(runner)

    def test_a_stable_request_id_and_polling_is_bounded_and_recorded(self):
        runner = self.runner(resolve_after_reads=3)
        result = runner.run("Approve case 4", VOICE)
        self.assertTrue(result["ok"])
        reads = [s for s in result["steps"] if s["step"].startswith("dispute read")]
        self.assertEqual(len(reads), 3)                                    # UNDER_REVIEW, UNDER_REVIEW, RESOLVED
        self.assertEqual(self.clock.sleeps, [2.0, 3.0])                    # sleeps between reads, growing by half
        read_receipts = [r for r in result["receipts"] if r["action_id"] == "clearwake.dispute.read"]
        self.assertEqual(len(read_receipts), 3)
        sent = [l for l in self.lines(runner) if l["action_id"] == "clearwake.dispute.accept_claim_sent"][0]
        request_id = sent["params"]["request_id"]
        self.assertEqual(runner.swarm.invariants.request_id(f"voice:accept_claim:{C4['dispute']}"), request_id)

    def test_polling_stops_at_its_bound_and_never_sends_again(self):
        runner = self.runner(resolve_after_reads=99)
        runner.poll_max_reads, runner.poll_total_wait = 5, 100.0
        result = runner.run("Approve case 4", VOICE)
        self.assertFalse(result["ok"])
        self.assertIn("after 5 reads", result["stopped_reason"])
        self.assertEqual(self.spy.count("accept_claim"), 1)
        self.assertLessEqual(sum(self.clock.sleeps), 100.0)
        self.assertEqual(len([s for s in result["steps"] if s["step"].startswith("dispute read")]), 5)
        again = runner.run("Approve case 4", VOICE)                         # a second command must not write a second time
        self.assertEqual(self.spy.count("accept_claim"), 1)
        self.assertFalse(again["ok"])
        self.assertTrue(any(s["state"] == "skipped" for s in self.steps(again, "accept claim")))
        self.assert_signed(runner)

    def test_the_total_wait_bound_ends_the_reads(self):
        runner = self.runner(resolve_after_reads=99)
        runner.poll_max_reads, runner.poll_total_wait = 50, 5.0
        result = runner.run("Approve case 4", VOICE)
        self.assertFalse(result["ok"])
        self.assertLessEqual(sum(self.clock.sleeps), 5.0)
        self.assertLess(len([s for s in result["steps"] if s["step"].startswith("dispute read")]), 50)

    def test_a_lost_response_is_reconciled_from_the_record_and_never_sent_again(self):
        runner = self.runner(outcome="lost-response")
        result = runner.run("Approve case 4", VOICE)
        self.assertEqual(self.spy.count("accept_claim"), 1)                  # no blind retry
        self.assertTrue(any(s["state"] == "unknown" for s in self.steps(result, "accept claim")))
        self.assertTrue(result["ok"], result["stopped_reason"])              # PayPal's record shows the refund: reconciled by reading
        self.assertEqual(result["paypal_record"]["refund_amount"], "5.00")
        self.assertIn("clearwake.dispute.accept_claim_unknown", [r["action_id"] for r in result["receipts"]])
        self.assertEqual(len(self.provider_refunds()), 1)
        self.assert_signed(runner)

    def test_a_lost_response_with_no_refund_on_record_stays_unknown_and_is_not_resent(self):
        class Silent(LocalGateway):
            def accept_claim(self, *args, **kwargs):
                raise GatewayError("The sandbox response is uncertain. No automatic retry was sent.")
        gateway = Silent(self.root / "silent.sqlite3")
        mirror_local(gateway, now=BASE)
        spy = Spy(gateway)
        runner = DecisionRunner(spy, self.root / "silent-log", clock=self.clock)
        runner.poll_max_reads = 3
        first = runner.run("Approve case 4", VOICE)
        self.assertFalse(first["ok"])
        self.assertEqual(first["paypal_record"]["status"], "UNDER_REVIEW")
        second = runner.run("Approve case 4", VOICE)
        self.assertFalse(second["ok"])
        self.assertEqual(spy.count("accept_claim"), 1)

    def test_the_money_movements_and_a_fee_line_are_recorded_as_paypal_shows_them(self):
        fee = {"party": "SELLER", "amount": {"currency_code": "USD", "value": "0.50"}, "initiated_time": "2026-11-12T00:00:00.000Z", "type": "DEBIT",
               "reason": "DISPUTE_SETTLEMENT_FEE"}
        runner = self.runner(fee_lines=[fee])
        result = runner.run("Approve case 4", VOICE)
        self.assertTrue(result["ok"])
        self.assertEqual(result["paypal_record"]["fees"], [fee])
        self.assertIn("SELLER DEBIT DISPUTE_SETTLEMENT_FEE USD 0.50", result["paypal_record"]["fund_movements"])
        check = [l for l in self.lines(runner) if l["action_id"] == "clearwake.dispute.checked"][-1]
        self.assertEqual(check["params"]["fees"], [fee])
        self.assertEqual(check["params"]["refund_id"], result["paypal_record"]["refund_id"])

    def test_movements_reads_both_record_shapes(self):
        moves = movements({"money_movements": [{"party": "SELLER", "type": "DEBIT", "reason": "CHARGEBACK_FEE", "amount": {"currency_code": "USD", "value": "1.00"}}],
                           "refund_details": {"transactions": [{"id": "R1", "amount": {"currency_code": "USD", "value": "5.00"}}]}})
        self.assertEqual((moves["refund_id"], moves["refund_amount"], len(moves["fees"])), ("R1", "5.00", 1))

    def test_a_refund_that_does_not_match_the_approved_amount_is_a_mismatch(self):
        runner = self.runner()
        db = sqlite3.connect(self.local.path)
        body = json.loads(db.execute("SELECT body FROM disputes WHERE id=?", (C4["dispute"],)).fetchone()[0])
        body["_resolve_after_reads"] = 1
        db.execute("UPDATE disputes SET body=? WHERE id=?", (json.dumps(body), C4["dispute"]))
        db.commit(); db.close()
        original = self.local._accept_claim_as_recorded

        def short(body, value, currency, request_id, claim_type):
            return original(body, "4.00", currency, request_id, claim_type)
        self.local._accept_claim_as_recorded = short
        result = runner.run("Approve case 4", VOICE)
        self.assertFalse(result["ok"])
        self.assertEqual(result["paypal_record"]["state"], "MISMATCH")

    def test_hard_cap_policy_and_the_dispute_state_are_checked_before_any_write(self):
        runner = self.runner()
        db = sqlite3.connect(self.local.path)
        body = json.loads(db.execute("SELECT body FROM disputes WHERE id=?", (C4["dispute"],)).fetchone()[0])
        body["dispute_amount"] = {"currency_code": "USD", "value": "6.00"}
        db.execute("UPDATE disputes SET body=? WHERE id=?", (json.dumps(body), C4["dispute"]))
        db.commit(); db.close()
        result = runner.run("Approve case 4", VOICE)
        self.assertFalse(result["ok"])
        self.assertIn("hard cap", result["stopped_reason"])
        self.assertEqual(self.spy.count("accept_claim"), 0)

    def test_when_paypal_lists_no_accept_claim_refund_nothing_is_sent(self):
        runner = self.runner()
        db = sqlite3.connect(self.local.path)
        body = json.loads(db.execute("SELECT body FROM disputes WHERE id=?", (C4["dispute"],)).fetchone()[0])
        body["allowed_response_options"] = {}
        db.execute("UPDATE disputes SET body=? WHERE id=?", (json.dumps(body), C4["dispute"]))
        db.commit(); db.close()
        result = runner.run("Approve case 4", VOICE)
        self.assertFalse(result["ok"])
        self.assertEqual(self.spy.count("accept_claim"), 0)
        self.assertIn("does not list accept_claim REFUND", result["stopped_reason"])

    def test_the_local_provider_refuses_make_offer_on_the_chargeback_as_paypal_does(self):
        runner = self.runner()
        from clearwake.paypal import ProviderRefused
        with self.assertRaises(ProviderRefused):
            self.local.make_offer(C4["dispute"], "x", "5.00", "USD", "11111111-1111-4111-8111-111111111111")


class CaseNineTests(Base):
    def test_no_money_moves_tracking_then_proof_then_read_back(self):
        runner = self.runner()
        result = runner.run("Don't pay case 9, send the proof", VOICE)
        self.assertTrue(result["ok"], result["stopped_reason"])
        self.assertEqual((result["command"], result["case"], result["dispute"]), (COMMAND_9, 9, C9["dispute"]))
        for forbidden in ("refund", "make_offer", "accept_claim", "send_message", "adjudicate"):
            self.assertEqual(self.spy.count(forbidden), 0, forbidden)
        self.assertEqual(self.provider_refunds(), [])
        self.assertEqual(self.spy.count("add_tracking"), 1)
        self.assertEqual(self.spy.count("provide_evidence"), 1)
        self.assertLess(self.spy.names().index("add_tracking"), self.spy.names().index("provide_evidence"))
        record = result["paypal_record"]
        self.assertTrue(record["evidence_received"])
        self.assertFalse(record["money_moved"])
        self.assertEqual((record["stage"], record["outcome"]), ("INQUIRY", ""))
        self.assertEqual(record["tracking_number"], sandbox_tracking_number(C9["order"], 9))
        dispute = self.local.dispute(C9["dispute"])
        self.assertNotIn("dispute_outcome", dispute)
        self.assertEqual(dispute["fund_movements"][0]["reason"], "HOLD_PLACED")
        order = self.local.order(C9["order"])
        self.assertEqual([t["id"] for t in order["purchase_units"][0]["shipping"]["trackers"]], [f"{C9['capture']}-SYNTH1Z94554W09"])
        sent = [c for c in self.spy.calls if c[0] == "provide_evidence"][0][1][1][0]
        self.assertEqual(sent["evidence_type"], "PROOF_OF_FULFILLMENT")
        self.assertEqual(sent["evidence_info"]["tracking_info"], [{"carrier_name": "UPS", "tracking_number": "SYNTH1Z94554W09"}])
        self.assertIn("sandbox test tracking value", sent["notes"])
        self.assert_signed(runner)

    def test_refund_and_offer_are_refused_by_policy_and_receipted(self):
        runner = self.runner()
        result = runner.run("Do not pay case nine, send the proof", VOICE)
        refused = [l for l in self.lines(runner) if l["action_id"] == "clearwake.policy.refused"]
        self.assertEqual({l["params"]["operation"] for l in refused}, {"refund", "make_offer", "accept_claim"})
        for line in refused:
            self.assertFalse(line["params"]["called"])
            self.assertFalse(line["success"])
        by_op = {l["params"]["operation"]: l["params"] for l in refused}
        self.assertEqual(by_op["refund"]["level"], "Draft")
        self.assertEqual(by_op["make_offer"]["level"], "Draft")
        self.assertTrue(result["ok"])

    def test_the_test_tracking_value_is_labelled_in_the_receipt(self):
        runner = self.runner()
        runner.run("Don't pay case 9, send the proof", VOICE)
        added = [l for l in self.lines(runner) if l["action_id"] == "clearwake.merchant.tracking_added"][0]["params"]
        self.assertEqual((added["tracking_number"], added["carrier"]), ("SYNTH1Z94554W09", "UPS"))
        self.assertEqual(added["label"], "sandbox test tracking value, not a real parcel")
        self.assertEqual(added["order"], C9["order"])

    def test_every_receipt_carries_the_source(self):
        runner = self.runner()
        typed = {"channel": "typed", "stt": None, "owner_voice": None, "reply_voice": None, "provider": None}
        result = runner.run("Don't pay case 9, send the proof", typed)
        lines = self.lines(runner)
        self.assertEqual(len(lines), len(result["receipts"]))
        self.assertTrue(all(l["params"]["source"] == typed for l in lines))
        self.assertEqual(result["approval"]["approved_by"], "owner, typed")

    def test_the_approval_is_recorded_with_no_money_limit(self):
        runner = self.runner()
        result = runner.run("Don't pay case 9, send the proof", VOICE)
        approval = result["approval"]
        self.assertEqual((approval["approver"], approval["approved_by"], approval["required"], approval["limit_minor"]), ("owner", "owner, by voice", False, 0))
        self.assertEqual(approval["source"], VOICE)
        self.assertIn("refund, make_offer and accept_claim refused", approval["rule"])

    def test_a_second_command_adds_nothing_twice(self):
        runner = self.runner()
        runner.run("Don't pay case 9, send the proof", VOICE)
        again = runner.run("Don't pay case 9, send the proof", VOICE)
        self.assertTrue(again["ok"], again["stopped_reason"])
        self.assertEqual(self.spy.count("add_tracking"), 1)
        self.assertEqual(self.spy.count("provide_evidence"), 1)
        self.assertEqual(len(self.local.dispute(C9["dispute"])["evidences"]), 3)

    def test_a_lost_answer_is_read_not_resent(self):
        runner = self.runner(outcome="lost-response")
        result = runner.run("Don't pay case 9, send the proof", VOICE)
        self.assertEqual(self.spy.count("add_tracking"), 1)
        self.assertEqual(self.spy.count("provide_evidence"), 1)
        self.assertTrue(result["ok"], result["stopped_reason"])      # both writes landed; the records show them
        self.assertIn("clearwake.dispute.evidence_unknown", [r["action_id"] for r in result["receipts"]])

    def test_a_lapsed_deadline_stops_before_any_write(self):
        runner = self.runner()
        self.clock.t = 60 * 24 * 3600
        result = runner.run("Don't pay case 9, send the proof", VOICE)
        self.assertFalse(result["ok"])
        self.assertIn("has passed", result["stopped_reason"])
        self.assertEqual(self.spy.count("add_tracking"), 0)

    def test_the_real_batch_tracking_number_format(self):
        self.assertEqual(sandbox_tracking_number(C4["order"], 4), "SYNTH1Z23114Y04")


class RefusalTests(Base):
    def test_an_unknown_command_runs_nothing(self):
        runner = self.runner()
        for text in ("Approve case 9", "Pay case 9", "Refund everything", "", "Approve case 5"):
            result = runner.run(text, VOICE)
            self.assertFalse(result["ok"], text)
            self.assertEqual(result["action"], "none")
            self.assertTrue(result["stopped_reason"].endswith("Nothing ran."), text)
        self.assertEqual(self.spy.calls, [])                      # no PayPal call at all, not even a read
        self.assertEqual(self.provider_refunds(), [])
        refused = [l for l in self.lines(runner) if l["action_id"] == "clearwake.voice.command_refused"]
        self.assertEqual(len(refused), 5)
        self.assertTrue(all(l["params"]["source"] == VOICE and l["params"]["pay_pal_calls"] == 0 for l in refused))
        self.assert_signed(runner)

    def test_a_source_that_is_neither_voice_nor_typed_is_refused(self):
        runner = self.runner()
        result = runner.run("Approve case 4", {"channel": "web"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.spy.calls, [])
        self.assertEqual(result["receipts"], [])

    def test_floats_and_odd_source_values_cannot_break_the_receipts(self):
        runner = self.runner()
        result = runner.run("Approve case 4", {"channel": "voice", "stt": 1.5, "owner_voice": ["a"], "reply_voice": None, "provider": "x"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.lines(runner)[0]["params"]["source"]["stt"], "1.5")
        self.assert_signed(runner)


class SandboxShapeTests(unittest.TestCase):
    """The same command through SandboxGateway with its network call replaced: the routes used, one write, one stable request id."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.requests, self.reads = [], 0
        record = {"dispute_id": C4["dispute"], "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "status": "UNDER_REVIEW", "dispute_life_cycle_stage": "CHARGEBACK",
                  "dispute_amount": {"currency_code": "USD", "value": "5.00"},
                  "disputed_transactions": [{"seller_transaction_id": C4["capture"], "gross_amount": {"currency_code": "USD", "value": "9.00"}}],
                  "fund_movements": [{"party": "SELLER", "type": "DEBIT", "reason": "HOLD_PLACED", "amount": {"currency_code": "USD", "value": "5.00"}}],
                  "allowed_response_options": {"accept_claim": {"accept_claim_types": ["REFUND"]}}}
        self.record, self.accepted = record, False
        self.clock = FakeClock()

    def tearDown(self):
        self.folder.cleanup()

    def send(self, request, timeout):
        path, method = request.full_url.split("api-m.sandbox.paypal.com")[1], request.get_method()
        self.requests.append((method, path, request.headers.get("Paypal-request-id")))
        if path == "/v1/oauth2/token":
            return {"access_token": "token", "token_type": "Bearer", "expires_in": 3000}
        if path == f"/v1/customer/disputes/{C4['dispute']}/accept-claim":
            self.accepted = True
            return {}
        if path == f"/v1/customer/disputes/{C4['dispute']}":
            if self.accepted:
                self.reads += 1
            if self.accepted and self.reads >= 2:
                return {**self.record, "status": "RESOLVED", "dispute_outcome": {"outcome_code": "RESOLVED_BUYER_FAVOUR"},
                        "refund_details": {"transactions": [{"id": "RF1", "amount": {"currency_code": "USD", "value": "5.00"}}]},
                        "fund_movements": [{"party": "BUYER", "type": "CREDIT", "reason": "DISPUTE_SETTLEMENT", "amount": {"currency_code": "USD", "value": "5.00"}}]}
            return self.record
        if path == f"/v2/checkout/orders/{C4['order']}":
            return {"id": C4["order"], "purchase_units": [{"payments": {"captures": [{"id": C4["capture"]}]}, "shipping": {"trackers": [{"id": C4["capture"] + "-SYNTH1Z23114Y04", "status": "SHIPPED"}]}}]}
        if path == "/v2/payments/refunds/RF1":
            return {"id": "RF1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "5.00"}}
        raise AssertionError(path)

    def test_case_four_through_the_sandbox_gateway(self):
        gateway = SandboxGateway("id", "secret", send=self.send)
        runner = DecisionRunner(gateway, self.folder.name, clock=self.clock)
        result = runner.run("Approve case 4", VOICE)
        self.assertTrue(result["ok"], result["stopped_reason"])
        writes = [r for r in self.requests if r[0] == "POST" and r[1] != "/v1/oauth2/token"]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0][1].endswith("/accept-claim"))
        self.assertEqual(writes[0][2], runner.swarm.invariants.request_id(f"voice:accept_claim:{C4['dispute']}"))
        self.assertFalse(any("make-offer" in path for _, path, _ in self.requests))
        self.assertEqual(result["paypal_record"]["refund_id"], "RF1")
        self.assertEqual(result["paypal_record"]["refund_record"]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()


def test_rules_parser_reads_speech_to_text_amounts():
    """Speech to text writes '5 US dollars'; the rules parser reads it as USD 5.00."""
    from clearwake import rules_nl
    got = rules_nl.parse_merchant("Refund anything under 5 US dollars that has not arrived in 10 days. Ask me above that. Never refund twice.")
    assert got["refund_limit"] == 500 and not got["question"]
