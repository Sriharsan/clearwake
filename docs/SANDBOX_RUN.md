# PayPal sandbox runs

All against `https://api-m.sandbox.paypal.com` with Sri's sandbox app. These are test money and test records only. IDs are PayPal sandbox IDs; there are no secrets here.

## Setup (31 October 2026)
* Order `1DW875094F275773J`, USD 20.00, approved by the sandbox personal test buyer in PayPal checkout.
* Capture `1PH921107B839311S` COMPLETED.
* Tracking `SYNTH1Z999AA10123456` (UPS) added to the order through the API. PayPal shows it SHIPPED.

## Four case check (`scripts/check_sandbox.ps1`, 31 October)
4 of 4 PASS:
* Refunds `79R527888E694933F` and `7A545589JM079780C`, each USD 1.00.
* An independent read later showed both COMPLETED and linked to the capture, which is now PARTIALLY_REFUNDED.

## Cases a to l (`python scripts/cases.py --sandbox`, 31 October)

| Case | How it ran | Result |
| --- | --- | --- |
| a. Buyer agent buys inside its mandate | local run on the local provider: no order id passed (use `--order` after a buyer approval) | PASS |
| b. Buyer agent refuses outside its mandate | mandate check, no payment | PASS |
| c. Refund under the limit, verified | **real sandbox** | PASS, refund `34A6137827870312B` VERIFIED |
| d. Approval inbox, then refund | **real sandbox** | PASS, refund `0X757409L5274794C` VERIFIED after approval |
| e. Lost response, UNKNOWN, reconciled | **injected fault in sandbox**: the real refund was sent and its reply withheld | PASS: 1 refund at PayPal, second call sent nothing, reconciled to VERIFIED |
| f. Split refunds stopped at the capture | local run (a USD 5 capture is needed to show it under the USD 5 cap) | PASS |
| g. Prompt injection | refused before any PayPal call | PASS |
| h. Tampered receipt | offline | PASS |
| i, k, l. Real disputes | **SKIPPED**: no open sandbox disputes. PayPal does not let this app open one for the buyer (HTTP 400 "No permissions to set target_client_id"), so the sandbox buyer must open them in the Resolution Center | SKIPPED |
| j. Mandate receipt as dispute evidence | local run dispute; receipt verified offline | PASS |

An earlier run of the same session, minutes before, failed cases c, d and e with **nothing sent to PayPal**. The swarm sent no refund request because sandbox authentication had not been prepared. Clearwake will not fetch a token in the moment before a POST, so the refunds were held. The fix adds a capture preflight read before every refund (commit after `8753970`). If the preflight fails, the refund is refused with "Nothing was sent".

## Case i on a real dispute (`python scripts/cases.py --sandbox --dispute PP-R-SLI-10195419 --only i`, 31 October)

The sandbox buyer opened dispute `PP-R-SLI-10195419` ("item not received") on order `8M960780ES843141H` in the Resolution Center.
When Clearwake read it, PayPal had already moved it to UNDER_REVIEW (stage CHARGEBACK). The only merchant action PayPal still
offered in the dispute's links was `provide_supporting_info`. Clearwake reads those links and uses only what PayPal offers.

* The swarm sent the tracker from the PayPal order record (`SYNTH1Z999AA10654321`, SHIPPED) as supporting info. Nothing else was sent.
* The Checker read the dispute back. PayPal's record shows the note as SUBMITTED_BY_SELLER at 2026-10-31T10:31:38Z, so the case is VERIFIED.
* Result: **PASS** (real sandbox). Evidence was sent as supporting info, not as `provide-evidence`, because PayPal no longer offered `provide-evidence`.
* The first run minutes earlier stopped at the OAuth token request with a transport error, so no dispute call was made. A second
  run was skipped because the script only counted WAITING_FOR_SELLER_RESPONSE and OPEN disputes. The third run is the PASS above.

## Dispute creation by API, retried (31 October, evening)

