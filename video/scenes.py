"""The nine scenes of the Clearwake video (VIDEO_SCRIPT.md), one function each.

Each scene function takes a Recorder (scripts/record_scene.py), opens its page, scrolls to the first frame it wants, calls rec.begin()
and then moves, hovers, clicks and scrolls at a human pace. Everything before rec.begin() is cut away. The recorder holds the last
frame until the scene reaches its script window, so a clip is as long as its slot in the script.

Scenes that need a voice (the rules by voice, the two real decisions) are stubs for the agent that builds them: the signature,
the window and a TODO with the steps. The recorder refuses to run a stub.

Sri speaks the narration. The line of each scene is kept here only so timing.json can show it in the slot.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Scene:
    number: str
    slug: str
    title: str
    script_start: int          # seconds in the finished video
    script_end: int
    tag: str                   # the label top left of the shot (VIDEO_SCRIPT.md)
    caption: str
    say: str                   # Sri's line for the slot
    needs: str = "site"        # site: a clean URL server over site/; console: python -m clearwake --port 8810
    run: Optional[Callable] = None
    stub: bool = False
    todo: str = ""


def _count(rec, selector):
    return rec.page.locator(selector).count()


# --------------------------------------------------------------------------------------------------------- 0:00 to 0:12
def scene_01_real_result(rec):
    """PayPal's own record of case 3 on screen from the first frame: RESOLVED at INQUIRY, USD 5.00."""
    rec.goto("/control-room", wait_for="#case-3")
    rec.page.wait_for_function("document.querySelectorAll('#case-cards .case').length >= 10")
    rec.scroll_to("#case-3", top=150, duration=0.1)
    rec.pause(0.4)
    rec.begin()
    rec.pause(1.6)
    rec.hover("#case-3", dwell=2.4, dx=0.3, dy=0.12)       # the line: PayPal's record reads RESOLVED at INQUIRY
    rec.hover("#case-3", dwell=2.6, dx=0.72, dy=0.3)        # PayPal's own record: status, stage, amount asked
    rec.hold_until(12)


# --------------------------------------------------------------------------------------------------------- 0:12 to 0:25
def _break_run(rec, attack):
    rec.goto("/break", wait_for="#run")
    rec.page.wait_for_function("document.querySelector('#label') && !/Loading/.test(document.querySelector('#label').textContent)")
    rec.click(f"label.attack:has(input[value={attack}])", after=0.4)
    rec.click("#run", after=0.9)
    rec.page.wait_for_selector("#result .side.guarded")


def scene_02_claim_and_bad_outcome(rec):
    """Break it, the attack run on the unguarded agent: the lost response is retried and the customer is paid twice."""
    rec.goto("/break", wait_for="#run")
    rec.page.wait_for_function("document.querySelector('#label') && !/Loading/.test(document.querySelector('#label').textContent)")
    rec.scroll_to("h2#h-pick, .picker", top=100, duration=0.1)
    rec.begin()
    rec.pause(0.5)
    rec.hover("label.attack:has(input[value=lost_response])", dwell=0.5)
    rec.click("#run", after=0.7)
    rec.page.wait_for_selector("#result .side.unguarded")
    rec.scroll_to("#result .sides", top=110, duration=1.0)
    rec.hover("#result .side.unguarded", dwell=2.2, dx=0.3, dy=0.25)
    rec.scroll_to("#h-tot", top=110, duration=1.0)
    rec.hover("#totals", dwell=1.6)


# --------------------------------------------------------------------------------------------------------- 0:25 to 0:40
def scene_03_same_action_stopped(rec):
    """Break it, the same fault through the guard: zero paid, the over limit request held for a person."""
    rec.goto("/break", wait_for="#run")
    rec.page.wait_for_function("document.querySelector('#label') && !/Loading/.test(document.querySelector('#label').textContent)")
    rec.scroll_to(".picker", top=100, duration=0.1)
    rec.begin()
    rec.pause(0.5)
    rec.click("label.attack:has(input[value=over_limit])", after=0.3)
    rec.click("#run", after=0.7)
    rec.page.wait_for_selector("#result .side.guarded")
    rec.scroll_to("#result .sides", top=110, duration=1.0)
    rec.hover("#result .side.guarded", dwell=2.6, dx=0.3, dy=0.25)
    rec.scroll_to("#result .receipts", top=110, duration=1.0)
    rec.hover("#result .receipts", dwell=1.8)


