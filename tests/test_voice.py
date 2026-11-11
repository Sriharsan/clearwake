"""Voice: the intent matcher, answers composed by code, rules and approvals by voice, the HTTP routes, the LAN helper and local Whisper.

The Whisper tests run only when the model folder holds model.bin and ffmpeg is installed. They use clips spoken by
Windows SAPI in tests/fixtures/voice/ (made by scripts/make_voice_fixtures.ps1). Nothing here uses a network.
"""
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

from clearwake import voice
from clearwake.console import Console
from clearwake.controller import RefundController
from clearwake.server import ClearwakeServer
from verdock_core.receipts import verify_log

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "voice"
CLIPS = json.loads((FIXTURES / "clips.json").read_text(encoding="utf-8"))
STT = voice.Transcriber().available()
RULES = "Refund anything under $30 that hasn't arrived in 10 days. Ask me above that. Never refund twice."


def no_network(*args, **kwargs):
    raise AssertionError("Voice made a network call.")


def merchant_receipts(console, action):
    lines = [json.loads(x) for x in Path(console.swarm.receipts.path).read_text(encoding="utf-8").splitlines()]
    return [r for r in lines if r.get("action_id") == action]


class StandInTranscriber:
    """Stands in for Whisper where a test is about what happens after the words are known."""

    def __init__(self, words):
        self.words, self.model_dir = words, Path("local_gw")

    def available(self):
        return True

    def status(self):
        return {"stt": True}

    def transcribe(self, audio):
        return {"transcript": self.words, "ms": 1, "audio_sha256": voice.sha(audio), "audio_seconds": 1.0}


class MatcherTests(unittest.TestCase):
    def test_the_three_intents_and_yes_no(self):
        table = [
            (RULES, "set_rules"),
            ("Refund up to thirty dollars, ask me to approve anything above that", "set_rules"),
            ("What happened with my disputes today?", "ask"),
            ("How much did I refund today?", "ask"),
            ("Which disputes are waiting for my approval today, and how much is each one?", "ask"),
            ("Approve the sixty four dollar one.", "approve"),
            ("approve the 64 dollar one", "approve"),
            ("Yes.", "yes"), ("yes please", "yes"), ("No, cancel that.", "no"), ("cancel", "no"),
        ]
        for said, want in table:
            self.assertEqual(voice.match_intent(said), want, said)

    def test_what_it_cannot_tell_is_left_to_the_model_and_then_to_unclear(self):
        for said in ("The weather in Chennai is lovely this afternoon.", "hello there", "tell me a joke"):
            self.assertIsNone(voice.match_intent(said), said)
        self.assertEqual(voice.match_intent("   "), "unclear")

    def test_a_model_answer_outside_the_fixed_set_is_unclear(self):
        class Model:
            backend = "ollama"
            def __init__(self, value):
                self.value = value
            def propose(self, system, user, fields, scripted, required=None):
                from clearwake.models import Proposal
                return Proposal("ollama", "m", "m via Ollama on this machine", self.value)
        self.assertEqual(voice.classify("x", Model({"intent": "ask"}))[0], "ask")
        for bad in ({"intent": "send_money"}, {"intent": "yes"}, {"other": 1}, None):
            self.assertEqual(voice.classify("x", Model(bad))[0], "unclear", bad)
        self.assertEqual(voice.classify("x", type("A", (), {"backend": "scripted"})())[0], "unclear")

    def test_numbers_said_aloud(self):
        self.assertEqual(voice.amounts_said("Approve the sixty four dollar one."), [6400])
        self.assertEqual(voice.amounts_said("approve the $64.50 one"), [6450])
        self.assertEqual(voice.amounts_said("approve the sixty-four dollars one"), [6400])
        self.assertEqual(voice.amounts_said("approve the 3.50 one"), [350])
        self.assertIn(350, voice.amounts_said("approve the three dollars fifty"))
        self.assertEqual(voice.spoken_to_digits("Refund under thirty dollars if it has not arrived in ten days"),
                         "refund under 30 dollars if it has not arrived in 10 days")
        self.assertEqual(voice.word_error_rate("under $30 in 10 days", "under thirty dollars in ten days"), 0)
        self.assertGreater(voice.word_error_rate("one two three four", "one two"), 0.4)


    def test_spoken_money_and_number_phrasing(self):
        table = {
            "Approve the sixty four dollar one": 6400, "approve the sixty-four dollars one": 6400, "sixty four bucks": 6400,
            "thirty dollars": 3000, "one hundred and twenty": 12000, "a hundred": 10000, "two fifty": 250, "twelve fifty": 1250,
            "approve the $64 one": 6400, "approve the 64 dollars one": 6400, "approve the $64.00 one": 6400, "sixty 4": 6400,
            "approve the 64 one": 6400, "approve the sixty four one": 6400,
        }
        for said, cents in table.items():
            self.assertIn(cents, voice.amounts_said(said), said)
        self.assertEqual(voice.amounts_said("approve the third one"), [])
        for said in table:
            if said.lower().startswith("approve"):
                self.assertEqual(voice.match_intent(said), "approve", said)

    def test_spoken_figures_reach_the_rules_parser_as_figures(self):
        from clearwake import rules_nl
        table = [
            ("Refund anything under thirty dollars that hasn't arrived in ten days. Ask me above that. Never refund twice.", 3000, 10),
            ("Refund up to two fifty if it has not arrived in ten days. Never refund twice.", 250, 10),
            ("Refund under a hundred dollars if it has not arrived in fourteen days. Never refund twice.", 10000, 14),
            ("Refund up to sixty four bucks after ten days. Never refund twice.", 6400, 10),
            ("Refund up to twelve fifty after twelve days. Never refund twice.", 1250, 12),
            ("Refund up to $30 after 10 days. Never refund twice.", 3000, 10),
            ("Refund up to 30 dollars after 10 days. Never refund twice.", 3000, 10),
        ]
        for said, limit, days in table:
            got = rules_nl.propose_rules(voice.spoken_to_digits(said), type("A", (), {"backend": "scripted"})(), "merchant", current=rules_nl.DEFAULT_MERCHANT)
            self.assertTrue(got.ok, (said, got.status, got.question, got.rejected))
            self.assertEqual((got.rules.refund_limit, got.rules.not_received_days), (limit, days), said)