`POST /v1/customer/disputes` with a buyer `PayPal-Auth-Assertion` (by payer id, then by email) on capture `1PH921107B839311S`: HTTP 400 "No permissions to set target_client_id". Without the assertion: HTTP 400 `TRANSACTION_NOT_ELIGIBLE`. The app's token carries `disputes/create`, `update-seller` and `read-seller` but not `update-buyer`. Real sandbox disputes are still opened by the sandbox buyer in the Resolution Center, and in case n the buyer accepts the offer there.

## Case m: network cut in the isolated containers (`python scripts/airgap.py`, 31 October)

Agents and Ollama on an internal Docker network; the verdock-core egress gateway is the only service with a route out and allows only `api-m.sandbox.paypal.com`. Capture `1PH921107B839311S` (set with `PAYPAL_SANDBOX_CAPTURE_ID` for the run; `.env` points at the PENDING capture `96H267908A407644D`, which the capture read correctly refused in the second run).

* Boundary: no direct route out of the agents' container (DNS fails); `CONNECT example.com:443` through the gateway refused with 403 and receipted; models `qwen3.5:4b` and `qwen2.5-coder:3b` answer inside.
* Before the cut: refund `6PX35920F4587564U`, USD 1.00, VERIFIED.
* 22:37:01, the gateway disconnected from the outside network: two USD 1.00 refunds held, offline, and still held on a resume call. `qwen2.5-coder:3b` kept drafting inside (13.1 s).
* 22:37:17, reconnected: PayPal's capture read first, then refunds `76C086475Y724052F` and `9C434129FA2384059` VERIFIED with their original request ids. Running m2 again opened no new tunnel.
* Every receipt log verified in a container started with `--network none`: 34 gateway lines, 12 merchant lines for this run.
* Result: **PASS**. Report: `data/airgap/airgap-20261031-223749.json`. The receipts are published on the site under `site/receipts/`.

## Case o, dispatch proof (1 November)

Run for real on 3 November 2026.

* New order `7RV99265V1496281G`, USD 20.00, approved by the sandbox buyer; capture `4AN16499K3427771T` COMPLETED; test UPS tracking added and shown SHIPPED by PayPal.
* The buyer opened dispute `PP-R-UKF-10195772` in the Resolution Center (item not received, expected refund USD 5.00): "Only 2 of 3 notebooks arrived." PayPal: OPEN, stage INQUIRY, and it offered the seller `provide_evidence`, `send_message`, `make_offer`, `escalate` and `accept_claim`.
* Packing: SAM 3 counted 3 of 3 on the CPU (`python scripts/dispatch.py pack --data data/sandbox/dispatch ... --counter sam --save-count`), signed receipt `8b92abb9e53a6244`.
* `provide-evidence` with the photo as an `evidence-file` part. Submission 1, refused: `400 INVALID_REQUEST ITEM_ID_IS_MANDATORY_FOR_MULTIPLE_EVIDENCES`, nothing applied (the tracking and the dispatch proof were two entries, and the disputed item shows no item id). The fix sends one merged entry. Submission 2: response lost, held as UNKNOWN; reading the dispute showed nothing had landed. Submission 3, same request id: HTTP 200 in 4.2 s.
* Read back: a PROOF_OF_FULFILLMENT entry, source SUBMITTED_BY_SELLER, 3 Nov 2026 10:13 UTC, with the dispatch notes, the tracker and a document `packing-photo-893632548b14c5d5.jpg` that PayPal now hosts. Status WAITING_FOR_BUYER_RESPONSE, stage INQUIRY.
* Result: **PASS**. The receipts of the run, including the refused submission, are `site/receipts/case-o-dispatch.ndjson` and verify in the browser.

## Cases a to n (`python scripts/cases.py --sandbox`, 31 October, evening)

9 PASS, 0 FAIL, 5 SKIPPED. c: refund `6SN41486G5579815G` VERIFIED. d: refund `2NB27940EC188891M` VERIFIED after approval. e: injected fault, one refund at PayPal, reconciled. i, k, l and n: SKIPPED, no answerable sandbox dispute open. m: runs in the isolated containers (above).
