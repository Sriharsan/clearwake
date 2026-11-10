"""Phone mode for voice, built like Relayloom's phone alerts: a SEPARATE small server on the laptop's private LAN address.

    python -m clearwake --phone            plain http on the LAN: the phone's own recorder (file capture) and typing
    python -m clearwake --phone --tls      https with a self signed certificate: the in page microphone as well

The main console stays on loopback. This server exposes only the voice surface (the page, status, transcribe, turn, answer),
and every request needs the random token that is printed with the link and the QR code, compared in constant time. Rules,
questions and approvals go through the same code as the console (clearwake/voice.py), so voice makes the same signed policy
and the same approval record, with source=voice and the transcript hash in the receipts.
"""
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from relayloom.controller import Rejected

from . import voice
from .console import ConsoleError
from .voice_lan import lan_address, make_certificate, qr_ascii
from .voice_strings import LANGUAGES, STRINGS

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DEFAULT_PORT = 8863
MAX_JSON = 16384

BODY = r"""<a class="skip" href="#mic" data-i="p.title">Clearwake voice</a>
<header class="bar"><span class="brand">Clearwake<span> Voice</span></span>
<label class="lang" hidden><span data-i="p.language">Language</span><select id="lang" aria-label="Language"></select></label>
<button class="theme" id="theme" type="button">Light</button></header>
<main>
<p class="label" data-i="p.label"></p>
<div class="notice" id="notice" role="alert" hidden></div>
<section class="mic-block" aria-label="Microphone">
<button class="mic" id="mic" type="button" aria-pressed="false" aria-describedby="status">
<svg viewBox="0 0 24 24" width="56" height="56" aria-hidden="true" focusable="false"><path d="M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4zm6-4a1 1 0 1 1 2 0 8 8 0 0 1-7 7.93V21h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-2.07A8 8 0 0 1 4 11a1 1 0 1 1 2 0 6 6 0 0 0 12 0z" fill="currentColor"/></svg>
<span class="mic-word" id="mic-word"></span></button>
<input id="clip" type="file" accept="audio/*" capture hidden>
<p class="status" id="status" role="status" aria-live="polite"></p>
<div class="meter-row"><meter id="level" min="0" max="1" value="0" aria-label="Microphone level"></meter><span class="timer" id="timer" aria-hidden="true">0:00</span></div>
<button class="plain" id="native" type="button" data-i="p.record_phone"></button>
</section>
<section class="card" aria-labelledby="h-said"><h2 id="h-said" data-i="p.said_h"></h2><p class="chip" id="heard-chip" data-i="p.no_recording"></p>
<p class="big" id="transcript" aria-live="polite" data-i="p.said_empty"></p></section>
<section class="card" id="readback-card" aria-labelledby="h-read" hidden><h2 id="h-read" data-i="p.read_h"></h2><p class="big" id="readback"></p>
<div class="yesno"><button class="yes" id="yes" type="button" data-i="p.yes"></button><button class="no" id="no" type="button" data-i="p.no"></button></div>
<p class="small" data-i="p.also_say"></p></section>
<section class="card" aria-labelledby="h-answer"><h2 id="h-answer" data-i="p.answer_h"></h2><p class="big" id="answer" aria-live="polite" data-i="p.answer_empty"></p>
<p class="small" id="meta"></p><div class="row"><button class="plain" id="speak" type="button" data-i="p.speak_again"></button>
<button class="plain" id="mute" type="button" aria-pressed="false" data-i="p.voice_on"></button></div></section>
<details class="card" id="typed"><summary data-i="p.type_h"></summary><label for="text" data-i="p.type_label"></label>
<textarea id="text" rows="3" maxlength="600" autocomplete="off" autocapitalize="sentences" data-ph="p.type_ph"></textarea>
<button class="send" id="send" type="button" data-i="p.send"></button></details>
<section class="card tips" aria-labelledby="h-tips"><h2 id="h-tips" data-i="p.tips_h"></h2><ul><li data-i="p.tip_rules"></li><li data-i="p.tip_ask"></li><li data-i="p.tip_approve"></li></ul>
<p class="small" data-i="p.tip_note"></p></section>
</main>"""

