# Results

Every number on this page comes from the run files in `data/runs/*.json` or from [SANDBOX_RUN.md](SANDBOX_RUN.md). Nothing is projected. Each run is labelled the way it ran: **real sandbox**, **injected fault in sandbox**, **rehearsal** (fake provider, invented records) or **offline**. The agents in every recorded run were **scripted, not AI**.

## Runs of the case runner (`scripts/cases.py`, 31 October 2026)

| Run file | Mode | PASS | FAIL | SKIPPED |
| --- | --- | --- | --- | --- |
| `cases-rehearsal-20261031-115247.json` | rehearsal | 12 | 0 | 0 |
| `cases-rehearsal-20261031-153547.json` | rehearsal | 12 | 0 | 0 |
| `cases-sandbox-20261031-115302.json` | sandbox run, first attempt | 6 | 3 | 3 |
| `cases-sandbox-20261031-115349.json` | sandbox run | 9 | 0 | 3 |

The first sandbox attempt failed cases c, d and e with nothing sent to PayPal: sandbox authentication had not been prepared, so the swarm held the refunds instead of sending them. The fix added a capture read before every refund ([SANDBOX_RUN.md](SANDBOX_RUN.md)). The second attempt, one minute later, passed.

Inside a sandbox run, only some cases touch PayPal. The rest run as rehearsal or offline, and the run file says so on each line:

| Case | Label in `cases-sandbox-20261031-115349.json` | Result |
| --- | --- | --- |
| a. Buyer agent buys inside its mandate | rehearsal (no `--order` passed) | PASS |
| b. Buyer agent refuses outside its mandate | rehearsal, mandate check, no payment | PASS |
| c. Refund under the limit, verified | **real sandbox** | PASS, refund `34A6137827870312B` VERIFIED |
| d. Approval inbox, then refund | **real sandbox** | PASS, refund `0X757409L5274794C` VERIFIED after approval |
| e. Lost response, UNKNOWN, reconciled | **injected fault in sandbox** | PASS, 1 refund at PayPal, second attempt sent nothing, reconciled to VERIFIED |
| f. Split refunds stopped at the capture | rehearsal | PASS |
| g. Prompt injection | rehearsal, refused before any PayPal call | PASS |
| h. Tampered receipt | offline | PASS |
| i. Item not received, tracking before the deadline | real sandbox | SKIPPED, no open sandbox dispute |
| j. Mandate receipt as dispute evidence | rehearsal dispute, receipt verified offline | PASS |
| k. Near deadline escalation | real sandbox | SKIPPED, no open sandbox dispute |
| l. Ten disputes in parallel | real sandbox | SKIPPED, no open sandbox dispute |

## Real sandbox money movements

All against `https://api-m.sandbox.paypal.com`, sandbox test money only, drawn on capture `1PH921107B839311S` (USD 20.00).

| Where | Refund | Amount | Checked against PayPal's record |
| --- | --- | --- | --- |
| Four case check, case a | `79R527888E694933F` | USD 1.00 | COMPLETED |
| Four case check, case c (reconciled after an injected fault) | `7A545589JM079780C` | USD 1.00 | COMPLETED |
| Case runner, case c | `34A6137827870312B` | USD 1.50 | VERIFIED |
| Case runner, case d (after approval) | `0X757409L5274794C` | USD 3.50 | VERIFIED |
| Case runner, case e (injected fault in sandbox) | ID not written to the run file | USD 1.50 | VERIFIED by reconciliation |

Amounts for c, d and e are the ones set in `scripts/cases.py`. The four case check passed 4 of 4 ([SANDBOX_RUN.md](SANDBOX_RUN.md)).

## Disputes

| Measure | Rehearsal (each of the two runs) | Real sandbox |
| --- | --- | --- |
| Disputes handled | 13 (i, j, k and ten in l) | 0 (none were open when the runs happened) |
| Item not received, case i | evidence sent, PayPal record shows UNDER_REVIEW | SKIPPED |
| Unauthorised agent order with mandate receipt, case j | evidence sent with the receipt, UNDER_REVIEW, receipt verifies offline | not run against a real dispute |
| Near deadline, case k | escalated to the approval inbox with 4 h 59 min left | SKIPPED |
| Batch of ten, case l (4 not received, 4 not as described, 2 unauthorised) | 4 evidenced, 4 refunded, 2 escalated | SKIPPED |
| Batch time, case l | 0.35 s and 0.37 s in total | not measured |
| Time per dispute, case l | 0.15 s and 0.14 s | not measured |

## Model calls and cost

| Measure | Value | Why |
| --- | --- | --- |
| Model calls in the recorded runs | 0 | every run file records `"model": "scripted, not AI"` |
| Model cost per dispute | USD 0 | scripted agents make no calls; the optional local model (Ollama, `qwen2.5-coder:3b`) runs on the same machine and has no per call price |
| PayPal fees | none charged | sandbox only |

No run with the local model is in `data/runs` yet. When one is recorded, its file will carry the model label instead of `scripted, not AI`.
