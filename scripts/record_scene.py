"""Record one scene of the Clearwake video as one finished mp4.

  python scripts/record_scene.py --list
  python scripts/record_scene.py --scene 07 [--base-url http://127.0.0.1:8820] [--out "D:/paypal hackathon/video"]
  python scripts/record_scene.py --all

What a recording is: a Chromium screen video of the page, 1440 pixels wide, with the page zoomed to 125 percent (CSS zoom, so the
page lays out about 1152 pixels wide), a visible cursor with click ripples, and smooth, human paced mouse moves. No narration is added: Sri speaks it.
Sound is kept as an event timeline (the page's audio elements and Web Audio sources, with the src file and the video time);
scripts/mux_audio.py builds the audio track from the cached WAV files at those times and writes the mp4.

Nothing here calls Sarvam, PayPal or any outside host. Site scenes run against a local clean URL server over site/ unless
--base-url is given. Console scenes expect the local console (python -m clearwake --port 8810).
"""
import argparse
import datetime as dt
import json
import math
import mimetypes
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import mux_audio  # noqa: E402

DEFAULT_OUT = Path(r"D:\paypal hackathon\video")
VIDEO_W, VIDEO_H = 1440, 810
ZOOM = 1.25
SITE = ROOT / "site"
CONSOLE_URL = "http://127.0.0.1:8810"

# ---------------------------------------------------------------------------------------------------------------------------
# Page side scripts. Both run in every page before its own code. They use only the DOM and CSSOM (no style element, no inline
# style attribute), so they work under the strict CSP of the site pages.

ZOOM_JS = r"""
(() => {
  if (window.top !== window) return;
  const apply = () => { if (document.documentElement) { document.documentElement.style.zoom = '__ZOOM__'; return true; } return false; };
  if (!apply()) { const mo = new MutationObserver(() => { if (apply()) mo.disconnect(); }); mo.observe(document, { childList: true }); }
})();
"""

CURSOR_JS = r"""
(() => {
  if (window.top !== window || window.__cwCursor) return;
  window.__cwCursor = true;
  const NS = 'http://www.w3.org/2000/svg';
  let host = null, arrow = null, x = -80, y = -80;
  function build() {
    if (host || !document.documentElement) return;
    host = document.createElement('div');
    host.id = '__cw_cursor';
    const s = host.style;
    s.position = 'fixed'; s.left = '0'; s.top = '0'; s.width = '0'; s.height = '0'; s.zIndex = '2147483647'; s.pointerEvents = 'none'; s.zoom = String(1 / __ZOOM__);
    arrow = document.createElementNS(NS, 'svg');
    arrow.setAttribute('width', '42'); arrow.setAttribute('height', '42'); arrow.setAttribute('viewBox', '0 0 24 24');
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', 'M4 2.5 L4 19.5 L8.4 15.6 L11.3 22.2 L14.2 20.9 L11.3 14.5 L17.2 14.5 Z');
    p.setAttribute('fill', '#ffffff'); p.setAttribute('stroke', '#0b0f19'); p.setAttribute('stroke-width', '1.6');
    p.setAttribute('stroke-linejoin', 'round');
    arrow.appendChild(p);
    const a = arrow.style;
    a.position = 'absolute'; a.left = '0'; a.top = '0'; a.overflow = 'visible'; a.transformOrigin = '4px 2.5px';
    a.filter = 'drop-shadow(0 2px 3px rgba(0,0,0,.55))';
    host.appendChild(arrow);
    document.documentElement.appendChild(host);
    place();
  }
  function place() { if (host) host.style.transform = 'translate(' + x + 'px,' + y + 'px)'; }
  function ripple(px, py) {
    if (!host) return;
    const r = document.createElement('div');
    const s = r.style;
    s.position = 'fixed'; s.left = (px - 22) + 'px'; s.top = (py - 22) + 'px'; s.width = '44px'; s.height = '44px';
    s.borderRadius = '50%'; s.border = '3px solid #5eead4'; s.background = 'rgba(94,234,212,.22)'; s.pointerEvents = 'none';
    s.zIndex = '2147483646'; s.boxSizing = 'border-box'; s.zoom = String(1 / __ZOOM__);
    document.documentElement.appendChild(r);
    const an = r.animate([{ transform: 'scale(.25)', opacity: .95 }, { transform: 'scale(1.7)', opacity: 0 }],
      { duration: 650, easing: 'cubic-bezier(.2,.7,.3,1)' });
    an.onfinish = () => r.remove();
  }
  window.addEventListener('mousemove', (e) => { x = e.clientX; y = e.clientY; build(); place(); }, true);
  window.addEventListener('mousedown', (e) => {
    x = e.clientX; y = e.clientY; build(); place(); ripple(x, y);
    if (arrow) arrow.animate([{ transform: 'scale(1)' }, { transform: 'scale(.82)' }], { duration: 110, fill: 'forwards' });
  }, true);
  window.addEventListener('mouseup', () => {
    if (arrow) arrow.animate([{ transform: 'scale(.82)' }, { transform: 'scale(1)' }], { duration: 140, fill: 'forwards' });
  }, true);
  window.__cwCursorMove = (px, py) => { x = px; y = py; build(); place(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build); else build();
})();
"""

