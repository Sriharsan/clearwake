"""The buyer agent's door into PayPal's Resolution Center, driven with Playwright (sync API).

Why a browser: creating a dispute through the Disputes API never worked for us (400 "No permissions to set target_client_id"),
and this app's token has no buyer scopes. The sandbox buyer opens, answers and escalates a dispute in the Resolution Center,
so the buyer agent does the same through a real browser window.

No password is ever typed, stored or printed by this code. The browser profile is a persistent folder (data/buyer-profile/,
git ignored). Sri logs in by hand once in that window (python scripts/buyer_dispute.py --login); later runs reuse the saved session.
If PayPal shows a CAPTCHA, a verification prompt or otherwise blocks the automation, the driver stops, saves a screenshot and raises
NeedsHuman with exact manual steps. It never tries to get past a challenge.

Every step takes a screenshot (data/buyer-shots/, also on failure) and writes one signed receipt to the buyer's own log, linked to
the mandate receipt hash. The text parsing is pure (parse_thread) and unit tested. The selectors are role and visible text based.
VALIDATION: the logic is tested against tests/fixtures/resolution_center/ (a local stand-in, tests only). The real sandbox pages are
validated only by a real run; see docs for what was run.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import re
import threading
import time

from verdock_core.receipts import ReceiptLog, create_seed, load_seed

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "data" / "buyer-profile"
SHOTS = ROOT / "data" / "buyer-shots"
BUYER_DIR = ROOT / "data" / "buyer"
LOGIN_COMMAND = "python scripts/buyer_dispute.py --login"
ACTOR = {"agent": "clearwake-buyer", "user": "buyer-owner"}

REASON_LABEL = {   # visible wording of the three reasons, matched case insensitively; the first that is visible wins
    "item_not_received": re.compile(r"(didn.?t|did not|haven.?t|have not)\s+receive|not received", re.I),
    "not_as_described": re.compile(r"not as described|different from (the )?description", re.I),
    "missing_items": re.compile(r"missing", re.I),
}
BLOCK_WORDS = re.compile(r"captcha|not a robot|verify (that )?you.?re human|verify you are human|security challenge|security check|"
                         r"confirm it.?s you|verification code|enter the code|unusual activity|are you a robot|"
                         r"let.?s make sure it.?s you|one.time (pass)?code", re.I)
BLOCK_FRAMES = ("recaptcha", "hcaptcha", "arkoselabs", "funcaptcha", "captcha")
OFFER = re.compile(r"(?:seller|merchant)\s+offered\s+you\s+a\s+refund\s+of\s+(?:([A-Z]{3})\s+|\$\s?)([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
REQUESTED = re.compile(r"you\s+asked\s+for\s+(?:([A-Z]{3})\s+|\$\s?)([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
DISPUTE_ID = re.compile(r"\b(PP-[A-Z]-[A-Z0-9][A-Z0-9-]{3,40})\b")
SELLER = re.compile(r"^(?:seller|merchant)\s*:\s*(.+)$", re.I)
BUYER = re.compile(r"^you\s*:\s*(.+)$", re.I)


class NeedsHuman(Exception):
    """A person must do this step. Carries the exact manual steps. The driver never tries to get past a challenge."""

    def __init__(self, why, steps):
        super().__init__(why)
        self.why, self.steps = why, list(steps)


class StepFailed(Exception):
    """A step failed after its retries. A screenshot and a failed receipt exist."""


@dataclass(frozen=True)
class Site:
    name: str                 # "paypal-sandbox" or "fixture": written into every receipt
    home_url: str             # the Resolution Center start page
    login_url: str
    login_markers: tuple = ("/signin", "/authflow", "/webapps/auth", "/auth/login")
    dispute_url_template: str = ""   # optional second try when the dispute is not found in the list; "{id}" is replaced


SANDBOX_BASE = "https://www.sandbox.paypal.com"


def sandbox_site():
    return Site("paypal-sandbox", SANDBOX_BASE + "/resolutioncenter/", SANDBOX_BASE + "/signin", dispute_url_template=SANDBOX_BASE + "/resolutioncenter/{id}")


def fixture_site(path=None, query=""):
    page = Path(path) if path else ROOT / "tests" / "fixtures" / "resolution_center" / "index.html"
    return Site("fixture", page.resolve().as_uri() + query, page.resolve().as_uri() + query)


# Pure parsing --------------------------------------------------------------------------------------------------------------

def minor(text):
    try:
        return int((Decimal(text.replace(",", "")) * 100).to_integral_value())
    except (InvalidOperation, AttributeError):
        raise ValueError("Not an amount: " + str(text)[:30]) from None


@dataclass
class Thread:
    dispute_id: str
    status: str = ""
    resolved: bool = False
    escalated: bool = False
    messages: list = field(default_factory=list)      # [("seller" | "buyer", text)]
    offer_minor: int | None = None
    currency: str = ""
    requested_minor: int | None = None
    can_accept: bool = False
    can_escalate: bool = False
    text_sha256: str = ""

    @property
    def seller_replied(self):
        return any(who == "seller" for who, _ in self.messages)

    @property
    def offer_open(self):
        """An offer the buyer can still act on: PayPal shows it and the Accept button is there."""
        return self.offer_minor is not None and self.can_accept and not self.resolved

    def facts(self):
        """What the buyer agent decides from: numbers and flags, never the seller's wording."""
        return {"offer_minor": self.offer_minor if self.offer_open else None, "evidence": self.seller_replied and not self.offer_open,
                "replied": self.seller_replied}


