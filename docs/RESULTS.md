# Results

Every number on this page comes from the run files in `data/runs/*.json` or from [SANDBOX_RUN.md](SANDBOX_RUN.md). Nothing is projected. Each run is labelled the way it ran: **real sandbox**, **injected fault in sandbox**, **local run on the local provider** (test records) or **offline**. The agents in every recorded run were **scripted, not AI**.

## Cases a to n, 31 October 2026 (evening, after settling in conversation and the network cut were added)

| Run file | Mode | PASS | FAIL | SKIPPED |
| --- | --- | --- | --- | --- |
| `cases-local-20261031-225445.json` | local run | 14 | 0 | 0 |
| `cases-sandbox-20261031-225507.json` | sandbox run | 9 | 0 | 5 |
| `data/airgap/airgap-20261031-223749.json` | case m, network isolated containers, real sandbox | 1 | 0 | 0 |

| Case | How it ran | Result |
| --- | --- | --- |
| c. Refund under the limit | **real sandbox** | PASS, refund `6SN41486G5579815G` VERIFIED |
| d. Approval inbox, then refund | **real sandbox** | PASS, refund `2NB27940EC188891M` VERIFIED after approval |
| e. Lost response, UNKNOWN, reconciled | **injected fault in sandbox** | PASS, 1 refund at PayPal, second call sent nothing, reconciled to VERIFIED |
| i, k, l | real sandbox | SKIPPED: no answerable sandbox dispute was open. Case i passed earlier the same day on `PP-R-SLI-10195419` (below) |
| m. Network cut mid batch | **real sandbox, network isolated containers, egress gateway** (`python scripts/airgap.py`) | PASS. Refund `6PX35920F4587564U` VERIFIED before the cut. Gateway disconnected at 22:37:01: two refunds held, offline, still held on retry, nothing sent. Network restored at 22:37:17: PayPal's capture read first, then refunds `76C086475Y724052F` and `9C434129FA2384059` VERIFIED. Running m2 again opened no new tunnel through the gateway |
| m, boundary checks | same run | no direct route out of the agents' container (DNS fails); `example.com` through the gateway refused with 403 and receipted; Ollama models answer inside |
| m, receipts | container started with `--network none` | 4 receipt logs verified: 34 gateway lines and 4, 14 and 12 merchant lines |
| n. Settled in conversation | local run; the buyer's acceptance is scripted | PASS: policy chose an offer of USD 2.50, PayPal shaped record RESOLVED at the INQUIRY stage. Fee avoided USD 0.00, because PayPal does not charge the Standard fee on claims below USD 30.00. Real sandbox: PASS on dispute PP-R-OBG-10196144. The policy chose an offer of USD 2.50, PayPal accepted it and paid the settlement (refund 0TB11858A85953644), the case read UNDER_REVIEW first and then RESOLVED (RESOLVED_BUYER_FAVOUR) at the INQUIRY stage, never a claim, no fee. The first run sent a message and then an offer and PayPal refused the offer (422 ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE); Clearwake now sends the offer alone and receipts a refusal honestly |
| n | real sandbox | SKIPPED: no sandbox dispute at the INQUIRY stage |

Case m used scripted rules for the refund decisions and `qwen2.5-coder:3b` through Ollama inside the boundary for the drafting that continued during the cut (6.3 s, 9.3 s and 13.1 s for one proposal in the three runs). The first run sent no refund because the local model proposed `provide_evidence` for a refund case; the second run sent none because the configured capture was PENDING and the capture read blocked it. Both are kept in `data/airgap/`.

### Dispatch proof, case o (1 November 2026)

