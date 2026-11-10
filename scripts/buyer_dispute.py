"""The buyer agent's dispute tool. No password is ever typed, stored or printed by this code.

  python scripts/buyer_dispute.py --login        Sri logs in by hand, once. Opens sandbox.paypal.com in a headed window
                                                 (profile folder data/buyer-profile/, git ignored) and waits until it shows signed in.
  python scripts/buyer_dispute.py --rehearsal    One full negotiation offline (fake provider and the local stand-in page).
  python scripts/buyer_dispute.py --sandbox      One real negotiation against the PayPal sandbox. Needs the login above.
  python scripts/buyer_dispute.py --sandbox --manual-buyer [--resume]
                                                 Same, with no browser here: buyer browser actions are printed as JSON lines and
                                                 PayPal is polled until each one shows. Add --case N (default 3).
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake.buyer_browser import PROFILE, blocked, launch, sandbox_site, wait_for_login  # noqa: E402


def login(timeout_s=900):
    from playwright.sync_api import Error, sync_playwright
    site = sandbox_site()
    print("Opening the PayPal sandbox sign in page in a new window.")
    print("Log in there by hand as the sandbox PERSONAL (buyer) test account. Nothing is typed for you.")
    print(f"The session is saved in {PROFILE.relative_to(ROOT)} and reused by later runs. Waiting up to {max(1, timeout_s // 60)} minute(s).", flush=True)
    with sync_playwright() as pw:
        context, page = launch(pw, PROFILE, headless=False)
        try:
            ok = wait_for_login(page, site, timeout_s=timeout_s)
            if ok:
                (PROFILE / ".clearwake-login-ok").write_text("signed in by hand", encoding="utf-8")
                print("Signed in. Session saved. You can close the window; the agent will reuse it.")
        except Error:
            print("The window was closed before the login finished. Nothing was saved. Run the command again.")
            return 1
        finally:
            try:
                context.close()
            except Exception:
                pass
    if not ok:
        print("Not signed in within the time limit. Run the command again.")
        return 1
    return 0


def negotiate(argv):
    """One full negotiation (buy, open, merchant answers, buyer decides) through the batch loop with a single case."""
    from clearwake import batch
    from clearwake.buyer_browser import NeedsHuman
    from clearwake.models import Adapter
    n = int(argv[argv.index("--case") + 1]) if "--case" in argv else 3
    cases = tuple(c for c in batch.CASES if c.n == n)
    adapter = Adapter(argv[argv.index("--model") + 1] if "--model" in argv else "scripted")
    try:
        if "--rehearsal" in argv:
            report = batch.run_rehearsal(adapter, cases)
        else:
            timeout = int(argv[argv.index("--manual-timeout") + 1]) if "--manual-timeout" in argv else 900
            report = batch.run_sandbox(adapter, cases, manual="--manual-buyer" in argv, resume="--resume" in argv, timeout_s=timeout)
    except NeedsHuman as stop:
        print("A person must do this step:", stop.why)
        for number, line in enumerate(stop.steps, 1):
            print(f"  {number}. {line}")
        return 3
    path = batch.save_report(report)
    print(batch.table(report["cases"]))
    print(report["label"])
    print("Saved", path.relative_to(ROOT))
    return 0 if report["summary"][batch.ERROR] == 0 else 1


def main(argv):
    if "--rehearsal" in argv or "--sandbox" in argv:
        return negotiate(argv)
    if "--login" in argv:
        timeout = int(argv[argv.index("--login-timeout") + 1]) if "--login-timeout" in argv else 900
        return login(timeout)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
