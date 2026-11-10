"""Build the data the public Control Room grid reads, from the recorded runs.

  python scripts/build_site_data.py

Writes site/data/ledger.json (the real sandbox cases c, d, e, i, m, n, o) and site/data/manifest.json,
which lists every *.json file in site/data/ so the page loads them all. To add rows, drop a file in the
format below into site/data/ and run this script again (or add its name to manifest.json by hand).

File format (UTF-8 JSON), also documented in docs/ and read by site/ledger.js:
  {"source": "short label", "recorded": "YYYY-MM-DD", "rows": [ROW, ...]}      (a bare list of rows also works)
ROW (same keys as the local console's dispute ledger, so a console row can be dropped in unchanged):
  dispute            string, required, unique: the PayPal dispute id, or the refund id for a refund row
  case               string: case letter or batch number
  kind               "dispute" or "refund" (default "dispute")
  reason             PayPal reason code or short text
  amount             string, USD, "2.50", or "" when the run did not record it
  stage              "INQUIRY" or "CHARGEBACK" from dispute_life_cycle_stage, "" for a refund
  paypal_status      PayPal's status as read back, for example "RESOLVED"
  state              the Checker's word: "VERIFIED", "UNKNOWN", "PENDING"
  due                seller_response_due_date as ISO 8601 UTC; when present the Deadline cell counts down live
  proposed           the model's (or scripted agent's) proposed action, or "" when the receipt has none
  model              who proposed it, for example "scripted, not AI" or the model name; "" when none
  decided            the policy decision, as words
  outcome            one line: what PayPal's record shows at the end
  fee_avoided        string, USD
  settled_before_escalation   true when PayPal read RESOLVED at INQUIRY
  dispatch           dispatch proof line, or ""
  message            what the buyer wrote, or ""
  record             object: the PayPal record fields the run saved (shown as JSON in the row detail)
  receipts           optional site path of the signed log for this row, for example "receipts/case-n-settle.ndjson"
  result             optional "settled", "evidence", "escalated" or "open": the bucket the Home totals count it in
  refunded           optional true when PayPal shows a refund paid on this dispute
  mode               "real sandbox" (default) or another label; shown in the detail, not in a badge column
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SCRIPTED = "scripted, not AI"


def receipt_proposals(name):
    """{case or dispute id: (proposed, model)} from the first proposal or decision line of a signed log."""
    found = {}
    for line in (SITE / "receipts" / name).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        p = r["params"]
        if r["action_id"] in ("clearwake.decider.proposal", "clearwake.dispute.proposal", "clearwake.dispute.decision"):
            key = p.get("case") or p.get("dispute")
            found.setdefault(key, (p.get("proposed") or "", SCRIPTED if p.get("model") in (None, "", "scripted") else p["model"]))
    return found


RESULT = {"settled_inquiry_no_fee": "settled", "evidence_sent": "evidence"}


def from_batch(body, name):
    """Rows for the buyer-seller batch of clearwake/batch.py. A rehearsal batch is never published: nothing in it is PayPal's."""
    mode = str(body.get("mode", "")).lower()
    if "rehearsal" in mode or "sandbox" not in mode:
        return None
    rows = []
    for c in body.get("cases", []):
        result = RESULT.get(c.get("outcome"), "escalated" if str(c.get("outcome", "")).startswith("escalated") else "open")
        refund = str(c.get("refund_confirmed") or "0.00")
        record = {k: c[k] for k in ("dispute_id", "paypal_status", "paypal_stage", "paypal_outcome", "refund_confirmed", "settlement", "order_id", "capture_id") if c.get(k)}
        steps = c.get("steps") or []
        rows.append({
            "dispute": c.get("dispute_id") or f"{name}-{c.get('n')}", "case": f"b{c.get('n')}", "kind": "dispute", "reason": c.get("reason", ""),
            "amount": str(c.get("ask") or ""), "stage": c.get("paypal_stage") or "", "paypal_status": c.get("paypal_status") or "", "state": c.get("merchant_state") or "",
            "due": c.get("due") or "", "proposed": c.get("merchant_proposed") or c.get("model_proposal") or "", "model": c.get("merchant_proposed_by") or "",
            "decided": c.get("merchant_decision") or "",
            "outcome": (str(c.get("outcome", "")).replace("_", " ") + (f", refund USD {refund} confirmed by PayPal" if refund != "0.00" else "")
                        + (f". {steps[-1]}" if steps else "")).strip(),
            "fee_avoided": "0.00", "settled_before_escalation": result == "settled", "result": result, "refunded": refund != "0.00",
            "dispatch": "", "message": c.get("message") or "", "record": record, "mode": "real sandbox", "recorded": str(body.get("finished", ""))[:10]})
    return {"source": f"Buyer and merchant agent batch, {name}", "recorded": str(body.get("finished", ""))[:10], "rows": rows}