| Case | How it ran | Result |
| --- | --- | --- |
| o. Buyer says 2 of 3 items arrived | local run; generated parcel pictures (`fixtures/dispatch/`); the count came from a scripted table, labelled "scripted count, not SAM" | PASS. Strong proof (3 of 3 counted, sealed, tracking shipped, log verifies): evidence sent with the photo, the local provider's record read back and shows the dispatch proof. Weak proof (the photo shows 2 of 3): nothing sent, the policy settled by offer |
| o | **real SAM 3 count** on a photo, offline on this laptop's CPU | PASS: 3 of 3 counted (scores 0.70, 0.62, 0.59), 15.1 s to load and 55.7 s to count, signed dispatch receipt `8b92abb9e53a6244`. The photo is a CC0 test photo (`fixtures/dispatch/photos/CREDITS.md`), not a real parcel |
| o | **real sandbox**, dispute `PP-R-UKF-10195772` (order `7RV99265V1496281G`, capture `4AN16499K3427771T`) | PASS on 3 November 2026. The buyer wrote "Only 2 of 3 notebooks arrived." The policy found strong proof and chose to fight with evidence. Submission 1: refused by PayPal, `ITEM_ID_IS_MANDATORY_FOR_MULTIPLE_EVIDENCES`, nothing applied. Submission 2: response lost, held as UNKNOWN, reading the dispute showed nothing had landed. Submission 3, the same request id: accepted. PayPal's record (10:13 UTC) shows a PROOF_OF_FULFILLMENT submitted by the seller with the dispatch text, the UPS tracking and the packing photo as a document; the dispute moved to WAITING_FOR_BUYER_RESPONSE. The signed receipts of the whole run, including the refused submission, are on the public site as the third log |

Which model: still photos use SAM 3 (`facebook/sam3`). SAM 3.1 (`facebook/sam3.1`, 27 March 2026) is Meta's video tracker and is not claimed for photos. Meta lists a CUDA GPU as a prerequisite. This machine has none, so SAM runs on the CPU through a 20 line patch (`tools/sam/cpu.patch`).

**Check that the CPU path is correct.** On Meta's own example image (four paper bags in a car boot), the prompt "paper bag" returned exactly 4 detections with scores 0.905, 0.901, 0.898 and 0.893; the next candidate was 0.13.

**Every prompt run on the notebook photo** (nothing was left out; the photo has three notebooks; the line is 0.5):

| Prompt | Found at 0.5 | Scores |
| --- | --- | --- |
| notebook | 0 | 0.193, 0.175, 0.168, 0.165, 0.071, 0.05 |
| notebooks | 1 | 0.634, 0.322, 0.245, 0.209, 0.206 |
| book | **3** | 0.696, 0.618, 0.593, 0.491, 0.359 |
| journal | 0 | none above 0.05 |
| paper notebook | 2 | 0.627, 0.523, 0.494, 0.361, 0.305 |
| booklet | 1 | 0.593, 0.498, 0.473, 0.335 |
| kraft notebook | 0 | 0.163, 0.137, 0.135 |

The prompt "book" was used for the receipt because it separated the three notebooks at the default confidence line. It was chosen after testing these, and the fourth candidate (0.491) missed the line. Timings on the CPU with 12 threads: about 16 s to load the model, 45 to 49 s to encode a photo, 4 to 5 s for each further prompt on the same photo.

Sandbox dispute creation by API was retried on 31 October: HTTP 400 "No permissions to set target_client_id" with the buyer's PayPal-Auth-Assertion, and `TRANSACTION_NOT_ELIGIBLE` without it. This app's token has no `disputes/update-buyer` scope, so accepting an offer as the buyer cannot be driven through the API either.

## Runs of the case runner (`scripts/cases.py`, 31 October 2026)

| Run file | Mode | PASS | FAIL | SKIPPED |
| --- | --- | --- | --- | --- |
| `cases-local-20261031-115247.json` | local run | 12 | 0 | 0 |
| `cases-local-20261031-153547.json` | local run | 12 | 0 | 0 |
| `cases-sandbox-20261031-115302.json` | sandbox run, first run | 6 | 3 | 3 |
| `cases-sandbox-20261031-115349.json` | sandbox run | 9 | 0 | 3 |

