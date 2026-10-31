# Clearwake

Clearwake answers every PayPal dispute for small merchants today, inside limits they set, with proof. And it is ready for orders placed by AI agents.

```sh
git clone --recurse-submodules https://github.com/Sriharsan/clearwake.git && cd clearwake && python -m clearwake --port 8810
```

Open http://127.0.0.1:8810/console for the three screens (buyer agent, merchant control room, receipt verifier), or http://127.0.0.1:8810 for the refund workroom. Python 3.12 or newer, nothing to install. Windows: `.\demo.ps1`. macOS or Linux: `./demo.sh`.

![Clearwake refund workroom in rehearsal: limit gauge at USD 1.00 of a USD 5.00 cap, autonomy levels, and a timeline holding a lost response as UNKNOWN](docs/screenshot-unknown-1440.png)

*Screenshot: the refund workroom in rehearsal mode, invented records, fake provider.*

**License:** MIT.

## Who it is for

Small PayPal merchants who lose disputes because they cannot gather evidence before the deadline. Clearwake reads the dispute, pulls the order, the capture and the tracking from PayPal's own record, and either answers with evidence, refunds inside the merchant's limit, or puts the case in an approval inbox before the deadline runs out. Every action is checked afterwards against PayPal's record and written to a signed receipt that anyone can verify offline.

When the buyer is an AI agent, Clearwake also signs the owner's spending mandate on the buyer side and links it to the PayPal order, so the merchant can attach it as evidence if the order is disputed.

## Status

| What | How it ran | Result |
| --- | --- | --- |
| Four refund cases (`scripts/check_sandbox.ps1`) | real sandbox, case b is an injected fault in sandbox | 4 of 4 PASS on 31 October. Refunds `79R527888E694933F` and `7A545589JM079780C` COMPLETED in PayPal's record |
| Cases c, d, e of `scripts/cases.py --sandbox` (refund, approval then refund, lost response) | real sandbox; e is an injected fault in sandbox | PASS on 31 October. Refunds `34A6137827870312B` and `0X757409L5274794C` VERIFIED |
| Case i (real PayPal dispute) | real sandbox | PASS on `PP-R-SLI-10195419`: tracking sent as the supporting info PayPal offered, read back VERIFIED |
| Cases k, l (real PayPal disputes) | real sandbox | SKIPPED: k needs a dispute close to its deadline, l needs ten real disputes |
| Cases a to l (`scripts/cases.py`) | rehearsal, fake provider, invented records | 12 of 12 PASS, twice |
| The console at `/console` | rehearsal, invented records | runs locally |
| Offline tests | fake transports | 78 Python and 12 UI tests pass (31 October) |

Every number is in [docs/RESULTS.md](docs/RESULTS.md) and [docs/SANDBOX_RUN.md](docs/SANDBOX_RUN.md), from the run files in `data/runs/`. Sandbox means PayPal's test environment with test money. No live PayPal, no real money.

## AI tools used

* **Scripted agents (default).** Fixed rules, labelled "scripted, not AI" on screen and in every run file. Zero model calls.
* **Ollama with `qwen2.5-coder:3b` (optional).** A local open weights model on loopback for agent proposals: `python scripts/cases.py --model ollama`, `python -m clearwake --console-model ollama`, or `--enable-local-ai` for the workroom specialists. No run with it is in `data/runs` yet.
* **Meta model API: off.** The adapter exists in the shared Relayloom core and is not enabled in Clearwake.

Models only propose. The limits live in [policy/merchant.yaml](policy/merchant.yaml), read by the server and never by a model: refunds up to USD 2.00 run alone, up to USD 5.00 need an approval, anything above is refused, and one customer is capped at USD 6.00 a day.

## Shared engine: verdock-core