AUDIO_JS = r"""
(() => {
  if (window.__cwAudioHook) return;
  window.__cwAudioHook = true;
  const send = (o) => { try { if (window.__cwAudio) window.__cwAudio(o); } catch (e) { /* the page keeps running */ } };
  const last = new WeakMap();
  function media(el, how) {
    const now = performance.now(), prev = last.get(el);
    if (prev && now - prev < 120) return;   // the play() call and its play event are one sound
    last.set(el, now);
    send({ kind: 'media', how: how, src: el.currentSrc || el.src || '', offset: el.currentTime || 0, volume: el.volume, muted: !!el.muted,
           loop: !!el.loop, tag: el.tagName.toLowerCase() });
  }
  const proto = window.HTMLMediaElement && window.HTMLMediaElement.prototype;
  if (proto && proto.play) {
    const orig = proto.play;
    proto.play = function () { const r = orig.apply(this, arguments); media(this, 'play()'); return r; };
  }
  window.addEventListener('play', (e) => { if (e.target && e.target.currentSrc !== undefined) media(e.target, 'event'); }, true);
  // Web Audio: remember which url every decoded buffer came from, report AudioBufferSourceNode.start with that url.
  const urlOf = new WeakMap(), bufUrl = new WeakMap();
  if (window.fetch) {
    const f = window.fetch;
    window.fetch = function (input) {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      return f.apply(this, arguments).then((resp) => {
        try {
          const ab = resp.arrayBuffer;
          resp.arrayBuffer = function () { return ab.apply(this, arguments).then((buf) => { urlOf.set(buf, new URL(url, location.href).href); return buf; }); };
        } catch (e) { /* read only response */ }
        return resp;
      });
    };
  }
  const Ctx = window.BaseAudioContext;
  if (Ctx && Ctx.prototype.decodeAudioData) {
    const dec = Ctx.prototype.decodeAudioData;
    Ctx.prototype.decodeAudioData = function (buf) {
      const u = urlOf.get(buf);
      const p = dec.apply(this, arguments);
      if (p && p.then && u) p.then((ab) => { bufUrl.set(ab, u); });
      return p;
    };
  }
  const Src = window.AudioBufferSourceNode;
  if (Src) {
    const st = Src.prototype.start;
    Src.prototype.start = function (when, offset) {
      send({ kind: 'webaudio', src: (this.buffer && bufUrl.get(this.buffer)) || '', offset: offset || 0, volume: 1, muted: false,
             delay: when || 0, loop: !!this.loop, tag: 'AudioBufferSourceNode' });
      return st.apply(this, arguments);
    };
  }
})();
"""