# --------------------------------------------------------------------------------------------------------- 0:40 to 1:00
RULE_LINE = "Refund anything under $5 that has not arrived in 10 days. Ask me above that. Never refund twice."
CASE4_LINE = "Approve case 4"
CASE9_LINE = "Don't pay case 9, send the proof"


def _wait(rec, test, timeout=90.0, what="the page"):
    """Poll a Python test (locators only: the console's policy forbids string scripts) until it holds."""
    import time
    end = time.time() + timeout
    while time.time() < end:
        if test():
            return
        rec.page.wait_for_timeout(250)
    raise RuntimeError(f"timed out waiting for {what}")


def _voice_ready(rec):
    _wait(rec, lambda: rec.page.locator("#owner").is_visible(), 20, "the owner button (Sarvam must be active)")


def _voice_command(rec, line, confirm=True, read_dwell=2.2):
    """The owner's voice (Sarvam Bulbul) says the line; Sarvam Saaras hears it; the page reads it back; Yes confirms.
    Sarvam is called only for lines not yet cached, and the owner's speech is heard once per command."""
    _voice_ready(rec)
    rec.page.evaluate("(t) => { document.querySelector('#text').value = t; }", line)
    before = rec.page.locator("#meta").inner_text()
    rec.click("#owner", after=0.3)
    _wait(rec, lambda: rec.page.locator("#readback-card").is_visible() or (rec.page.locator("#meta").inner_text() != before and "source: voice" in rec.page.locator("#meta").inner_text()), 90, "the readback or the answer")
    rec.hover("#transcript", dwell=read_dwell, dx=0.3)
    if confirm and rec.page.locator("#readback-card").is_visible():
        rec.hover("#readback", dwell=1.8, dx=0.3)
        rec.click("#yes", after=0.5)
        _wait(rec, lambda: not rec.page.locator("#readback-card").is_visible(), 90, "the confirmed answer")
    rec.page.wait_for_timeout(600)


def scene_04_rules_by_voice(rec):
    """The owner says the rule once on the voice page: the words heard, read back in plain words, Yes, then the signed policy hash."""
    rec.goto("/voice", wait_for="#owner")
    _voice_ready(rec)
    rec.begin()
    rec.pause(0.8)
    _voice_command(rec, RULE_LINE)
    rec.hover("#meta", dwell=2.4, dx=0.3)
    rec.hold_until(20)


# --------------------------------------------------------------------------------------------------------- 1:00 to 1:30
def scene_05_anatomy(rec):
    """Proof page, anatomy: one dispute, six layers. Explode, the case 3 bead down the layers, then the layer switch."""
    rec.goto("/proof", wait_for="#anatomy .anat-board")
    rec.scroll_to("#anatomy .anat-board", top=70, duration=0.1)
    rec.pause(0.5)
    rec.begin()
    rec.pause(1.2)
    rec.click("#anatomy .anat-replay", after=0.3)            # explode, then the bead drops through layers 1 to 6 (about 24 s)
    rec.move_to_el("#anatomy .slab[data-layer='3']", duration=1.2)
    rec.hover("#anatomy .slab[data-layer='4']", dwell=0.2)
    rec.hold_until(25.4)
    rec.click("#anatomy .anat-view[data-view='receipts']", after=0.5)   # layer switch: receipts only
    rec.click("#anatomy .anat-view[data-view='paypal']", after=0.5)     # then PayPal's record


# --------------------------------------------------------------------------------------------------------- 1:30 to 1:48
def scene_06_two_agents_settle(rec):
    """Two spoken decisions through the signed policy and the approval record: case 4 approved, case 9 not paid and the proof sent."""
    rec.goto("/voice", wait_for="#owner")
    _voice_ready(rec)
    rec.begin()
    rec.pause(0.8)
    _voice_command(rec, CASE4_LINE)
    rec.hover("#answer", dwell=3.0, dx=0.3)
    rec.hover("#meta", dwell=1.6, dx=0.3)
    _voice_command(rec, CASE9_LINE)
    rec.hover("#answer", dwell=3.0, dx=0.3)
    rec.hover("#meta", dwell=1.6, dx=0.3)


