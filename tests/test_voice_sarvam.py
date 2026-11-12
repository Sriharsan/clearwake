"""Voice by Sarvam: speech to text order, spoken replies, the owner voice, the audio route, the source record and the spend counts.

Nothing here reaches the network or spends a credit: clearwake.sarvam._post is replaced by a stand in that returns a short tone for
speech and a fixed sentence for transcription, the cache and the ledger live in a temporary folder, and urlopen is made to fail loudly.
"""
import base64
import http.client
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from clearwake import sarvam, voice
from clearwake.console import Console
from clearwake.controller import RefundController
from clearwake.server import ClearwakeServer

RULES = "Refund anything under $30 that has not arrived in 10 days. Ask me above that. Never refund twice."
ASK = "What happened with my disputes today?"
KEY_NAME = "SARVAM_API_KEY"
TEST_KEY = "test-key-for-stubbed-calls"


def tone(seconds=1.0):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(int(8000 * seconds))))
    return buffer.getvalue()


class Stand:
    """The stand in for Sarvam's two endpoints. Counts the requests it was given."""

    def __init__(self, transcript=RULES, fail_stt=False):
        self.transcript, self.fail_stt, self.calls = transcript, fail_stt, []

    def __call__(self, url, body, headers, timeout=60):
        self.calls.append(url)
        if url == sarvam.TTS_URL:
            return {"audios": [base64.b64encode(tone()).decode()]}
        if self.fail_stt:
            raise sarvam.SarvamError("Sarvam answered HTTP 500.")
        return {"transcript": self.transcript}


class LocalWhisper:
    def __init__(self, words="local words", ready=True):
        self.words, self.ready, self.model_dir, self.used = words, ready, Path("local_gw"), 0

    def available(self):
        return self.ready

    def status(self):
        return {"stt": self.ready, "label": voice.LABEL}

    def transcribe(self, audio):
        if not self.ready:
            raise voice.ConsoleError("Speech to text is not installed on this server. Type instead.", 503)
        self.used += 1
        return {"transcript": self.words, "ms": 1, "audio_sha256": voice.sha(audio), "audio_seconds": 1.0}


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        cache = root / "voice-cache"
        self.patches = [patch.object(sarvam, "CACHE", cache), patch.object(sarvam, "LEDGER", cache / "spend.json"),
                        patch.dict(os.environ, {KEY_NAME: TEST_KEY}),
                        patch("urllib.request.urlopen", side_effect=AssertionError("a network call was made"))]
        for p in self.patches:
            p.start()
        os.environ.pop("CLEARWAKE_VOICE", None)
        self.stand = Stand()
        post = patch.object(sarvam, "_post", self.stand)
        post.start(); self.patches.append(post)
        self.console = Console(root / "console")

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.folder.cleanup()

    def make(self, local=None, cloud=True, runner=None, bound=True):
        v = voice.Voice(self.console, local or LocalWhisper(), cloud=cloud)
        if bound:
            v.server = type("S", (), {"decision_runner": runner})() if runner is not None else object()
        self.console.voice = v
        return v


