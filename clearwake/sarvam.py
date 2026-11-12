"""Sarvam AI voice for the product: Bulbul text to speech and Saaras speech to text.

The key is read from the SARVAM_API_KEY environment variable (loaded from .env) and is never printed, logged or written to a file.
Every spoken line is cached by its text, voice and settings, so a line is paid for once. The cache lives under data/voice-cache (git ignored).
Credits are limited: short texts only, one request per new line, one retry never (a failed call is reported, not repeated).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

TTS_URL = "https://api.sarvam.ai/text-to-speech"
STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_MODEL = "bulbul:v3"
STT_MODEL = "saaras:v4"
CACHE = Path(__file__).resolve().parent.parent / "data" / "voice-cache"
MAX_TTS_CHARS = 400     # a spoken line in the product is short; this also protects the credits
# Hard spending caps for the whole project (Sri has a few credits and cannot buy more). Raising them takes an environment variable set on purpose.
TTS_CHARS_CAP = int(os.environ.get("CLEARWAKE_SARVAM_TTS_CHARS_CAP", "3600"))     # about 11 rupees on Bulbul v3
STT_SECONDS_CAP = int(os.environ.get("CLEARWAKE_SARVAM_STT_SECONDS_CAP", "240"))  # about 2 rupees
LEDGER = CACHE / "spend.json"


class SarvamError(Exception):
    pass


def key():
    value = os.environ.get("SARVAM_API_KEY", "").strip()
    if not value:
        raise SarvamError("SARVAM_API_KEY is not set in .env")
    return value


def available():
    return bool(os.environ.get("SARVAM_API_KEY", "").strip())


def _post(url, body, headers, timeout=60):
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read(400).decode("utf-8", "replace")
        except Exception:
            pass
        if error.code == 402:
            raise SarvamError("Sarvam credits are used up (HTTP 402).") from None
        raise SarvamError(f"Sarvam answered HTTP {error.code}. {detail[:160]}") from None
    except Exception as error:  # noqa: BLE001
        raise SarvamError(f"Sarvam could not be reached: {type(error).__name__}") from None


def _spend():
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return {"tts_chars": 0, "stt_seconds": 0.0, "calls": 0}


def _record(**add):
    CACHE.mkdir(parents=True, exist_ok=True)
    data = _spend()
    for name, value in add.items():
        data[name] = data.get(name, 0) + value
    data["calls"] = data.get("calls", 0) + 1
    LEDGER.write_text(json.dumps(data), encoding="utf-8")
    return data


def spent():
    """What has been used so far: characters spoken, seconds heard, requests made (cached lines cost nothing and are not counted)."""
    return _spend()


def speak(text, speaker, pace=1.0, model=TTS_MODEL, sample_rate=24000):
    """Return the path of a WAV file for this line. A line already spoken is read from the cache and costs nothing."""
    text = " ".join(str(text).split())
    if not text or len(text) > MAX_TTS_CHARS:
        raise SarvamError(f"a spoken line must be 1 to {MAX_TTS_CHARS} characters")
    digest = hashlib.sha256(json.dumps([text, speaker, model, round(float(pace), 2), sample_rate], sort_keys=True).encode()).hexdigest()[:24]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{speaker}-{digest}.wav"
    if path.exists():
        return path
    if _spend().get("tts_chars", 0) + len(text) > TTS_CHARS_CAP:
        raise SarvamError("the Sarvam text to speech budget for this project is used up; ask Sri before raising it")
    body = json.dumps({"text": text, "language_code": "en-IN", "speaker": speaker, "model": model, "pace": float(pace),
                       "speech_sample_rate": sample_rate, "output_audio_codec": "wav"}).encode("utf-8")
    reply = _post(TTS_URL, body, {"Content-Type": "application/json", "api-subscription-key": key()})
    audios = reply.get("audios") or []
    if not audios:
        raise SarvamError("Sarvam returned no audio")
    path.write_bytes(base64.b64decode(audios[0]))
    _record(tts_chars=len(text))
    return path


def transcribe(audio_bytes, filename="owner.wav", language="en-IN", seconds=10.0):
    """Return the transcript of a short recording (under 30 seconds). Costs credits per second of audio; seconds is the length of the clip."""
    if seconds > 30:
        raise SarvamError("a clip for speech to text must be under 30 seconds")
    if _spend().get("stt_seconds", 0) + seconds > STT_SECONDS_CAP:
        raise SarvamError("the Sarvam speech to text budget for this project is used up; ask Sri before raising it")
    boundary = "----clearwake" + uuid.uuid4().hex
    parts = []
    for name, value in (("model", STT_MODEL), ("language_code", language)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                 + audio_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    reply = _post(STT_URL, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}", "api-subscription-key": key()})
    _record(stt_seconds=float(seconds))
    return str(reply.get("transcript", "")).strip()
