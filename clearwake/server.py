"""The Clearwake console server. It reuses pinned Relayloom HTTP/session/CSRF handling; the refund workroom page is no longer served (/ goes to /console)."""
from pathlib import Path
from urllib.parse import urlsplit
from http.cookies import CookieError, SimpleCookie

import collections
import io
import json
import os
import re
import secrets
import threading
import time

from http.server import ThreadingHTTPServer

from relayloom.server import Handler, LocalServer, COOKIE
from relayloom.controller import Rejected

from .console import ConsoleError

ASSETS = Path(__file__).resolve().parent.parent / "web"
VERIFY_JS = Path(__file__).resolve().parent.parent / "vendor" / "verdock-core" / "js" / "verify.js"
CONSOLE_COOKIE = "clearwake_console"
MAX_BODY = 1 << 20
# Fixed style blocks that AG Grid 35.3.1 writes while it loads, before the grid gets this page's nonce.
# Listed by exact SHA-256 so nothing else inline is allowed. Recompute them if the vendored file changes.
AG_GRID_STYLE_HASHES = " ".join("'sha256-%s'" % h for h in (
    "vCdgOn5r7+50hv0fSyNA/UhS3G10q3Rc/EvM1j3HJ7g=",
    "n/jLSmeREqUxcuqub7Kuz6vz8MPx1xKx9bOESi5lmvM=",
    "47JG+Icotai/YQ5+MnJnjTV8e9M1nFS1n5DTCW/kAo8=",
    "au60U7LxI343gDbEQU7hZtTc1hbrvGcvU9qGDant0V0=",
    "nf1sroLSakzniJTkX+8i0PIFkSGgWjG5mPGAsgoxIxU=",
    "C6dMyeQ0VQdETHOPKR+JADr0JDElLaNWFWDvMRxLe7o=",
    "TpM9G9ZKBt+31bZ3h4Y0MkoP2aysh7AI0EcoFMnR+k4=",
    "39Q1r3e7Fob1zhI7Z43IDrTh0c5eYSqRiEET+a78i0s=",
    "mvhJWU+0vXpp4dPWZbp+3bA6SYYF0J45O3f81cXqqbo=",
    "SJYVEguegPpBuUcJiD5Y0Okns1caQK/qkZCFglqgsYQ=",
    "KMak0OkUSEgGET+sgHkIV1Y35kopID/yhZfQHXzqdZQ=",
    "4pe1KrAEDwjT6xVouCIg1E8rtZnERw6aaWSiOSRT7j0=",
    "dZJgLOiKwxMaxFF+gbc4rEegWWsPo7iRGxN468zCBCg=",
    "xNhuE0G9r0EEPguBS/EhU3t72C3e45R0mS1nxxhjkGM=",
))
# Files the console serves, each from a fixed path. Nothing else under web/ or vendor/ is reachable.
CONSOLE_ASSETS = {
    "/console": ("console.html", "text/html"), "/console/": ("console.html", "text/html"),
    "/console.css": ("console.css", "text/css"), "/console.js": ("console.js", "text/javascript"),
    "/console-lib.js": ("console-lib.js", "text/javascript"),
    # AG Grid Community 35.3.1, MIT, vendored unchanged (docs/THIRD_PARTY_UI.txt). Its styles carry the page's nonce.
    "/vendor/ag-grid-community.min.js": ("vendor/ag-grid-community-35.3.1.min.js", "text/javascript"),
    "/console-theme.js": ("theme.js", "text/javascript"),
}
# Self hosted fonts (SIL OFL 1.1, docs/THIRD_PARTY.md). Only this file is reachable under /fonts/.
FONT_FILES = ("Figtree-var",)
CONSOLE_ASSETS.update({f"/fonts/{name}.woff2": (f"fonts/{name}.woff2", "font/woff2") for name in FONT_FILES})


# The voice page (mobile first). Plain files under the base policy: script-src 'self', style-src 'self'.
VOICE_ASSETS = {"/voice": ("voice.html", "text/html"), "/voice/": ("voice.html", "text/html"),
                "/voice.css": ("voice.css", "text/css"), "/voice.js": ("voice.js", "text/javascript")}
VOICE_TRANSCRIBE = "/console/api/voice/transcribe"


TOTALS = Path(__file__).resolve().parent.parent / "site" / "data" / "totals.json"
HOSTED_ENV = "CLEARWAKE_HOSTED"


