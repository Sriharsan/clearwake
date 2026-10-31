"""Reuse pinned Relayloom HTTP/session/CSRF/SSE with a reviewed payment view."""
from pathlib import Path
from urllib.parse import urlsplit
from http.cookies import CookieError, SimpleCookie

import json
import re
import secrets

from relayloom.server import Handler, LocalServer, WEB, COOKIE
from relayloom.controller import Rejected

from .console import ConsoleError

ASSETS = Path(__file__).resolve().parent.parent / "web"
VERIFY_JS = Path(__file__).resolve().parent.parent / "vendor" / "verdock-core" / "js" / "verify.js"
CONSOLE_COOKIE = "clearwake_console"
# Files the console serves, each from a fixed path. Nothing else under web/ or vendor/ is reachable.
CONSOLE_ASSETS = {
    "/console": ("console.html", "text/html"), "/console/": ("console.html", "text/html"),
    "/console.css": ("console.css", "text/css"), "/console.js": ("console.js", "text/javascript"),
    "/console-lib.js": ("console-lib.js", "text/javascript"),
}


def core_script():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    hooks = {
        "snapshot = state;": "snapshot = state; document.dispatchEvent(new CustomEvent('clearwake:state', {detail: state}));",
        "csrf = session.csrf;": "csrf = session.csrf; document.dispatchEvent(new CustomEvent('clearwake:session', {detail: {csrf}}));",
        "function signedOut() {": "function signedOut() { document.dispatchEvent(new CustomEvent('clearwake:clear'));",
    }
    for anchor, replacement in hooks.items():
        if script.count(anchor) != 1:
            raise RuntimeError("Pinned core UI hooks changed. Review the extension before serving it.")
        script = script.replace(anchor, replacement, 1)
    script = script.replace("$('#mode-title').textContent = rehearsal ? 'Local rehearsal' : 'Meta adapter configured';",
        "$('#mode-title').textContent = rehearsal ? 'Local rehearsal' : state.room.mode === 'local-ai' ? 'Local AI configured' : 'Meta adapter configured';")
    script = script.replace("'Synthetic scope · request attempts and reported usage below'",
        "(state.room.mode === 'local-ai' ? 'Local model · synthetic scope · actual attempts recorded' : 'Synthetic scope · request attempts and reported usage below')")
    return script.encode()


def workroom_page():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    page = page.replace("Relayloom · Shared workroom", "Clearwake · Refund operations")
    page = page.replace('aria-label="Relayloom home"', 'aria-label="Clearwake home"')
    page = page.replace('relayloom<span class="brand-dot">', 'clearwake<span class="brand-dot">')
    page = page.replace('<span class="brand-mark" aria-hidden="true">r</span>', '<span class="brand-mark" aria-hidden="true">c</span>')
    page = page.replace('<link rel="stylesheet" href="/style.css">', '<link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/theme.css"><link rel="stylesheet" href="/payment.css">')
    page = page.replace('<script src="/app.js" defer></script>', '<script src="/app.js" defer></script><script src="/payment.js" defer></script>')
    page = page.replace("Change direction.<br>Keep the useful work.", "Resolve the refund.<br>Keep the evidence.")
    page = page.replace("Give your team a goal. Let specialists work together, revise what changes, and check the result before taking action.",
        "Prepare a refund case together. Approve one exact sandbox effect, keep uncertain responses held, and check the provider record before calling it complete.")
    page = page.replace("LOCAL REHEARSAL <span>Built for synthetic work. No live model calls are made in rehearsal mode.</span>",
        "SYNTHETIC WORKROOM <span>Default rehearsal makes no provider/model calls. Live modes need explicit server opt-in.</span>")
    anchor = '<div class="workspace-grid">'
    if page.count(anchor) != 1:
        raise RuntimeError("The pinned core workroom layout changed; review the payment view.")
    return page.replace(anchor, (ASSETS / "payment-panel.html").read_text(encoding="utf-8") + anchor, 1).encode()


class ClearwakeHandler(Handler):
    server_version = "Clearwake"

    def send_header(self, keyword, value):
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
            return self.send_asset(lambda: source.read_bytes(), kind)
        asset = {"/": (workroom_page, "text/html"), "/app.js": (core_script, "text/javascript"),
            "/payment.js": (lambda: (ASSETS / "payment.js").read_bytes(), "text/javascript"),
            "/payment.css": (lambda: (ASSETS / "payment.css").read_bytes(), "text/css"),
            "/theme.css": (lambda: (ASSETS / "theme.css").read_bytes(), "text/css")}.get(path)
        if asset is None:
            return super().do_GET()
        return self.send_asset(*asset)

    def send_asset(self, read, kind):
        try:
            self.local_origin()
            body = read()
            self.send_response(200); self.headers_common()
            self.send_header("Content-Type", kind + "; charset=utf-8")
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

    def console_reply(self, status, value, sid=None):
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status); self.headers_common()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if sid:
            self.send_header("Set-Cookie", f"{CONSOLE_COOKIE}={sid}; Path=/console; HttpOnly; SameSite=Strict; Max-Age=28800")
        self.end_headers(); self.wfile.write(body)

    def console_get(self, path):
        console = self.server.console
        try:
            self.local_origin()
            if console is None:
                raise Rejected("The console is not configured on this server.", 404)
            if path == "/console/api/session":
                sid = self.console_sid() or secrets.token_hex(32)
                return self.console_reply(200, {"csrf": console.csrf_for(sid), "label": "rehearsal, invented records"}, sid)
            if path == "/console/api/state":
                return self.console_reply(200, console.state())
            if path == "/console/api/receipts":
                return self.console_reply(200, console.receipts())
            raise Rejected("This page was not found.", 404)
        except (Rejected, ConsoleError) as error:
            self.console_reply(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def do_POST(self):
        path = urlsplit(self.path).path
        if not path.startswith("/console/api/"):
            return super().do_POST()
        console = self.server.console
        try:
            self.local_origin(mutation=True)
            if console is None:
                raise Rejected("The console is not configured on this server.", 404)
            body = self.body()
            console.check_csrf(self.console_sid(), self.headers.get("X-Clearwake-CSRF", ""))
            action = path[len("/console/api/"):]
            if action == "buy":
                result = console.buy(body.get("request"))
            elif action == "case":
                result = console.run_case(body.get("case"))
            elif action == "approve":
                result = console.approve(body.get("approval_id"), body.get("approver"))
            elif action == "reconcile":
                result = console.reconcile(body.get("case_id"))
            elif action == "reset":
                result = console.reset()
            else:
                raise Rejected("Unknown action.", 404)
            self.console_reply(200, result)
        except (Rejected, ConsoleError) as error:
            self.console_reply(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            self.console_reply(500, {"error": "The console action could not be completed. Nothing was retried."})


class ClearwakeServer(LocalServer):
    def __init__(self, address, controller, console=None):
        super().__init__(address, controller)
        self.RequestHandlerClass = ClearwakeHandler
        self.console = console
