# Clearwake

### Send once. Resolve uncertainty. Verify the refund.

Clearwake is a shared refund workroom for finance operations teams. People and
specialists prepare the case together; the owner approves one exact effect;
uncertain provider responses stay held until a known payment record verifies
what happened. An agent saying “done” is not a payment receipt.

**Current build:** runnable local prototype with a durable fake gateway,
sandbox-only PayPal adapter and a pinned public multi-agent workroom. Default
mode makes zero network/model calls. Real PayPal sandbox and live AI acceptance
are separate gates; see [the contribution and verification record](docs/PROVENANCE.md).

## Run a clean checkout

Python 3.11 or newer is required. No package install or Docker is needed for the
default rehearsal. Clone with the public shared-core submodule:

```sh
git clone --recurse-submodules https://github.com/Sriharsan/clearwake.git
cd clearwake
python -m clearwake --port 8810
```

If you cloned without submodules, run `git submodule update --init --recursive`
first. Open **http://127.0.0.1:8810**. Keep this local server on loopback; do not
expose it through a public proxy or tunnel. Prepare Python and the checkout
while online before disconnected rehearsal. PayPal itself requires internet.

1. Create a workroom. Its prefilled brief is a fictional policy case.
2. Optionally invite an editor/viewer through the inherited scoped invitation
   system. Use a separate browser profile for a second participant.
3. Run the specialists. Product and Engineering work in parallel; Support waits
   for their results. Default specialist outputs are deterministic, not live AI.
4. Allow artifact publication and publish the checked current plan. This grants
   **no payment permission**.
5. In Payment operations, inspect the exact configured capture and USD 1.00
   amount. Check the owner acknowledgement, then grant the five-minute refund
   permission. Editors/viewers can read but cannot approve or send refunds.
6. Simulate one refund. The fake provider records it, but Clearwake still waits
   for a provider-record read. Click **Check provider record** to verify.
7. Repeat the send request or restart the server: the same durable operation
   stays held, rather than creating a second refund effect.

The payment panel shows actual application state, grant/revocation history,
provider status and checks. Raw payment evidence is in a closed disclosure.
Local SQLite records are stored under ignored `data/`; use synthetic data only.

## Revocation and uncertain outcomes

The owner can revoke the bound grant before dispatch. A fresh grant, role,
session, revision and plan check occurs at the final dispatch boundary.
Revocation during capture preflight blocks the later POST. The database
serializes the actual send with grant/intent changes: a revocation that commits
after dispatch cannot undo that already-sent effect.

One configured capture has at most one durable operation in this database.
Unknown/pending/interrupted operations retain their original `PayPal-Request-Id`.
There is no automatic refund retry, second request identity, or “reverse a
refund” action. Reconciliation is an explicit read of a known refund ID and
validates amount, USD currency, sandbox capture link, custom request correlation
and final status. A verified outcome needs `COMPLETED` from that read.

To rehearse a provider that remains pending or loses its response:

```sh
python -m clearwake --database data/pending/case.sqlite3 --rehearsal-outcome pending
python -m clearwake --database data/uncertain/case.sqlite3 --rehearsal-outcome lost-response
```

Use separate fictional cases for these modes. The fake provider has its own
durable `rehearsal-provider.sqlite3` record store. In a lost-response test, an
operator must obtain the known refund ID from that synthetic provider record
before reconciliation, just as a sandbox merchant would inspect its own record.
Never delete a real sandbox operation ledger or change databases to evade a
held payment; unresolved cases require explicit operator review.

## Explicit PayPal sandbox mode

The adapter uses only **https://api-m.sandbox.paypal.com**. Production URLs,
redirects, ambient proxies and arbitrary request destinations are refused.
The fixed case supports USD only, with a positive two-decimal amount up to 5.00.
The capture, amount, merchant and mode are pinned to the database.

Set server environment values described in [.env.example](.env.example):
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_SANDBOX_CAPTURE_ID`,
`CLEARWAKE_REFUND_AMOUNT`, and
`CLEARWAKE_SANDBOX_ACK=I_CONFIRM_SANDBOX_ONLY`. This app does not load an env
file automatically or create sandbox accounts/orders/captures for you.

```sh
python -m clearwake --database data/sandbox/case.sqlite3 --enable-paypal-sandbox
```

Use a capture belonging to the authorized sandbox merchant. The application
reads that capture before attempting its one bounded refund. Opening the page
does not send a payment. No live sandbox request was made in the offline test
suite; credentials and an actual sandbox outcome remain acceptance work.

## AI boundary

The reused workroom supports separate opt-ins for a reviewed local model
(`--enable-local-ai`) or its fixed-synthetic Meta adapter
(`--enable-meta-synthetic`); they cannot be combined. Neither is enabled by
default. Local/model configuration and verification are recorded separately;
do not infer a successful live model trial from an adapter being present.

The upstream Meta instructions are in `vendor/relayloom/docs/META.md`. Its
six-attempt default ledger is a request bound, not a dollar cap or evidence of
free credits. Model inputs are the bundled fictional fixture, never payment
credentials or a user's financial records. Models propose scoped text; they
cannot approve, dispatch, revoke or verify money authority by voting.

For the local option, prepare the reviewed `qwen2.5-coder:3b` model in Ollama on
the same trusted machine. Set `CLEARWAKE_LOCAL_AI_ACK=I_CONFIRM_LOCAL_SYNTHETIC`,
`CLEARWAKE_LOCAL_MODEL_DIGEST` to its reviewed 64-character SHA256 digest and
`CLEARWAKE_LOCAL_LEDGER` to an absolute private path. The route is fixed to
loopback 11434, with one inference slot, a six-attempt ledger, context 2048 and
output 512 tokens. The app never downloads a model automatically. Use a separate
database from deterministic rehearsal; worker configuration is pinned.

```sh
python -m clearwake --database data/local-ai/case.sqlite3 --enable-local-ai
```

## Verify offline

```sh
python -m unittest discover -s tests -v
node --check web/payment.js
node --test tests/payment.test.cjs
```

Node 22 is used for the dependency-free UI tests. Python tests use real SQLite,
controller threads and loopback HTTP, with fake PayPal transports only. They
cover separate grants, exact scope, current authority, revocation while waiting,
parallel duplicate requests, restart/unknown holds, correlated record checks,
cross-room/role refusal, HTTP CSRF/origin checks and production endpoint refusal.

## Reuse and event work

Clearwake reuses the MIT public Relayloom shared core at the pinned commit in
[NOTICE.md](NOTICE.md). It extends that real controller/server; it is not another
generic agent executor. The PayPal adapter, financial grant boundary, durable
uncertainty handling and payment evidence panel are the event-specific work.
No private Verdock source, history, data or credentials are included.

See [security boundaries](SECURITY.md), [official API references](docs/REFERENCES.md)
and [new-work provenance](docs/PROVENANCE.md). This prototype does not establish
customer production readiness, measured savings, regulatory compliance or final
hackathon eligibility. The live PayPal+AI demonstration and public video remain
explicit submission gates.
