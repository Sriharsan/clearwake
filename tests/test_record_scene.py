"""Tests for the scene recorder and the audio mux. No network beyond localhost, no Sarvam, no PayPal: the sounds are short WAV files
generated here, the page is a small local file."""
import array
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import mux_audio  # noqa: E402
import record_scene  # noqa: E402
from video import scenes  # noqa: E402

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Local page</title></head>
<body style="font:24px sans-serif;background:#0b1020;color:#eee"><h1>Recorder check</h1>
<button id="go" style="font-size:28px;padding:12px 24px">Play the tone</button>
<audio id="a" src="/tone.wav" preload="auto"></audio>
<p id="out">waiting</p>
<script>document.getElementById('go').addEventListener('click', function () {
  document.getElementById('a').play(); document.getElementById('out').textContent = 'played'; });</script>
</body></html>"""


def make_wav(path, seconds=0.5, hz=440, rate=48000):
    n = int(seconds * rate)
    samples = array.array("h", (int(20000 * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


def first_loud_second(mp4, threshold=2000):
    """Decode the audio of an mp4 to 16 bit mono and return the time of the first loud sample."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    for i, v in enumerate(samples):
        if abs(v) > threshold:
            return i / 8000.0
    return None


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    folder = tmp_path_factory.mktemp("site")
    (folder / "index.html").write_text(PAGE, encoding="utf-8")
    (folder / "second.html").write_text(PAGE.replace("Recorder check", "Second"), encoding="utf-8")
    make_wav(folder / "tone.wav")
    with record_scene.StaticSite(folder) as base:
        yield base


def test_clean_url_server(site):
    import urllib.request
    assert b"Second" in urllib.request.urlopen(site + "/second").read()
    assert urllib.request.urlopen(site + "/tone.wav").headers["Content-Type"].startswith("audio")


def test_scene_list_is_complete():
    nums = [s.number for s in scenes.SCENES]
    assert nums == ["01", "02", "03", "04", "05", "06", "06b", "07", "08", "09"]
    assert [(s.script_start, s.script_end) for s in scenes.SCENES] == [(0, 12), (12, 25), (25, 40), (40, 60), (60, 90), (90, 108), (108, 118), (108, 123), (123, 153), (153, 175)]
    assert not [s.number for s in scenes.SCENES if s.stub]
    for s in scenes.SCENES:
        assert callable(s.run) and s.say and s.tag


def test_plan_places_wav_at_the_right_offset(tmp_path):
    wav = make_wav(tmp_path / "voice.wav")
    events = [{"t": 4.25, "src": "http://127.0.0.1:1/voice.wav", "file": str(wav), "offset": 0.0, "volume": 1.0},
              {"t": 1.0, "src": "http://127.0.0.1:1/missing.wav", "file": None},
              {"t": 3.0, "src": "x.wav", "file": str(wav), "muted": True}]
    placed, skipped = mux_audio.plan_events(events, scene_start=1.25, roots=[tmp_path])
    assert len(placed) == 1 and placed[0]["delay_ms"] == 3000 and placed[0]["trim"] == 0.0
    assert {s["why"] for s in skipped} == {"no local file for this source", "muted"}
    # a sound that began before the cut is trimmed, not delayed
    placed, _ = mux_audio.plan_events([{"t": 1.0, "file": str(wav), "offset": 0.0}], scene_start=1.5)
    assert placed[0]["delay_ms"] == 0 and placed[0]["trim"] == 0.5
    graph = mux_audio.build_filter(mux_audio.plan_events([{"t": 2.0, "file": str(wav)}], 0.0)[0], 5.0)
    assert "adelay=2000|2000" in graph and "amix=inputs=1" in graph and "[aout]" in graph


def test_resolve_audio_file(tmp_path):
    wav = make_wav(tmp_path / "a-1234.wav")
    assert mux_audio.resolve_audio_file("http://127.0.0.1:8810/anything/a-1234.wav", [tmp_path]) == tmp_path / "a-1234.wav"
    assert mux_audio.resolve_audio_file(str(wav)) == wav
    assert mux_audio.resolve_audio_file("blob:http://x/abc") is None


def test_mux_puts_sound_at_its_time(tmp_path):
    video = tmp_path / "silent.webm"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1440x810:r=25:d=4", "-c:v", "libvpx", str(video)], check=True)
    wav = make_wav(tmp_path / "tone.wav", 0.4)
    tl = {"scene_start": 0.5, "scene_end": 3.5, "events": [{"t": 2.0, "file": str(wav), "src": "tone.wav", "offset": 0.0, "volume": 1.0}]}
    rep = mux_audio.mux(video, tl, tmp_path / "out.mp4")
    assert rep["has_audio"] and rep["width"] == 1440 and abs(rep["duration"] - 3.0) < 0.15
    at = first_loud_second(tmp_path / "out.mp4")
    assert at is not None and abs(at - 1.5) < 0.08, at   # 2.0 s on the raw clock, 0.5 s cut away


def test_record_three_second_scene(site, tmp_path):
    def run(rec):
        rec.goto("/", wait_for="#go")
        rec.begin()
        rec.pause(0.4)
        rec.click("#go", after=0.3)
        rec.page.wait_for_function("document.getElementById('out').textContent === 'played'")

    scene = scenes.Scene("99", "local-check", "Local check", 0, 3, "Local run", "caption", "line", run=run)
    # the page serves tone.wav from its own folder; the recorder logs the audio element's src and the mux finds the file by name
    wav_dir = tmp_path / "audio"
    wav_dir.mkdir()
    make_wav(wav_dir / "tone.wav")
    orig = mux_audio.DEFAULT_ROOTS
    mux_audio.DEFAULT_ROOTS = [wav_dir] + list(orig)
    try:
        rep = record_scene.record(scene, tmp_path / "video", base_url=site)
    finally:
        mux_audio.DEFAULT_ROOTS = orig
    mp4 = Path(rep["out"])
    assert mp4.name == "scene-99-local-check.mp4" and mp4.is_file()
    info = mux_audio.probe(mp4)
    assert info["width"] == 1440 and info["height"] == 810
    assert info["video_codec"] == "h264" and info["audio_codec"] == "aac"
    assert 2.7 <= info["duration"] <= 3.4, info
    assert info["has_audio"]
    assert len(rep["placed"]) == 1, rep["skipped"]
    t = json.loads((tmp_path / "video" / "timing.json").read_text(encoding="utf-8"))
    e = t["scenes"][0]
    assert e["number"] == "99" and e["audio_events"] and e["narration"]["speaker"] == "Sri" and e["start"] == 0.0 and e["end"] == 3.0
    # the sound begins when the click happened: after the begin() pause of 0.4 s, inside the first second or two
    assert 0.3 <= e["audio_events"][0]["video_time"] <= 2.5
    at = first_loud_second(mp4)
    assert at is not None and abs(at - e["audio_events"][0]["video_time"]) < 0.12