def scene_06b_case4_read_back(rec):
    """Later, the same command again: PayPal's record already reads RESOLVED, so nothing is written a second time and the record is read back."""
    rec.goto("/voice", wait_for="#owner")
    _voice_ready(rec)
    rec.begin()
    rec.pause(0.8)
    _voice_command(rec, CASE4_LINE)
    rec.hover("#answer", dwell=3.0, dx=0.3)
    rec.hover("#meta", dwell=1.6, dx=0.3)


# --------------------------------------------------------------------------------------------------------- 1:48 to 2:03
def scene_07_verify_it(rec):
    """Home page: the Verify button checks every signed log in the browser. Hold on the result."""
    rec.goto("/", wait_for="#verify-all")
    rec.scroll_to("#verify", top=120, duration=0.1)
    rec.pause(0.5)
    rec.begin()
    rec.pause(1.6)
    rec.click("#verify-all", dwell=0.35, after=0.4)
    rec.page.wait_for_function("/^(Pass|Fail)/.test(document.querySelector('#verify-result').textContent.trim())", timeout=30000)
    rec.hover("#verify-result", dwell=3.0, dx=0.3)
    rec.hold_until(15)


# --------------------------------------------------------------------------------------------------------- 2:03 to 2:33
def scene_08_ten_cases(rec):
    """Control Room: the batch of ten counted, the case cards, the dispute ledger with its stage filter."""
    rec.goto("/control-room", wait_for="#tally")
    rec.page.wait_for_function("document.querySelectorAll('#case-cards .case').length >= 10")
    rec.begin()
    for sel, dwell in (("#t-settled", 0.9), ("#t-review", 0.7), ("#t-owner", 0.7), ("#t-mandate", 0.9)):
        rec.hover(sel, dwell=dwell)
    rec.scroll_to("#cases", top=96, duration=1.2)
    for n in (1, 3, 4, 7):
        rec.hover(f"#case-{n}", dwell=0.9, dx=0.3, dy=0.04)
    rec.scroll_to("#disputes", top=90, duration=1.2)
    rec.page.wait_for_selector("#ledger-grid .ag-row")
    rec.hover("#ledger-grid .ag-row", dwell=1.0, dx=0.2)
    rec.move_to_el("#stage-filter", duration=0.8)
    rec.page.select_option("#stage-filter", "INQUIRY")
    rec.pause(1.6)
    rec.page.select_option("#stage-filter", "all")
    rec.pause(0.5)
    rec.hover("#export-csv", dwell=1.0)             # hovered, not clicked: nothing is downloaded
    rec.hold_until(30)


# --------------------------------------------------------------------------------------------------------- 2:33 to 2:55
def _end_numbers():
    """The three numbers of the end card, read from site/data/totals.json (derived from the run files). Fails if one is missing."""
    data = json.loads((ROOT / "site" / "data" / "totals.json").read_text(encoding="utf-8"))
    rows = data["public"] + data["local"]
    find = lambda value: next(r for r in rows if r["value"] == value)
    settled, overpaid = find("4 of 10"), find("USD 2,633.25")
    label = overpaid["label"]
    if "61 double refunds against 0" not in label:
        raise RuntimeError("totals.json no longer carries the double refund count; the end card will not guess it")
    return settled, overpaid


