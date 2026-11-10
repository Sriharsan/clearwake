"""Market price reference from Channel3, used by the buyer mandate check.

Credits are the owner's. Rules enforced here:
- The key is read only from the environment variable CHANNEL3_API_KEY. It is never printed, logged, stored or put in a receipt or an error.
- CHANNEL3_MAX_CALLS is a hard cap on live calls per calendar month (UTC). It defaults to 0, which refuses every live call.
- Every attempted live call is written to data/channel3-usage.json before it is sent, so a crash cannot hide a spend.
- Only the compact result of a query is cached, for 24 hours, so the same query never costs twice. No catalog is stored.
- No retries. A 401, 402, 429, 5xx, a timeout or a bad body ends the check with a note; the caller decides.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
USAGE_PATH = ROOT / "data" / "channel3-usage.json"
ENV_PATH = ROOT / ".env"
URL = "https://api.trychannel3.com/v1/search"
KEY_ENV = "CHANNEL3_API_KEY"
CAP_ENV = "CHANNEL3_MAX_CALLS"
CACHE_SECONDS = 24 * 3600
LIMIT = 5            # products asked for per search; one search costs one credit
TIMEOUT = 8
CACHE_MAX = 200      # compact entries kept; not a catalog
DISCLOSURE = "Channel3 may earn a commission on purchases made through links shown here."


@dataclass
class MarketCheck:
    reference_minor: object   # int or None
    source_domain: object     # str or None
    title: object             # str or None
    brand: object             # str or None
    within_tolerance: object  # True, False, or None when there is no reference or no tolerance
    credits_used: int
    note: str
    ts_ms: int
    currency: str = "USD"

    def to_receipt_params(self):
        """Compact fields only. No key, no catalog, no offer list."""
        return {"reference_minor": self.reference_minor, "currency": self.currency, "source_domain": self.source_domain,
                "within_tolerance": self.within_tolerance, "credits_used": self.credits_used, "note": self.note,
                "title": (self.title or "")[:80] or None, "brand": self.brand}


def _load_key_vars(path=ENV_PATH):
    """Fill only the two Channel3 names from .env; existing environment values win. Values are never returned."""
    path = Path(path)
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"(CHANNEL3_API_KEY|CHANNEL3_MAX_CALLS)=(.*)", raw.strip())
        if m and m[2].strip() and not os.environ.get(m[1]):
            os.environ[m[1]] = m[2].strip()


def max_calls():
    _load_key_vars()
    try:
        return max(0, int(os.environ.get(CAP_ENV, "0")))
    except ValueError:
        return 0


def _month(ts_ms):
    return time.strftime("%Y-%m", time.gmtime(ts_ms / 1000))


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"calls": list(data.get("calls", [])), "cache": dict(data.get("cache", {}))}
    except (OSError, ValueError):
        pass
    return {"calls": [], "cache": {}}


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def calls_this_month(usage_path=None, now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    data = _read(usage_path or USAGE_PATH)
    return sum(1 for c in data["calls"] if _month(c.get("ts_ms", 0)) == _month(now_ms))


def _norm(query, currency):
    return " ".join(str(query).lower().split()) + "|" + currency.upper()


def _reference(body, currency):
    """Median of offer prices in `currency` across the returned products, with the offer nearest the median as the source."""
    rows = []
    for p in (body.get("products") or [])[:LIMIT]:
        for o in (p.get("offers") or []):
            price = o.get("price") or {}
            try:
                value = float(price.get("price"))
            except (TypeError, ValueError):
                continue
            if str(price.get("currency", "")).upper() == currency.upper() and value > 0:
                rows.append((value, o.get("domain"), p.get("title"), p.get("brand_name") or p.get("brand")))
    if not rows:
        return None
    med = statistics.median(v for v, *_ in rows)
    near = min(rows, key=lambda r: abs(r[0] - med))
    brand = near[3]
    if isinstance(brand, dict):
        brand = brand.get("name")
    return int(round(med * 100)), near[1], near[2], brand


def _urllib_transport(url, headers, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, {}
    # timeouts and network errors propagate as OSError and are handled by the caller


def _within(our_price_minor, reference, tolerance_percent):
    if reference is None or tolerance_percent is None:
        return None
    return our_price_minor <= reference * (1 + float(tolerance_percent) / 100)


def _done(ref, wa, credits, note, now, currency):
    if ref:
        minor, domain, title, brand = ref
        return MarketCheck(minor, domain, title, brand, _within(wa[0], minor, wa[1]), credits, note, now, currency)
    return MarketCheck(None, None, None, None, None, credits, note, now, currency)


def price_check(query, our_price_minor, currency="USD", tolerance_percent=None, transport=None, usage_path=None):
    """Ask for the typical retail price of `query`. Never raises for service problems; the note says what happened.

    within_tolerance is None (flag, do not refuse) when no reference could be had."""
    now = int(time.time() * 1000)
    currency = (currency or "USD").upper()
    wa = (our_price_minor, tolerance_percent)
    path = Path(usage_path) if usage_path else USAGE_PATH
    key = _norm(query, currency)
    data = _read(path)
    hit = data["cache"].get(key)
    if hit and now - hit.get("ts_ms", 0) < CACHE_SECONDS * 1000:
        r = hit["result"]
        ref = (r["reference_minor"], r.get("source_domain"), r.get("title"), r.get("brand")) if r.get("reference_minor") else None
        return _done(ref, wa, 0, "cached", now, currency)
    cap = max_calls()
    used = calls_this_month(path, now)
    if cap <= 0:
        return _done(None, wa, 0, "refused: CHANNEL3_MAX_CALLS is 0, no live calls allowed", now, currency)
    if used >= cap:
        return _done(None, wa, 0, f"refused: monthly cap reached ({used} of {cap})", now, currency)
    api_key = os.environ.get(KEY_ENV, "")
    if not api_key:
        return _done(None, wa, 0, "refused: no CHANNEL3_API_KEY in the environment", now, currency)
    # Record the attempt first: the credit may be spent even when the reply fails.
    data["calls"].append({"ts_ms": now, "q": key})
    _write(path, data)
    send = transport or _urllib_transport
    try:
        status, body = send(URL, {"x-api-key": api_key, "content-type": "application/json"}, {"query": str(query), "limit": LIMIT}, TIMEOUT)
    except (OSError, TimeoutError):
        return _done(None, wa, 1, "no reference: network error or timeout, not retried", now, currency)
    except Exception:
        return _done(None, wa, 1, "no reference: transport error, not retried", now, currency)
    if status != 200 or not isinstance(body, dict):
        reasons = {401: "key rejected (401)", 402: "out of credits (402)", 429: "rate limited (429)"}
        why = reasons.get(status) or (f"server error ({status})" if status >= 500 else f"http {status}")
        return _done(None, wa, 1, f"no reference: {why}, not retried", now, currency)
    ref = _reference(body, currency)
    fresh = _read(path)
    fresh["cache"][key] = {"ts_ms": now, "result": ({"reference_minor": ref[0], "source_domain": ref[1], "title": ref[2], "brand": ref[3]} if ref else {"reference_minor": None})}
    if len(fresh["cache"]) > CACHE_MAX:
        for k in sorted(fresh["cache"], key=lambda k: fresh["cache"][k]["ts_ms"])[:len(fresh["cache"]) - CACHE_MAX]:
            del fresh["cache"][k]
    _write(path, fresh)
    return _done(ref, wa, 1, "ok" if ref else "no reference: no offer in this currency", now, currency)


def plan(queries, usage_path=None):
    """What a live run would do: per query cached (free) or live (1 credit), against the cap. Makes no call."""
    now = int(time.time() * 1000)
    path = Path(usage_path) if usage_path else USAGE_PATH
    data = _read(path)
    cap, used = max_calls(), calls_this_month(path, now)
    rows, cost = [], 0
    for q, cur in queries:
        hit = data["cache"].get(_norm(q, cur))
        cached = bool(hit and now - hit.get("ts_ms", 0) < CACHE_SECONDS * 1000)
        rows.append({"query": q, "currency": cur, "cached": cached, "credits": 0 if cached else 1})
        cost += 0 if cached else 1
    return {"queries": rows, "credits": cost, "cap": cap, "used_this_month": used, "allowed": cap - used >= cost}
