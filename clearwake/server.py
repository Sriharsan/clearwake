"""Reuse pinned Relayloom HTTP/session/CSRF/SSE with a reviewed payment view."""
from pathlib import Path
from urllib.parse import urlsplit
from http.cookies import CookieError, SimpleCookie

from relayloom.server import Handler, LocalServer, WEB, COOKIE
from relayloom.controller import Rejected

ASSETS = Path(__file__).resolve().parent.parent / "web"


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
    page = page.replace('<link rel="stylesheet" href="/style.css">', '<link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/payment.css">')
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
        asset = {"/": (workroom_page, "text/html"), "/app.js": (core_script, "text/javascript"),
            "/payment.js": (lambda: (ASSETS / "payment.js").read_bytes(), "text/javascript"),
            "/payment.css": (lambda: (ASSETS / "payment.css").read_bytes(), "text/css")}.get(path)
        if asset is None:
            return super().do_GET()
        try:
            self.local_origin()
            body = asset[0]()
            self.send_response(200); self.headers_common()
            self.send_header("Content-Type", asset[1] + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except Rejected as error:
            self.response(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return


class ClearwakeServer(LocalServer):
    def __init__(self, address, controller):
        super().__init__(address, controller)
        self.RequestHandlerClass = ClearwakeHandler