# Extension points: each block below registers one handler and returns None for actions that are not its own.
POST_EXTENSIONS = []   # handler(console, action, body) -> dict or None
GET_EXTENSIONS = []    # handler(console, path) -> dict or None


class RateLimiter:
    """Sliding window per client address and kind of request. Used only in hosted mode (CLEARWAKE_HOSTED=1)."""

    def __init__(self, limits, clock=time.monotonic, window=60.0, max_clients=5000):
        self.limits, self.clock, self.window, self.max_clients = dict(limits), clock, window, max_clients
        self.seen = {}
        self.lock = threading.Lock()

    def allow(self, client, kind):
        """0 when the request may go on, else the whole seconds to wait."""
        now = self.clock()
        with self.lock:
            if len(self.seen) >= self.max_clients and client not in self.seen:  # forget clients idle for a whole window
                self.seen = {c: w for c, w in self.seen.items() if any(slots and now - slots[-1] < self.window for slots in w.values())}
                if len(self.seen) >= self.max_clients:
                    return int(self.window)
            slots = self.seen.setdefault(client, {}).setdefault(kind, collections.deque())
            while slots and now - slots[0] >= self.window:
                slots.popleft()
            if len(slots) >= self.limits[kind]:
                return max(1, int(self.window - (now - slots[0])) + 1)
            slots.append(now)
            return 0


