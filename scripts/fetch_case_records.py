"""Collect, for each of the ten real sandbox cases, what the merchant agent sent and what PayPal recorded.

Read only: it reads PayPal dispute records (GET) and the signed receipt logs. Personal fields (names, emails, phones, addresses, account ids)
are removed from the PayPal JSON before anything is written. Output: data/runs/case-records-<date>.json, the run file the Control Room cards read.
Run: python scripts/fetch_case_records.py
"""
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clearwake import envfile  # noqa: E402
from clearwake.paypal import SandboxGateway  # noqa: E402

DROP = re.compile(r"(email|name|phone|address|payer_id|merchant_id|account_id|links|postal|country_code|city|state_code)", re.I)
KEEP_NAME = {"name"}  # PayPal error names are not personal


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if not DROP.search(k) or k == "reason"}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def read_log(path):
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            record = json.loads(line)
            rows.append((number, record))
    return rows


def main():
    envfile.load(str(ROOT / ".env"))
    gateway = SandboxGateway.from_environment()
    state = json.loads((ROOT / "data/buyer/manual-batch/state.json").read_text(encoding="utf-8"))["cases"]
    merchant = read_log(ROOT / "site/receipts/batch-merchant.ndjson")
    buyer = read_log(ROOT / "site/receipts/batch-buyer.ndjson")
    batch_path = sorted((ROOT / "data/runs").glob("batch-sandbox-*.json"))[-1]
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    rows = {int(c["n"]): c for c in batch["cases"]}
    by_capture = {}
    for item in gateway.disputes():
        detail = gateway.dispute(item["dispute_id"])
        by_capture[detail["disputed_transactions"][0]["seller_transaction_id"]] = detail
    cases = []
    for key, entry in state.items():
        n = int(key)
        row = rows.get(n, {})
        order, capture = entry["order_id"], entry["capture_id"]
        dispute = by_capture.get(capture)
        dispute_id = dispute["dispute_id"] if dispute else None
        mine = [(ln, r) for ln, r in merchant if order in r["step_id"] or (dispute_id and dispute_id in r["step_id"])
                or r["params"].get("order") == order or (dispute_id and r["params"].get("dispute") == dispute_id)]
        theirs = [(ln, r) for ln, r in buyer if order in r["step_id"] or (dispute_id and dispute_id in r["step_id"])
                  or r["params"].get("order") == order or r["params"].get("order_id") == order or (dispute_id and r["params"].get("dispute") == dispute_id)]
        tracking = None
        for ln, r in mine:
            if r["action_id"] == "clearwake.merchant.tracking_added":
                p = r["params"]
                tracking = {"number": p.get("tracking"), "carrier": p.get("carrier"), "carrier_status": p.get("carrier_status"),
                            "paypal_tracker_status": p.get("paypal_tracker_status"), "how": p.get("how"),
                            "confirmed_in_paypal": p.get("confirmed_in_paypal"), "added_before_dispute": p.get("added_before_dispute"),
                            "receipt_line": ln, "log": "batch-merchant.ndjson"}
        steps = [{"action": r["action_id"], "line": ln, "log": "batch-merchant.ndjson", "step": r["step_id"][:70],
                  "state": r["params"].get("state") or r["params"].get("decided") or r["params"].get("status") or ""} for ln, r in mine[:40]]
        buyer_steps = [{"action": r["action_id"], "line": ln, "log": "batch-buyer.ndjson", "step": r["step_id"][:70]} for ln, r in theirs[:20]]
        cases.append({"n": n, "scenario": row.get("scenario"), "order": order, "capture": capture, "dispute": dispute_id,
                      "ask": row.get("ask"), "outcome": row.get("outcome"), "merchant_state": row.get("merchant_state"),
                      "paypal_status": row.get("paypal_status"), "paypal_stage": row.get("paypal_stage"), "paypal_outcome": row.get("paypal_outcome"),
                      "refund_confirmed": row.get("refund_confirmed"), "steps": row.get("steps"), "tracking": tracking,
                      "merchant_receipts": steps, "buyer_receipts": buyer_steps,
                      "paypal_record": redact(dispute) if dispute else None})
        time.sleep(0.3)
    out = {"kind": "case-records", "mode": "real sandbox", "source_batch": f"data/runs/{batch_path.name}", "read_at": date.today().isoformat(),
           "note": "PayPal dispute records read back from the sandbox with personal fields removed; receipt lines point into the published signed logs.",
           "cases": sorted(cases, key=lambda c: c["n"])}
    path = ROOT / "data/runs" / f"case-records-{date.today().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", path.name, len(cases), "cases")


if __name__ == "__main__":
    main()