class OrderTests(Base):
    def test_sarvam_first_with_the_clip_length_and_the_model(self):
        local = LocalWhisper()
        v = self.make(local)
        with patch.object(sarvam, "transcribe", wraps=sarvam.transcribe) as spy:
            out = v.transcribe(tone(2.0), kind="audio/wav")
        self.assertEqual((out["stt"], out["transcript"]), ("sarvam saaras:v4", RULES))
        self.assertEqual(spy.call_args.kwargs["seconds"], 2.0)
        self.assertEqual(local.used, 0)
        self.assertEqual(sarvam.spent()["stt_seconds"], 2.0)

    def test_local_mode_and_a_missing_key_use_local_whisper_and_never_call_sarvam(self):
        local = LocalWhisper()
        v = self.make(local)
        with patch.dict(os.environ, {"CLEARWAKE_VOICE": "local"}):
            self.assertEqual(v.transcribe(tone())["stt"], "local whisper")
        os.environ.pop("CLEARWAKE_VOICE", None)
        with patch.dict(os.environ, {KEY_NAME: ""}):
            self.assertEqual(v.transcribe(tone())["stt"], "local whisper")
            self.assertFalse(v.status()["sarvam"]["active"])
        self.assertEqual(self.stand.calls, [])

    def test_a_sarvam_failure_falls_back_to_local_whisper_then_to_a_clean_refusal(self):
        self.stand.fail_stt = True
        local = LocalWhisper("from whisper")
        out = self.make(local).transcribe(tone())
        self.assertEqual((out["stt"], out["transcript"]), ("local whisper", "from whisper"))
        with self.assertRaises(voice.ConsoleError) as caught:
            self.make(LocalWhisper(ready=False)).transcribe(tone())
        self.assertEqual(caught.exception.status, 503)
        self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_nothing_without_a_key_and_without_whisper_can_transcribe_so_the_page_types_or_uses_the_browser(self):
        with patch.dict(os.environ, {KEY_NAME: ""}):
            v = self.make(LocalWhisper(ready=False))
            status = v.status()
            self.assertEqual((status["stt"], status["stt_engine"], status["typing"]), (False, "browser speech", True))
            with self.assertRaises(voice.ConsoleError):
                v.transcribe(tone())

    def test_a_clip_over_thirty_seconds_is_refused_before_any_request(self):
        with self.assertRaises(voice.ConsoleError) as caught:
            self.make().transcribe(b"webmdata" * 10, seconds="45", kind="audio/webm")
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(self.stand.calls, [])

    def test_a_voice_built_by_hand_never_reaches_sarvam(self):
        v = voice.Voice(self.console, LocalWhisper())
        self.assertEqual(v.transcribe(tone())["stt"], "local whisper")
        self.assertEqual(self.stand.calls, [])


class TurnTests(Base):
    def test_source_record_for_typed_browser_and_spoken_commands(self):
        v = self.make()
        typed = v.turn(None, ASK)["source_record"]
        self.assertEqual(typed, {"channel": "voice", "stt": "typed", "owner_voice": None, "reply_voice": "advait", "provider": "sarvam"})
        browser = v.turn(None, ASK, "browser speech")["source_record"]
        self.assertEqual(browser["stt"], "browser speech")
        spoken = v.turn(v.transcribe(tone())["transcript_id"])["source_record"]
        self.assertEqual((spoken["stt"], spoken["owner_voice"]), ("sarvam saaras:v4", None))
        owner = v.owner_play(RULES)
        record = v.turn(owner["transcript_id"])["source_record"]
        self.assertEqual(record, {"channel": "voice", "stt": "sarvam saaras:v4", "owner_voice": "kabir", "reply_voice": "advait", "provider": "sarvam"})

    def test_reply_voice_is_null_when_replies_are_not_spoken_by_sarvam(self):
        record = self.make(bound=False).turn(None, ASK)["source_record"]
        self.assertIsNone(record["reply_voice"])
        with patch.dict(os.environ, {"CLEARWAKE_VOICE": "local"}):
            reply = self.make().turn(None, ASK)
            self.assertIsNone(reply["source_record"]["reply_voice"])
            self.assertNotIn("reply_audio", reply)

    def test_the_reply_is_spoken_with_advait_and_the_text_is_the_text_shown(self):
        reply = self.make().turn(None, ASK)
        self.assertEqual((reply["reply_voice"], reply["voice_label"]), ("advait", "Clearwake's voice: Sarvam Bulbul"))
        self.assertTrue(reply["reply_audio"].startswith("/console/api/voice/audio/advait-"))
        self.assertEqual(reply["spoken_text"], voice.first_sentences(reply["text"]))
        calls = len(self.stand.calls)
        self.make().turn(None, ASK)
        self.assertEqual(len(self.stand.calls), calls)       # the same line is read from the cache and costs nothing

    def test_a_long_reply_is_spoken_in_whole_sentences_under_the_limit(self):
        long = ("First sentence is here. " * 40).strip()
        spoken = voice.first_sentences(long)
        self.assertLessEqual(len(spoken), sarvam.MAX_TTS_CHARS)
        self.assertTrue(spoken.endswith("."))

    def test_a_speech_failure_leaves_the_text_and_a_note_not_an_error(self):
        v = self.make()
        with patch.object(sarvam, "speak", side_effect=sarvam.SarvamError("the budget is used up")):
            reply = v.turn(None, ASK)
        self.assertNotIn("reply_audio", reply)
        self.assertIn("not available", reply["voice_note"])
        self.assertTrue(reply["text"])

    def test_the_decision_runner_gets_the_command_and_the_source_record(self):
        seen = []

        class Runner:
            def run(self, command_text, source):
                seen.append((command_text, source))
                return {"text": "The decision layer answered.", "intent": "ask"}
        reply = self.make(runner=Runner()).turn(None, ASK)
        self.assertEqual(seen[0][0], ASK)
        self.assertEqual(seen[0][1]["channel"], "voice")
        self.assertEqual(reply["text"], "The decision layer answered.")
        self.assertEqual(reply["source_record"], seen[0][1])

    def test_a_missing_or_failing_runner_falls_back_to_the_rules_flow(self):
        reply = self.make(runner=None).turn(None, ASK)
        self.assertEqual(reply["intent"], "ask")

        class Broken:
            def run(self, command_text, source):
                raise RuntimeError("down")
        self.assertEqual(self.make(runner=Broken()).turn(None, ASK)["intent"], "ask")

    def test_yes_and_no_stay_with_the_confirmation_flow_and_never_reach_the_runner(self):
        class Runner:
            def run(self, command_text, source):
                raise AssertionError("the runner must not see a yes or a no")
        v = self.make(runner=Runner())
        self.assertIn("Nothing is waiting", v.turn(None, "yes")["text"])