def build():
    n = receipt_proposals("case-n-settle.ndjson")["PP-R-OBG-10196144"]
    o = receipt_proposals("case-o-dispatch.ndjson")["PP-R-UKF-10195772"]
    m = receipt_proposals("case-m-merchant.ndjson")
    capture = "1PH921107B839311S"

    def refund(case, refund_id, amount, decided, outcome, extra=None, proposed=("", ""), record_extra=None, receipts=None, state="VERIFIED"):
        rec = {"refund_id": refund_id or "not written to the run file", "amount": {"currency_code": "USD", "value": amount},
               "capture_id": capture, "checked": "read back from PayPal's record by the Checker"}
        rec.update(record_extra or {})
        return {"dispute": refund_id or f"refund of case {case}", "case": case, "kind": "refund", "reason": "buyer complaint", "amount": amount, "stage": "",
                "paypal_status": "refund read back", "state": state, "due": "", "proposed": proposed[0], "model": proposed[1], "decided": decided,
                "outcome": outcome, "fee_avoided": "0.00", "settled_before_escalation": False, "dispatch": "", "message": "", "record": rec,
                "receipts": receipts, "mode": "real sandbox", "recorded": "2026-10-31"}

    rows = [
        refund("c", "6SN41486G5579815G", "1.50", "refund inside the USD 5.00 limit", "Refund VERIFIED at PayPal"),
        refund("d", "2NB27940EC188891M", "3.50", "held for approval above USD 2.00, then refund", "Approved, refund VERIFIED at PayPal",
               record_extra={"approval": "approved by a person before the refund was sent"}),
        refund("e", "", "1.50", "refund, then read PayPal before any retry", "One refund at PayPal, VERIFIED by reconciliation",
               record_extra={"fault": "the response to the refund was withheld; the second attempt sent nothing"}),
    ]
    for i, refund_id in enumerate(("6PX35920F4587564U", "76C086475Y724052F", "9C434129FA2384059"), 1):
        key = f"m{i}-fe0692"
        held = i > 1
        rows.append(refund(f"m{i}", refund_id, "1.00", "held while offline, sent after the network came back" if held else "refund inside the USD 5.00 limit",
                           "Refund VERIFIED at PayPal after the cable was put back" if held else "Refund VERIFIED at PayPal before the cable was pulled",
                           proposed=m[key], receipts="receipts/case-m-merchant.ndjson",
                           record_extra={"capture_status_read_first": "PARTIALLY_REFUNDED"} if held else None))
        rows[-1]["recorded"] = "2026-10-31"
    rows += [
        {"dispute": "PP-R-SLI-10195419", "case": "i", "kind": "dispute", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "amount": "", "stage": "CHARGEBACK",
         "paypal_status": "UNDER_REVIEW", "state": "VERIFIED", "due": "", "proposed": "", "model": "", "decided": "fight_with_evidence",
         "outcome": "Tracking note SUBMITTED_BY_SELLER on PayPal's record", "result": "evidence", "fee_avoided": "0.00", "settled_before_escalation": False,
         "dispatch": "", "message": "", "receipts": None, "mode": "real sandbox", "recorded": "2026-10-31",
         "record": {"dispute_id": "PP-R-SLI-10195419", "status": "UNDER_REVIEW", "dispute_life_cycle_stage": "CHARGEBACK", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
                    "order_id": "8M960780ES843141H", "seller_actions_offered": ["provide_supporting_info"],
                    "supporting_info": {"source": "SUBMITTED_BY_SELLER", "submitted": "2026-10-31T10:31:38Z",
                                        "tracker": {"number": "SYNTH1Z999AA10654321", "status": "SHIPPED"}}}},
        {"dispute": "PP-R-OBG-10196144", "case": "n", "kind": "dispute", "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "amount": "2.50", "stage": "INQUIRY",
         "paypal_status": "RESOLVED", "state": "VERIFIED", "due": "", "proposed": n[0], "model": n[1], "decided": "settle_by_offer",
         "outcome": "RESOLVED_BUYER_FAVOUR at INQUIRY, refund 0TB11858A85953644 paid", "result": "settled", "refunded": True, "fee_avoided": "0.00", "settled_before_escalation": True,
         "dispatch": "", "message": "", "receipts": "receipts/case-n-settle.ndjson", "mode": "real sandbox", "recorded": "2026-11-03",
         "record": {"dispute_id": "PP-R-OBG-10196144", "status": "RESOLVED", "dispute_life_cycle_stage": "INQUIRY",
                    "dispute_outcome": {"outcome_code": "RESOLVED_BUYER_FAVOUR"}, "offer": {"offer_type": "REFUND", "seller_offered_amount": {"currency_code": "USD", "value": "2.50"}},
                    "refund_id": "0TB11858A85953644", "status_before_acceptance": "UNDER_REVIEW"}},
        {"dispute": "PP-R-UKF-10195772", "case": "o", "kind": "dispute", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "amount": "5.00", "stage": "INQUIRY",
         "paypal_status": "WAITING_FOR_BUYER_RESPONSE", "state": "VERIFIED", "due": "", "proposed": o[0], "model": o[1], "decided": "fight_with_evidence",
         "outcome": "PROOF_OF_FULFILLMENT on PayPal's record, waiting for the buyer", "result": "evidence", "fee_avoided": "0.00", "settled_before_escalation": False,
         "dispatch": "3 of 3 counted, sealed, tracking shipped", "message": "Only 2 of 3 notebooks arrived.",
         "receipts": "receipts/case-o-dispatch.ndjson", "mode": "real sandbox", "recorded": "2026-11-03",
         "record": {"dispute_id": "PP-R-UKF-10195772", "status": "WAITING_FOR_BUYER_RESPONSE", "dispute_life_cycle_stage": "INQUIRY",
                    "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "order_id": "7RV99265V1496281G", "capture_id": "4AN16499K3427771T",
                    "seller_actions_offered": ["provide_evidence", "send_message", "make_offer", "escalate", "accept_claim"],
                    "evidences": [{"evidence_type": "PROOF_OF_FULFILLMENT", "source": "SUBMITTED_BY_SELLER", "date": "2026-11-03T10:13Z",
                                   "carrier": "UPS", "tracking_status": "SHIPPED", "documents": ["packing-photo-893632548b14c5d5.jpg"]}]}},
    ]
    return {"source": "Real PayPal sandbox, cases c, d, e, i, m, n and o, recorded 31 Oct and 3 Nov 2026", "recorded": "2026-11-03", "rows": rows}