Policy decisions, approvals, swarm invariants (locks, caps per capture and per customer per day, one stable request id per action), outcome states with reconciliation, and signed receipts with an offline verifier all come from [verdock-core](https://github.com/Sriharsan/verdock-core) v0.1.0, MIT, pinned as a git submodule at `vendor/verdock-core`. It uses the Python standard library only. Clearwake adds the PayPal adapter, the agents and the screens.

## Where this goes

Built today on PayPal: limits outside the model, recorded approvals, swarm invariants, a separate check of every money movement against PayPal's record, signed receipts on both sides, and dispute evidence with deadline escalation.

Planned, not built: agent work inside the business's own isolated environment, local open weights models by default, shared context for teams of people and agents, continuous daily operations, and receipts accepted by payment platforms as proof. Details in [docs/VISION.md](docs/VISION.md).

## Cases, one command each

```sh
python scripts/cases.py                         # rehearsal, a to l, no network
python scripts/cases.py --sandbox               # real sandbox where PayPal allows it (keys in .env)
python scripts/cases.py --sandbox --only i --dispute <dispute id>   # one real dispute, read by id
python scripts/cases.py --sandbox --order <order id>                # case a after a sandbox buyer approval
```

Every line prints PASS, FAIL or SKIPPED with how it ran, and the run is saved to `data/runs/`. The older four refund cases still run with `scripts/check_demo.ps1` (rehearsal) and `scripts/check_sandbox.ps1` (sandbox). Sandbox setup: copy `.env.example` to `.env`, add your own sandbox app keys, then run `scripts/sandbox_setup.ps1` once and approve the order as the sandbox personal buyer.

Submission notes: [SUBMISSION_PAYPAL.md](SUBMISSION_PAYPAL.md). Changes during the hackathon: [docs/HACKATHON_UPDATES.md](docs/HACKATHON_UPDATES.md).

### Autonomy where it is safe, approval where it matters, proof after every action

| Operation | Autonomy level | What that means |
| --- | --- | --- |
| Specialist review | Draft | AI specialists prepare the plan. They cannot approve, send, revoke or reconcile money. |
| Publish plan | Execute with Approval | The owner allows publication. Publishing never grants payment permission. |
| Refund | Execute with Approval | The owner approves one exact amount on one capture, within the USD 5.00 limit, for five minutes. Never retried automatically. |
| Reconcile | Execute within Limits | A read only check of the provider record runs on its own and never sends money. |

These levels apply to the refund workroom and live in [policy/autonomy.json](policy/autonomy.json), read by the server, never by the model, and bound to each case database. A prompt cannot change them. Every refund has an approval record (who, exact amount and capture, when, against which limit), shown on screen and in the activity log. A refund is shown as settled only when the provider record matches.

## Run a clean checkout

Python 3.12 or newer is required. No package install or Docker is needed for the
default rehearsal. Clone with the public submodules:

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
   amount. Check the owner acknowledgement, then grant the five minute refund
   permission. Editors/viewers can read but cannot approve or send refunds.
6. Simulate one refund. The fake provider records it, but Clearwake still waits
   for a provider record read. Click **Check provider record** to verify.
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
after dispatch cannot undo that already sent effect.

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
durable `rehearsal-provider.sqlite3` record store. In a lost response test, an
operator must obtain the known refund ID from that synthetic provider record
before reconciliation, just as a sandbox merchant would inspect its own record.
Never delete a real sandbox operation ledger or change databases to evade a
held payment; unresolved cases require explicit operator review.

## Explicit PayPal sandbox mode

The adapter uses only **https://api-m.sandbox.paypal.com**. Production URLs,
redirects, ambient proxies and arbitrary request destinations are refused, and
only an allowlist of OAuth, Orders v2, Payments v2 and Disputes v1 routes can be
called. The refund workroom supports USD only, with a positive two decimal amount
up to 5.00. The capture, amount, merchant and mode are pinned to the database.

Set server environment values described in [.env.example](.env.example):
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_SANDBOX_CAPTURE_ID`,
`CLEARWAKE_REFUND_AMOUNT`, and
`CLEARWAKE_SANDBOX_ACK=I_CONFIRM_SANDBOX_ONLY`.

```sh
python -m clearwake --database data/sandbox/case.sqlite3 --enable-paypal-sandbox
```

Use a capture belonging to the authorized sandbox merchant. The application
reads that capture before attempting its one bounded refund. Opening the page
does not send a payment. The offline test suite uses fake transports only; the
sandbox results above come from the scripted runs recorded in `data/runs/` and
[docs/SANDBOX_RUN.md](docs/SANDBOX_RUN.md).

## AI boundary

The reused workroom supports separate opt ins for a reviewed local model
(`--enable-local-ai`) or its fixed synthetic Meta adapter
(`--enable-meta-synthetic`); they cannot be combined. Neither is enabled by
default, and the Meta adapter is not used for Clearwake. Do not infer a
successful live model trial from an adapter being present.

The upstream Meta instructions are in `vendor/relayloom/docs/META.md`. Its
six attempt default ledger is a request bound, not a dollar cap or evidence of
free credits. Model inputs are the bundled fictional fixture, never payment
credentials or a user's financial records. Models propose scoped text; they
cannot approve, dispatch, revoke or verify money authority by voting.

For the local option, prepare the reviewed `qwen2.5-coder:3b` model in Ollama on
the same trusted machine. Set `CLEARWAKE_LOCAL_AI_ACK=I_CONFIRM_LOCAL_SYNTHETIC`,
`CLEARWAKE_LOCAL_MODEL_DIGEST` to its reviewed 64 character SHA256 digest and
`CLEARWAKE_LOCAL_LEDGER` to an absolute private path. The route is fixed to
loopback 11434, with one inference slot, a six attempt ledger, context 2048 and
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

Node 22 is used for the dependency free UI tests. Python tests use real SQLite,
controller threads and loopback HTTP, with fake PayPal transports only. They
cover separate grants, exact scope, current authority, revocation while waiting,
parallel duplicate requests, restart/unknown holds, correlated record checks,
cross room/role refusal, HTTP CSRF/origin checks, production endpoint refusal,
the merchant swarm, disputes, the evidence agent and the buyer mandate.

A receipt log can be checked with the network off:

```sh
python -m verdock_core verify <log.ndjson> --public-key <64 hex characters>
```

(run with `vendor/verdock-core` on `PYTHONPATH`), or in the browser on the console's Receipt verifier screen.

## Reuse and event work

Clearwake reuses two of Sri's public MIT projects as pinned submodules:
Relayloom (`vendor/relayloom`, the shared workroom controller and server, see
[NOTICE.md](NOTICE.md)) and verdock-core (`vendor/verdock-core`, the policy,
approval, invariant, outcome and receipt engine). The PayPal adapter, the merchant
swarm, the evidence agent and deadline watch, the buyer agent and its mandate
receipt, the financial grant boundary and the screens are the event work.
No private Verdock source, history, data or credentials are included. Third
party credits: [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

See [security boundaries](SECURITY.md), [official API references](docs/REFERENCES.md),
[design decisions](docs/DESIGN_DECISIONS.md) and [new work provenance](docs/PROVENANCE.md).
Clearwake makes no claim of customers, revenue, measured savings, regulatory
compliance or final hackathon eligibility.
