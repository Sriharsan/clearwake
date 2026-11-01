# Design decisions

## Receipts: IETF draft-sahu-agent-action-receipts-00
Chosen over a W3C Verifiable Credential format. The draft is small and uses Ed25519. It chains each receipt to the exact bytes of the one before, and verifies with no network, no service and no canonicalizer for the chain. It also ships test vectors, so the implementation is checked byte for byte. Chrome's built in WebCrypto supports Ed25519, so the browser Verify button needs no library. Pinned version: draft 00 (16 August 2026). The verifier proves a log was not altered after it was written. It cannot prove that every action was recorded, or that the end of the log was not cut off (draft section 9).

## Shared engine: verdock-core
Policy, approvals, swarm invariants and locks, outcome states with the reconciler interface, signed receipts and the offline verifier live in verdock-core. It has an MIT license, uses only the Python standard library, and is pinned into Clearwake as a git submodule, so the one command run needs nothing installed. Clearwake adds only the PayPal adapters, agents and UI.

## PayPal agent toolkit: optional, not the default path
paypal/agent-toolkit (Apache 2.0, 1.11.0) pins openai-agents, langchain and crewai-tools. Making it a hard dependency would break the run with nothing installed. Clearwake keeps its own sandbox only adapter with an allowlist of routes, and uses the toolkit only in an optional environment for the toolkit comparison. The toolkit has no capture refund tool. Its money returning action for disputes is accept_dispute_claim, so the comparison uses that.

## Disputes
* `POST /v1/customer/disputes` with a buyer PayPal-Auth-Assertion was tried against the sandbox on 31 October. It returned HTTP 400 "No permissions to set target_client_id". Opening a dispute on the buyer's behalf needs partner permission that a normal merchant app does not have.
* So real PayPal disputes are opened by the sandbox buyer in the sandbox Resolution Center (a manual step by Sri). Clearwake then lists, reads and resolves them through the Disputes API: accept claim with a refund amount, or provide evidence. In the sandbox it can also settle a dispute with `/adjudicate`, which is sandbox only.
* For repeatable demo cases, the buyer agent's complaint reaches the merchant through Clearwake itself, labelled "buyer complaint". Money still moves only through real sandbox refunds checked against PayPal's record.

## Buyer payments
The sandbox merchant for this app is not enabled for card processing (PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING, observed 31 October). So buyer agent purchases are approved by the sandbox buyer in PayPal's checkout. A US sandbox business account with card processing would let the buyer agent pay with PayPal's published sandbox test cards, without a login.

## Models
One OpenAI compatible adapter with three backends:
* A free open weights model through Ollama on loopback (default; `qwen2.5-coder:3b` is installed).
* Meta Muse Spark through the Meta Model API, off unless Sri confirms the credit terms or pays.
* Scripted agents, always labelled "scripted, not AI".

Models only propose. The policy file decides.
* **Dispatch proof (1 November).** A signed receipt written at packing, in the merchant's own receipt chain, so it verifies offline with the rest. The buyer's message is read only as a claim to check ("only 2 of 3 arrived") and never decides an amount or an action. Strong proof (count matches the order, sealed, tracking shows shipped, log verifies) goes out as evidence; weak proof is never sent, so Clearwake does not answer a claim of missing items with tracking alone. Only photos whose SHA-256 the receipt lists are attached. SAM runs as a separate process in its own environment, offline, so the app stays on the Python standard library. Still photos use SAM 3 because Meta's image code loads that checkpoint; SAM 3.1 is the video tracker, and the receipt names the model that actually ran.