def parse_thread(dispute_id, body_text, can_accept=False, can_escalate=False):
    """Everything the buyer agent reads from a dispute page, from its visible text alone."""
    thread = Thread(dispute_id, can_accept=can_accept, can_escalate=can_escalate,
                    text_sha256=hashlib.sha256(body_text.encode("utf-8")).hexdigest())
    for raw in body_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if (hit := SELLER.match(line)):
            thread.messages.append(("seller", hit[1].strip()))
        elif (hit := BUYER.match(line)):
            thread.messages.append(("buyer", hit[1].strip()))
        elif (hit := re.match(r"^status\s*:\s*(.+)$", line, re.I)):
            thread.status = hit[1].strip()
    low = thread.status.lower()
    thread.resolved = low.startswith("resolved") or "resolved" == low or bool(re.search(r"\bresolved\b", low))
    thread.escalated = "escalated" in low or "now a claim" in body_text.lower()
    if (hit := OFFER.search(body_text)):
        thread.currency = (hit[1] or "USD").upper()
        thread.offer_minor = minor(hit[2])
    if (hit := REQUESTED.search(body_text)):
        thread.requested_minor = minor(hit[2])
        thread.currency = thread.currency or (hit[1] or "USD").upper()
    return thread


def detect_block_text(body_text):
    hit = BLOCK_WORDS.search(body_text or "")
    return hit[0] if hit else ""


def manual_steps(operation, **d):
    """Exact steps for Sri when the browser cannot continue. Each ends by saying what to send back."""
    home = d.get("home", SANDBOX_BASE + "/resolutioncenter/")
    if operation == "login":
        return [f"Run: {LOGIN_COMMAND}", "A browser window opens at the PayPal sandbox sign in page.",
                "Log in by hand as the sandbox PERSONAL (buyer) test account. Do not type the password anywhere else.",
                "Leave the window open until the command prints that the session is saved."]
    if operation == "open_dispute":
        return [f"In the signed in sandbox buyer window open {home}", "Click Report a problem.",
                f"Choose the payment {d.get('transaction', '(the order payment)')}.", f"Choose the reason: {d.get('reason', '')}.",
                f"Ask for {d.get('amount', 'the amount shown')} and paste this message: {d.get('message', '')}",
                "Submit. Copy the dispute id shown and give it to the agent with: --dispute-id ID"]
    if operation == "accept_offer":
        return [f"Open dispute {d.get('dispute_id', '')} in {home}", "Read the seller's offer.", "Click Accept offer and confirm.",
                "Then run the batch or negotiation again: it reads the result from PayPal."]
    if operation == "counter":
        return [f"Open dispute {d.get('dispute_id', '')} in {home}", f"Reply to the seller with: {d.get('message', '')}", "Click Send message."]
    if operation == "escalate":
        return [f"Open dispute {d.get('dispute_id', '')} in {home}", "Decide with the buyer owner. This hands the case to the owner; "
                "press Escalate to claim only if the owner chose that."]
    return [f"Do the step '{operation}' by hand in the sandbox buyer window at {home}"]


# Receipts --------------------------------------------------------------------------------------------------------------------