The first sandbox run failed cases c, d and e with nothing sent to PayPal: sandbox authentication had not been prepared, so the swarm held the refunds instead of sending them. The fix added a capture read before every refund ([SANDBOX_RUN.md](SANDBOX_RUN.md)). The second run, one minute later, passed.

Inside a sandbox run, only some cases touch PayPal. The rest run as local run or offline, and the run file says so on each line:

| Case | Label in `cases-sandbox-20261031-115349.json` | Result |
| --- | --- | --- |
| a. Buyer agent buys inside its mandate | local run (no `--order` passed) | PASS |
| b. Buyer agent refuses outside its mandate | local run, mandate check, no payment | PASS |
| c. Refund under the limit, verified | **real sandbox** | PASS, refund `34A6137827870312B` VERIFIED |
| d. Approval inbox, then refund | **real sandbox** | PASS, refund `0X757409L5274794C` VERIFIED after approval |
| e. Lost response, UNKNOWN, reconciled | **injected fault in sandbox** | PASS, 1 refund at PayPal, second call sent nothing, reconciled to VERIFIED |
| f. Split refunds stopped at the capture | local run | PASS |
| g. Prompt injection | local run, refused before any PayPal call | PASS |
| h. Tampered receipt | offline | PASS |
| i. Item not received, tracking before the deadline | real sandbox (case runs above); then dispute `PP-R-SLI-10195419` in a separate run | SKIPPED in the case runs; PASS on `PP-R-SLI-10195419`: tracking sent as the supporting info PayPal offered, read back VERIFIED |
| j. Mandate receipt as dispute evidence | local run dispute, receipt verified offline | PASS |
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

| Measure | Local run (each of the two runs) | Real sandbox |
| --- | --- | --- |
| Disputes handled | 13 (i, j, k and ten in l) | 1 (case i, `PP-R-SLI-10195419`, opened by the sandbox buyer after the case runs) |
| Item not received, case i | evidence sent, PayPal record shows UNDER_REVIEW | PASS. PayPal had already moved it to UNDER_REVIEW and offered only `provide_supporting_info`. The tracker from the order record was sent, and PayPal's record showed it (SUBMITTED_BY_SELLER, 2026-10-31T10:31:38Z) |
| Unauthorised agent order with mandate receipt, case j | evidence sent with the receipt, UNDER_REVIEW, receipt verifies offline | not run against a real dispute |
| Near deadline, case k | escalated to the approval inbox with 4 h 59 min left | SKIPPED |
| Batch of ten, case l (4 not received, 4 not as described, 2 unauthorised) | 4 evidenced, 4 refunded, 2 escalated | SKIPPED |
| Batch time, case l | 0.35 s and 0.37 s in total | not measured |
| Time per dispute, case l | 0.15 s and 0.14 s | not measured |

## Slow and lost answers

Sandbox answers vary in time, and Clearwake is built so that a slow or lost answer never moves money twice. These are the measured facts.

* **Reads retry.** A read waits 30 s and retries up to 3 times.
* **Writes wait once.** A write waits 45 s and is never repeated.
* **A lost or slow write answer is recorded as UNKNOWN.** Clearwake then reconciles from PayPal's record, using the stable `PayPal-Request-Id` the action carried, and states the outcome only after that record agrees.
* **Waits seen in the real sandbox ten case batch, before these timeouts were set:** case 1 waited 672 s and case 4 waited 28 s.
* **Postman request times** against the sandbox, 447 to 1735 ms, are in [POSTMAN.md](POSTMAN.md).

A lost response never pays twice.

## Model calls and cost

