# Results

Every number on this page comes from the run files in `data/runs/*.json` or from [SANDBOX_RUN.md](SANDBOX_RUN.md). Nothing is projected. Each run is labelled the way it ran: **real sandbox**, **injected fault in sandbox**, **rehearsal** (fake provider, invented records) or **offline**. The agents in every recorded run were **scripted, not AI**.

## Cases a to n, 31 October 2026 (evening, after settling in conversation and the network cut were added)

| Run file | Mode | PASS | FAIL | SKIPPED |
| --- | --- | --- | --- | --- |
| `cases-rehearsal-20261031-225445.json` | rehearsal | 14 | 0 | 0 |
| `cases-sandbox-20261031-225507.json` | sandbox run | 9 | 0 | 5 |
| `data/airgap/airgap-20261031-223749.json` | case m, network isolated containers, real sandbox | 1 | 0 | 0 |

| Case | How it ran | Result |
| --- | --- | --- |
| c. Refund under the limit | **real sandbox** | PASS, refund `6SN41486G5579815G` VERIFIED |
| d. Approval inbox, then refund | **real sandbox** | PASS, refund `2NB27940EC188891M` VERIFIED after approval |
| e. Lost response, UNKNOWN, reconciled | **injected fault in sandbox** | PASS, 1 refund at PayPal, second attempt sent nothing, reconciled to VERIFIED |
| i, k, l | real sandbox | SKIPPED: no answerable sandbox dispute was open. Case i passed earlier the same day on `PP-R-SLI-10195419` (below) |
| m. Network cut mid batch | **real sandbox, network isolated containers, egress gateway** (`python scripts/airgap.py`) | PASS. Refund `6PX35920F4587564U` VERIFIED before the cut. Gateway disconnected at 22:37:01: two refunds held, offline, still held on retry, nothing sent. Network restored at 22:37:17: PayPal's capture read first, then refunds `76C086475Y724052F` and `9C434129FA2384059` VERIFIED. Running m2 again opened no new tunnel through the gateway |
| m, boundary checks | same run | no direct route out of the agents' container (DNS fails); `example.com` through the gateway refused with 403 and receipted; Ollama models answer inside |
| m, receipts | container started with `--network none` | 4 receipt logs verified: 34 gateway lines and 4, 14 and 12 merchant lines |
| n. Settled in conversation | rehearsal; the buyer's acceptance is simulated | PASS: policy chose an offer of USD 2.50, PayPal shaped record RESOLVED at the INQUIRY stage. Fee avoided USD 0.00, because PayPal does not charge the Standard fee on claims below USD 30.00 |
| n | real sandbox | SKIPPED: no sandbox dispute at the INQUIRY stage |

Case m used scripted rules for the refund decisions and `qwen2.5-coder:3b` through Ollama inside the boundary for the drafting that continued during the cut (6.3 s, 9.3 s and 13.1 s for one proposal in the three attempts). The first attempt sent no refund because the local model proposed `provide_evidence` for a refund case; the second sent none because the configured capture was PENDING and the capture read blocked it. Both are kept in `data/airgap/`.

Sandbox dispute creation by API was retried on 31 October: HTTP 400 "No permissions to set target_client_id" with the buyer's PayPal-Auth-Assertion, and `TRANSACTION_NOT_ELIGIBLE` without it. This app's token has no `disputes/update-buyer` scope, so accepting an offer as the buyer cannot be driven through the API either.

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
| i. Item not received, tracking before the deadline | real sandbox (case runs above); then dispute `PP-R-SLI-10195419` in a separate run | SKIPPED in the case runs; PASS on `PP-R-SLI-10195419`: tracking sent as the supporting info PayPal offered, read back VERIFIED |
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
| Case m, before the cut | `6PX35920F4587564U` | USD 1.00 | VERIFIED |
| Case m, held offline then resumed | `76C086475Y724052F`, `9C434129FA2384059` | USD 1.00 each | VERIFIED |
| Evening run, case c | `6SN41486G5579815G` | USD 1.50 | VERIFIED |
| Evening run, case d (after approval) | `2NB27940EC188891M` | USD 3.50 | VERIFIED |
| Evening run, case e (injected fault in sandbox) | ID not written to the run file | USD 1.50 | VERIFIED by reconciliation |

Amounts for c, d and e are the ones set in `scripts/cases.py`. The four case check passed 4 of 4 ([SANDBOX_RUN.md](SANDBOX_RUN.md)).

## Disputes

| Measure | Rehearsal (each of the two runs) | Real sandbox |
| --- | --- | --- |
| Disputes handled | 13 (i, j, k and ten in l) | 1 (case i, `PP-R-SLI-10195419`, opened by the sandbox buyer after the case runs) |
| Item not received, case i | evidence sent, PayPal record shows UNDER_REVIEW | PASS. PayPal had already moved it to UNDER_REVIEW and offered only `provide_supporting_info`. The tracker from the order record was sent, and PayPal's record showed it (SUBMITTED_BY_SELLER, 2026-10-31T10:31:38Z) |
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

The case runs in `data/runs` used scripted agents. The one recorded local model use is the drafting in case m above, inside the network isolated containers.