# ---------------------------------------------------------------------------------------------------------------------------
# Local clean URL server (the pattern of Vercel's cleanUrls: /proof serves proof.html). Localhost only.

class CleanHandler(SimpleHTTPRequestHandler):
    mounts = {}

    def log_message(self, *args):
        pass

    def translate_path(self, path):
        p = unquote(urlparse(path).path)
        for prefix, folder in self.mounts.items():
            if p.startswith(prefix + "/"):
                return str(Path(folder) / p[len(prefix) + 1:])
        root = Path(self.directory)
        rel = p.lstrip("/")
        if rel == "":
            return str(root / "index.html")
        cand = root / rel
        if cand.is_dir():
            return str(cand / "index.html")
        if not cand.suffix and cand.with_suffix(".html").is_file():
            return str(cand.with_suffix(".html"))
        return str(cand)

    def guess_type(self, path):
        if str(path).endswith(".ndjson"):
            return "application/x-ndjson; charset=utf-8"
        return mimetypes.guess_type(path)[0] or "application/octet-stream"


class StaticSite:
    """with StaticSite(folder) as base_url: ... A threaded clean URL server on 127.0.0.1 and a free port."""

    def __init__(self, folder, mounts=None):
        handler = type("Handler", (CleanHandler,), {"mounts": dict(mounts or {})})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(folder)))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


# ---------------------------------------------------------------------------------------------------------------------------

def ease(t):
    """Ease in and out (cubic)."""
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