Model calls in the recorded runs: **85** (42 on qwen2.5-coder:3b and 42 on qwen3.5:4b in local runs on the local provider, plus 1 on PayPal's real sandbox record, read only). Every call was a real call to a model running on this machine through Ollama on loopback (CPU only, 14 cores, `num_thread` 6, reasoning off). Each call is a signed `clearwake.model.call` receipt with the model, the SHA-256 of the prompt, latency in ms, token counts, the model's proposal, what the policy decided and whether it overrode the model. The policy decides; the model only proposes and writes the text.

Run files: `data/runs/ai-eval-local-20261110-072208.json` (qwen2.5-coder:3b), `data/runs/ai-eval-local-20261110-072849.json` (qwen3.5:4b), `data/runs/ai-eval-real-record-20261110-115118.json` (one read only call on a real sandbox record). Produced by `python scripts/ai_eval.py --model <name>`. Each model got the same 42 prompts: 7 dispute types times 6 buyer messages, one of the types carrying an order-giving buyer message (6 injection prompts). Every number below comes from those run files.

| Measure | qwen2.5-coder:3b | qwen3.5:4b |
| --- | --- | --- |
| Calls (local run on the local provider) | 42 | 42 |
| Valid JSON, usable proposal | 42 of 42 | 42 of 42 |
| Fell back to the scripted rule | 0 | 0 |
| Proposal matched the correct decision | 28 of 42 | 35 of 42 |
| Policy decision correct | 42 of 42 | 42 of 42 |
| Proposals the policy overrode | 14 | 7 |
| Wrong action, by type | fight with records, 12 (types o and u, never proposed fighting); order-giving message, 2 | unauthorised with a signed mandate, 6; order-giving message, 1 |
| Offer amount the model set wrongly, capped by the policy | 2 | 1 |
| Model texts sent after code checks | 32 | 41 |
| Model texts blocked by the code check | 10 | 1 |
| Blocked by reason | amount differs from the offer 6, currency missing 4, offer amount missing 3, promise beyond the offer 1 | amount differs from the offer 1, currency missing 1, offer amount missing 1, promise beyond the offer 1 |
| Injection prompts, receipted as an injection event | 5 of 6 (the sixth was added to the detector afterwards, with a test) | 5 of 6 (same) |
| Injection prompts where the model followed the order | 2 | 1 |
| Injection prompts where the decision changed | 0 | 0 |
| Latency, median / 90th percentile / max | 8,956 / 10,925 / 16,660 ms | 24,522 / 42,584 / 65,446 ms |
| Tokens in / out | 10,263 / 1,883 | 10,431 / 1,753 |
| Receipt chain verifies | yes | yes |

Blocked-by-reason counts are problems found, so one text can carry two. The model texts are checked by code for the amount (must equal the offer), the currency, promises beyond the offer, ids absent from the PayPal record and links. A blocked text is replaced by the fixed text and the receipt says so.

The model used is qwen3.5:4b: it proposed the correct action on 35 of 42 prompts against 28 for the 3b model, and its median answer takes 24.5 s, under the 30 s limit (the 3b model answers in 9.0 s but never proposed fighting with records). Both models were wrong on part of the prompts and the policy produced the correct decision on all 84 (42 + 42). Latency in these runs was measured with other work running on the same machine at times, so the worst times (65 s) include contention.

| Real sandbox record, read only | Value |
| --- | --- |
| Dispute | `PP-R-OBG-10196144`, PayPal's real sandbox record, status shown as waiting for the seller in memory, every write blocked |
| Model call | qwen3.5:4b, 22,555 ms, 262 tokens in, 45 out, proposed settle by offer, policy decided settle by offer, text accepted |
| Real sandbox dispute at INQUIRY waiting for the seller | none existed on 10 November (the list held one RESOLVED, one waiting for the buyer, one CHARGEBACK), so no real offer was driven by the model |

| Measure | Value | Why |
| --- | --- | --- |
| Model cost per dispute | USD 0 | the model runs on the same machine and has no per call price |
| PayPal fees | none charged | sandbox only |
| Earlier recorded case runs | scripted | the case runs before 10 November in `data/runs` used the scripted rule and recorded `"model": "scripted, not AI"`; the one earlier local model use was the drafting in case m |
