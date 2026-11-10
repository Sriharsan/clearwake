"""Measure local speech to text on the spoken test clips: word error and transcription time.
Writes data/runs/voice-<timestamp>.json. Label: local run on this laptop CPU (Whisper small.en, int8)."""
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clearwake import voice  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "voice"
REPEATS = 5


def main():
    clips = json.loads((FIX / "clips.json").read_text(encoding="utf-8"))
    t = voice.Transcriber()
    started = time.perf_counter()
    t.model()
    load_ms = round((time.perf_counter() - started) * 1000)
    rows = []
    for name, spec in clips.items():
        audio = (FIX / f"{name}.wav").read_bytes()
        runs = [t.transcribe(audio) for _ in range(REPEATS)]
        ms = sorted(r["ms"] for r in runs)
        text = runs[0]["transcript"]
        rows.append({"clip": name, "audio_seconds": runs[0]["audio_seconds"], "said": spec["words"], "heard": text,
                     "word_error": round(voice.word_error_rate(spec["words"], text), 3), "ms_median": statistics.median(ms), "ms_min": ms[0], "ms_max": ms[-1],
                     "intent": voice.match_intent(text) or "unclear", "intent_expected": spec["intent"]})
    report = {"label": "local run on this laptop CPU", "model": "Whisper small.en via faster-whisper 1.2.1, int8, cpu, beam 5, VAD on",
              "machine": platform.processor() or platform.machine(), "model_load_ms": load_ms, "repeats_per_clip": REPEATS,
              "clips": len(rows), "mean_word_error": round(sum(r["word_error"] for r in rows) / len(rows), 3),
              "intents_correct": sum(r["intent"] == r["intent_expected"] for r in rows),
              "clip_5s_ms_median": next(r["ms_median"] for r in rows if r["clip"] == "clip5"),
              "clip_10s_ms_median": next(r["ms_median"] for r in rows if r["clip"] == "clip10"),
              "rows": rows, "note": "Clips are Windows SAPI speech, not a human voice; a person on a phone microphone will differ."}
    out = ROOT / "data" / "runs" / f"voice-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(out.name, {k: report[k] for k in ("mean_word_error", "intents_correct", "clip_5s_ms_median", "clip_10s_ms_median", "model_load_ms")})
    for r in rows:
        print(r["clip"], r["audio_seconds"], r["word_error"], r["ms_median"], "|", r["heard"])


if __name__ == "__main__":
    main()
