# PayPal sandbox runs

All against `https://api-m.sandbox.paypal.com` with Sri's sandbox app. These are test money and invented records only. IDs are PayPal sandbox IDs; there are no secrets here.

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
| a. Buyer agent buys inside its mandate | rehearsal: no order id passed (use `--order` after a buyer approval) | PASS |
| b. Buyer agent refuses outside its mandate | mandate check, no payment | PASS |
| c. Refund under the limit, verified | **real sandbox** | PASS, refund `34A6137827870312B` VERIFIED |
| d. Approval inbox, then refund | **real sandbox** | PASS, refund `0X757409L5274794C` VERIFIED after approval |
| e. Lost response, UNKNOWN, reconciled | **injected fault in sandbox**: the real refund was sent and its reply withheld | PASS: 1 refund at PayPal, second attempt sent nothing, reconciled to VERIFIED |
| f. Split refunds stopped at the capture | rehearsal (a USD 5 capture is needed to show it under the USD 5 cap) | PASS |
| g. Prompt injection | refused before any PayPal call | PASS |
| h. Tampered receipt | offline | PASS |
| i, k, l. Real disputes | **SKIPPED**: no open sandbox disputes. PayPal does not let this app open one for the buyer (HTTP 400 "No permissions to set target_client_id"), so the sandbox buyer must open them in the Resolution Center | SKIPPED |
| j. Mandate receipt as dispute evidence | rehearsal dispute; receipt verified offline | PASS |

An earlier attempt of the same run, minutes before, failed cases c, d and e with **nothing sent to PayPal**. The swarm sent no refund request because sandbox authentication had not been prepared. Clearwake will not fetch a token in the moment before a POST, so the refunds were held. The fix adds a capture preflight read before every refund (commit after `8753970`). If the preflight fails, the refund is refused with "Nothing was sent".

## Case i on a real dispute (`python scripts/cases.py --sandbox --dispute PP-R-SLI-10195419 --only i`, 31 October)

The sandbox buyer opened dispute `PP-R-SLI-10195419` ("item not received") on order `8M960780ES843141H` in the Resolution Center.
When Clearwake read it, PayPal had already moved it to UNDER_REVIEW (stage CHARGEBACK). The only merchant action PayPal still
offered in the dispute's links was `provide_supporting_info`. Clearwake reads those links and uses only what PayPal offers.

* The swarm sent the tracker from the PayPal order record (`SYNTH1Z999AA10654321`, SHIPPED) as supporting info. Nothing else was sent.
* The Checker read the dispute back. PayPal's record shows the note as SUBMITTED_BY_SELLER at 2026-10-31T10:31:38Z, so the case is VERIFIED.
* Result: **PASS** (real sandbox). Evidence was sent as supporting info, not as `provide-evidence`, because PayPal no longer offered `provide-evidence`.
* The first attempt minutes earlier stopped at the OAuth token request with a transport error, so no dispute call was made. A second
  attempt was skipped because the script only counted WAITING_FOR_SELLER_RESPONSE and OPEN disputes. The third attempt is the PASS above.
