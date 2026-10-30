# Clearwake

Clearwake lets AI agents prepare refunds while a person approves one exact amount, and PayPal's own record decides whether the refund really happened. A lost response is held as UNKNOWN and never retried blindly; a refund above the limit is refused before any money moves.

```sh
git clone --recurse-submodules https://github.com/Sriharsan/clearwake.git && cd clearwake && python -m clearwake --port 8810
```

Open http://127.0.0.1:8810. Python 3.11 or newer, nothing to install. Windows: `.\demo.ps1`. macOS or Linux: `./demo.sh`.

![Clearwake payment view in rehearsal: limit gauge at USD 1.00 of a USD 5.00 cap, autonomy levels, and a timeline holding a lost response as UNKNOWN](docs/screenshot-unknown-1440.png)

*Screenshot: rehearsal mode, invented records, fake provider.*

**License:** MIT. **Status:** a working local app with 39 offline tests (35 Python, 4 UI). Default mode is a rehearsal with a fake provider and invented records. A real PayPal sandbox adapter is built in; what has actually run against the sandbox is listed in [SUBMISSION_PAYPAL.md](SUBMISSION_PAYPAL.md). Built during the PayPal AI Hackathon submission period; see [docs/HACKATHON_UPDATES.md](docs/HACKATHON_UPDATES.md).

### Autonomy where it is safe, approval where it matters, proof after every action

| Operation | Autonomy level | What that means |
| --- | --- | --- |
| Specialist review | Draft | AI specialists prepare the plan. They cannot approve, send, revoke or reconcile money. |
| Publish plan | Execute with Approval | The owner allows publication. Publishing never grants payment permission. |
| Refund | Execute with Approval | The owner approves one exact amount on one capture, within the USD 5.00 limit, for five minutes. Never retried automatically. |
| Reconcile | Execute within Limits | A read only check of the provider record runs on its own and never sends money. |

The levels live in [policy/autonomy.json](policy/autonomy.json), read by the server, never by the model, and bound to each case database. A prompt cannot change them. Every refund has an approval record (who, exact amount and capture, when, against which limit), shown on screen and in the activity log. A refund is shown as settled only when the provider record matches.

### Four cases, one command each

| Case | Rehearsal (no network) | PayPal sandbox (needs keys in `.env`) |
| --- | --- | --- |
| a. Refund under the limit, checked against the record | `scripts/check_demo.ps1` | `scripts/check_sandbox.ps1` |
| b. Lost response goes to UNKNOWN, no blind retry | same | same (injected fault in sandbox) |
| c. Reconciliation resolves UNKNOWN | same | same |
| d. Over limit refund refused before money moves | same | same |

Each prints PASS or FAIL per case. Shell versions: `scripts/check_demo.sh`, `scripts/check_sandbox.sh`. Sandbox setup: copy `.env.example` to `.env`, add your own sandbox app keys, then run `scripts/sandbox_setup.ps1` once.

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