class OwnerVoiceTests(Base):
    def test_owner_command_is_spoken_by_kabir_and_goes_through_speech_to_text(self):
        v = self.make()
        out = v.owner_play(RULES)
        self.assertEqual((out["owner_voice"], out["voice_label"], out["stt"]), ("kabir", "Owner's voice: Sarvam Bulbul", "sarvam saaras:v4"))
        self.assertTrue(out["owner_audio"].startswith("/console/api/voice/audio/kabir-"))
        self.assertEqual(out["transcript"], RULES)
        self.assertEqual(self.stand.calls, [sarvam.TTS_URL, sarvam.STT_URL])
        self.assertEqual(v.transcripts[out["transcript_id"]]["owner_voice"], "kabir")

    def test_an_empty_line_uses_the_default_owner_command(self):
        self.assertEqual(self.make().owner_play("  ")["spoken_text"], voice.OWNER_LINE)

    def test_without_the_key_the_owner_voice_is_refused_cleanly(self):
        with patch.dict(os.environ, {KEY_NAME: ""}):
            with self.assertRaises(voice.ConsoleError) as caught:
                self.make().owner_play(RULES)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.stand.calls, [])

    def test_the_label_text_is_exact(self):
        self.assertEqual(voice.OWNER_LABEL, "Owner's voice: Sarvam Bulbul")
        self.assertEqual(voice.REPLY_LABEL, "Clearwake's voice: Sarvam Bulbul")
        script = (Path(voice.__file__).resolve().parent.parent / "web" / "voice.js").read_text(encoding="utf-8")
        self.assertIn("\"Owner's voice: Sarvam Bulbul\"", script)
        self.assertIn("\"Clearwake's voice: Sarvam Bulbul\"", script)


class BudgetTests(Base):
    def test_status_shows_counts_only(self):
        v = self.make()
        v.turn(None, ASK)
        status = v.status()["sarvam"]
        self.assertTrue(status["active"])
        self.assertGreater(status["tts_chars"], 0)
        self.assertEqual(status["calls"], 1)
        self.assertNotIn(TEST_KEY, json.dumps(v.status()))
        self.assertEqual(set(status), {"key_set", "active", "owner_voice", "reply_voice", "tts_chars", "stt_seconds", "calls", "tts_chars_cap", "stt_seconds_cap"})