EXTRA_CSS = ".lang{display:flex;align-items:center;gap:8px;font-size:14px;color:var(--muted)}.lang select{min-height:44px;background:var(--raised);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:0 10px;font-size:16px}"


def page(nonce):
    """ONE self contained page: style and script inline under a per response nonce, no outside fonts, scripts or requests."""
    css = (WEB / "voice.css").read_text(encoding="utf-8") + EXTRA_CSS
    script = (WEB / "voice_phone.js").read_text(encoding="utf-8")
    cfg = json.dumps({"languages": LANGUAGES, "strings": STRINGS}, ensure_ascii=False).replace("</", "<\\/")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><meta name="color-scheme" content="dark light">'
            f'<title>Clearwake voice</title><style nonce="{nonce}">{css}</style></head><body>{BODY}'
            f'<script type="application/json" id="cfg">{cfg}</script><script nonce="{nonce}">{script}</script></body></html>')


class PhoneHandler(BaseHTTPRequestHandler):
    server_version = "ClearwakePhone"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):  # quiet: no tokens in logs
        pass

    # the interface clearwake.voice.handle_transcribe expects
    def rate_limit(self, kind):
        limiter = self.server.limiter
        wait = limiter.allow(self.client_address[0], kind if kind in limiter.limits else "write")
        if wait:
            raise Rejected(f"Too many requests from this address. Try again in {wait} s.", 429)

    def reply(self, status, kind, body, nonce=None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        # Strict: no unsafe-inline. The one inline style and script carry this response's nonce; nothing loads from outside.
        n = f"'nonce-{nonce}'" if nonce else "'none'"
        self.send_header("Content-Security-Policy", f"default-src 'none'; style-src {n}; script-src {n}; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        try:
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, OSError):
            self.close_connection = True

    def json_reply(self, status, value):
        self.reply(status, "application/json; charset=utf-8", json.dumps(value, separators=(",", ":")).encode())

    def authorised(self, query):
        given = (query.get("t") or [""])[0]
        return hmac.compare_digest(given.encode(), self.server.token.encode())

    def drain(self):
        try:
            remaining = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
        except ValueError:
            return
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

    def same_origin(self):
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
            raise Rejected("Use the page from the laptop's link.", 403)

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if not self.authorised(query):
            return self.reply(403, "text/plain; charset=utf-8", b"forbidden")
        if url.path == "/":
            nonce = secrets.token_urlsafe(18)
            return self.reply(200, "text/html; charset=utf-8", page(nonce).encode(), nonce)
        if url.path == "/status":
            return self.json_reply(200, voice.service(self.server.console).status())
        self.reply(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path not in ("/transcribe", "/turn", "/answer") or not self.authorised(query):
            self.drain()
            return self.reply(403 if url.path in ("/transcribe", "/turn", "/answer") else 405, "text/plain; charset=utf-8",
                              b"forbidden" if url.path in ("/transcribe", "/turn", "/answer") else b"not allowed")
        console = self.server.console
        try:
            self.same_origin()
            if url.path == "/transcribe":
                return self.json_reply(200, voice.handle_transcribe(self, console))
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if not 0 < length <= MAX_JSON or (self.headers.get("Content-Type") or "").split(";")[0].lower() != "application/json":
                self.drain()
                raise Rejected("Send a small JSON object.", 413 if length > MAX_JSON else 415)
            self.rate_limit("write")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise Rejected("Send a JSON object.", 400)
            self.json_reply(200, voice.post_extension(console, "voice" + url.path, body))
        except (Rejected, ConsoleError) as error:
            self.json_reply(error.status, {"error": str(error)})
        except (ValueError, UnicodeError):
            self.json_reply(400, {"error": "The request could not be read as JSON."})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            self.json_reply(500, {"error": "That could not be completed. Nothing was retried."})


class PhoneServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # on Windows reuse lets a second copy share the port and answer with a different token

    def __init__(self, address, console, token=None, tls=None):
        from .server import RateLimiter
        self.console, self.token = console, token or secrets.token_urlsafe(16)
        self.limiter = RateLimiter({"read": 240, "write": 40, "voice": 12})
        super().__init__(address, PhoneHandler)
        self.tls = bool(tls)
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(tls[0]), str(tls[1]))
            self.socket = context.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)

    def finish_request(self, request, client_address):
        if self.tls:   # the handshake runs in the connection's own thread, so one stalled phone cannot block the others
            request.settimeout(10)
            try:
                request.do_handshake()
            except (ssl.SSLError, OSError):
                return
        super().finish_request(request, client_address)

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError, OSError)):
            return
        super().handle_error(request, client_address)

    def link(self, host):
        return f"{'https' if self.tls else 'http'}://{host}:{self.server_address[1]}/?t={self.token}"

    def start(self):
        thread = threading.Thread(target=self.serve_forever, daemon=True, name="phone-voice")
        thread.start()
        return thread