class Recorder:
    """One browser, one page, one video. Scenes drive it with move_to, hover, click, scroll_to, pause and goto."""

    def __init__(self, base_url, work_dir, size=(VIDEO_W, VIDEO_H), zoom=ZOOM, headless=True, pace=1.0):
        self.base_url = base_url.rstrip("/")
        self.work_dir = Path(work_dir)
        self.size, self.zoom, self.headless, self.pace = size, zoom, headless, pace
        # The window is the full video size. The page is zoomed to 125 percent with CSS zoom on the root element, so it lays out at
        # about 1152 CSS pixels wide and renders at 1440 real pixels (a device scale factor would leave gray bars in the video).
        self.viewport = {"width": size[0], "height": size[1]}
        self.css_viewport = {"width": round(size[0] / zoom), "height": round(size[1] / zoom)}
        self.events = []
        self.scene_start = None
        self.scene_end = None
        self.mx, self.my = self.viewport["width"] * 0.8, self.viewport["height"] * 0.7
        self._pw = self._browser = self._context = self.page = None
        self._t0 = None
        self._flip = 1

    # --- lifecycle
    def start(self):
        from playwright.sync_api import sync_playwright
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless, args=["--autoplay-policy=no-user-gesture-required", "--hide-scrollbars"])
        self._context = self._browser.new_context(
            viewport=self.viewport, device_scale_factor=1, color_scheme="dark", reduced_motion="no-preference",
            record_video_dir=str(self.work_dir), record_video_size={"width": self.size[0], "height": self.size[1]})
        self._context.add_init_script(ZOOM_JS.replace("__ZOOM__", str(self.zoom)))
        self._context.add_init_script(CURSOR_JS.replace("__ZOOM__", str(self.zoom)))
        self._context.add_init_script(AUDIO_JS)
        self._context.expose_function("__cwAudio", self._on_audio)
        self._t0 = time.monotonic()
        self.page = self._context.new_page()
        self.page.set_default_timeout(20000)
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    def close(self):
        for obj in (self._context, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = self._browser = self._context = None

    def now(self):
        """Seconds on the video clock (the video starts when the page is created)."""
        return time.monotonic() - self._t0

    def _on_audio(self, payload):
        ev = {"t": round(self.now(), 3), "kind": payload.get("kind", "media"), "src": payload.get("src", ""),
              "offset": float(payload.get("offset") or 0.0),
              "volume": float(payload.get("volume", 1.0) if payload.get("volume") is not None else 1.0),
              "muted": bool(payload.get("muted")), "loop": bool(payload.get("loop")), "how": payload.get("how", ""),
              "file": None}
        if payload.get("delay"):
            ev["t"] = round(ev["t"] + float(payload["delay"]), 3)
        self.events.append(ev)

    def add_audio(self, file, offset=0.0, volume=1.0, at=None):
        """Log a sound the product played outside the page (a file played by another program). at defaults to now."""
        ev = {"t": round(self.now() if at is None else at, 3), "kind": "external", "src": str(file), "file": str(file),
              "offset": float(offset), "volume": float(volume), "muted": False, "loop": False, "how": "add_audio"}
        self.events.append(ev)
        return ev

    # --- timing
    def pause(self, seconds):
        self.page.wait_for_timeout(max(0, seconds * 1000 * self.pace))

    def begin(self):
        """Mark the first frame of the scene. Everything recorded before this (page load, settling) is cut away."""
        self.scene_start = self.now()

    def elapsed(self):
        return self.now() - (self.scene_start or 0.0)

    def hold_until(self, seconds):
        """Keep the screen still until the scene has run this many seconds."""
        left = seconds - self.elapsed()
        if left > 0:
            self.page.wait_for_timeout(left * 1000)
        return left

    # --- page
    def url(self, path):
        return path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"

    def goto(self, path, wait_for=None, settle=0.9):
        """Open a page and wait until it has settled: load, fonts, network quiet, optional selector, then a short pause."""
        self.page.goto(self.url(path), wait_until="load")
        try:
            self.page.evaluate("document.fonts && document.fonts.ready ? document.fonts.ready.then(() => true) : true")
        except Exception:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        if wait_for:
            self.page.wait_for_selector(wait_for, state="visible")
        self.page.evaluate("window.scrollTo(0, 0)")
        self.page.mouse.move(self.mx, self.my)   # puts the cursor back after a navigation
        self.pause(settle)

    def _loc(self, target):
        return self.page.locator(target).first if isinstance(target, str) else target

    def box(self, target):
        loc = self._loc(target)
        loc.wait_for(state="visible")
        b = loc.bounding_box()
        if not b:
            raise RuntimeError(f"{target} has no box")
        return b

    # --- smooth scrolling
    def scroll_to_y(self, y, duration=None):
        cur = self.page.evaluate("window.scrollY")
        mx = self.page.evaluate("Math.max(0, document.documentElement.scrollHeight - window.innerHeight)")
        y = max(0, min(mx, y))
        dist = abs(y - cur)
        if dist < 2:
            return
        ms = (duration if duration else min(2.2, 0.55 + dist / 1100)) * 1000 * self.pace
        self.page.evaluate("""([target, ms]) => new Promise((done) => {
            const start = window.scrollY, t0 = performance.now(), root = document.documentElement, prev = root.style.scrollBehavior;
            const ease = (t) => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
            root.style.scrollBehavior = 'auto';
            const step = (now) => {
              const p = Math.min(1, (now - t0) / ms);
              window.scrollTo(0, start + (target - start) * ease(p));
              if (p < 1) requestAnimationFrame(step); else { root.style.scrollBehavior = prev; done(window.scrollY); }
            };
            requestAnimationFrame(step);
          })""", [y, ms])

    def scroll_to(self, target, top=110, duration=None):
        """Scroll with easing until the element sits `top` CSS pixels below the top of the window."""
        b = self.box(target)
        self.scroll_to_y(self.page.evaluate("window.scrollY") + b["y"] - top, duration)
        self.pause(0.25)

    def scroll_by(self, dy, duration=None):
        self.scroll_to_y(self.page.evaluate("window.scrollY") + dy, duration)

    def ensure_visible(self, target, margin=150, dx=0.5, dy=0.5):
        """Scroll (with easing) when the point to point at is outside the window, bringing that point to 40 percent of its height."""
        b = self.box(target)
        py = b["y"] + b["height"] * dy
        if py < margin or py > self.viewport["height"] - margin:
            self.scroll_to_y(self.page.evaluate("window.scrollY") + py - self.viewport["height"] * 0.4)
            self.pause(0.2)

    # --- smooth, human paced mouse
    def move_to(self, x, y, duration=None):
        """Move the pointer along a gentle curve with easing. Coordinates are CSS pixels of the window."""
        sx, sy = self.mx, self.my
        dx, dy = x - sx, y - sy
        dist = math.hypot(dx, dy)
        if dist < 1:
            return
        secs = (duration if duration else min(1.5, 0.32 + dist / 1500)) * self.pace
        nx, ny = -dy / dist, dx / dist
        bend = min(60.0, dist * 0.08) * self._flip
        self._flip = -self._flip
        cx, cy = sx + dx * 0.5 + nx * bend, sy + dy * 0.5 + ny * bend
        t0 = time.monotonic()
        while True:
            p = min(1.0, (time.monotonic() - t0) / secs)
            e = ease(p)
            px = (1 - e) ** 2 * sx + 2 * (1 - e) * e * cx + e ** 2 * x
            py = (1 - e) ** 2 * sy + 2 * (1 - e) * e * cy + e ** 2 * y
            self.page.mouse.move(px, py)
            if p >= 1.0:
                break
            self.page.wait_for_timeout(8)
        self.mx, self.my = x, y

    def move_to_el(self, target, dx=0.5, dy=0.5, duration=None):
        self.ensure_visible(target, dx=dx, dy=dy)
        b = self.box(target)
        self.move_to(b["x"] + b["width"] * dx, b["y"] + b["height"] * dy, duration)

    def hover(self, target, dwell=0.7, dx=0.5, dy=0.5):
        self.move_to_el(target, dx, dy)
        self.pause(dwell)

    def click(self, target, dwell=0.2, after=0.5, dx=0.5, dy=0.5):
        self.move_to_el(target, dx, dy)
        self.pause(dwell)
        self.page.mouse.down()
        self.pause(0.09)
        self.page.mouse.up()
        self.pause(after)

    # --- finish
    def finish(self, tail=0.6):
        """Close the page so the video is written. Returns (raw video path, timeline dict)."""
        if self.scene_start is None:
            self.scene_start = 0.0
        self.scene_end = self.now()   # the clip ends here; the tail only lets the video file close cleanly
        self.pause(tail)
        video = self.page.video
        self.page.close()
        raw = Path(video.path())
        self.close()
        return raw, {"scene_start": round(self.scene_start, 3), "scene_end": round(self.scene_end, 3), "events": self.events}


# ---------------------------------------------------------------------------------------------------------------------------

def fmt_clock(sec):
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def update_timing(out_dir, entry, size):
    path = Path(out_dir) / "timing.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    scenes = [s for s in data.get("scenes", []) if s.get("number") != entry["number"]] + [entry]
    scenes.sort(key=lambda s: s["number"])
    data = {"video_size": list(size), "zoom_percent": 125, "format": "mp4, H.264 video, AAC audio, 25 frames per second",
            "updated": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "scenes": scenes}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def record(scene, out_dir, base_url=None, headless=True, pace=1.0, keep_raw=True):
    """Record one Scene (video/scenes.py) to out_dir/scene-<NN>-<slug>.mp4 and update timing.json. Returns the report."""
    if scene.stub:
        raise SystemExit(f"scene {scene.number} ({scene.slug}) is a stub for another agent: {scene.todo}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work" / f"scene-{scene.number}"
    if work.exists():
        for f in work.glob("*"):
            f.unlink()
    target = scene.script_end - scene.script_start
    server = None
    try:
        if base_url is None:
            if scene.needs == "console":
                base_url = CONSOLE_URL
            else:
                server = StaticSite(SITE, mounts={"/__video": ROOT / "video"})
                base_url = server.__enter__()
        rec = Recorder(base_url, work, headless=headless, pace=pace)
        with rec:
            rec.scene = scene
            scene.run(rec)
            if rec.scene_start is None:
                rec.begin()
            ran = rec.elapsed()
            rec.hold_until(target)
            raw, timeline = rec.finish()
    finally:
        if server:
            server.__exit__(None, None, None)
    raw_final = work / f"scene-{scene.number}.webm"
    if raw_final.exists():
        raw_final.unlink()
    raw.replace(raw_final)
    (work / f"scene-{scene.number}.events.json").write_text(json.dumps(timeline, indent=2) + "\n", encoding="utf-8")
    mp4 = out_dir / f"scene-{scene.number}-{scene.slug}.mp4"
    rep = mux_audio.mux(raw_final, timeline, mp4)
    entry = {
        "number": scene.number, "slug": scene.slug, "title": scene.title, "file": mp4.name,
        "script_window": f"{fmt_clock(scene.script_start)} to {fmt_clock(scene.script_end)}",
        "start": float(scene.script_start), "end": float(scene.script_end), "target_duration": float(target),
        "duration": round(rep["duration"], 2), "ran_for": round(ran, 2), "width": rep["width"], "height": rep["height"],
        "tag": scene.tag, "caption": scene.caption,
        "audio_events": [{"video_time": round(p["delay_ms"] / 1000, 3), "file": p["file"], "volume": p["volume"], "trim": p["trim"]} for p in rep["placed"]],
        "audio_events_skipped": [{"src": s["event"].get("src"), "why": s["why"]} for s in rep["skipped"]],
        "narration": {"speaker": "Sri", "slot": f"{fmt_clock(scene.script_start)} to {fmt_clock(scene.script_end)}",
                      "line": scene.say, "note": "Sri records this in his own voice. The recorder adds no narration."},
        "recorded": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    update_timing(out_dir, entry, (VIDEO_W, VIDEO_H))
    if not keep_raw:
        raw_final.unlink(missing_ok=True)
    rep["entry"] = entry
    return rep


def main(argv=None):
    from video import scenes as sc
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list the scenes")
    ap.add_argument("--scene", action="append", default=[], help="scene number, for example 07 (repeatable)")
    ap.add_argument("--all", action="store_true", help="record every scene that is not a stub")
    ap.add_argument("--base-url", default=None, help="page host; default is a local server over site/ (console scenes: http://127.0.0.1:8810)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output folder (default D:\\paypal hackathon\\video)")
    ap.add_argument("--headed", action="store_true", help="show the browser while recording")
    ap.add_argument("--pace", type=float, default=1.0, help="1.0 is the planned pace; 1.5 is slower")
    a = ap.parse_args(argv)
    if a.list or not (a.scene or a.all):
        print(f"{'No':3} {'Window':12} {'Slug':22} {'Needs':8} Status")
        for s in sc.SCENES:
            print(f"{s.number:3} {fmt_clock(s.script_start) + ' to ' + fmt_clock(s.script_end):12} {s.slug:22} {s.needs:8} {'STUB: ' + s.todo[:60] if s.stub else 'ready'}")
        return 0
    todo = [sc.by_number(n) for n in a.scene] if a.scene else [s for s in sc.SCENES if not s.stub]
    for s in todo:
        if s.stub and a.all:
            continue
        print(f"recording scene {s.number} {s.slug} ...", flush=True)
        rep = record(s, a.out, a.base_url, headless=not a.headed, pace=a.pace)
        e = rep["entry"]
        print(f"  {rep['out']}\n  {e['duration']:.2f} s (window {e['target_duration']:.0f} s), {e['width']}x{e['height']}, audio {rep['has_audio']}, "
              f"{rep['size_bytes'] / 1e6:.1f} MB, sounds placed {len(rep['placed'])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
