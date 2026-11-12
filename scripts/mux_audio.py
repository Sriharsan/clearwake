"""Build the sound of one recorded scene and mux it into one finished mp4.

Playwright records pictures only. While a scene runs, scripts/record_scene.py writes an event timeline: every sound the page or the
product plays, with the source file and the video time in seconds. This script places each cached WAV file on that timeline with
ffmpeg (adelay, amix), cuts the start of the video where the scene began, and writes one H.264 and AAC mp4.

  python scripts/mux_audio.py --video raw.webm --timeline raw.events.json --out scene-03-x.mp4

It makes no network call and downloads nothing. ffmpeg and ffprobe must be on PATH.

Timeline file (written by the recorder):
  {"scene_start": 1.2, "scene_end": 16.0 or null, "events": [{"t": 4.31, "src": "http://.../a.wav", "file": "D:/.../a.wav" or null,
   "offset": 0.0, "volume": 1.0, "muted": false, "kind": "media"}]}
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_RATE = 48000
DEFAULT_ROOTS = [ROOT / "data" / "voice-cache", ROOT / "site", ROOT / "web", ROOT / "data", ROOT]


class MuxError(RuntimeError):
    pass


def need_tool(name):
    if not shutil.which(name):
        raise MuxError(f"{name} is not on PATH")


def probe(path):
    """Return the ffprobe summary of a media file: duration, streams, width, height."""
    need_tool("ffprobe")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,duration:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True)
    if out.returncode:
        raise MuxError(f"ffprobe failed for {path}: {out.stderr.strip()[:300]}")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    return {
        "duration": float((data.get("format") or {}).get("duration") or 0.0),
        "has_video": video is not None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": int(video["width"]) if video and video.get("width") else None,
        "height": int(video["height"]) if video and video.get("height") else None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), None),
    }


def resolve_audio_file(src, roots=None):
    """Find the local WAV file behind a src the page played. Returns a Path or None (blob and data URLs have no file)."""
    if not src or src.startswith(("blob:", "data:")):
        return None
    p = Path(src)
    try:
        if p.is_file():
            return p
    except OSError:
        pass
    parsed = urlparse(src)
    path = unquote(parsed.path or "")
    if parsed.scheme == "file":
        cand = Path(path.lstrip("/") if len(path) > 2 and path[2] == ":" else path)
        if cand.is_file():
            return cand
    rel = path.lstrip("/")
    for base in (roots or DEFAULT_ROOTS):
        for cand in (Path(base) / rel, Path(base) / Path(rel).name):
            if rel and cand.is_file():
                return cand
    return None


def plan_events(events, scene_start=0.0, roots=None):
    """Turn recorder events into placements: [{file, delay_ms, trim, volume, t}] on the trimmed video clock, plus skipped events.

    delay_ms is where the sound starts after the first frame of the finished clip. A sound that began before scene_start is
    started late: the part before the cut is trimmed off (trim, in seconds) and the delay is 0.
    """
    placed, skipped = [], []
    for ev in sorted(events, key=lambda e: e.get("t", 0.0)):
        if ev.get("muted") or float(ev.get("volume", 1.0)) <= 0:
            skipped.append({"event": ev, "why": "muted"})
            continue
        f = Path(ev["file"]) if ev.get("file") else resolve_audio_file(ev.get("src"), roots)
        if not f or not Path(f).is_file():
            skipped.append({"event": ev, "why": "no local file for this source"})
            continue
        at = float(ev["t"]) - float(scene_start)
        trim = float(ev.get("offset") or 0.0)
        if at < 0:
            trim += -at
            at = 0.0
        placed.append({"file": str(f), "delay_ms": int(round(at * 1000)), "trim": round(trim, 3),
                       "volume": float(ev.get("volume", 1.0)), "t": float(ev["t"])})
    return placed, skipped


def build_filter(placed, duration, first_input=1):
    """The ffmpeg filter graph for the placements. Inputs numbered from first_input; output label [aout]."""
    parts, labels = [], []
    for i, p in enumerate(placed):
        n = first_input + i
        chain = [f"atrim=start={p['trim']}" if p["trim"] > 0 else "anull", "asetpts=PTS-STARTPTS",
                 f"aresample={SAMPLE_RATE}", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
        if abs(p["volume"] - 1.0) > 1e-6:
            chain.append(f"volume={p['volume']:.4f}")
        chain.append(f"adelay={p['delay_ms']}|{p['delay_ms']}")
        parts.append(f"[{n}:a]{','.join(chain)}[a{i}]")
        labels.append(f"[a{i}]")
    mix = f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
    parts.append(f"{mix}apad=whole_dur={duration:.3f},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[aout]")
    return ";".join(parts)


def mux(video, timeline, out, roots=None, silent_track=True, crf=18, strict=False):
    """Mux the video with the audio built from the timeline. Returns a report dict."""
    need_tool("ffmpeg")
    video, out = Path(video), Path(out)
    tl = timeline if isinstance(timeline, dict) else json.loads(Path(timeline).read_text(encoding="utf-8"))
    src_info = probe(video)
    start = float(tl.get("scene_start") or 0.0)
    end = tl.get("scene_end")
    end = min(float(end), src_info["duration"]) if end else src_info["duration"]
    duration = round(end - start, 3)
    if duration <= 0:
        raise MuxError(f"scene has no length (start {start}, end {end})")
    placed, skipped = plan_events(tl.get("events", []), start, roots)
    if strict and skipped:
        raise MuxError(f"{len(skipped)} audio events have no local file: {[s['event'].get('src') for s in skipped]}")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video)]
    for p in placed:
        cmd += ["-i", p["file"]]
    if placed:
        cmd += ["-filter_complex", build_filter(placed, duration), "-map", "0:v:0", "-map", "[aout]"]
    elif silent_track:
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo", "-map", "0:v:0", "-map", "1:a:0"]
    else:
        cmd += ["-map", "0:v:0"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-r", "25"]
    if placed or silent_track:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE), "-ac", "2"]
    cmd += ["-t", f"{duration:.3f}", "-movflags", "+faststart", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode:
        raise MuxError(f"ffmpeg failed: {res.stderr.strip()[-600:]}")
    info = probe(out)
    return {"out": str(out), "duration": info["duration"], "width": info["width"], "height": info["height"], "has_audio": info["has_audio"],
            "size_bytes": out.stat().st_size, "placed": placed, "skipped": skipped}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, help="the raw Playwright video (webm)")
    ap.add_argument("--timeline", required=True, help="the events json written by the recorder")
    ap.add_argument("--out", required=True, help="the finished mp4")
    ap.add_argument("--no-silent-track", action="store_true", help="leave out the audio stream when the scene has no sound")
    ap.add_argument("--strict", action="store_true", help="fail when a played sound has no local file")
    ap.add_argument("--root", action="append", default=[], help="extra folder to look for audio files (repeatable)")
    a = ap.parse_args(argv)
    roots = [Path(r) for r in a.root] + DEFAULT_ROOTS
    try:
        rep = mux(a.video, a.timeline, a.out, roots=roots, silent_track=not a.no_silent_track, strict=a.strict)
    except MuxError as e:
        print(f"FAIL: {e}")
        return 1
    print(f"wrote {rep['out']}  {rep['duration']:.2f} s  {rep['width']}x{rep['height']}  audio {rep['has_audio']}  "
          f"{rep['size_bytes'] / 1e6:.1f} MB  placed {len(rep['placed'])}  skipped {len(rep['skipped'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