def announce(server, ip):
    """Print the phone link and a QR code (segno), like Relayloom's phone alerts."""
    print("Phone voice, local network only. Open the link on a phone on the SAME Wi-Fi, or scan the QR code with the phone camera.")
    print("Anyone with the link can use the voice page, so keep it to yourself.", flush=True)
    link = server.link(ip)
    print(f"\n  {link}", flush=True)
    try:
        import segno
        segno.make(link, error="m").terminal(compact=False, border=2)
    except ImportError:
        print("  (install segno with: python -m pip install segno, to get a QR code here)", flush=True)
    except Exception:
        print("  (the QR code could not be drawn in this window, use the link above)", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phone-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--port", type=int, default=8810, help="the main console, loopback only")
    parser.add_argument("--tls", action="store_true", help="https with a self signed certificate (data/voice-tls/), for the in page microphone")
    parser.add_argument("--lan-ip", default=None, help="use this private address instead of the detected one")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "clearwake.sqlite3")
    parser.add_argument("--console-model", choices=("scripted", "ollama"), default="scripted")
    args = parser.parse_args(argv)
    from .console import Console
    from .controller import RefundController
    from .paypal import RehearsalGateway
    from .server import ClearwakeServer
    ip = lan_address(args.lan_ip)
    tls = None
    if args.tls:
        cert, key, fingerprint = make_certificate(ip)
        tls = (cert, key)
    database = args.database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    controller = RefundController(database, gateway=RehearsalGateway(database.with_name("rehearsal-provider.sqlite3"), "completed"))
    console = Console(database.parent / "console", args.console_model)
    main_server = ClearwakeServer(("127.0.0.1", args.port), controller, console, hosted=False)   # the main console stays on loopback
    phone = PhoneServer((ip, args.phone_port), console, tls=tls)
    threading.Thread(target=main_server.serve_forever, daemon=True, name="console").start()
    print(f"Console (this laptop only): http://127.0.0.1:{args.port}/console")
    announce(phone, ip)
    if args.tls:
        print(f"https with a certificate made on this laptop ({tls[0]}). The phone shows a one time warning: Advanced, then Proceed.")
    else:
        print("Plain http: the phone uses its own recorder. For the in page microphone, run again with --tls.")
    def warm():   # load the Whisper model and run one tiny transcription now, so the first sentence on the phone is not slow
        try:
            transcriber = voice.service(console).transcriber
            if transcriber.available():
                print("Speech model loading", flush=True)
                took = transcriber.warm()
                print(f"Speech model ready ({took / 1000:.0f} s to load and warm up)", flush=True)
            else:
                print("Speech to text is not installed here (model folder or ffmpeg missing). Typing still works.", flush=True)
        except Exception as error:
            print(f"Speech model did not load ({type(error).__name__}). Typing still works.", flush=True)
    threading.Thread(target=warm, daemon=True, name="whisper-warm").start()
    print("Speech to text runs on this laptop. Press Ctrl+C here to stop.", flush=True)
    try:
        phone.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        phone.server_close(); main_server.shutdown(); main_server.server_close(); controller.close()


if __name__ == "__main__":
    main()