class ClearwakeHandler(Handler):
    server_version = "Clearwake"

    style_nonce = None

    # Hosted mode (CLEARWAKE_HOSTED=1, e.g. on Render): other hosts allowed by name, Secure cookie, per client rate limits.
    def local_origin(self, mutation=False):
        server = self.server
        lan = getattr(server, "lan_hosts", None)   # python -m clearwake --voice-lan: the laptop's own LAN address, over https only
        if lan:
            try:
                host = (self.headers.get("Host") or "").lower()
                if host not in lan:
                    raise ValueError()
                origin = self.headers.get("Origin")
                if origin:
                    parsed = urlsplit(origin)
                    if parsed.scheme != "https" or parsed.netloc.lower() != host or parsed.path or parsed.query or parsed.fragment:
                        raise ValueError()
                if mutation and self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
                    raise ValueError()
            except (ValueError, TypeError):
                raise Rejected("Use this console's own address and same-origin page.", 403)
            return
        if not getattr(server, "hosted", False) or not server.allowed_hosts:
            return super().local_origin(mutation)
        try:
            host = (self.headers.get("Host") or "").lower()
            if host not in server.allowed_hosts:
                raise ValueError()
            origin = self.headers.get("Origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != host or parsed.path or parsed.query or parsed.fragment:
                    raise ValueError()
            if mutation and self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
                raise ValueError()
        except (ValueError, TypeError):
            raise Rejected("Use this console's own address and same-origin page.", 403)

    def client_ip(self):
        # Behind Render's proxy the connecting address is the proxy; the last X-Forwarded-For entry is the one it added.
        forwarded = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
        return forwarded or self.client_address[0]

    def rate_limit(self, kind):
        limiter = getattr(self.server, "limiter", None)
        if limiter is None:
            return
        wait = limiter.allow(self.client_ip(), kind)
        if wait:
            error = Rejected(f"Too many requests from this address. Try again in {wait} s.", 429)
            error.retry_after = wait
            raise error

    def send_header(self, keyword, value):
        # The console page lets in only styles carrying this response's nonce (AG Grid's); everything else stays 'self'.
        if keyword.lower() == "content-security-policy" and self.style_nonce:
            value = value.replace("style-src 'self'", f"style-src 'self' 'nonce-{self.style_nonce}' {AG_GRID_STYLE_HASHES}", 1)
        # Fonts come from this origin only; the base policy has no font-src, so default-src 'none' would block them.
        if keyword.lower() == "content-security-policy" and "font-src" not in value:
            value = value.replace("img-src 'self';", "img-src 'self'; font-src 'self';", 1)
        # AG Grid 35.3.1 embeds its icon font as a data: URI; only the console page, which loads the grid, allows that.
        if keyword.lower() == "content-security-policy" and self.style_nonce:
            value = value.replace("font-src 'self'", "font-src 'self' data:", 1) if "font-src" in value else value
        # Cookies are scoped by host, not port. Keep separate local apps from
        # overwriting each other's sessions while retaining upstream attributes.
        if keyword.lower() == "set-cookie" and value.startswith(COOKIE + "="):
            value = "clearwake_session=" + value[len(COOKIE) + 1:]
        super().send_header(keyword, value)

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        return cookie["clearwake_session"].value if "clearwake_session" in cookie else ""

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/console/api/"):
            return self.console_get(path)
        if path in CONSOLE_ASSETS or path == "/verdock/verify.js":
            name, kind = CONSOLE_ASSETS.get(path, (None, "text/javascript"))
            source = VERIFY_JS if name is None else ASSETS / name
            if kind == "text/html":
                self.style_nonce = secrets.token_urlsafe(18)
                try:
                    return self.send_asset(lambda: source.read_bytes().replace(b"__STYLE_NONCE__", self.style_nonce.encode()), kind)
                finally:
                    self.style_nonce = None
            return self.send_asset(lambda: source.read_bytes(), kind)
        if path in VOICE_ASSETS:  # the phone page: its own strict policy, no inline script or style, no nonce
            name, kind = VOICE_ASSETS[path]
            return self.send_asset(lambda: (ASSETS / name).read_bytes(), kind)
        if path == "/healthz":  # for Render's health check and a keep-warm ping: no data, no origin check, never rate limited
            return self.health()
        if path == "/":  # the refund workroom is not a product page any more
            return self.redirect("/console")
        asset = {"/theme.css": (lambda: (ASSETS / "theme.css").read_bytes(), "text/css")}.get(path)
        if asset is None:
            return super().do_GET()
        return self.send_asset(*asset)

    def health(self):
        body = b'{"ok":true}'
        self.send_response(200); self.headers_common()
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def redirect(self, location):
        self.send_response(302); self.headers_common()
        self.send_header("Location", location); self.send_header("Content-Length", "0"); self.end_headers()

    def send_asset(self, read, kind):
        try:
            self.local_origin()
            body = read()
            self.send_response(200); self.headers_common()
            self.send_header("Content-Type", kind if kind.startswith("font/") else kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except Rejected as error:
            self.response(error.status, {"error": str(error)})
        except OSError:
            self.response(404, {"error": "This file is not installed."})

    # Console API: its own HttpOnly session cookie and an HMAC CSRF token, on top of the same-origin checks.
    def console_sid(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        sid = cookie[CONSOLE_COOKIE].value if CONSOLE_COOKIE in cookie else ""
        return sid if re.fullmatch(r"[0-9a-f]{64}", sid) else ""

    def console_reply(self, status, value, sid=None, retry_after=None):
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status); self.headers_common()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if retry_after:
            self.send_header("Retry-After", str(retry_after))
        if sid:
            secure = "; Secure" if getattr(self.server, "hosted", False) or getattr(self.server, "lan_hosts", None) else ""
            self.send_header("Set-Cookie", f"{CONSOLE_COOKIE}={sid}; Path=/console; HttpOnly; SameSite=Strict; Max-Age=28800{secure}")
        self.end_headers(); self.wfile.write(body)

    def console_get(self, path):
        console = self.server.console
        try:
            self.local_origin()
            if console is None:
                raise Rejected("The console is not configured on this server.", 404)
            self.rate_limit("read")
            if path == "/console/api/session":
                sid = self.console_sid() or secrets.token_hex(32)
                return self.console_reply(200, {"csrf": console.csrf_for(sid), "label": "local run data"}, sid)
            if path == "/console/api/state":
                return self.console_reply(200, console.state())
            if path == "/console/api/negotiation":
                return self.console_reply(200, console.negotiation_log())
            if path == "/console/api/totals":  # measured numbers for the console header, built from the run files
                try:
                    return self.console_reply(200, json.loads(TOTALS.read_text(encoding="utf-8")).get("local", []))
                except (OSError, ValueError):
                    return self.console_reply(200, [])
            if path == "/console/api/receipts":
                return self.console_reply(200, console.receipts())
            for handler in GET_EXTENSIONS:
                answer = handler(console, path)
                if answer is not None:
                    return self.console_reply(200, answer)
            raise Rejected("This page was not found.", 404)
        except (Rejected, ConsoleError) as error:
            self.console_reply(error.status, {"error": str(error)}, retry_after=getattr(error, "retry_after", None))
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def do_POST(self):
        # A refused POST whose body is unread makes Windows reset the socket before the client reads the refusal.
        # Read a bounded body first and replay it, so every route (core and console) answers cleanly.
        original = self.rfile
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        bound = (5 << 20) if urlsplit(self.path).path == VOICE_TRANSCRIBE else MAX_BODY   # a recording may be up to 5 MB
        if 0 < length <= bound:
            self.rfile = io.BytesIO(original.read(length))
        try:
            self.route_post()
        finally:
            self.rfile = original

    def route_post(self):
        path = urlsplit(self.path).path
        if not path.startswith("/console/api/"):
            return super().do_POST()
        console = self.server.console
        try:
            self.local_origin(mutation=True)
            if console is None:
                raise Rejected("The console is not configured on this server.", 404)
            self.rate_limit("write")
            if path == VOICE_TRANSCRIBE:   # audio bytes, not JSON: same origin, rate limit and CSRF checks as every console POST
                console.check_csrf(self.console_sid(), self.headers.get("X-Clearwake-CSRF", ""))
                from . import voice
                return self.console_reply(200, voice.handle_transcribe(self, console))
            body = self.body()
            console.check_csrf(self.console_sid(), self.headers.get("X-Clearwake-CSRF", ""))
            action = path[len("/console/api/"):]
            result = next((r for r in (handler(console, action, body) for handler in POST_EXTENSIONS) if r is not None), None)
            if result is not None:
                pass  # an extension block (below) answered
            elif action == "buy":
                result = console.buy(body.get("request"))
            elif action == "case":
                result = console.run_case(body.get("case"))
            elif action == "approve":
                result = console.approve(body.get("approval_id"), body.get("approver"))
            elif action == "reconcile":
                result = console.reconcile(body.get("case_id"))
            elif action == "negotiate":
                result = console.start_negotiation()
            elif action == "reset":
                result = console.reset(wipe=self.server.hosted)
            else:
                raise Rejected("Unknown action.", 404)
            self.console_reply(200, result)
        except (Rejected, ConsoleError) as error:
            self.console_reply(error.status, {"error": str(error)}, retry_after=getattr(error, "retry_after", None))
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            self.console_reply(500, {"error": "The console action could not be completed. Nothing was retried."})


def hosted_from_environment():
    return os.environ.get(HOSTED_ENV) == "1"


class ClearwakeServer(LocalServer):
    def __init__(self, address, controller, console=None, hosted=None, clock=time.monotonic):
        self.hosted = hosted_from_environment() if hosted is None else bool(hosted)
        if self.hosted and address[0] not in ("127.0.0.1", "::1", "localhost"):
            # Only hosted mode (CLEARWAKE_HOSTED=1) may listen beyond loopback. Otherwise LocalServer refuses, as before.
            self.controller = controller
            self.stream_slots = threading.BoundedSemaphore(12)
            ThreadingHTTPServer.__init__(self, address, ClearwakeHandler)
        else:
            super().__init__(address, controller)
        self.RequestHandlerClass = ClearwakeHandler
        self.console = console
        if console is not None:
            console.hosted = self.hosted
        names = [h.strip().lower() for h in os.environ.get("CLEARWAKE_ALLOWED_HOSTS", "").split(",") if h.strip()]
        render = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
        self.allowed_hosts = set(names + ([render] if render else []))
        # Per client address and minute. Writes run a case or a purchase, so they get the smaller allowance.
        self.limiter = RateLimiter({"read": int(os.environ.get("CLEARWAKE_RATE_READ", "120")),
                                    "write": int(os.environ.get("CLEARWAKE_RATE_WRITE", "20")),
                                    "voice": int(os.environ.get("CLEARWAKE_RATE_VOICE", "6"))}, clock) if self.hosted else None


# ===== BEGIN plain words rules routes (typed path). A voice block can sit below this one and append its own handlers. =====
def rules_post(console, action, body):
    if action == "rules/propose":
        return console.rules_propose(body.get("text"), body.get("role", "merchant"))
    if action == "rules/confirm":
        return console.rules_confirm(body.get("role", "merchant"), body.get("rules_hash"), "typed", None)
    return None


POST_EXTENSIONS.append(rules_post)
# ===== END plain words rules routes =====


# ===== BEGIN voice routes (clearwake/voice.py): status, turn (a transcript or typed text in, one answer out), answer (Yes or No tap). =====
def voice_post(console, action, body):
    if not action.startswith("voice/"):
        return None
    from . import voice
    return voice.post_extension(console, action, body)


def voice_get(console, path):
    if not path.startswith("/console/api/voice/"):
        return None
    from . import voice
    return voice.get_extension(console, path)


POST_EXTENSIONS.append(voice_post)
GET_EXTENSIONS.append(voice_get)
# ===== END voice routes =====
