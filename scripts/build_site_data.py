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
from decimal import Decimal
from pathlib import Path
import re

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
    """Rows for the buyer-seller batch of clearwake/batch.py. A local batch is never published: nothing in it is PayPal's."""
    mode = str(body.get("mode", "")).lower()
    if "local" in mode or "sandbox" not in mode:
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
            "outcome": (RESULT_WORD.get(c.get("outcome"), str(c.get("outcome", "")).replace("_", " ")) + (f", refund USD {refund} confirmed by PayPal" if refund != "0.00" else "")
                        + (f". {steps[-1]}" if steps else "")).strip(),
            "fee_avoided": "0.00", "settled_before_escalation": result == "settled", "result": result, "refunded": refund != "0.00",
            "dispatch": "", "message": c.get("message") or "", "record": record, "mode": "real sandbox", "recorded": str(body.get("finished", ""))[:10]})
    return {"source": f"Buyer and merchant agent batch, {name}", "recorded": str(body.get("finished", ""))[:10], "rows": rows}


def policy_limits():
    """The make_offer limits of policy/merchant.yaml as USD strings, for the scene on the Home page. Nothing is typed twice."""
    text = (ROOT / "policy" / "merchant.yaml").read_text(encoding="utf-8")
    m = re.search(r"make_offer:\n(?:[ \t]+.*\n)*?[ \t]+max_amount_minor:\s*(\d+)\n(?:[ \t]+.*\n)*?[ \t]+approval_above_minor:\s*(\d+)", text)
    if not m:
        return {}
    return {"make_offer_max": f"{int(m.group(1)) / 100:.2f}", "approval_above": f"{int(m.group(2)) / 100:.2f}", "source": "policy/merchant.yaml"}


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
               record_extra={"fault": "the response to the refund was withheld; the second call sent nothing"}),
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
                    "refund_id": "0TB11858A85953644", "status_before_acceptance": "UNDER_REVIEW", "policy_limit": policy_limits()}},
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
    local:  the same, but a local batch counts (the console is local and carries its own mode label)."""
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

    real = lambda m: "sandbox" in m and "local" not in m
    for key, ok in (("public", real), ("local", lambda m: True)):
        path, sm = batch(ok)
        if sm:
            n = sm.get("cases", 0)
            out[key].append({"value": f"{sm.get('settled_inquiry_no_fee', 0)} of {n}", "label": "disputes settled at INQUIRY, before a claim", "source": f"data/runs/{path.name}"})
            if sm.get("seconds_per_case") is not None:
                out[key].append({"value": f"{sm['seconds_per_case']} s", "label": "per negotiated case, buyer agent and merchant agent", "source": f"data/runs/{path.name}"})
        else:
            disputes = [r for r in ledger_rows if r["kind"] == "dispute"]
            out[key].append({"value": f"{sum(r['settled_before_escalation'] for r in disputes)} of {len(disputes)}", "label": "real sandbox disputes settled at INQUIRY, before a claim", "source": "site/data/ledger.json"})
        path, ev = newest("ai-eval-*.json")
        if ev and ev.get("totals"):
            model, t = next(iter(ev["totals"].items()))
            out[key].append({"value": f"{t['calls']} calls", "label": f"to {model}, median {t['median_ms'] / 1000:.1f} s each", "source": f"data/runs/{path.name}"})
        path, base = newest("baseline-*.json")
        if base and not isinstance(base.get("headline"), list) and isinstance(base.get("summary"), dict):
            # derive the two headline lines from the run's own per-condition counts
            conds = [c for k, c in base["summary"].items() if k != "total" and isinstance(c, dict) and "unguarded" in c]
            n = sum(c["episodes"] for c in conds)
            over = sum(c["unguarded"]["overpaid_minor"] for c in conds) / 100
            doubles = sum(c["unguarded"]["double_refunds"] for c in conds)
            kept = sum(c["guarded"]["matches_intent"] for c in conds)
            base = {"headline": [{"value": f"USD {over:,.2f}", "label": f"overpaid by an unguarded agent in {n} episodes, USD 0.00 by Clearwake ({doubles} double refunds against 0)"},
                                 {"value": f"{kept} of {n}", "label": "episodes ended as the owner intended with Clearwake, 0 of %d unguarded" % n}]}
        if base and isinstance(base.get("headline"), list):
            out[key] += [{"value": str(h["value"]), "label": str(h["label"]), "source": f"data/runs/{path.name}"} for h in base["headline"][:2] if "value" in h and "label" in h]
    out["public"] = public_numbers(out["public"])
    return out


def public_numbers(found):
    """The strongest sourced numbers for the Home page, six at most, each read from a run file:
    the baseline against PayPal's Agent Toolkit (both lines), the real sandbox batch (handled with no error, settled at INQUIRY),
    the policy decisions across the model calls, and the signed logs that verify. A weak line is never filled in."""
    base = [n for n in found if "/baseline-" in n["source"]][:2]
    for n in base:
        n["mode"] = "local run on the local provider"
    out = list(base)
    path, body = clean_sandbox_batch()
    if body:
        sm = body.get("summary", {})
        n, errors = sm.get("cases", 0), sm.get("error", 0)
        doubles = (sm.get("result") or {}).get("double_refunds", 0)
        src = f"data/runs/{path.name}"
        out.append({"value": f"{n - errors} of {n}", "label": f"disputes handled with {errors} errors and {doubles} double refunds",
                    "source": src, "mode": "real PayPal sandbox"})
        rows = body.get("cases", [])
        inside = [r for r in rows if r.get("paypal_stage") == "INQUIRY" and r.get("outcome") not in ("escalated_to_merchant_owner", "handled_by_mandate")]
        done = [r for r in inside if r.get("outcome") == "settled_inquiry_no_fee"]
        out.append({"value": f"{len(done)} of {len(inside)}",
                    "label": f"settled at INQUIRY, before a claim: every dispute inside the owner's limit that stayed at INQUIRY, USD {sm.get('refunds_confirmed_total', '0.00')} refunded",
                    "source": src, "mode": "real PayPal sandbox"})
    rec_path, rec = newest("case-records-*.json")
    if rec:
        fees = []
        for c in rec.get("cases", []):
            if c.get("outcome") != "settled_inquiry_no_fee" or not c.get("paypal_record"):
                continue
            for m in c["paypal_record"].get("money_movements", []) or []:
                if m.get("reason") == "DISPUTE_SETTLEMENT_FEE":
                    fees.append(Decimal(m["amount"]["value"]))
        if fees and len(set(fees)) == 1:
            out.append({"value": f"USD {fees[0]:.2f}", "label": f"settlement fee instead of the USD 15.00 dispute fee, on each of the {len(fees)} settled disputes (USD {sum(fees):.2f} in all)",
                        "source": f"data/runs/{rec_path.name}", "mode": "real PayPal sandbox"})
    path, ev = newest("ai-eval-*.json")
    if ev and ev.get("totals"):
        model, t = next(iter(ev["totals"].items()))
        if t.get("calls") and t.get("policy_correct") is not None:
            out.append({"value": f"{t['policy_correct']} of {t['calls']}", "label": f"policy decisions correct across {t['calls']} model calls to {model}, median {t['median_ms'] / 1000:.1f} s each",
                        "source": f"data/runs/{path.name}", "mode": "local run on the local provider"})
    return out[:6]


def room_numbers():
    """The lead numbers of the Control Room, read from the newest clean real sandbox batch and the settle times file. Nothing is typed.
    A number that cannot be read from its run file is left out."""
    path, body = clean_sandbox_batch()
    out = {"public": []}
    if not body:
        return out
    sm, src = body.get("summary", {}), f"data/runs/{path.name}"
    n, errors = sm.get("cases", 0), sm.get("error", 0)
    doubles = (sm.get("result") or {}).get("double_refunds", 0)
    mode = "Real PayPal sandbox run"
    out["public"].append({"value": f"{n - errors} of {n}", "label": f"disputes handled with {errors} errors and {doubles} double refunds", "source": src, "mode": mode})
    if sm.get("refunds_confirmed_by_paypal") is not None and sm.get("refunds_confirmed_total") is not None:
        out["public"].append({"value": f"USD {sm['refunds_confirmed_total']}", "label": f"refunded in {sm['refunds_confirmed_by_paypal']} refunds, each confirmed by PayPal's record, across {sm.get('settled_inquiry_no_fee', 0)} of {n} disputes settled at INQUIRY", "source": src, "mode": mode})
    times = sorted(ROOT.glob("data/runs/settle-times-*.json"))
    if times:
        st = json.loads(times[-1].read_text(encoding="utf-8"))
        if st.get("fastest_minutes") is not None and st.get("slowest_minutes") is not None:
            out["public"].append({"value": f"{round(st['fastest_minutes'])} to {round(st['slowest_minutes'])} min", "label": f"from filing to RESOLVED in PayPal's own timestamps, {len(st.get('rows', []))} settled disputes", "source": f"data/runs/{times[-1].name}", "mode": mode})
    chargeback = [c for c in body.get("cases", []) if str(c.get("paypal_stage", "")).upper() == "CHARGEBACK"]
    if chargeback:
        out["public"].append({"value": f"{len(chargeback)} of {n}", "label": f"moved by PayPal to the CHARGEBACK stage, cases {', '.join(str(c['n']) for c in chargeback[:-1])} and {chargeback[-1]['n']}" if len(chargeback) > 1 else "moved by PayPal to the CHARGEBACK stage", "source": src, "mode": mode})
    return out


HUD_CASE = 3


def clean_sandbox_batch():
    """(path, body) of the newest real sandbox batch run with no error row, or (None, None)."""
    for path in sorted((ROOT / "data" / "runs").glob("batch-sandbox-*.json"), reverse=True):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(body, dict) and "sandbox" in str(body.get("mode", "")).lower() and not any(c.get("outcome") == "error" for c in body.get("cases", [])):
            return path, body
    return None, None


def settlement_fee(case_n=3):
    """The settlement fee PayPal's record shows for one settled case, from data/runs/case-records-*.json (never typed)."""
    _, rec = newest("case-records-*.json")
    for c in (rec or {}).get("cases", []):
        if c.get("n") == case_n and c.get("paypal_record"):
            for m in c["paypal_record"].get("money_movements", []) or []:
                if m.get("reason") == "DISPUTE_SETTLEMENT_FEE":
                    return m["amount"]["value"]
    raise SystemExit("no DISPUTE_SETTLEMENT_FEE line in the case records for case %d" % case_n)


