"""Write data/runs/voice-decisions-<date>.json: the two spoken decisions on the real sandbox, as PayPal's record shows them.

Read only: this script sends GET requests to the PayPal sandbox and reads the local receipts file. It writes nothing to PayPal and never calls Sarvam.
The decision facts come from the signed receipts (data/voice-decisions/sandbox/merchant-receipts.ndjson); every status, stage, outcome, refund id and fee
comes from a fresh read of PayPal's dispute record. A value that PayPal does not show is left out, not typed.

Usage: python scripts/voice_run_file.py
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clearwake import envfile  # noqa: E402
from clearwake.decisions import CASES  # noqa: E402
from clearwake.paypal import SandboxGateway  # noqa: E402

RECEIPTS = ROOT / "data" / "voice-decisions" / "sandbox" / "merchant-receipts.ndjson"
SPEND = ROOT / "data" / "voice-cache" / "spend.json"
BATCH = "data/runs/batch-sandbox-20261111-132948.json"


def receipts():
    return [json.loads(line) for line in RECEIPTS.read_text(encoding="utf-8").splitlines() if line.strip()]


def money(m):
    return (m or {}).get("value")


def of_case(rows, n, action=None):
    return [r for r in rows if r["params"].get("case") == n and (action is None or r["action_id"] == action)]


def case4(rows, record):
    sending = of_case(rows, 4, "clearwake.dispute.accept_claim_sending")
    approval = of_case(rows, 4, "clearwake.approval.granted")[0]
    pending = [r for r in of_case(rows, 4, "clearwake.dispute.checked") if r["params"].get("state") == "PENDING"]
    outcome = record.get("dispute_outcome") or {}
    movements = record.get("money_movements") or []
    fees = [m for m in movements if "FEE" in str(m.get("reason", ""))]
    refund = ((record.get("refund_details") or {}).get("transactions") or [{}])[0]
    return {"case": 4, "dispute": record["dispute_id"], "command": "Approve case 4",
            "what_ran": "accept_claim REFUND, no offer (PayPal lists no make_offer at CHARGEBACK)",
            "accept_claim_writes": len(sending), "accept_claim_request_id": sending[0]["params"]["request_id"] if sending else None,
            "approval_id": approval["params"]["approval"], "approved_by": approval["params"]["approver"], "approved_via": approval["params"]["via"],
            "source": approval["params"]["source"], "policy_hash": approval["params"]["policy_hash"],
            "paypal_still_under_review_after_reads": pending[0]["params"]["reads"] if pending else 0,
            "paypal": {"status": record.get("status"), "dispute_state": record.get("dispute_state"), "stage": record.get("dispute_life_cycle_stage"),
                       "outcome_code": outcome.get("outcome_code"), "outcome_reason": outcome.get("outcome_reason"),
                       "amount_refunded": money(outcome.get("amount_refunded")), "refund_id": refund.get("id"), "refund_amount": money(refund.get("gross_amount")),
                       "fees": [{"reason": f.get("reason"), "type": f.get("type"), "amount": money(f.get("amount")), "party": f.get("affected_party")} for f in fees]},
            "receipt_lines": len(of_case(rows, 4))}


def case9(rows, record):
    track = next(r for r in of_case(rows, 9) if "paypal_tracker" in r["params"])
    evidence = next(r for r in of_case(rows, 9) if r["params"].get("evidence_type") == "PROOF_OF_FULFILLMENT")
    command = next(r for r in of_case(rows, 9) if "heard" in r["params"])
    checked = next(r for r in of_case(rows, 9, "clearwake.dispute.checked"))
    proof = [e for e in (record.get("evidences") or []) if e.get("evidence_type") == "PROOF_OF_FULFILLMENT" and e.get("source") != "REQUESTED_FROM_SELLER"]
    outcome = record.get("dispute_outcome") or {}
    return {"case": 9, "dispute": record["dispute_id"], "command": "Don't pay case 9, send the proof",
            "what_ran": "Add Tracking, then provide-evidence PROOF_OF_FULFILLMENT; no refund, offer or accept_claim",
            "provide_evidence_writes": evidence["params"]["writes"], "provide_evidence_request_id": evidence["params"]["request_id"],
            "tracking": {"number": track["params"].get("tracking_number"), "carrier": track["params"].get("carrier"),
                         "label": "sandbox test tracking value, not a real parcel", "paypal_tracker_status": track["params"].get("paypal_tracker_status")},
            "source": command["params"]["source"], "policy_hash": command["params"]["policy"],
            "read_right_after_sending": {"status": checked["params"]["status"], "stage": checked["params"]["stage"],
                                         "evidence_received": checked["params"]["evidence_received"], "money_moved": checked["params"]["money_moved"]},
            "paypal": {"status": record.get("status"), "dispute_state": record.get("dispute_state"), "stage": record.get("dispute_life_cycle_stage"),
                       "seller_proof_on_record": len(proof), "amount_refunded": money(outcome.get("amount_refunded"))},
            "receipt_lines": len(of_case(rows, 9))}


def main():
    envfile.load(ROOT / ".env")
    gateway = SandboxGateway.from_environment()
    rows = receipts()
    r4, r9 = gateway.dispute(CASES[4]["dispute"]), gateway.dispute(CASES[9]["dispute"])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    spend = json.loads(SPEND.read_text(encoding="utf-8")) if SPEND.exists() else {}
    body = {"kind": "voice decisions", "mode": "Real PayPal sandbox run", "recorded": now.isoformat().replace("+00:00", "Z"), "source_batch": BATCH,
            "sandbox_only": True, "channel": "voice", "stt": "Sarvam Saaras v4", "owner_voice": "Sarvam Bulbul kabir", "reply_voice": "Sarvam Bulbul advait",
            "cases": [case4(rows, r4), case9(rows, r9)],
            "case_7": {"case": 7, "outcome": "refused by the buyer's mandate before any dispute", "dispute": None,
                       "why": "The claim of 20.00 is more than the 9.00 the order cost. No dispute was opened. This stays a refusal."},
            "receipts": {"file": "data/voice-decisions/sandbox/merchant-receipts.ndjson", "lines": len(rows), "sha256": hashlib.sha256(RECEIPTS.read_bytes()).hexdigest()},
            "sarvam_spend": {k: spend.get(k) for k in ("tts_chars", "stt_seconds", "calls")},
            "note": "The first spoken reply for case 4 read 'I did not run that' while PayPal still showed UNDER_REVIEW after 9 reads over 56 seconds. "
                    "The refund had been sent once and was not sent again. The wording was corrected."}
    out = ROOT / "data" / "runs" / f"voice-decisions-{now:%Y%m%d}.json"
    out.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("written", out.name)


if __name__ == "__main__":
    main()