def newest(pattern):
    found = sorted((ROOT / "data" / "runs").glob(pattern))
    for path in reversed(found):
        try:
            return path, json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return None, None


def totals(ledger_rows):
    """The few measured numbers the Home page and the console header lead with, read from the run files. Nothing is typed here.

    public: real sandbox batch if one exists, else the real sandbox ledger; model calls from the newest ai-eval run; the newest baseline run's
            "headline" list ([{"value", "label"}]) when agent E's run file has one.
    local:  the same, but a rehearsal batch counts (the console is local and carries its own mode label)."""
    out = {"public": [], "local": []}

    def batch(kind_ok):
        for path in sorted((ROOT / "data" / "runs").glob("batch-*.json"), reverse=True):
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if kind_ok(str(body.get("mode", "")).lower()) and isinstance(body.get("summary"), dict):
                return path, body["summary"]
        return None, None

    real = lambda m: "sandbox" in m and "rehearsal" not in m
    for key, ok in (("public", real), ("local", lambda m: True)):
        path, sm = batch(ok)
        if sm:
            n = sm.get("cases", 0)
            out[key].append({"value": f"{sm.get('settled_inquiry_no_fee', 0)} of {n}", "label": "disputes settled at INQUIRY, no fee", "source": f"data/runs/{path.name}"})
            if sm.get("seconds_per_case") is not None:
                out[key].append({"value": f"{sm['seconds_per_case']} s", "label": "per negotiated case, buyer agent and merchant agent", "source": f"data/runs/{path.name}"})
        else:
            disputes = [r for r in ledger_rows if r["kind"] == "dispute"]
            out[key].append({"value": f"{sum(r['settled_before_escalation'] for r in disputes)} of {len(disputes)}", "label": "real sandbox disputes settled at INQUIRY, no fee", "source": "site/data/ledger.json"})
        path, ev = newest("ai-eval-*.json")
        if ev and ev.get("totals"):
            model, t = next(iter(ev["totals"].items()))
            out[key].append({"value": f"{t['calls']} calls", "label": f"to {model}, median {t['median_ms'] / 1000:.1f} s each", "source": f"data/runs/{path.name}"})
        path, base = newest("baseline-*.json")
        if base and isinstance(base.get("headline"), list):
            out[key] += [{"value": str(h["value"]), "label": str(h["label"]), "source": f"data/runs/{path.name}"} for h in base["headline"][:2] if "value" in h and "label" in h]
        out[key] = out[key][:3]
    return out


def main():
    data = SITE / "data"
    data.mkdir(exist_ok=True)
    (data / "ledger.json").write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    # The buyer batch (data/runs/batch-*.json) goes in when it already has the site format above; anything else is reported, not guessed.
    for source in sorted((ROOT / "data" / "runs").glob("batch-*.json")):
        try:
            body = json.loads(source.read_text(encoding="utf-8"))
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get("kind") == "buyer-seller batch":
            converted = from_batch(body, source.stem)
            if converted is None:
                print("not published", source.name, "(a rehearsal batch: its records are not PayPal's)")
            else:
                (data / source.name).write_text(json.dumps(converted, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                print("converted", source.name, "to", len(converted["rows"]), "rows")
        elif isinstance(body, dict) and isinstance(body.get("rows"), list) and all(isinstance(r, dict) and r.get("dispute") for r in body["rows"]):
            (data / source.name).write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print("copied", source.name, "with", len(body["rows"]), "rows")
        else:
            print("skipped", source.name, "(not in the site row format, see the top of this file)")
    (data / "totals.json").write_text(json.dumps(totals(build()["rows"]), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    files = sorted(p.name for p in data.glob("*.json") if p.name not in ("manifest.json", "totals.json"))
    files.remove("ledger.json"); files.insert(0, "ledger.json")
    (data / "manifest.json").write_text(json.dumps({"files": files}, indent=1) + "\n", encoding="utf-8")
    print("site/data/manifest.json lists:", ", ".join(files))


if __name__ == "__main__":
    main()
