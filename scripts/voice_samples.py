"""Make short Sarvam Bulbul samples of one sentence in several male voices, and measure each one's pitch and pace.

Credits are limited: the sentence is short, each voice is generated once (cached by text and voice), nothing is repeated.
Output: D:\\paypal hackathon\\video\\voices\\sample-<voice>.wav and a measurements file. The key is never printed.
Usage: python scripts/voice_samples.py shubh rahul kabir advait aditya
"""
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clearwake import envfile, sarvam  # noqa: E402

SENTENCE = "Approve case four. Send the refund of five dollars, inside my limit, and read PayPal's record back before anything else."
OUT = Path(r"D:\paypal hackathon\video\voices")


def pitch_and_pace(path):
    with wave.open(str(path), "rb") as w:
        rate, frames = w.getframerate(), w.readframes(w.getnframes())
    x = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    seconds = len(x) / rate
    # median fundamental frequency from voiced frames (autocorrelation, 70 to 300 Hz)
    hop, size, f0s = int(rate * 0.02), int(rate * 0.04), []
    lo, hi = int(rate / 300), int(rate / 70)
    for i in range(0, len(x) - size, hop):
        frame = x[i:i + size]
        if np.sqrt(np.mean(frame ** 2)) < 600:
            continue
        frame = frame - frame.mean()
        ac = np.correlate(frame, frame, mode="full")[size - 1:]
        if ac[0] <= 0:
            continue
        peak = lo + int(np.argmax(ac[lo:hi]))
        if ac[peak] / ac[0] > 0.45:
            f0s.append(rate / peak)
    words = len(SENTENCE.split())
    return {"seconds": round(seconds, 2), "median_f0_hz": round(float(np.median(f0s)), 1) if f0s else None,
            "voiced_frames": len(f0s), "words_per_minute": round(words / seconds * 60)}


def main(voices):
    envfile.load(str(ROOT / ".env"))
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for voice in voices:
        try:
            cached = sarvam.speak(SENTENCE, voice, pace=1.0)
        except sarvam.SarvamError as error:
            print(voice, "failed:", error)
            results[voice] = {"error": str(error)}
            continue
        target = OUT / f"sample-{voice}.wav"
        target.write_bytes(cached.read_bytes())
        results[voice] = pitch_and_pace(target)
        print(voice, results[voice])
    (OUT / "measurements.json").write_text(json.dumps({"sentence": SENTENCE, "model": sarvam.TTS_MODEL, "voices": results}, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:] or ["shubh", "rahul", "kabir", "advait", "aditya"])
