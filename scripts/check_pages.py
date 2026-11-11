"""Page audit: every page at 390px and 1440px, light and dark.

For each page and each combination it checks: the page loads, no console errors, no horizontal scroll, every same site link resolves,
and no placeholder text such as [NAME] except [VIDEO_URL]. Result: PASS or FAIL per page, saved to data/runs/pages-<date>.json.

Usage:
  python scripts/check_pages.py --site https://clearwake-mu.vercel.app --console https://clearwake-console.onrender.com
  python scripts/check_pages.py --site http://127.0.0.1:8890 --console http://127.0.0.1:8891
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE_PAGES = ["/", "/control-room", "/break", "/proof", "/developers"]
CONSOLE_PAGES = ["/console", "/voice"]
VIEWPORTS = (("390", 390, 844), ("1440", 1440, 900))
SCHEMES = ("light", "dark")
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z_]{3,}\]")


def status(url):
    try:
        req = Request(url, headers={"User-Agent": "clearwake-page-audit"})
        with urlopen(req, timeout=40) as reply:
            return reply.status
    except Exception as error:  # noqa: BLE001
        return getattr(error, "code", 0)


def audit_page(browser, base, path, results, link_cache):
    url = urljoin(base, path.lstrip("/")) if path != "/" else base.rstrip("/") + "/"
    entry = {"page": path, "base": base, "checks": []}
    for vname, width, height in VIEWPORTS:
        for scheme in SCHEMES:
            ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m, e=errors: e.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda x, e=errors: e.append(str(x)))
            problems = []
            try:
                reply = page.goto(url, wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(1500)
                if not reply or reply.status >= 400:
                    problems.append(f"status {reply.status if reply else 'none'}")
                over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                if over > 1:
                    problems.append(f"horizontal scroll {over}px")
                text = page.evaluate("document.body.innerText")
                holes = sorted({m for m in PLACEHOLDER.findall(text) if m != "[VIDEO_URL]"})
                if holes:
                    problems.append("placeholder text " + ",".join(holes))
                if errors:
                    problems.append("console errors: " + " | ".join(sorted(set(errors))[:3]))
                hrefs = page.evaluate("[...document.querySelectorAll('a[href]')].map(a=>a.href)")
                for href in sorted(set(hrefs)):
                    parts = urlparse(href)
                    if parts.scheme not in ("http", "https") or "[VIDEO_URL]" in href or "VIDEO_URL" in href:
                        continue
                    same = parts.netloc == urlparse(base).netloc
                    key = href.split("#")[0]
                    if key not in link_cache:
                        link_cache[key] = status(key) if (same or parts.netloc.endswith(("vercel.app", "onrender.com", "github.com"))) else None
                    if link_cache[key] is not None and link_cache[key] >= 400 and not (parts.netloc == "github.com" and link_cache[key] in (403, 429)):
                        problems.append(f"link {href} gives {link_cache[key]}")
            except Exception as error:  # noqa: BLE001
                problems.append("error " + str(error)[:120])
            entry["checks"].append({"viewport": vname, "scheme": scheme, "pass": not problems, "problems": problems})
            ctx.close()
    entry["pass"] = all(c["pass"] for c in entry["checks"])
    results.append(entry)
    print(("PASS " if entry["pass"] else "FAIL "), path, "" if entry["pass"] else "; ".join(sorted({p for c in entry["checks"] for p in c["problems"]}))[:300])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--console", default="")
    args = ap.parse_args()
    results, cache = [], {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for path in SITE_PAGES:
            audit_page(browser, args.site.rstrip("/") + "/", path, results, cache)
        if args.console:
            for path in CONSOLE_PAGES:
                audit_page(browser, args.console.rstrip("/") + "/", path, results, cache)
        browser.close()
    out = {"kind": "page-audit", "mode": "real", "site": args.site, "console": args.console, "date": date.today().isoformat(),
           "viewports": [v[0] for v in VIEWPORTS], "schemes": list(SCHEMES), "pages": results,
           "summary": {"pages": len(results), "pass": sum(1 for r in results if r["pass"]), "fail": sum(1 for r in results if not r["pass"])}}
    path = ROOT / "data" / "runs" / f"pages-{date.today().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("saved", path.name, out["summary"])
    return 0 if not out["summary"]["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())
