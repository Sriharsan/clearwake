"""Two signed receipt logs, one story: the buyer agent's log and the merchant agent's log verified together, offline.

For every PayPal dispute a case closed on, both logs must hold a signed case_closed receipt that names the same dispute id.
Each log must verify on its own (every signature and the whole hash chain), and every buyer step must carry the hash of a
mandate receipt that is in the buyer's log. A case the buyer agent's mandate refused has no PayPal dispute: only the buyer's log
holds it, with the evidence handed to its person.
"""
import json
from pathlib import Path

from verdock_core.receipts import line_hash, verify_log

BUYER_CLOSED = "clearwake.buyer.case_closed"
MERCHANT_CLOSED = "clearwake.batch.case_closed"
MANDATE = "clearwake.buyer.mandate"


def _lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_pair(buyer_path, buyer_key, merchant_path, merchant_key, dispute_id=None):
    """Returns {"ok", "failures": [exact reasons], "disputes": {id: {...}}, "no_dispute_cases": n}."""
    failures = []
    for label, path, key in (("buyer", buyer_path, buyer_key), ("merchant", merchant_path, merchant_key)):
        if not Path(path).is_file():
            failures.append(f"The {label} log is missing: {path}")
            continue
        result = verify_log(str(path), key)
        if not result["ok"]:
            first = result["failures"][0] if result["failures"] else {}
            failures.append(f"The {label} log does not verify: line {first.get('line')}: {first.get('reason')}")
    if failures:
        return {"ok": False, "failures": failures, "disputes": {}, "no_dispute_cases": 0}
    buyer, merchant = _lines(buyer_path), _lines(merchant_path)
    mandate_hashes = set()
    raw = Path(buyer_path).read_text(encoding="utf-8").splitlines()
    for text, body in zip(raw, buyer):
        if body.get("action_id") == MANDATE:
            mandate_hashes.add(line_hash(text))
    for body in buyer:
        link = body.get("params", {}).get("mandate_receipt")
        if body.get("action_id") != MANDATE and link and set(link) != {"0"} and link not in mandate_hashes:
            failures.append(f"Buyer receipt {body.get('step_id')} names a mandate receipt that is not in the buyer log")
            break
    b_closed = {b["params"]["dispute_id"]: b for b in buyer if b.get("action_id") == BUYER_CLOSED and b["params"].get("dispute_id")}
    m_closed = {m["params"]["dispute"]: m for m in merchant if m.get("action_id") == MERCHANT_CLOSED and m["params"].get("dispute")}
    wanted = [dispute_id] if dispute_id else sorted(set(b_closed) | set(m_closed))
    disputes = {}
    for did in wanted:
        b, m = b_closed.get(did), m_closed.get(did)
        if b is None:
            failures.append(f"Dispute {did}: the merchant log names it but the buyer log has no case_closed receipt for it")
        if m is None:
            failures.append(f"Dispute {did}: the buyer log names it but the merchant log has no case_closed receipt for it")
        if b and m:
            if b["params"].get("outcome") != m["params"].get("outcome"):
                failures.append(f"Dispute {did}: the two logs record different outcomes ({b['params'].get('outcome')} and {m['params'].get('outcome')})")
            if b["params"].get("order_id") != m["params"].get("order"):
                failures.append(f"Dispute {did}: the two logs name different orders")
            disputes[did] = {"outcome": b["params"].get("outcome"), "order": m["params"].get("order"), "paypal_status": m["params"].get("paypal_status")}
    if dispute_id and not wanted:
        failures.append("No dispute id given")
    none = sum(1 for b in buyer if b.get("action_id") == BUYER_CLOSED and not b["params"].get("dispute_id"))
    if not wanted and not none:
        failures.append("Neither log holds a closed case")
    return {"ok": not failures, "failures": failures, "disputes": disputes, "no_dispute_cases": none}


def verify_report(report, base):
    """Verify the pair of logs a batch report names (paths relative to the folder holding the report)."""
    logs = report.get("logs") or {}
    if not logs:
        return {"ok": False, "failures": ["The report names no saved logs"], "disputes": {}, "no_dispute_cases": 0}
    base = Path(base)
    return verify_pair(base / logs["buyer"], logs["buyer_key"], base / logs["merchant"], logs["merchant_key"])