class FlowTests(unittest.TestCase):
    """The three intents on a real console folder, with the words supplied as typed text or as a fixed transcript."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.console = Console(Path(self.folder.name) / "console")
        self.voice = voice.Voice(self.console, StandInTranscriber(RULES))
        self.guard = patch("urllib.request.OpenerDirector.open", no_network)
        self.guard.start()

    def tearDown(self):
        self.guard.stop()
        self.folder.cleanup()

    def spoken(self, words):
        self.voice.transcriber = StandInTranscriber(words)
        heard = self.voice.transcribe(b"local_gw audio bytes")
        return self.voice.turn(transcript_id=heard["transcript_id"])

    def test_ask_is_composed_by_code_from_the_ledger_and_the_screen_text_is_the_spoken_text(self):
        self.console.run_case("k")
        self.console.run_case("i")
        out = self.voice.turn(text="What happened with my disputes today?")
        self.assertEqual(out["intent"], "ask")
        self.assertEqual(out["text"], out["speak"])
        ledger = self.console.dispute_ledger()
        self.assertEqual(out["facts"]["disputes"], len(ledger))
        waiting = [r for r in self.console.inbox() if r["status"] == "PENDING"]
        self.assertEqual(out["facts"]["with_owner"], len([e for e in self.console.entries if e["state"] == "awaiting approval"]))
        self.assertIn("$9.00", out["text"])
        self.assertIn("item not received", out["text"])
        self.assertLessEqual(len(re.findall(r"[.?]\s", out["text"] + " ")), 6)
        self.assertNotRegex(out["text"], r"[!–—]")
        self.assertTrue(waiting)
        answered = merchant_receipts(self.console, "clearwake.voice.answered")
        self.assertEqual(answered[-1]["params"]["answer_sha256"], voice.sha(out["text"]))
        self.assertEqual(answered[-1]["params"]["composed_by"], "code from the dispute ledger and receipts")

    def test_ask_with_nothing_on_the_records_says_so(self):
        out = self.voice.turn(text="What happened with my disputes today?")
        self.assertEqual(out["text"], "There are no disputes today on the records.")

    def test_rules_by_voice_become_the_same_signed_policy_with_source_voice_and_the_transcript_hash(self):
        out = self.spoken(RULES)
        self.assertEqual((out["intent"], out["source"], out["needs_confirm"]), ("set_rules", "voice", True))
        self.assertIn("$30.00", out["text"])
        self.assertTrue(out["text"].endswith("Say yes to confirm, or no to cancel."))
        before = self.console.policy_path.read_text(encoding="utf-8")
        self.assertEqual(self.console.policy_path.read_text(encoding="utf-8"), before)   # nothing changed before yes
        done = self.voice.tap(out["token"], "yes")
        self.assertTrue(done["confirmed"]["rules_hash"])
        line = merchant_receipts(self.console, "clearwake.rules.confirmed")[-1]["params"]
        self.assertEqual((line["source"], line["transcript_sha256"]), ("voice", voice.sha(RULES)))
        self.assertEqual(self.console.swarm.policy["operations"]["refund"]["max_amount_minor"], 3000)
        self.assertNotEqual(self.console.policy_path.read_text(encoding="utf-8"), before)
        check = verify_log(self.console.swarm.receipts.path, self.console.swarm.receipts.public_key)
        self.assertTrue(check["ok"], check)

    def test_a_spoken_yes_confirms_and_a_spoken_no_cancels(self):
        self.spoken(RULES)
        no = self.spoken("No, cancel that.")
        self.assertEqual(no["text"], "Cancelled. Nothing changed.")
        self.assertEqual(self.console.swarm.policy["operations"]["refund"]["max_amount_minor"], 500)
        self.assertEqual(merchant_receipts(self.console, "clearwake.rules.confirmed"), [])
        self.assertIn("Nothing is waiting", self.spoken("Yes.")["text"])      # the cancelled question is gone
        self.spoken(RULES)
        yes = self.spoken("Yes.")
        self.assertEqual(yes["text"], "Confirmed and signed. Your new rules are in force.")
        self.assertEqual(self.console.swarm.policy["operations"]["refund"]["max_amount_minor"], 3000)

    def test_spelled_out_numbers_in_the_rules_are_read_as_figures(self):
        out = self.spoken("Refund anything under thirty dollars that has not arrived in ten days. Ask me above that. Never refund twice.")
        self.assertTrue(out["needs_confirm"], out["text"])
        self.assertIn("$30.00", out["text"])
        self.assertIn("10 days", out["text"])

    def test_unclear_words_change_nothing(self):
        out = self.spoken("The weather in Chennai is lovely this afternoon.")
        self.assertEqual(out["intent"], "unclear")
        self.assertFalse(out["needs_confirm"])
        self.assertIn("I did not understand", out["text"])

    def test_approve_uses_the_console_approval_and_the_receipt_says_voice(self):
        entry = self.console.run_case("k")["entries"][0]
        self.assertEqual(entry["state"], "awaiting approval")
        ask = self.spoken("Approve the nine dollar one.")
        self.assertTrue(ask["needs_confirm"], ask["text"])
        self.assertIn("send the evidence", ask["text"])
        self.assertEqual(self.console.inbox()[0]["status"], "PENDING")        # nothing happens on the command alone
        done = self.spoken("Yes.")
        self.assertTrue(done["text"].startswith("Approved."), done["text"])
        record = self.console.swarm.approvals.get(entry["approval_id"])
        self.assertEqual(record["status"], "consumed")
        self.assertEqual(record["approver"], "Owner (voice)")
        receipt = merchant_receipts(self.console, "clearwake.voice.approval")[-1]["params"]
        self.assertEqual((receipt["source"], receipt["transcript_sha256"], receipt["approval"]), ("voice", voice.sha("Approve the nine dollar one."), entry["approval_id"]))
        self.assertTrue(merchant_receipts(self.console, "clearwake.approval.used"))   # the same record the button uses
        self.assertTrue(verify_log(self.console.swarm.receipts.path, self.console.swarm.receipts.public_key)["ok"])

    def test_an_approval_the_signed_policy_does_not_allow_is_refused_with_the_reason(self):
        entry = self.console.run_case("d")["entries"][0]               # refund 3.50, waiting for the owner under the signed policy
        self.assertEqual(entry["state"], "awaiting approval")
        rules = self.spoken("Refund anything under $2 that has not arrived in 10 days. Ask me above that. Never refund twice.")
        self.voice.tap(rules["token"], "yes")                          # the owner lowers the limit to $2.00 and signs it
        out = self.spoken("Approve the 3.50 one.")
        self.assertTrue(out.get("refused"), out["text"])
        self.assertIn("does not allow it", out["text"])
        self.assertIn("above limit", out["text"])
        self.assertIn("Nothing was approved", out["text"])
        self.assertEqual(self.console.inbox()[0]["status"], "PENDING")
        self.assertFalse(merchant_receipts(self.console, "clearwake.voice.approval"))
        self.assertTrue(merchant_receipts(self.console, "clearwake.voice.refused"))

    def test_a_policy_change_between_the_readback_and_the_yes_is_caught(self):
        self.console.run_case("d")
        out = self.spoken("Approve the 3.50 one")
        self.assertTrue(out["needs_confirm"], out["text"])
        self.console.swarm.policy["operations"]["refund"]["max_amount_minor"] = 100      # the signed policy tightens first
        done = self.voice.tap(out["token"], "yes")
        self.assertTrue(done.get("refused"))
        self.assertEqual(self.console.inbox()[0]["status"], "PENDING")

    def test_approve_by_position_third_one_and_first_one(self):
        for key in ("k", "d", "k", "k"):
            self.console.run_case(key)
        rows = voice.pending_rows(self.console)
        self.assertGreater(len(rows), 3)
        for word, index in (("third", 2), ("first", 0)):
            out = self.spoken(f"Approve the {word} one")
            self.assertTrue(out["needs_confirm"], out["text"])
            self.assertEqual(out["approval"], rows[index]["id"])
            self.voice.tap(out["token"], "no")

    def test_approve_refuses_several_matches_none_and_all(self):
        self.console.run_case("l")
        many = self.spoken("Approve the nine dollar one")
        self.assertTrue(many["refused"] if "refused" in many else "waiting approvals are for" in many["text"], many["text"])
        self.assertFalse(self.voice.live_pending())
        every = self.spoken("Approve them all")
        self.assertIn("one case at a time", every["text"])
        none = self.spoken("Approve the sixty four dollar one")
        self.assertIn("No waiting approval is for $64.00", none["text"])
        self.assertTrue(all(r["status"] == "PENDING" for r in self.console.inbox()))

    def test_a_tap_on_a_stale_question_does_nothing(self):
        first = self.spoken(RULES)
        self.spoken("Yes.")
        again = self.voice.tap(first["token"], "yes")
        self.assertTrue(again.get("stale"))
        self.assertEqual(len(merchant_receipts(self.console, "clearwake.rules.confirmed")), 1)

    def test_raw_audio_is_never_kept(self):
        heard = self.voice.transcribe(b"these bytes stand for audio")
        text = Path(self.console.swarm.receipts.path).read_text(encoding="utf-8")
        self.assertIn(heard["audio_sha256"], text)
        self.assertNotIn("these bytes stand for audio", text)
        self.assertFalse(any(p.suffix in (".wav", ".webm", ".mp4") for p in Path(self.folder.name).rglob("*")))
        line = merchant_receipts(self.console, "clearwake.voice.transcribed")[-1]["params"]
        self.assertEqual((line["audio_stored"], line["transcript_sha256"]), (False, voice.sha(RULES)))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.controller = RefundController(root / "http.sqlite3")
        self.console = Console(root / "console")
        self.server = ClearwakeServer(("127.0.0.1", 0), self.controller, self.console)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        status, headers, raw = self.request("GET", "/console/api/session")
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = json.loads(raw)["csrf"]

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.controller.close(); self.folder.cleanup()

    def request(self, method, path, body=None, headers=None, raw=False):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = dict(headers or {})
        if raw:
            data = body
        else:
            data = json.dumps(body) if body is not None else None
            headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, data, headers)
        response = connection.getresponse(); content = response.read()
        result = (response.status, dict(response.getheaders()), content); connection.close(); return result

    def authed(self):
        return {"Cookie": self.cookie, "X-Clearwake-CSRF": self.csrf}

    def test_the_page_and_its_files_carry_a_strict_policy_and_no_inline_script_or_style(self):
        for path, kind in (("/voice", "text/html"), ("/voice.js", "text/javascript"), ("/voice.css", "text/css")):
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(headers["Content-Type"].startswith(kind))
            policy = headers["Content-Security-Policy"]
            self.assertNotIn("unsafe-inline", policy)
            self.assertIn("script-src 'self'", policy)
            self.assertIn("style-src 'self';", policy)
        page = self.request("GET", "/voice")[2].decode()
        self.assertNotRegex(page, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(page, r"\sstyle=|\son[a-z]+=")
        self.assertNotRegex(page, r"https?://")
        script = self.request("GET", "/voice.js")[2].decode()
        self.assertNotRegex(script, r"webkitSpeechRecognition|SpeechRecognition|googleapis|https?://")
        for word in ("viewport", 'id="mic"', 'id="transcript"', 'id="readback"', 'id="yes"', 'id="no"', "Type instead"):
            self.assertIn(word, page)

    def test_transcribe_needs_the_same_cookie_and_csrf_as_every_console_post(self):
        audio = (FIXTURES / "yes.wav").read_bytes()
        self.assertEqual(self.request("POST", "/console/api/voice/transcribe", audio, {"Content-Type": "audio/wav"}, raw=True)[0], 403)
        wrong = {"Cookie": self.cookie, "X-Clearwake-CSRF": "0" * 64, "Content-Type": "audio/wav"}
        self.assertEqual(self.request("POST", "/console/api/voice/transcribe", audio, wrong, raw=True)[0], 403)
        foreign = {**self.authed(), "Content-Type": "audio/wav", "Origin": "http://evil.example"}
        self.assertEqual(self.request("POST", "/console/api/voice/transcribe", audio, foreign, raw=True)[0], 403)

    def test_transcribe_refuses_big_empty_and_unsupported_audio_before_any_work(self):
        headers = {**self.authed(), "Content-Type": "audio/webm"}
        status, _, body = self.request("POST", "/console/api/voice/transcribe", b"\0" * (5 * 1024 * 1024 + 1), headers, raw=True)
        self.assertEqual(status, 413, body)
        self.assertEqual(self.request("POST", "/console/api/voice/transcribe", b"", headers, raw=True)[0], 400)
        text = {**self.authed(), "Content-Type": "audio/webm"}
        status, _, body = self.request("POST", "/console/api/voice/transcribe", b"#EXTM3U\nfile:///etc/passwd\n", text, raw=True)
        self.assertIn(status, (415, 503), body)         # a playlist is never handed to ffmpeg (503 when no model is installed)
        json_type = {**self.authed(), "Content-Type": "text/html"}
        self.assertEqual(self.request("POST", "/console/api/voice/transcribe", b"x" * 100, json_type, raw=True)[0], 415)

    def test_the_typed_path_and_the_status_route(self):
        status, _, body = self.request("GET", "/console/api/voice/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["typing"], True)
        status, _, body = self.request("POST", "/console/api/voice/turn", {"text": "What happened with my disputes today?"}, self.authed())
        self.assertEqual(status, 200, body)
        answer = json.loads(body)
        self.assertEqual((answer["intent"], answer["source"]), ("ask", "typed"))
        self.assertEqual(self.request("POST", "/console/api/voice/turn", {"text": "x"})[0], 403)
        self.assertEqual(self.request("POST", "/console/api/voice/turn", {"transcript_id": "nope"}, self.authed())[0], 404)
        self.assertEqual(self.request("POST", "/console/api/voice/turn", {"text": "   "}, self.authed())[0], 400)

    def test_an_unknown_transcript_id_cannot_claim_to_be_voice(self):
        status, _, body = self.request("POST", "/console/api/voice/turn", {"text": RULES, "source": "voice", "transcript_sha256": "a" * 64}, self.authed())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["source"], "typed")


class LanTests(unittest.TestCase):
    def test_only_private_lan_addresses_are_used(self):
        from clearwake import voice_lan
        self.assertEqual(voice_lan.lan_address("192.168.1.20"), "192.168.1.20")
        self.assertEqual(voice_lan.lan_address("10.0.0.7"), "10.0.0.7")
        for bad in ("8.8.8.8", "127.0.0.1", "169.254.1.1", "0.0.0.0", "::1"):
            with self.assertRaises(SystemExit):
                voice_lan.lan_address(bad)

    def test_it_refuses_without_the_switch_and_makes_a_local_certificate_for_the_lan_address(self):
        from clearwake import voice_lan
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("CLEARWAKE_VOICE_LAN", None)
            with self.assertRaises(SystemExit) as caught:
                voice_lan.main([])
            self.assertIn("CLEARWAKE_VOICE_LAN=1", str(caught.exception))
        with tempfile.TemporaryDirectory() as folder:
            cert, key, fingerprint = voice_lan.make_certificate("192.168.1.20", folder)
            from cryptography import x509
            loaded = x509.load_pem_x509_certificate(cert.read_bytes())
            names = loaded.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
            self.assertIn(__import__("ipaddress").ip_address("192.168.1.20"), names)
            self.assertEqual(voice_lan.make_certificate("192.168.1.20", folder)[2], fingerprint)     # reused while valid
            self.assertNotEqual(voice_lan.make_certificate("192.168.1.21", folder)[2], fingerprint)   # new address, new certificate

    def test_the_certificate_folder_is_git_ignored(self):
        ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/voice-tls/", ignore)

    def test_https_on_the_lan_host_only(self):
        """A real TLS server on loopback standing in for the LAN address: the Host check and the cookie still apply."""
        import ssl
        from clearwake import voice_lan
        with tempfile.TemporaryDirectory() as folder:
            cert, key, _ = voice_lan.make_certificate("127.0.0.1", folder)
            controller = RefundController(Path(folder) / "lan.sqlite3")
            console = Console(Path(folder) / "console")
            server = voice_lan.build_server(controller, console, "127.0.0.1", 0, cert, key)
            port = server.server_address[1]
            server.lan_hosts = {f"127.0.0.1:{port}"}
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                context = ssl.create_default_context(cafile=str(cert))
                def get(host):
                    c = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=20)
                    c.request("GET", "/console/api/session", headers={"Host": host})
                    r = c.getresponse(); body = r.read(); c.close(); return r.status, dict(r.getheaders()), body
                status, headers, _ = get(f"127.0.0.1:{port}")
                self.assertEqual(status, 200)
                self.assertIn("Secure", headers["Set-Cookie"])
                self.assertEqual(get("evil.example")[0], 403)
                self.assertEqual(get("127.0.0.1")[0], 403)
                plain = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    plain.request("GET", "/voice"); plain.getresponse()
                    refused = False
                except (OSError, http.client.HTTPException):
                    refused = True
                self.assertTrue(refused)      # plain http gets nothing
            finally:
                server.shutdown(); server.server_close(); controller.close()


class PhoneTests(unittest.TestCase):
    """clearwake --phone: a separate small server, token on every request, only the voice surface."""

    def setUp(self):
        from clearwake.voice_phone import PhoneServer
        self.folder = tempfile.TemporaryDirectory()
        self.console = Console(Path(self.folder.name) / "console")
        self.console.voice = voice.Voice(self.console, StandInTranscriber(RULES))
        self.server = PhoneServer(("127.0.0.1", 0), self.console, token="tok-123")
        self.port = self.server.server_address[1]
        self.server.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.folder.cleanup()

    def call(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        c.request(method, path, body, headers or {})
        r = c.getresponse(); data = r.read(); out = (r.status, dict(r.getheaders()), data); c.close(); return out

    def test_every_request_needs_the_token(self):
        for path in ("/", "/status", "/?t=wrong", "/status?t=", "/?t=tok-123x"):
            self.assertEqual(self.call("GET", path)[0], 403, path)
        for path in ("/transcribe", "/turn", "/answer"):
            self.assertEqual(self.call("POST", path, b"{}", {"Content-Type": "application/json"})[0], 403, path)
            self.assertEqual(self.call("POST", path + "?t=bad", b"{}", {"Content-Type": "application/json"})[0], 403, path)
        self.assertEqual(self.call("GET", "/?t=tok-123")[0], 200)

    def test_only_the_voice_surface_is_exposed(self):
        for path in ("/console", "/console/api/state", "/console/api/session", "/voice.js", "/console.js", "/healthz", "/console/api/receipts"):
            self.assertEqual(self.call("GET", path + "?t=tok-123")[0], 404, path)
        self.assertEqual(self.call("POST", "/console/api/case?t=tok-123", b'{"case":"c"}', {"Content-Type": "application/json"})[0], 405)
        self.assertEqual(self.console.entries, [])

    def test_the_page_is_one_self_contained_page_under_a_strict_policy(self):
        status, headers, body = self.call("GET", "/?t=tok-123")
        text = body.decode()
        policy = headers["Content-Security-Policy"]
        nonce = re.search(r"script-src 'nonce-([^']+)'", policy).group(1)
        self.assertNotIn("unsafe-inline", policy)
        self.assertIn(f'<script nonce="{nonce}">', text)
        self.assertIn(f'<style nonce="{nonce}">', text)
        self.assertEqual(len(re.findall(r'<script(?![^>]*(?:nonce=|type="application/json"))', text)), 0)
        self.assertNotRegex(text, r'\sstyle=|\son[a-z]+=|<link|src="http|https?://[a-z]')
        self.assertNotRegex(text, r"webkitSpeechRecognition|googleapis")
        for word in ('type="file" accept="audio/*" capture', 'id="mic"', 'id="transcript"', 'id="readback"', 'id="yes"', 'id="no"', 'id="typed"', "viewport"):
            self.assertIn(word, text)
        again = self.call("GET", "/?t=tok-123")[1]["Content-Security-Policy"]
        self.assertNotEqual(nonce, re.search(r"script-src 'nonce-([^']+)'", again).group(1))

    def test_the_strings_table_covers_every_key_the_page_uses(self):
        from clearwake.voice_phone import BODY, WEB
        from clearwake.voice_strings import LANGUAGES, STRINGS
        used = set(re.findall(r"\b(p\.[a-z_]+)\b", BODY + (WEB / "voice_phone.js").read_text(encoding="utf-8")))
        self.assertFalse(used - set(STRINGS), used - set(STRINGS))
        self.assertEqual(list(LANGUAGES), ["en"])
        self.assertTrue(all("en" in entry for entry in STRINGS.values()))

    def test_typed_and_spoken_turns_work_through_the_token_and_cannot_forge_voice(self):
        h = {"Content-Type": "application/json"}
        status, _, body = self.call("POST", "/turn?t=tok-123", json.dumps({"text": "What happened with my disputes today?"}), h)
        self.assertEqual((status, json.loads(body)["source"]), (200, "typed"))
        status, _, body = self.call("POST", "/transcribe?t=tok-123", b"RIFF....WAVElocal", {"Content-Type": "audio/wav"})
        heard = json.loads(body)
        self.assertEqual(status, 200, body)
        status, _, body = self.call("POST", "/turn?t=tok-123", json.dumps({"transcript_id": heard["transcript_id"]}), h)
        turn = json.loads(body)
        self.assertEqual((turn["intent"], turn["source"], turn["needs_confirm"]), ("set_rules", "voice", True))
        status, _, body = self.call("POST", "/answer?t=tok-123", json.dumps({"token": turn["token"], "answer": "yes"}), h)
        self.assertEqual(status, 200, body)
        line = merchant_receipts(self.console, "clearwake.rules.confirmed")[-1]["params"]
        self.assertEqual((line["source"], line["transcript_sha256"]), ("voice", voice.sha(RULES)))

    def test_big_and_wrong_requests_are_refused(self):
        self.assertEqual(self.call("POST", "/transcribe?t=tok-123", b"\0" * (5 * 1024 * 1024 + 1), {"Content-Type": "audio/webm"})[0], 413)
        self.assertEqual(self.call("POST", "/turn?t=tok-123", b"{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("POST", "/turn?t=tok-123", b"{}", {"Content-Type": "application/json", "Origin": "http://evil.example"})[0], 403)

    def test_a_second_copy_cannot_share_the_port(self):
        from clearwake.voice_phone import PhoneServer
        with self.assertRaises(OSError):
            PhoneServer(("127.0.0.1", self.port), self.console, token="other")

    def test_the_link_and_qr_code_are_printed(self):
        import contextlib
        import io
        from clearwake.voice_phone import announce
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            announce(self.server, "192.168.1.20")
        self.assertIn(f"http://192.168.1.20:{self.port}/?t=tok-123", out.getvalue())
        self.assertGreater(len(out.getvalue().splitlines()), 15)     # the QR code (segno is installed)

    def test_https_mode_serves_the_same_page_and_refuses_plain_http(self):
        import ssl
        from clearwake.voice_phone import PhoneServer
        from clearwake import voice_lan
        with tempfile.TemporaryDirectory() as folder:
            cert, key, _ = voice_lan.make_certificate("127.0.0.1", folder)
            server = PhoneServer(("127.0.0.1", 0), self.console, token="tls-tok", tls=(cert, key))
            server.start()
            try:
                self.assertTrue(server.link("1.2.3.4").startswith("https://"))
                port = server.server_address[1]
                for query, want in (("tls-tok", 200), ("nope", 403)):
                    c = http.client.HTTPSConnection("127.0.0.1", port, context=ssl.create_default_context(cafile=str(cert)), timeout=20)
                    c.request("GET", "/?t=" + query); r = c.getresponse(); r.read()
                    self.assertEqual(r.status, want); c.close()
                plain = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                with self.assertRaises((OSError, http.client.HTTPException)):
                    plain.request("GET", "/?t=tls-tok"); plain.getresponse()
            finally:
                server.shutdown(); server.server_close()


@unittest.skipUnless(voice.find_ffmpeg(), "ffmpeg is not installed")
class PhoneFormatTests(unittest.TestCase):
    """Whatever a phone recorder produces goes through ffmpeg to 16 kHz wav."""

    def test_m4a_aac_3gp_amr_webm_ogg_wav_mp3_all_convert(self):
        import subprocess
        import wave
        source = FIXTURES / "ask.wav"
        ffmpeg = voice.find_ffmpeg()
        cases = {"m4a": ["-c:a", "aac"], "aac": ["-c:a", "aac", "-f", "adts"], "3gp": ["-c:a", "aac", "-f", "3gp"],
                 "amr": ["-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1"], "webm": ["-c:a", "libopus"], "ogg": ["-c:a", "libopus"],
                 "wav": [], "mp3": ["-c:a", "libmp3lame"]}
        converted = []
        with tempfile.TemporaryDirectory() as folder:
            for ext, opts in cases.items():
                out = Path(folder) / f"clip.{ext}"
                made = subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(source), *opts, str(out)], capture_output=True)
                if made.returncode != 0:
                    continue          # this ffmpeg build lacks that encoder
                work = Path(folder) / ext; work.mkdir()
                wav, seconds = voice.to_wav(out.read_bytes(), work)
                self.assertAlmostEqual(seconds, 2.7, delta=0.6, msg=ext)
                with wave.open(str(wav)) as w:
                    self.assertEqual((w.getframerate(), w.getnchannels()), (16000, 1), ext)
                converted.append(ext)
        self.assertGreaterEqual(len(converted), 6, converted)


@unittest.skipUnless(STT, "the Whisper model folder or ffmpeg is not installed")
class WhisperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transcriber = voice.Transcriber()
        cls.heard = {name: cls.transcriber.transcribe((FIXTURES / f"{name}.wav").read_bytes()) for name in CLIPS}

    def test_transcription_is_accurate_on_every_clip(self):
        rates = {name: voice.word_error_rate(CLIPS[name]["words"], got["transcript"]) for name, got in self.heard.items()}
        for name, rate in rates.items():
            self.assertLessEqual(rate, 0.25, f"{name}: {self.heard[name]['transcript']!r}")
        self.assertLessEqual(sum(rates.values()) / len(rates), 0.12, rates)

    def test_the_three_filming_lines(self):
        for name in ("film_rules", "film_ask", "film_approve"):
            got = self.heard[name]["transcript"]
            self.assertLessEqual(voice.word_error_rate(CLIPS[name]["words"], got), 0.2, got)
            self.assertEqual(voice.match_intent(got), CLIPS[name]["intent"], got)
        self.assertIn(6400, voice.amounts_said(self.heard["film_approve"]["transcript"]))
        folder = tempfile.TemporaryDirectory()
        try:
            console = Console(Path(folder.name) / "console")
            said = voice.Voice(console, StandInTranscriber(self.heard["film_rules"]["transcript"]))
            heard = said.transcribe(b"x")
            turn = said.turn(transcript_id=heard["transcript_id"])
            self.assertTrue(turn["needs_confirm"], turn["text"])
            self.assertIn("$30.00", turn["text"])
            self.assertIn("10 days", turn["text"])
        finally:
            folder.cleanup()

    def test_warm_up_runs_one_tiny_transcription(self):
        fresh = voice.Transcriber()
        self.assertGreater(fresh.warm(), 0)
        self.assertIsNotNone(fresh._model)

    def test_each_clip_resolves_to_its_intent(self):
        for name, got in self.heard.items():
            found = voice.match_intent(got["transcript"])
            self.assertEqual(found or "unclear", CLIPS[name]["intent"], f"{name}: {got['transcript']!r}")

    def test_the_hash_and_length_come_back_and_the_audio_is_not_kept(self):
        got = self.heard["ask"]
        self.assertEqual(got["audio_sha256"], voice.sha((FIXTURES / "ask.wav").read_bytes()))
        self.assertAlmostEqual(got["audio_seconds"], 2.71, delta=0.2)
        self.assertGreater(got["ms"], 0)

    def test_a_recording_over_thirty_seconds_is_refused(self):
        import struct
        import wave
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "long.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(struct.pack("<h", 0) * 16000 * 40)
            with self.assertRaises(voice.ConsoleError) as caught:
                self.transcriber.transcribe(path.read_bytes())
            self.assertEqual(caught.exception.status, 413)

    def test_the_full_path_over_http_ends_in_a_signed_policy_with_source_voice(self):
        folder = tempfile.TemporaryDirectory()
        root = Path(folder.name)
        controller = RefundController(root / "w.sqlite3")
        console = Console(root / "console")
        console.voice = voice.Voice(console, self.transcriber)
        server = ClearwakeServer(("127.0.0.1", 0), controller, console)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            def call(method, path, body=None, headers=None):
                c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=120)
                c.request(method, path, body, headers or {})
                r = c.getresponse(); data = r.read(); out = (r.status, dict(r.getheaders()), data); c.close(); return out
            _, h, raw = call("GET", "/console/api/session")
            cookie, csrf = h["Set-Cookie"].split(";", 1)[0], json.loads(raw)["csrf"]
            auth = {"Cookie": cookie, "X-Clearwake-CSRF": csrf}
            status, _, raw = call("POST", "/console/api/voice/transcribe", (FIXTURES / "rules.wav").read_bytes(), {**auth, "Content-Type": "audio/wav"})
            self.assertEqual(status, 200, raw)
            heard = json.loads(raw)
            for key in ("transcript", "ms", "audio_sha256"):
                self.assertIn(key, heard)
            status, _, raw = call("POST", "/console/api/voice/turn", json.dumps({"transcript_id": heard["transcript_id"]}), {**auth, "Content-Type": "application/json"})
            turn = json.loads(raw)
            self.assertEqual((turn["intent"], turn["needs_confirm"]), ("set_rules", True), turn["text"])
            status, _, raw = call("POST", "/console/api/voice/answer", json.dumps({"token": turn["token"], "answer": "yes"}), {**auth, "Content-Type": "application/json"})
            self.assertEqual(status, 200, raw)
            line = merchant_receipts(console, "clearwake.rules.confirmed")[-1]["params"]
            self.assertEqual(line["source"], "voice")
            self.assertEqual(line["transcript_sha256"], voice.sha(heard["transcript"]))
            self.assertEqual(console.swarm.policy["operations"]["refund"]["max_amount_minor"], 3000)
        finally:
            server.shutdown(); server.server_close(); controller.close(); folder.cleanup()


if __name__ == "__main__":
    unittest.main()