class HTTPTests(Base):
    def setUp(self):
        super().setUp()
        root = Path(self.folder.name)
        self.controller = RefundController(root / "http.sqlite3")
        self.make(LocalWhisper())
        self.server = ClearwakeServer(("127.0.0.1", 0), self.controller, self.console)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        status, headers, raw = self.request("GET", "/console/api/session")
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = json.loads(raw)["csrf"]

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.controller.close()
        super().tearDown()

    def request(self, method, path, body=None, headers=None, raw=False):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = dict(headers or {})
        data = body if raw else (json.dumps(body) if body is not None else None)
        if not raw:
            headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, data, headers)
        response = connection.getresponse(); content = response.read()
        result = (response.status, dict(response.getheaders()), content); connection.close(); return result

    def authed(self):
        return {"Cookie": self.cookie, "X-Clearwake-CSRF": self.csrf}

    def test_the_full_loop_over_http_owner_voice_transcript_read_back_reply_voice(self):
        status, _, raw = self.request("POST", "/console/api/voice/owner", {"text": RULES}, self.authed())
        owner = json.loads(raw)
        self.assertEqual((status, owner["voice_label"]), (200, "Owner's voice: Sarvam Bulbul"))
        status, headers, audio = self.request("GET", owner["owner_audio"], headers={"Cookie": self.cookie})
        self.assertEqual((status, headers["Content-Type"], audio[:4]), (200, "audio/wav", b"RIFF"))
        status, _, raw = self.request("POST", "/console/api/voice/turn", {"transcript_id": owner["transcript_id"]}, self.authed())
        turn = json.loads(raw)
        self.assertTrue(turn["needs_confirm"])
        self.assertEqual((turn["reply_voice"], turn["voice_label"]), ("advait", "Clearwake's voice: Sarvam Bulbul"))
        self.assertEqual(turn["source_record"]["owner_voice"], "kabir")
        status, headers, audio = self.request("GET", turn["reply_audio"], headers={"Cookie": self.cookie})
        self.assertEqual((status, audio[:4]), (200, b"RIFF"))

    def test_the_audio_route_rejects_path_tricks_and_unknown_names(self):
        self.request("POST", "/console/api/voice/owner", {"text": RULES}, self.authed())
        real = next(sarvam.CACHE.glob("kabir-*.wav")).name
        bad = ["../spend.json", "..%2fspend.json", "%2e%2e/spend.json", "..\\spend.json", "spend.json", real + "/", real + "%00", real[:-4], real.upper(),
               "kabir-" + "0" * 24 + ".wav", "advait-xyz.wav", "", "/etc/passwd", "kabir-" + "0" * 24 + ".wav/../spend.json", "..%5cspend.json", real + ".json"]
        for name in bad:
            status = self.request("GET", "/console/api/voice/audio/" + name, headers={"Cookie": self.cookie})[0]
            self.assertIn(status, (400, 403, 404), name)
        self.assertEqual(self.request("GET", "/console/api/voice/audio/" + real, headers={"Cookie": self.cookie})[0], 200)

    def test_the_voice_page_may_play_audio_from_its_own_origin_only(self):
        policy = self.request("GET", "/voice")[1]["Content-Security-Policy"]
        self.assertIn("media-src 'self'", policy)
        self.assertNotIn("unsafe-inline", policy)

    def test_status_route_shows_counts_and_never_the_key(self):
        status, _, raw = self.request("GET", "/console/api/voice/status", headers={"Cookie": self.cookie})
        body = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertTrue(body["sarvam"]["active"])
        self.assertEqual(body["stt_engine"], "sarvam saaras:v4")
        self.assertNotIn(TEST_KEY, raw.decode())

    def test_transcribe_over_http_uses_sarvam_with_the_clip_length_header(self):
        headers = {**self.authed(), "Content-Type": "audio/webm", "X-Clearwake-Seconds": "3.5"}
        status, _, raw = self.request("POST", "/console/api/voice/transcribe", b"x" * 2000, headers, raw=True)
        out = json.loads(raw)
        self.assertEqual((status, out["stt"], out["audio_seconds"]), (200, "sarvam saaras:v4", 3.5))

    def test_the_page_files_carry_the_players_the_button_and_the_labels(self):
        page = self.request("GET", "/voice")[2].decode()
        for word in ('id="owner"', "Play owner command", '<audio id="owner-audio"', '<audio id="reply-audio"', 'id="transcript"', 'id="readback"'):
            self.assertIn(word, page)
        script = self.request("GET", "/voice.js")[2].decode()
        self.assertNotRegex(script, r"webkitSpeechRecognition|SpeechRecognition|googleapis|https?://")
        self.assertIn("18px", self.request("GET", "/voice.css")[2].decode())


if __name__ == "__main__":
    unittest.main()
