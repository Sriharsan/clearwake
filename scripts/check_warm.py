"""Warm response time of the hosted console.

Requests /healthz and /console several times. The first request may be a cold start (the free plan sleeps after 15 minutes
without traffic), so it is recorded apart. Then one warm request is made, a short pause follows, and the next request after
that warm one is the measured "first request after a warm request". It must answer in under 5 seconds.

Result: printed, and saved to data/runs/warm-<date>.json (the file name takes today's date).

Usage:
  python scripts/check_warm.py
  python scripts/check_warm.py --base https://clearwake-console.onrender.com --rounds 5 --limit 5
"""
import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://clearwake-console.onrender.com"


def timed(url):
    started = time.perf_counter()
    try:
        with urlopen(Request(url, headers={"User-Agent": "clearwake-warm-check"}), timeout=90) as reply:
            reply.read(65536)
            code = reply.status
    except Exception as error:  # noqa: BLE001 - the status is the result
        code = getattr(error, "code", 0)
    return {"status": code, "seconds": round(time.perf_counter() - started, 3)}


def measure(base, rounds, pause):
    out = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "base": base, "paths": {}}
    for path in ("/healthz", "/console"):
        url = base.rstrip("/") + path
        cold = timed(url)  # may wake the service
        warm = timed(url)  # a warm request
        time.sleep(pause)
        first_after_warm = timed(url)  # the request that follows a warm one
        later = [timed(url) for _ in range(max(rounds - 3, 0))]
        out["paths"][path] = {"first_request": cold, "warm_request": warm, "first_after_warm": first_after_warm, "later": later}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--rounds", type=int, default=5, help="requests per path (at least 3)")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between the warm request and the measured one")
    parser.add_argument("--limit", type=float, default=5.0, help="seconds allowed when warm")
    args = parser.parse_args()
    result = measure(args.base, max(args.rounds, 3), args.pause)
    failures = []
    for path, row in result["paths"].items():
        measured = [row["warm_request"], row["first_after_warm"], *row["later"]]
        for item in measured:
            if item["status"] != 200 or item["seconds"] >= args.limit:
                failures.append(f"{path}: {item['status']} in {item['seconds']}s")
    result["limit_seconds"] = args.limit
    result["warm_under_limit"] = not failures
    result["failures"] = failures
    folder = ROOT / "data" / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"warm-{date.today().isoformat()}.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"saved {target.relative_to(ROOT).as_posix()}")
    if failures:
        print("FAIL: " + "; ".join(failures))
        return 1
    print(f"OK: every warm request answered 200 in under {args.limit:g} seconds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