def scene_09_end_card(rec):
    """End card: three numbers, one command, the links. Built from the numbers of the run files."""
    _end_numbers()
    html = (ROOT / "video" / "endcard.html").read_text(encoding="utf-8")
    fill = {"n1": "4 of 10", "l1": "settled at INQUIRY, before a claim", "n2": "USD 0.00", "l2": "overpaid, against USD 2,633.25 for an agent on the PayPal Agent Toolkit alone",
            "n3": "0 double refunds", "l3": "against 61 for an agent on the PayPal Agent Toolkit alone",
            "command": "git clone --recurse-submodules https://github.com/Sriharsan/clearwake.git && cd clearwake && python -m clearwake --port 8810",
            "console": "clearwake-console.onrender.com", "github": "github.com/Sriharsan/clearwake"}
    for k, v in fill.items():
        html = html.replace("{{" + k + "}}", v)
    rec.page.route("**/__video/endcard.html", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
    rec.goto("/__video/endcard.html", wait_for="#cmd")
    rec.begin()
    rec.pause(1.5)
    rec.hover("#n1", dwell=2.2)
    rec.hover("#n2", dwell=2.2)
    rec.hover("#n3", dwell=2.2)
    rec.hover("#cmd", dwell=3.0, dx=0.3)
    rec.move_to(rec.viewport["width"] * 0.9, rec.viewport["height"] * 0.9, duration=1.2)
    rec.hold_until(22)


SCENES = [
    Scene("01", "real-result", "The real result", 0, 12, "Real PayPal sandbox run, case 3", "PayPal's record: RESOLVED at INQUIRY",
          "An AI agent bought something. It never arrived. Five dollars. PayPal's own record reads resolved, at the inquiry stage.", run=scene_01_real_result),
    Scene("02", "claim-and-bad-outcome", "The claim, then the bad outcome", 12, 25, "Planted failure, local run, PayPal Agent Toolkit",
          "200 episodes: USD 2,633.25 overpaid, 61 double refunds",
          "A response is lost, the agent retries, and the customer is paid twice. A message says ignore your limits, and a claim is accepted.", run=scene_02_claim_and_bad_outcome),
    Scene("03", "same-action-stopped", "The same action, stopped", 25, 40, "Planted failure, same faults, same layer",
          "Clearwake: USD 0.00 overpaid, 0 double refunds, 200 of 200 as the owner intended",
          "Same faults through Clearwake. Zero dollars overpaid. Zero double refunds. The injected message is refused before any PayPal call.", run=scene_03_same_action_stopped),
    Scene("04", "rules-by-voice", "Rules said once, by voice", 40, 60, "Real PayPal sandbox run, rules said by the owner",
          "Settle up to USD 5.00. Ask up to USD 9.00. Never more.",
          "Settle an item that has not arrived on its own, up to five dollars. Ask me up to nine. Never more.", needs="console", run=scene_04_rules_by_voice),
    Scene("05", "anatomy", "Anatomy: one dispute, six layers", 60, 90, "Real PayPal sandbox run, case 3", "Settled inside PayPal. Paid once. USD 5.00.",
          "One dispute. Six layers. The skeleton is the owner's rule, said once and signed. The muscles are two agents.", run=scene_05_anatomy),
    Scene("06", "two-agents-settle", "The two agents settle it, live", 90, 108, "Real PayPal sandbox run, buyer agent through a local browser",
          "Model proposed counter. The owner's rule decided wait.",
          "The model drafts. The rules decide. The offer goes alone, through PayPal's own offer call.", needs="console", run=scene_06_two_agents_settle),
    Scene("06b", "case-4-read-back", "Case 4, PayPal's record read back", 108, 118, "Real PayPal sandbox run, read back from PayPal",
          "RESOLVED at CHARGEBACK. One refund of USD 5.00. Nothing written twice.",
          "PayPal's own record now reads resolved. One refund of five dollars, written once.", needs="console", run=scene_06b_case4_read_back),
    Scene("07", "verify-it", "Do not trust us. Check it.", 108, 123, "Verified in your browser", "Two receipts, one dispute id. Change one line, the chain breaks.",
          "Two signed receipts, one from each side, the same dispute id. Verify them offline. Change one line and the chain breaks.", run=scene_07_verify_it),
    Scene("08", "ten-cases", "All ten cases, counted aloud", 123, 153, "Real PayPal sandbox run, batch of 10, read back from PayPal",
          "4 settled, 3 under PayPal review, 2 awaiting the owner, 1 refused by the mandate",
          "Ten cases on the real sandbox. Four settled at inquiry, before a claim. Three answered with proof. Two are waiting for the owner. One was refused by the buyer's mandate.",
          run=scene_08_ten_cases),
    Scene("09", "end-card", "End card: numbers, one command, links", 153, 175, "Verified in your browser",
          "4 of 10 settled. USD 0.00 against USD 2,633.25. 0 against 61 double refunds. clearwake-console.onrender.com  github.com/Sriharsan/clearwake",
          "Four of ten settled before a claim. Zero dollars overpaid against twenty six hundred. Zero double refunds against sixty one. One command runs it.", run=scene_09_end_card),
]


def by_number(number):
    n = str(number).zfill(2)
    for s in SCENES:
        if s.number == n:
            return s
    raise SystemExit(f"no scene {n}; python scripts/record_scene.py --list")
