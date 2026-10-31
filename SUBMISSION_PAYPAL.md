# Clearwake: PayPal AI Hackathon submission notes

## What it does

Finance operations teams want AI agents to help with refunds, but an agent saying "done" is not a payment receipt. Clearwake is a shared refund workroom:

* AI specialists prepare the case.
* The owner approves one exact refund, for one amount on one capture.
* Clearwake sends at most one request to PayPal.
* PayPal's own record decides whether the refund happened.

A lost provider response is held as UNKNOWN until a read of PayPal's refund record settles it. It is never blindly retried. A refund above the limit is refused before any money moves.

## Features

* **Autonomy policy** (`policy/autonomy.json`, read by the server, never by the model): specialist review runs at Draft, publishing and refunds at Execute with Approval, reconciliation at Execute within Limits. A prompt cannot change it, and each case database is bound to the policy it started with.
* **Recorded approval**: who approved, the exact amount and capture, when, the limit and the level. Shown on screen and in the activity log. No approval means no request.
* **Limit gauge**: the refund amount against the USD 5.00 cap. Above the cap is refused at setup and again at send time.
* **Send once**: the request ID is reserved before dispatch. A duplicate, a restart or a second click replays the held operation instead of sending again.
* **UNKNOWN node**: a lost or interrupted response stays UNKNOWN, pulsing in the timeline, until reconciliation reads the provider record. It then resolves to settled (COMPLETED) or reversed (declined or cancelled).
* **Record check**: amount, currency, capture link, request correlation (`custom_id`) and status must all match before the refund is shown as settled.
* **Shared workroom**: owner, editor and viewer roles. Only the owner can approve, send, revoke or reconcile.

## How PayPal is used (sandbox only)

| PayPal API | Used for |
| --- | --- |
| OAuth client credentials | Server side token, never sent to the browser |
| `POST /v2/checkout/orders` and `/capture` | One time setup: a USD 20.00 sandbox payment, approved by the sandbox buyer |
| `GET /v2/payments/captures/{id}` | Preflight before every refund |
| `POST /v2/payments/captures/{id}/refund` with `PayPal-Request-Id` and `custom_id` | One refund, under the limit |
| `GET /v2/payments/refunds/{id}` | Record check and reconciliation |

The adapter refuses any base URL other than `https://api-m.sandbox.paypal.com`, refuses redirects and proxies, and only allows these routes. Keys load from the ignored local `.env` and are never printed.

## Where AI is used

* Specialists (product, engineering, support) prepare the refund case in parallel; support waits for both.
* **Local AI:** `--enable-local-ai` runs them on `qwen2.5-coder:3b` through Ollama on the same machine. It is free, with no provider calls, a fixed fictional brief and a six attempt ledger.
* **Default:** without that flag, specialists are deterministic so the rehearsal makes no model calls.
* Models can only propose text. They cannot approve, send or reconcile money.

## What ran (filled from actual runs only)

| Run | Mode | Result |
| --- | --- | --- |
| Four cases, `scripts/check_demo.ps1` | Rehearsal, invented records, fake provider | 4 of 4 PASS (30 Oct) |
| Specialists on the local model (`qwen2.5-coder:3b`, Ollama) | Real local model, fictional brief | Ran (30 Oct): 3 real model calls, 412 tokens reported. Product and engineering outputs passed their contract checks. The support output failed validation and was refused, so this flow does not complete on the local model yet. The rehearsal uses deterministic specialists |
| Sandbox OAuth and setup order | PayPal sandbox | Ran: token issued, order `1DW875094F275773J` created (USD 20.00). The first order, `3BU49347KG046682J`, expired unapproved and the setup now replaces expired orders |
| Sandbox capture | PayPal sandbox | Ran (31 Oct): approved by the sandbox personal test buyer. Capture `1PH921107B839311S` COMPLETED, USD 20.00 sandbox money |
| Four cases, `scripts/check_sandbox.ps1` | PayPal sandbox (case b is an injected fault in sandbox) | **4 of 4 PASS (31 Oct).** a: refund `79R527888E694933F` sent, then VERIFIED from PayPal's refund record. b: a real refund was sent and its reply withheld, so it was held as UNKNOWN, the second send was replayed, and there was exactly 1 POST. c: refund `7A545589JM079780C` read from PayPal resolved UNKNOWN to VERIFIED with no second POST. d: USD 6.00 refused at setup and at send, 0 POSTs |
| Independent read of the sandbox records | PayPal sandbox | Ran (31 Oct): capture `1PH921107B839311S` is PARTIALLY_REFUNDED. Both refunds are COMPLETED, USD 1.00 each, linked to that capture, and carry Clearwake's request ID in `custom_id` |
| Test card setup (`--test-card`) | PayPal sandbox | Refused by PayPal for this sandbox merchant: PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING. Nothing captured |

## How to run

```sh
git clone --recurse-submodules https://github.com/Sriharsan/clearwake.git
cd clearwake
python -m clearwake --port 8810
```

To use the sandbox:
1. Copy `.env.example` to `.env` and add your own sandbox app's `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`.
2. Run `scripts/sandbox_setup.ps1` once and approve with a sandbox personal account.
3. Run `scripts/check_sandbox.ps1`.

## Changes during the submission period

Every commit in this repository and in the pinned Relayloom core is dated after 1 October 2026; see [docs/HACKATHON_UPDATES.md](docs/HACKATHON_UPDATES.md).

## Not claimed

No live PayPal (production), no real money, no customers. Sandbox results show the integration working against PayPal's test environment, nothing more.