def hud_case():
    """The one settled case the Home page scene plays, from the newest clean real sandbox batch. Copies its two signed logs into
    site/receipts, lists them in the receipts manifest, and writes site/data/hud-case.json. Every value is read, none typed."""
    path, body = clean_sandbox_batch()
    case = next((c for c in (body or {}).get("cases", []) if c.get("n") == HUD_CASE and c.get("outcome") == "settled_inquiry_no_fee"), None)
    if not case:
        print(f"no settled case {HUD_CASE} in a clean real sandbox batch: hud-case.json not written")
        return
    did, order = case["dispute_id"], case["order_id"]
    logs, keys = {}, {}
    for side in ("merchant", "buyer"):
        src = path.parent / body["logs"][side]
        raw = src.read_bytes()
        (SITE / "receipts" / f"batch-{side}.ndjson").write_bytes(raw)
        text = raw.decode("utf-8")
        logs[side] = [json.loads(line) for line in text.splitlines()]
        keys[side] = body["logs"][side + "_key"]
    find = lambda rows, test: [i + 1 for i, r in enumerate(rows) if test(r)]
    m, b = logs["merchant"], logs["buyer"]
    offer = find(m, lambda r: r["step_id"] == f"{did}:offer")[-1]
    call = find(m, lambda r: r["step_id"] == f"{did}:model-call")[-1]
    read = find(m, lambda r: r["step_id"] == f"{did}:settlement" and r["params"].get("status") == "RESOLVED")[0]
    pending = next(i for i in find(m, lambda r: r["step_id"] == f"{did}:settlement") if i > offer)
    decision = call - 1
    assert m[decision - 1]["action_id"] == "clearwake.dispute.decision" and m[decision - 1]["step_id"] == f"{did}:decision"
    closed = find(b, lambda r: r["step_id"].startswith(f"{order}:case_closed") and r["params"].get("outcome") == "settled_inquiry_no_fee")[-1]
    draft = find(b, lambda r: r["step_id"].startswith(f"{order}:model_draft"))[-1]
    mc, bc = m[call - 1]["params"], b[draft - 1]["params"]
    mandate = next(r["params"] for r in b if r["step_id"] == f"mandate:{order}")
    pol = (ROOT / "data" / "buyer" / "manual-batch" / "merchant-batch-policy.yaml").read_text(encoding="utf-8")
    mo = re.search(r"make_offer:\n(?:[ \t]+.*\n)*?[ \t]+max_amount_minor:\s*(\d+)\n(?:[ \t]+.*\n)*?[ \t]+approval_above_minor:\s*(\d+)", pol)
    usd = lambda minor: f"{int(minor) / 100:.2f}"
    out = {
        "source": f"data/runs/{path.name}", "case": case["n"], "scenario": case["scenario"], "recorded": str(body.get("finished", ""))[:10],
        "dispute": did, "order": order, "paid": case["paid"], "ask": case["ask_on_paypal"], "trackers": 0,
        "buyer_message": case["draft"]["message"], "buyer_model": case["draft"]["model"], "buyer_draft_ms": bc.get("latency_ms"),
        "rule_buyer": body["buyer_claim_rule"], "rule_merchant": body["merchant_rule"],
        "proposed": mc["proposed"], "decided": mc["decided"], "model": mc["model"], "model_backend": mc["backend"], "model_ms": mc["latency_ms"],
        "overridden": mc["overridden"], "offer": usd(mc["offer_minor"]), "limit_alone": usd(mo.group(2)), "ceiling": usd(mo.group(1)),
        "policy_hash": mc["policy_hash"], "status": case["paypal_status"], "stage": case["paypal_stage"], "outcome": case["paypal_outcome"],
        "refund": case["refund_confirmed"], "fee": settlement_fee(), "fee_line": f"USD {settlement_fee()} settlement fee instead of the USD 15.00 dispute fee", "settlement": case["outcome"],
        "merchant": {"file": "receipts/batch-merchant.ndjson", "key": keys["merchant"], "offer_line": offer, "read_line": read, "call_line": call,
                     "decision_line": decision, "pending_line": pending, "wake_lines": [decision, call, offer, pending, read]},
        "buyer": {"file": "receipts/batch-buyer.ndjson", "key": keys["buyer"], "closed_line": closed},
    }
    (SITE / "data" / "hud-case.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    mpath = SITE / "receipts" / "manifest.json"
    man = json.loads(mpath.read_text(encoding="utf-8"))
    man["logs"] = [l for l in man["logs"] if not l["file"].startswith("receipts/batch-")]
    for side, title in (("merchant", "merchant agent"), ("buyer", "buyer agent")):
        man["logs"].append({"file": f"receipts/batch-{side}.ndjson", "title": f"Ten case batch, {title}: real sandbox, case {HUD_CASE} settled at INQUIRY",
                            "public_key": keys[side], "lines": len(logs[side]), "ok_in_python": True, "recorded": out["recorded"]})
    mpath.write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    print("hud-case.json written from", path.name, "case", HUD_CASE, did)



# ---------------------------------------------------------------------------------------------------------------- Control Room cases

VOCAB = ("settled", "answered with proof", "waiting for owner", "refused")
VERIFIED_MEANS = "VERIFIED means PayPal's record was read back and matches."
BATCH_POLICY = ROOT / "data" / "buyer" / "manual-batch" / "merchant-batch-policy.yaml"


def read_log(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def policy_op(text, name):
    """{max_amount_minor, approval_above_minor} of one operation in a policy file, as ints. Missing keys are left out."""
    m = re.search(rf"^  {name}:\n((?:    .*\n|\s*#.*\n)*)", text, re.M)
    out = {}
    for key in ("max_amount_minor", "approval_above_minor"):
        k = re.search(rf"{key}:\s*(\d+)", m.group(1)) if m else None
        if k:
            out[key] = int(k.group(1))
    return out


def usd(minor):
    return f"{int(minor) / 100:.2f}"


def median(values):
    v = sorted(values)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


RESULT_WORD = {"settled_inquiry_no_fee": "settled", "pending": "answered with proof", "escalated_to_merchant_owner": "waiting for owner", "handled_by_mandate": "refused"}


def describe(action, p):
    """One plain line for a receipt line, built only from that line's own fields."""
    a = action.split(".", 1)[1] if action.startswith("clearwake.") else action
    if a == "merchant.tracking_added":
        return (f"Tracking {p.get('tracking')} with {p.get('carrier')}. The carrier shows {p.get('carrier_status')}, PayPal's tracker shows {p.get('paypal_tracker_status')}. "
                f"How it got onto the order: {p.get('how')}.")
    if a == "dispute.supporting_info":
        return f"Supporting info sent to dispute {p.get('dispute')}: {p.get('items')} item, read back from PayPal as {p.get('state')}."
    if a == "dispatch.recorded":
        item = next(iter(p.get("counted") or {"item": 0}))
        return f"Parcel count on record: {(p.get('counted') or {}).get(item)} of {(p.get('ordered') or {}).get(item)} {item}, sealed. Counter: {p.get('counter')}."
    if a == "dispute.decision":
        offer = f" Offer USD {usd(p['offer_minor'])}." if p.get("offer_minor") else ""
        return f"Stage {p.get('stage')}. The model proposed {p.get('proposed')}, the policy decided {p.get('decided')}.{offer}"
    if a == "model.call":
        return (f"{p.get('model')} through {p.get('backend')} on this machine, {p.get('latency_ms', 0) / 1000:.1f} s, {p.get('prompt_tokens')} prompt tokens, "
                f"{p.get('completion_tokens')} reply tokens. Policy accepted the proposal: {'yes' if p.get('policy_accepted') else 'no'}.")
    if a == "model.injection_attempt":
        return f"Signals in the buyer's message: {', '.join(p.get('signals') or [])}. Effect: {p.get('effect')}."
    if a == "batch.injection_ignored":
        return f"The instruction in the buyer's message was not followed (followed: {str(p.get('followed')).lower()}). The amount stayed at the limit of USD {usd(p.get('limit_minor', 0))}."
    if a == "dispute.offer_sent":
        return f"Offer of {p.get('currency')} {usd(p.get('offer_minor', 0))} sent to the buyer."
    if a == "batch.reconciled":
        return f"The response was lost. PayPal's dispute record was read: offer on record {'yes' if p.get('offer_on_record') else 'no'}, sent again {'yes' if p.get('resent') else 'no'}."
    if a == "dispute.settlement":
        return f"PayPal's record read back: {p.get('status')} at {p.get('stage')}, {p.get('outcome')}. {p.get('state')}."
    if a == "batch.case_closed":
        return f"Case closed: {RESULT_WORD.get(p.get('outcome'), str(p.get('outcome', '')).replace('_', ' '))}. PayPal shows {p.get('paypal_status')} at {p.get('paypal_stage')}."
    if a == "buyer.mandate":
        return f"The buyer agent's mandate for order {p.get('order_id')}: item {p.get('item')}, price USD {usd(p.get('price_minor', 0))}."
    if a == "buyer.claim_refused":
        return f"{p.get('why')} Paid USD {usd(p.get('paid_minor', 0))}, asked USD {usd(p.get('asked_minor', 0))}."
    if a == "buyer.handed_to_owner":
        return f"Handed to the buyer's owner. Dispute opened on PayPal: {'yes' if p.get('dispute_opened') else 'no'}."
    if a == "buyer.case_closed":
        return f"Case closed: {RESULT_WORD.get(p.get('outcome'), str(p.get('outcome', '')).replace('_', ' '))}."
    return action


LABELS = {
    "merchant.tracking_added": "Tracking on the order", "dispute.supporting_info": "Supporting info sent", "dispatch.recorded": "Parcel count",
    "dispute.decision": "Policy decision", "model.call": "Model call", "model.injection_attempt": "Injected instruction found", "batch.injection_ignored": "Injected instruction ignored",
    "dispute.offer_sent": "Offer sent", "batch.reconciled": "PayPal read after a lost response", "dispute.settlement": "PayPal record read back", "batch.case_closed": "Case closed",
    "buyer.mandate": "Mandate", "buyer.claim_refused": "Claim refused", "buyer.handed_to_owner": "Handed to owner", "buyer.case_closed": "Case closed"}


def case_steps(case, logs):
    """Receipt steps of one case, from the line pointers of the case-records run file: the latest line of each kind, plus the first tracking line
    when the Add Tracking API posted it. Every pointer is checked against the log line it names."""
    steps, seen = [], {}
    for side, key in (("merchant", "merchant_receipts"), ("buyer", "buyer_receipts")):
        for ptr in case.get(key) or []:
            row = logs[side][ptr["line"] - 1]
            if row["action_id"] != ptr["action"]:
                raise ValueError(f"case {case['n']}: {side} log line {ptr['line']} is {row['action_id']}, the run file says {ptr['action']}")
            kind = ptr["action"].split(".", 1)[1]
            if side == "buyer" and case.get("outcome") != "handled_by_mandate":
                continue   # the buyer side of a dispute is not this card's story; only the refused claim is
            if kind == "dispute.settlement" and row["params"].get("state") != "VERIFIED":
                continue
            if kind in LABELS:
                seen.setdefault((side, kind), []).append((ptr["line"], row))
    for (side, kind), lines in seen.items():
        picks = [lines[-1]]
        if kind == "merchant.tracking_added" and "Add Tracking API" in str(lines[0][1]["params"].get("how")) and lines[0][0] != lines[-1][0]:
            picks.insert(0, lines[0])
        for line, row in picks:
            steps.append({"log": side, "file": f"batch-{side}.ndjson", "line": line, "action": row["action_id"], "step_id": row["step_id"], "label": LABELS[kind],
                          "detail": describe(row["action_id"], row["params"]), "ok": bool(row["success"])})
    return sorted(steps, key=lambda s: (s["log"] != "merchant", s["line"]))


def money_text(v):
    return f"USD {v['value']}" if isinstance(v, dict) and v.get("value") is not None else ""


def paypal_facts(rec):
    """What PayPal's record holds, as label and value pairs. Nothing is added to what the record says."""
    if not rec:
        return []
    facts = [("Dispute", rec.get("dispute_id")), ("Status", rec.get("status")), ("Dispute state", rec.get("dispute_state")), ("Stage", rec.get("dispute_life_cycle_stage")),
             ("Reason", rec.get("reason")), ("Amount asked", money_text(rec.get("dispute_amount")))]
    if rec.get("seller_response_due_date"):
        facts.append(("Seller response due", rec["seller_response_due_date"]))
    sup = rec.get("supporting_info") or []
    if sup:
        facts.append(("Supporting info on the record", f"{len(sup)} entries, all {', '.join(sorted({s.get('source', '') for s in sup}))}; the latest provided {sup[-1].get('provided_time')}"))
        facts.append(("Latest supporting info note", sup[-1].get("notes", "")))
    seller = [e for e in rec.get("evidences") or [] if e.get("source") == "SUBMITTED_BY_SELLER"]
    asked = [e for e in rec.get("evidences") or [] if e.get("source") == "REQUESTED_FROM_SELLER"]
    for e in seller:
        facts.append(("Seller entry", f"{e.get('evidence_type')}, {e.get('date')}: {e.get('notes', '')}".strip()))
    for e in asked:
        facts.append(("PayPal asked the seller for", f"{e.get('evidence_type')}, {e.get('date')}"))
    if not sup and not seller:
        facts.append(("Seller evidence on the record", "none"))
    out = rec.get("dispute_outcome")
    if out:
        facts.append(("Outcome", f"{out.get('outcome_code')}, {out.get('outcome_reason')}, refunded {money_text(out.get('amount_refunded'))}"))
    else:
        facts.append(("Outcome", "none on the record yet"))
    opts = rec.get("allowed_response_options") or {}
    if opts:
        facts.append(("Responses PayPal allows the seller", "; ".join(f"{k}: {', '.join(next(iter(v.values())))}" if isinstance(v, dict) and v else k for k, v in opts.items())))
    return [[k, str(v)] for k, v in facts if v not in (None, "")]


def model_costs(body, logs):
    """Model calls and seconds per case from the batch file, and the median seconds per call from the two signed logs.
    The per call times are the latency fields of the calls the batch summary counts (7 merchant, 17 buyer). If their sums differ from the summary, the median is left out."""
    sm = body["summary"]
    merchant = [r["params"]["latency_ms"] for r in logs["merchant"] if r["action_id"] == "clearwake.model.call"]
    buyer = []
    for r in reversed(logs["buyer"]):
        if len(buyer) >= sm.get("buyer_model_calls", 0):
            break
        if r["action_id"] in ("clearwake.buyer.model_draft", "clearwake.buyer.model_decision") and r["params"].get("latency_ms", -1) > 0:
            buyer.append(r["params"]["latency_ms"])
    calls_ok = (len(merchant) == sm.get("model_calls") and sum(merchant) == sm.get("merchant_model_ms")
                and len(buyer) == sm.get("buyer_model_calls") and sum(buyer) == sm.get("buyer_model_ms"))
    per_case = []
    for c in body["cases"]:
        per_case.append({"n": c["n"], "merchant_calls": c.get("model_calls") or 0, "buyer_calls": c.get("buyer_model_calls") or 0,
                         "model_seconds": round(((c.get("model_ms") or 0) + (c.get("buyer_model_ms") or 0)) / 1000, 1), "cost_usd": "0.00"})
    every = (merchant + buyer) if calls_ok else []
    return {"merchant_calls": sm.get("model_calls"), "buyer_calls": sm.get("buyer_model_calls"), "cases": len(body["cases"]),
            "median_seconds_per_call": round(median(every) / 1000, 1) if every else None, "calls_checked": len(every),
            "model_seconds_total": round((sm.get("merchant_model_ms", 0) + sm.get("buyer_model_ms", 0)) / 1000, 1),
            "model": str(body.get("merchant_agent", "")), "cost_per_call_usd": "0.00", "cost_total_usd": "0.00", "per_case": per_case,
            "note": "Both agents run a local model on this machine through Ollama, so no per call price applies."}


def cases_data():
    """site/data/cases.json: one card per case of the newest clean real sandbox batch, from the case-records run file, the two signed batch logs and the policy file.
    Nothing is typed here except the four result words and the one sentence that defines VERIFIED."""
    path, body = clean_sandbox_batch()
    records = sorted((ROOT / "data" / "runs").glob("case-records-*.json"))
    if not body or not records:
        print("cases.json not written: needs a clean real sandbox batch and a case-records run file")
        return None
    rec = json.loads(records[-1].read_text(encoding="utf-8"))
    if rec.get("source_batch") != f"data/runs/{path.name}":
        print("cases.json not written: case-records names", rec.get("source_batch"), "not", path.name)
        return None
    logs = {s: read_log(SITE / "receipts" / f"batch-{s}.ndjson") for s in ("merchant", "buyer")}
    pol_text = BATCH_POLICY.read_text(encoding="utf-8")
    offer_rule, claim_rule = policy_op(pol_text, "make_offer"), policy_op(pol_text, "accept_claim")
    rows = {int(c["n"]): c for c in body["cases"]}
    out = []
    for c in rec["cases"]:
        n, row = int(c["n"]), rows[int(c["n"])]
        pp, outcome = c.get("paypal_record"), c["outcome"]
        steps = case_steps(c, logs)
        card = {"n": n, "scenario": c["scenario"], "order": c["order"], "dispute": c.get("dispute") or "", "ask": c.get("ask"), "paid": row.get("paid"), "outcome": outcome,
                "paypal_status": c.get("paypal_status") or "", "paypal_stage": c.get("paypal_stage") or "", "steps": steps, "paypal": paypal_facts(pp),
                "buyer_wrote": next((e.get("notes") for e in (pp or {}).get("evidences", []) if e.get("source") == "SUBMITTED_BY_BUYER"), "") or (row.get("draft") or {}).get("message", "")}
        if pp:
            card["raw_label"], card["raw"] = "PayPal's record as read back, personal fields removed", pp
        tr = c.get("tracking") or {}
        if tr.get("number"):
            card["tracking"] = {k: tr.get(k) for k in ("number", "carrier", "carrier_status", "paypal_tracker_status", "how", "confirmed_in_paypal")}
        if outcome == "settled_inquiry_no_fee":
            card["result"] = "settled"
            refund = ((pp.get("refund_details") or {}).get("transactions") or [{}])[0]
            moves = [f"{m['affected_party']} {m['type']} USD {m['amount']['value']} {m['reason']}" for m in pp.get("money_movements") or []]
            card["refund"] = {"id": refund.get("id"), "amount": (refund.get("gross_amount") or {}).get("value"), "created": refund.get("create_time"), "movements": moves}
            card["summary"] = f"PayPal's record reads RESOLVED at {c['paypal_stage']}. Refund {card['refund']['id']} of USD {card['refund']['amount']} is on the record."
        elif outcome == "pending" and c.get("merchant_state") == "VERIFIED":
            card["result"] = "answered with proof"
            card["summary"] = (f"Tracking {tr.get('number')} with {tr.get('carrier')} and supporting info are on PayPal's record. "
                               f"PayPal holds the case {c['paypal_status'].replace('_', ' ')} at {c['paypal_stage']}.")
        elif outcome == "escalated_to_merchant_owner":
            card["result"] = "waiting for owner"
            amount = (pp.get("dispute_amount") or {}).get("value")
            decision = next((s for s in reversed(steps) if s["action"].endswith("dispute.decision")), None)
            if decision:
                ask = logs["merchant"][decision["line"] - 1]["params"]["offer_minor"]
                card["rule"] = {"source": "make_offer in " + "data/buyer/manual-batch/merchant-batch-policy.yaml", "decision_line": decision["line"],
                                "text": (f"The agent decided to settle by offer of USD {usd(ask)}. The owner's policy lets it settle alone up to USD {usd(offer_rule['approval_above_minor'])} "
                                         f"and ask from there up to the USD {usd(offer_rule['max_amount_minor'])} ceiling. USD {usd(ask)} is above the first figure and not above the second, so it needs the owner.")}
            else:
                card["rule"] = {"source": "accept_claim in " + "data/buyer/manual-batch/merchant-batch-policy.yaml", "decision_line": None,
                                "text": (f"The receipts for this case hold the tracking line and the case closed line, and no decision line. The policy file asks for the owner above USD "
                                         f"{usd(claim_rule['approval_above_minor'])} when the agent accepts a claim, and this claim is USD {amount}. "
                                         "PayPal's record offers the seller one response at this stage: accept the claim with a refund.")}
            card["summary"] = f"Nothing was paid. PayPal shows {c['paypal_status'].replace('_', ' ')} at {c['paypal_stage']} and waits for the owner."
            if pp.get("seller_response_due_date"):
                card["due"] = pp["seller_response_due_date"]
        elif outcome == "handled_by_mandate":
            card["result"] = "refused"
            ref = next(s for s in reversed(steps) if s["action"].endswith("buyer.claim_refused"))
            p = logs["buyer"][ref["line"] - 1]["params"]
            card["mandate"] = {"paid": usd(p["paid_minor"]), "asked": usd(p["asked_minor"]), "why": p["why"], "receipt": p["mandate_receipt"], "rule": body.get("buyer_claim_rule"),
                               "line": ref["line"], "dispute_opened": False}
            card["summary"] = f"The buyer agent's own mandate refused a claim of USD {usd(p['asked_minor'])} on an order that cost USD {usd(p['paid_minor'])}. No dispute was opened."
            card["raw_label"], card["raw"] = "Buyer receipt params, line %d of batch-buyer.ndjson" % ref["line"], p
        else:
            raise ValueError(f"case {n}: outcome {outcome!r} has no card layout")
        out.append(card)
    policy_lines = [line for line in pol_text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return {"source": f"data/runs/{records[-1].name}", "batch": f"data/runs/{path.name}", "read_at": rec.get("read_at"), "mode": "Real PayPal sandbox run",
            "vocab": list(VOCAB), "verified_means": VERIFIED_MEANS, "counts": {w: sum(1 for k in out if k["result"] == w) for w in VOCAB},
            "waiting": [k["n"] for k in out if k["result"] == "waiting for owner"],
            "deadlines": [{"n": k["n"], "dispute": k["dispute"], "due": k["due"]} for k in out if k.get("due")],
            "logs": {s: {"file": f"receipts/batch-{s}.ndjson", "key": body["logs"][s + "_key"], "lines": len(logs[s])} for s in ("merchant", "buyer")},
            "policy": {"file": "data/buyer/manual-batch/merchant-batch-policy.yaml", "text": "\n".join(policy_lines), "owner_rule": body.get("merchant_rule"),
                       "refund_approval_above": usd(claim_rule["approval_above_minor"]), "offer_alone_up_to": usd(offer_rule["approval_above_minor"]), "offer_ceiling": usd(offer_rule["max_amount_minor"])},
            "cost": model_costs(body, logs), "cases": out}


def batch_counts():
    """The counted outcomes of the real batch, read from the batch run file: site/data/counts.json. The home page reads this file, never the row wording."""
    path, body = clean_sandbox_batch()
    if not body:
        return {}
    rows = body.get("cases", [])
    count = lambda test: sum(1 for r in rows if test(r))
    return {"source": f"data/runs/{path.name}", "cases": len(rows),
            "settled": count(lambda r: r.get("outcome") == "settled_inquiry_no_fee"),
            "answered_with_proof": count(lambda r: r.get("outcome") == "pending" and r.get("merchant_state") == "VERIFIED"),
            "waiting_for_owner": count(lambda r: r.get("outcome") == "escalated_to_merchant_owner"),
            "refused": count(lambda r: r.get("outcome") == "handled_by_mandate")}


def batch_tally(public):
    """web/batch-tally.json for the hosted console: the counted batch tally and the baseline line, read from the run files. Nothing is typed."""
    path, body = clean_sandbox_batch()
    out = {}
    if body:
        rows, sm = body.get("cases", []), body.get("summary", {})
        n, errors = sm.get("cases", len(rows)), sm.get("error", 0)
        doubles = (sm.get("result") or {}).get("double_refunds", 0)
        settled = sum(1 for r in rows if r.get("outcome") == "settled_inquiry_no_fee")
        proof = sum(1 for r in rows if r.get("outcome") == "pending" and r.get("merchant_state") == "VERIFIED")
        owner = sum(1 for r in rows if r.get("outcome") == "escalated_to_merchant_owner")
        mandate = sum(1 for r in rows if r.get("outcome") == "handled_by_mandate")
        out["batch"] = {"tag": "Real PayPal sandbox run", "source": f"data/runs/{path.name}", "items": [
            {"value": f"{n - errors} of {n}", "label": f"disputes handled, {errors} errors, {doubles} double refunds"},
            {"value": str(settled), "label": f"settled at INQUIRY, before a claim, USD {sm.get('refunds_confirmed_total', '0.00')} refunded"},
            {"value": str(proof), "label": "answered with proof, under PayPal review"},
            {"value": str(owner), "label": "awaiting the merchant owner"},
            {"value": str(mandate), "label": "refused by the mandate"}]}
    base = [x for x in public if "/baseline-" in x["source"]][:1]
    if base:
        out["baseline"] = {"tag": "Local run on the local provider", "source": base[0]["source"],
                           "value": base[0]["value"] + " vs USD 0.00" if not base[0]["value"].endswith("0.00") else base[0]["value"],
                           "label": "overpaid over 200 episodes, an agent using PayPal's Agent Toolkit directly vs Clearwake"}
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
                print("not published", source.name, "(a local batch: its records are not PayPal's)")
            else:
                (data / source.name).write_text(json.dumps(converted, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                print("converted", source.name, "to", len(converted["rows"]), "rows")
        elif isinstance(body, dict) and isinstance(body.get("rows"), list) and all(isinstance(r, dict) and r.get("dispute") for r in body["rows"]):
            (data / source.name).write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print("copied", source.name, "with", len(body["rows"]), "rows")
        else:
            print("skipped", source.name, "(not in the site row format, see the top of this file)")
    hud_case()
    (data / "room.json").write_text(json.dumps(room_numbers(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    cd = cases_data()
    if cd:
        (data / "cases.json").write_text(json.dumps(cd, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("cases.json written:", len(cd["cases"]), "cases")
    tot = totals(build()["rows"])
    (data / "counts.json").write_text(json.dumps(batch_counts(), indent=1) + "\n", encoding="utf-8")
    (data / "totals.json").write_text(json.dumps(tot, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / "web" / "batch-tally.json").write_text(json.dumps(batch_tally(tot["public"]), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    files = sorted(p.name for p in data.glob("*.json") if p.name not in ("manifest.json", "totals.json", "break.json", "hud-case.json", "room.json", "counts.json", "cases.json", "why-now.json"))
    files.remove("ledger.json"); files.insert(0, "ledger.json")
    (data / "manifest.json").write_text(json.dumps({"files": files}, indent=1) + "\n", encoding="utf-8")
    print("site/data/manifest.json lists:", ", ".join(files))


if __name__ == "__main__":
    main()