def open_buyer_log(folder=BUYER_DIR):
    """The buyer agent's own signed log (own key, same format as the merchant's). Mandate and browser steps go in it."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    seed = folder / "buyer.seed"
    if not seed.exists():
        create_seed(str(seed))
    return ReceiptLog(str(folder / "buyer-receipts.ndjson"), load_seed(str(seed)))


class Recorder:
    """One signed receipt and one screenshot per buyer step, each linked to the mandate receipt by hash."""

    def __init__(self, log, mandate_digest, source, shots=SHOTS, clock=time.time):
        self.log, self.mandate_digest, self.source, self.shots, self._n = log, mandate_digest, source, Path(shots), 0
        self._lock, self.steps = threading.Lock(), []
        self.shots.mkdir(parents=True, exist_ok=True)

    def shot(self, page, label):
        with self._lock:
            self._n += 1
            n = self._n
        name = f"{int(time.time())}-{n:03d}-{re.sub('[^A-Za-z0-9_.-]', '-', label)[:60]}.png"
        path = self.shots / name
        try:
            page.screenshot(path=str(path), full_page=True)
            return path
        except Exception:   # a failed screenshot must never hide the real error
            return None

    def step(self, page, context, name, params, success, label=None):
        path = self.shot(page, f"{context}-{label or name}") if page is not None else None
        extra = {"shot": path.name, "shot_sha256": hashlib.sha256(path.read_bytes()).hexdigest()} if path else {"shot": "", "shot_sha256": ""}
        with self._lock:
            line = self.log.append(f"{context}:{name}:{len(self.steps) + 1}", f"clearwake.buyer.{name}",
                                   {**params, **extra, "mandate_receipt": self.mandate_digest, "source": self.source}, bool(success), actor=ACTOR)
            self.steps.append({"step": name, "success": bool(success), "context": context, "shot": extra["shot"]})
        return line


# The driver -------------------------------------------------------------------------------------------------------------------

def visible(locator):
    try:
        return locator.first.is_visible()
    except Exception:
        return False


def is_signed_in(page, site):
    """Signed in = off the sign in pages, no password box, no Log in button, and the Resolution Center is on screen."""
    try:
        if any(m in page.url.lower() for m in site.login_markers):
            return False
        if visible(page.locator("input[type=password]")):
            return False
        if visible(page.get_by_role("button", name=re.compile(r"^\s*(log in|sign in)\s*$", re.I))) or visible(page.get_by_role("link", name=re.compile(r"^\s*(log in|sign in)\s*$", re.I))):
            return False
        return bool(re.search(r"resolution center", page.inner_text("body"), re.I))
    except Exception:
        return False


def blocked(page):
    """Why the page is a challenge (a word or frame), or an empty string. A challenge is never solved by this code."""
    try:
        for frame in page.frames:
            if any(k in (frame.url or "").lower() for k in BLOCK_FRAMES):
                return "challenge frame " + frame.url[:60]
        return detect_block_text(page.inner_text("body"))
    except Exception:
        return ""


def ensure_signed_in(page, site=None, timeout_s=20):
    """True when the saved session is signed in. Otherwise NeedsHuman with the login command; nothing is typed."""
    site = site or sandbox_site()
    if site.home_url.split("#")[0].split("?")[0] not in page.url:
        page.goto(site.home_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if is_signed_in(page, site):
            return True
        if (why := blocked(page)):
            raise NeedsHuman("PayPal shows a challenge (" + why + "). The agent stops here and never bypasses it.", manual_steps("login"))
        time.sleep(0.5)
    raise NeedsHuman("The saved browser session is not signed in.", manual_steps("login"))


def wait_for_login(page, site=None, timeout_s=600, on_wait=None, poll_s=2):
    """Used only by --login: open the sign in page and wait while Sri logs in by hand. Types nothing."""
    site = site or sandbox_site()
    page.goto(site.login_url, wait_until="domcontentloaded", timeout=60000)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        try:
            if not any(m in page.url.lower() for m in site.login_markers) and not visible(page.locator("input[type=password]")) and not blocked(page):
                if "sandbox.paypal.com" in page.url or site.name == "fixture":
                    if site.home_url.split("#")[0].split("?")[0] not in page.url:
                        page.goto(site.home_url, wait_until="domcontentloaded", timeout=60000)
                    if is_signed_in(page, site):
                        return True
        except Exception as error:
            if page.is_closed() or "closed" in str(error).lower():
                raise   # the window was closed: stop instead of waiting for nothing
        if on_wait:
            on_wait()
        time.sleep(poll_s)
    return False


class ResolutionCenter:
    def __init__(self, page, site, recorder, attempts=3, timeout_ms=15000, pause_s=0.5):
        self.page, self.site, self.rec = page, site, recorder
        self.attempts, self.timeout, self.pause = attempts, timeout_ms, pause_s

    # plumbing
    def guard(self, context, name):
        why = blocked(self.page)
        if why:
            self.rec.step(self.page, context, f"{name}.blocked", {"why": why[:120]}, False)
            raise NeedsHuman("PayPal shows a challenge (" + why + "). The agent stops here and never bypasses it.", manual_steps(name, home=self.site.home_url))

    def run(self, context, name, params, fn, success=lambda out: True, summary=lambda out: {}):
        """Retry a step, take a screenshot and write one receipt for the outcome, failed or not."""
        last = None
        for attempt in range(1, self.attempts + 1):
            try:
                self.guard(context, name)
                out = fn()
                self.guard(context, name)
                ok = bool(success(out))
                self.rec.step(self.page, context, name, {**params, **summary(out), "attempt": attempt}, ok)
                return out
            except NeedsHuman:
                raise
            except Exception as error:
                last = error
                self.rec.shot(self.page, f"{context}-{name}-try{attempt}-failed")
                time.sleep(self.pause)
        self.rec.step(self.page, context, f"{name}.failed", {**params, "error": f"{type(last).__name__}: {str(last)[:160]}", "attempts": self.attempts}, False)
        raise StepFailed(f"{name} failed after {self.attempts} tries: {type(last).__name__}") from last

    def home(self):
        if self.site.home_url.split("#")[0].split("?")[0] in self.page.url:
            link = self.page.get_by_role("link", name=re.compile(r"all disputes|resolution center|disputes", re.I)).first
            if visible(link):
                link.click(timeout=self.timeout)
            return
        self.page.goto(self.site.home_url, wait_until="domcontentloaded", timeout=self.timeout * 4)

    def open_view(self, dispute_id):
        self.home()
        link = self.page.get_by_role("link", name=re.compile(re.escape(dispute_id), re.I)).first
        try:
            link.click(timeout=self.timeout)
        except Exception:
            if not self.site.dispute_url_template:
                raise
            self.page.goto(self.site.dispute_url_template.format(id=dispute_id), wait_until="domcontentloaded", timeout=self.timeout * 4)
        self.wait_text(re.escape(dispute_id))

    def wait_text(self, pattern, flags=re.I):
        """Wait until the visible page text matches. Hidden elements do not count."""
        regex = pattern if isinstance(pattern, str) else pattern.pattern
        self.page.wait_for_function("(src) => new RegExp(src, 'i').test(document.body.innerText)", arg=regex, timeout=self.timeout)

    # steps
    def ensure_signed_in(self, context="session"):
        return self.run(context, "signed_in", {}, lambda: ensure_signed_in(self.page, self.site, self.timeout / 1000))

    def open_dispute(self, transaction_id, reason, message, amount=None, context=None):
        """Item not received, not as described, or significant item missing. Returns {"dispute_id": the id the page shows}."""
        if reason not in REASON_LABEL:
            raise ValueError("reason must be one of: " + ", ".join(REASON_LABEL))
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,40}", transaction_id or "") or not (message or "").strip() or len(message) > 2000:
            raise ValueError("A transaction id and a message of at most 2000 characters are required.")
        context = context or transaction_id

        def work():
            page = self.page
            self.home()
            page.get_by_role("button", name=re.compile(r"report a problem|open a dispute|resolve a problem", re.I)).first.click(timeout=self.timeout)
            select = page.get_by_role("combobox", name=re.compile(r"transaction|payment", re.I)).first
            options = select.locator("option")
            wanted = next((o.get_attribute("value") for i in range(options.count()) for o in [options.nth(i)]
                           if transaction_id in (o.inner_text() + (o.get_attribute("value") or ""))), None)
            if wanted is None:
                raise LookupError("The payment is not in the list.")
            select.select_option(value=wanted)
            page.get_by_role("radio", name=REASON_LABEL[reason]).first.check(timeout=self.timeout)
            if amount is not None:
                box = page.get_by_role("textbox", name=re.compile(r"amount", re.I)).first
                if visible(box):
                    box.fill(str(amount))
            page.get_by_role("textbox", name=re.compile(r"message", re.I)).first.fill(message)
            page.get_by_role("button", name=re.compile(r"^\s*(submit|send|open dispute)\s*$", re.I)).first.click(timeout=self.timeout)
            self.wait_text(DISPUTE_ID)
            hit = DISPUTE_ID.search(page.inner_text("body"))
            return {"dispute_id": hit[1]}
        return self.run(context, "open_dispute", {"transaction": transaction_id, "reason": reason, "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
                                                  "amount": str(amount) if amount is not None else ""},
                        work, summary=lambda out: {"dispute_id": out["dispute_id"]})

    def read_thread(self, dispute_id, context=None):
        def work():
            self.open_view(dispute_id)
            page = self.page
            accept = visible(page.get_by_role("button", name=re.compile(r"accept( the)? offer", re.I)))
            claim = visible(page.get_by_role("button", name=re.compile(r"escalate|file a claim|escalate to claim", re.I)))
            return parse_thread(dispute_id, page.inner_text("body"), accept, claim)
        return self.run(context or dispute_id, "read_thread", {"dispute_id": dispute_id}, work,
                        summary=lambda t: {"status": t.status[:60], "offer_minor": t.offer_minor if t.offer_minor is not None else -1,
                                           "seller_messages": sum(1 for who, _ in t.messages if who == "seller"), "text_sha256": t.text_sha256})

    def accept_offer(self, dispute_id, context=None):
        """Press Accept offer. The receipt says the page changed; only PayPal's record (read by the merchant side) says it is done."""
        def work():
            self.open_view(dispute_id)
            self.page.get_by_role("button", name=re.compile(r"accept( the)? offer", re.I)).first.click(timeout=self.timeout)
            confirm = self.page.get_by_role("button", name=re.compile(r"^\s*(confirm|yes|accept)\s*$", re.I)).first
            if visible(confirm):
                confirm.click(timeout=self.timeout)
            self.wait_text(r"resolved")
            return parse_thread(dispute_id, self.page.inner_text("body"))
        return self.run(context or dispute_id, "accept_offer", {"dispute_id": dispute_id}, work, success=lambda t: t.resolved,
                        summary=lambda t: {"status": t.status[:60], "page_shows_resolved": t.resolved})

    def counter(self, dispute_id, message, context=None):
        if not (message or "").strip() or len(message) > 2000:
            raise ValueError("A counter needs a message of at most 2000 characters.")

        def work():
            self.open_view(dispute_id)
            self.page.get_by_role("textbox", name=re.compile(r"reply|message", re.I)).first.fill(message)
            self.page.get_by_role("button", name=re.compile(r"send message|send|reply", re.I)).first.click(timeout=self.timeout)
            self.wait_text(re.escape(message[:40]))
            return parse_thread(dispute_id, self.page.inner_text("body"))
        return self.run(context or dispute_id, "counter", {"dispute_id": dispute_id, "message_sha256": hashlib.sha256(message.encode()).hexdigest()}, work,
                        summary=lambda t: {"status": t.status[:60]})

    def escalate(self, dispute_id, to="owner", rule=None, why="", context=None):
        """to="owner": stop and hand the case to the buyer's owner (screenshot and receipt, nothing pressed).
        to="claim": press PayPal's own escalate to claim. Only when the owner's dispute rule allows it."""
        context = context or dispute_id
        if to not in ("owner", "claim"):
            raise ValueError("Escalate to the owner or to a claim.")
        if to == "owner":
            def view():
                self.open_view(dispute_id)
                return parse_thread(dispute_id, self.page.inner_text("body"))
            return self.run(context, "escalate_to_owner", {"dispute_id": dispute_id, "why": why[:200]}, view, summary=lambda t: {"status": t.status[:60]})
        if rule is None or not getattr(rule, "escalate_to_claim", False):
            self.rec.step(None, context, "escalate_to_claim.refused", {"dispute_id": dispute_id, "why": "the owner's dispute rule does not allow it"}, False)
            raise PermissionError("The owner's dispute rule does not let the agent escalate to a claim.")

        def work():
            self.open_view(dispute_id)
            self.page.get_by_role("button", name=re.compile(r"escalate|file a claim", re.I)).first.click(timeout=self.timeout)
            confirm = self.page.get_by_role("button", name=re.compile(r"^\s*(confirm|yes|continue)\s*$", re.I)).first
            if visible(confirm):
                confirm.click(timeout=self.timeout)
            self.wait_text(r"now a claim|escalated")
            return parse_thread(dispute_id, self.page.inner_text("body"))
        return self.run(context, "escalate_to_claim", {"dispute_id": dispute_id, "why": why[:200]}, work, summary=lambda t: {"status": t.status[:60]})


def chromium_path():
    """The newest full Chromium already installed for Playwright, or None to let Playwright choose its own."""
    import os
    base = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright")
    found = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), key=lambda p: int(re.search(r"chromium-(\d+)", str(p))[1]))
    return str(found[-1]) if found else None


def launch(playwright, profile=PROFILE, headless=False):
    """A persistent Chromium context in the profile folder. The session Sri logged in to by hand lives there."""
    Path(profile).mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(str(profile), headless=headless, viewport={"width": 1280, "height": 900},
                                                       executable_path=None if headless else chromium_path())
    page = context.pages[0] if context.pages else context.new_page()
    return context, page
