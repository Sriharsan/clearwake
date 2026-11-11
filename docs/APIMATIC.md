# APIMatic: what is ready, and the steps that need Sri's login

APIMatic has three jobs in Clearwake. None of them is decoration: the spec describes the console API that judges can call, the Context Plugin reviews the PayPal calls in `clearwake/paypal.py`, and the generated SDK is the client for the console API.

| Job | Input in this repository | Done when |
| --- | --- | --- |
| Context Plugin for PayPal | `clearwake/paypal.py`, `postman/clearwake-paypal.postman_collection.json` | Each PayPal call was checked against the plugin, and every correction is in the log table below |
| OpenAPI 3.1 spec of the console API | `openapi/clearwake-console.openapi.yaml` | Imports into APIMatic without errors |
| SDK and API portal | the same spec | The SDK snippet below runs against the local console, and the portal link is on the Developers page |

Everything that does not need an account is done. The only steps left need Sri to be logged in to APIMatic.

## What was checked offline (9 November 2026)

```sh
python openapi/check_openapi.py            # structure, references, JSON Schema 2020-12, routes against clearwake/server.py
python openapi/check_openapi.py --live     # also starts the console on port 8844 and validates real responses against the schemas
```

The spec has 8 operations and 20 schemas. The live check ran the buyer agent, cases c, d and n, an approval, the state, the receipts and a reset against a real local console, and every response validated. This is not APIMatic's own validator: its result goes in the log below.

## Step A: Context Plugin for PayPal

Source: https://context.apimatic.io/ and the PayPal developer blog post "A New Context Plugin for AI-Assisted Coding with PayPal SDKs".

1. In a terminal in the repository root, run the one command the plugin page gives: `npx context-plugins install paypal`. It installs into every coding assistant it detects. For Claude Code the catalog also lists `claude plugin marketplace add context-plugins/plugin-marketplace` followed by `claude plugin install paypal@context-plugins`. If it asks you to sign in to APIMatic, do that in the browser it opens.
2. Restart the assistant so it loads the plugin.
3. Ask it about each PayPal call, one at a time, and compare with `clearwake/paypal.py`. The list of calls is in `postman/clearwake-paypal.postman_collection.json`: token, create order, get order, capture order, add tracking, get capture, refund, get refund, list disputes, get dispute, send message, make offer, provide evidence, provide supporting info, accept claim, adjudicate.
4. Prompts that give a useful answer: "Is the request body of POST /v2/checkout/orders/{id}/track correct?", "What does PayPal require in provide-evidence when more than one evidence is sent?", "Which fields can a make-offer body hold?"
5. Write what you saw in the table below. Write "no change" for a call the plugin confirmed. Write a change only if the plugin said something that differs from the code or the Postman request, and say whether you changed the code.

### Log: what the Context Plugin corrected

Filled on 11 Nov 2026 from the Context Plugin skills themselves (marketplace `context-plugins`, plugin `paypal` 0.4.1, the `python-*` skills), read from the local plugin cache. The skills teach the use of the APIMatic generated PayPal Server SDK for Python. They are not a checker of raw REST calls, so each row says what a skill stated, what it did not cover, and whether `clearwake/paypal.py` matches. Nothing is copied here that a skill did not say. Line numbers are those of `clearwake/paypal.py` on 11 Nov 2026.

| Date | PayPal call | What the plugin said | What was changed in the code or the collection | Commit |
| --- | --- | --- | --- | --- |
| 11 Nov 2026 | Token, `POST /v1/oauth2/token` (`_access_token`, lines 132 to 144) | `python-authentication`: the token is fetched lazily on the first authenticated call by a form encoded POST to the token endpoint taken from the base URL, with id and secret "commonly" in the Authorization header (client_secret_basic), both halves percent-encoded before base64; it is cached in memory under a lock, renewed about 30 seconds before `expires_in`, and client credentials re-acquire instead of refresh; on a 401 the cached token is invalidated and the failing request is not retried. `python-getting-started`: path `/v1/oauth2/token`, default host `https://api-m.sandbox.paypal.com`, pass the host explicitly. | No change. Matches: path, host pinned, form POST of `grant_type=client_credentials`, id and secret in the Authorization header, lock, in memory cache, renewal 30 seconds before expiry, token re-acquired. Two differences recorded: no percent-encoding of id and secret before base64 (line 136), and a 401 does not invalidate the cached token (lines 95 to 104, 132 to 144). | none, not committed |
| 11 Nov 2026 | Create order, `POST /v2/checkout/orders` (`create_order` line 187, `create_card_order` line 198) | `python-getting-started` lists `orders.create_order` as an operation of the SDK. The route, the request body, `PayPal-Request-Id`, `Prefer` and `Content-Type` for it are not in the skills (they sit in the SDK map, which is not part of the plugin). `python-calling-endpoints` says only, in general, that a parameter with a declared default is always sent and that a representation switch can default to the minimal form. | No change. Nothing in the skills to compare the body or headers with; no contradiction found. | none, not committed |
| 11 Nov 2026 | Get order, `GET /v2/checkout/orders/{id}` (`order`, line 283) | Names `orders.get_order`; no route or response shape. `python-configuration-resilience`: a GET is retried up to three times with a 1 second start and a factor of 2; the default timeout is 30 seconds per wait, not for the whole call. | No change. Matches: reads sent up to three times, waits of 1 and 2 seconds, 30 second timeout (lines 159 to 172). | none, not committed |
| 11 Nov 2026 | Capture order, `POST /v2/checkout/orders/{id}/capture` (`capture_order`, line 286) | Names `orders.capture_order`; body and headers not in the skills. `python-configuration-resilience`: a POST is not repeated by default; where the outcome is uncertain, re-read state and decide; keep a claim in the application's own store before the call. `python-error-handling`: assert on the members you depend on after a write. | No change. Matches the rule: one send, uncertain answer held and reconciled (lines 159 to 161, 172). Where the request id is derived and claimed lives outside `paypal.py` and was not part of this review. | none, not committed |
| 11 Nov 2026 | Add tracking, `POST /v2/checkout/orders/{id}/track` (`add_tracking`, line 276) | Names `orders.create_order_tracking` (and `orders.update_order_tracking`, which returns `None`). The route, the fields `capture_id`, `tracking_number`, `carrier`, `notify_payer` and the headers are not in the skills. | No change. Not covered by the skills, so the body was not compared. | none, not committed |
| 11 Nov 2026 | Get capture, `GET /v2/payments/captures/{id}` (`capture`, line 174) | Names `payments.get_captured_payment`; no route or response shape. Same GET retry and timeout rules as above. | No change. Matches the retry and timeout rules. | none, not committed |
| 11 Nov 2026 | Refund, `POST /v2/payments/captures/{id}/refund` (`refund`, line 177) | Names `payments.refund_captured_payment`; body and headers not in the skills. `python-configuration-resilience`: the SDK sends an `Idempotency-Key` header on every non GET call (it does not name `PayPal-Request-Id`); derive the key from what the request is for, never a fresh `uuid4()`, reuse it on every repeat, and check with the provider whether it deduplicates. | No change. Matches the one send, no automatic repeat rule. The `PayPal-Request-Id` header (line 158) is not named in the skills; the skills neither confirm nor contradict it. | none, not committed |
| 11 Nov 2026 | Get refund, `GET /v2/payments/refunds/{id}` (`refund_record`, line 184) | Names `payments.get_refund`; no route or response shape. Same GET retry and timeout rules. | No change. Matches the retry and timeout rules. | none, not committed |
| 11 Nov 2026 | List disputes, `GET /v1/customer/disputes` (`disputes`, line 214) | Not covered. The SDK has five controllers (orders, payments, subscriptions, transaction search, vault); none handles disputes, and no skill mentions `/v1/customer/disputes`. | No change. Nothing to compare. Only the general GET rules apply (retry, timeout). | none, not committed |
| 11 Nov 2026 | Get dispute, `GET /v1/customer/disputes/{id}` (`dispute`, line 217) | Not covered, same reason. | No change. Nothing to compare. | none, not committed |
| 11 Nov 2026 | Send message, `POST .../send-message` (`send_message`, line 260) | Not covered. Only the general rules for a POST: one send, no automatic repeat, reconcile when the answer is uncertain. | No change. The one send rule matches (`_post`, lines 220 to 233). | none, not committed |
| 11 Nov 2026 | Make offer, `POST .../make-offer` (`make_offer`, line 264) | Not covered. Same general POST rules. | No change. Same as above. | none, not committed |
| 11 Nov 2026 | Provide evidence, `POST .../provide-evidence` (`provide_evidence`, line 235) | Not covered. `python-file-handling` and `python-calling-endpoints` describe how the generated SDK builds multipart bodies in general; they do not say what PayPal expects for this operation (the `input` part, the `evidence-file` parts, the content types, the size limit). | No change. Nothing to compare for the multipart layout. | none, not committed |
| 11 Nov 2026 | Provide supporting info, `POST .../provide-supporting-info` (`provide_supporting_info`, line 248) | Not covered, same reason as provide evidence. | No change. Nothing to compare. | none, not committed |
| 11 Nov 2026 | Accept claim, `POST .../accept-claim` (`accept_claim`, line 255) | Not covered. Same general POST rules. | No change. Same as above. | none, not committed |
| 11 Nov 2026 | Adjudicate, `POST .../adjudicate` (`adjudicate`, line 270) | Not covered. Same general POST rules. | No change. Same as above. | none, not committed |
| 11 Nov 2026 | Error handling and retry across all calls (`transport`, lines 77 to 110; `_request`, lines 159 to 172) | `python-error-handling`: a refused connection, a DNS failure or a rejected tunnel means nothing was sent (known); a read timeout, a write timeout or a dropped connection after the send means the outcome is unknown and must be reconciled before any retry; a 4xx is a rejection that a retry cannot fix; a body that does not decode is not an API error. `python-configuration-resilience`: the default retry set is 408, 429, 500, 502, 503, 504 for GET, HEAD, PUT and OPTIONS, honouring `Retry-After`, and a 401 is never retried. | No change. Matches: `Offline` for failures before any byte left, `GatewayError` for an uncertain answer, `ProviderRefused` for a 4xx, a malformed body rejected. Two differences recorded: a 429 is treated as a refusal and not retried, and `Retry-After` is not read (lines 96 to 103); a connect timeout counts as uncertain where the skill calls it known (the safe side). | none, not committed |

For the Devpost answer: the calls in `clearwake/paypal.py` were written between 30 October and 3 November 2026, before the plugin was installed. The plugin's role is a review of the existing calls and of the Postman collection, not their first draft. Say so.

## Step B: SDK and API portal from the spec

APIMatic's web dashboard flow is being retired and new projects use the CLI, so these steps use the CLI. Sources: https://docs.apimatic.io/apimatic-cli/commands/ and https://docs.apimatic.io/cli-getting-started/portal-quickstart-dac/. Node.js 20 or later.

```sh
npm install -g @apimatic/cli@1
apimatic --version
apimatic auth login          # opens the browser: this is the login step
apimatic auth status
apimatic api validate --file=openapi/clearwake-console.openapi.yaml
```

Write the validator's errors, warnings and messages in the second log table below.

SDK for the console API:

```sh
apimatic sdk generate --help     # shows the flag that takes the spec file (documented as -i, --input)
apimatic sdk generate --language=python --input=openapi/clearwake-console.openapi.yaml --destination=sdk/python
apimatic sdk generate --language=typescript --input=openapi/clearwake-console.openapi.yaml --destination=sdk/typescript
```

API portal:

```sh
mkdir portal && cd portal
apimatic quickstart          # choose "API Documentation Portal", give it ../openapi/clearwake-console.openapi.yaml, pick Python and TypeScript
apimatic portal serve        # http://localhost:3000; then follow "Hosting your portal" in the APIMatic docs
```

The generated `sdk/` and `portal/` folders are APIMatic output. Check the licence in each generated package before committing them, and say in `docs/THIRD_PARTY.md` that they are generated by APIMatic. If they are not committed, link the hosted portal from the Developers page instead.

### SDK snippet (placeholder, fill after the SDK is generated)

Start the local console first (`python -m clearwake --port 8810`). The snippet must run unchanged against it. Replace the lines below with the real generated calls and paste the output you got.

```python
# TODO(Sri): paste the generated Python SDK calls here after Step B. Do not publish a snippet that has not run.
# Expected flow: getSession, buy("a pack of three A5 notebooks"), runCase("n"), getState
# Output seen: [paste the printed result of the real run]
```

### Log: what APIMatic reported on the spec

| Date | Tool | Errors | Warnings | Messages | What was changed in the spec |
| --- | --- | --- | --- | --- | --- |
|  | `apimatic api validate` |  |  |  |  |

## After Step B

1. Put the portal link and the SDK snippet on the Developers page. Agent C owns `site/developers.html`; the exact lines are below.
2. The portal link `https://clearwake-api.vercel.app` is filled in `docs/DEVPOST_FORM.md`; add your own APIMatic words there.
3. Run `python openapi/check_openapi.py --live` after any change to the console routes. It compares the spec with `clearwake/server.py` and fails when they differ.

## Developers page lines (for agent C's pass)

* Section title: `API reference and SDKs`
* Body line: `The console API is described in OpenAPI 3.1. Download the spec, open the API portal, or generate a client with APIMatic.`
* Links in this order: `OpenAPI spec (YAML)` to `https://github.com/Sriharsan/clearwake/blob/main/openapi/clearwake-console.openapi.yaml`; `API portal` to `https://clearwake-api.vercel.app`; `Postman collection` to `https://github.com/Sriharsan/clearwake/blob/main/postman/clearwake-paypal.postman_collection.json`.
* Code block: the Python SDK snippet above, once it has run.
* The spec and Postman links can go in now. Add the portal link and the snippet only after the portal exists and the snippet has run.

## Run of 11 Nov

Done through Sri's signed in Chrome, in a new tab, on 11 November 2026.

* Spec on GitHub: `https://raw.githubusercontent.com/Sriharsan/clearwake/main/openapi/clearwake-console.openapi.yaml` was fetched. It has the three routes `/console/api/negotiation`, `/console/api/totals` and `/console/api/negotiate` (operationId `negotiate`), next to the 8 earlier ones. The pushed file is current.
* APIMatic: https://app.apimatic.io opened the login page (Email and Password, Continue with Google, Continue with GitHub, Enterprise SSO). The browser had no signed in APIMatic session, so the run stopped there. No password was typed and no sign in button was pressed.
* Earlier record, superseded by the sections below. Not done at that time: spec import, validation (warnings and errors: none seen, none recorded), Python SDK, API portal. No portal URL and no SDK file name exist yet, and the SDK snippet above stays a placeholder because it has not run. Whether the free trial allows the SDK and the portal is not known, since the dashboard was not reached.
* Context Plugin: https://context.apimatic.io/ is "API Context Marketplace", a directory of plugins for coding agents (install in a terminal, see Step A). It cannot be used from a browser, so no PayPal call was checked and the correction log above holds no correction.
* Next step for Sri: sign in at https://app.apimatic.io (Continue with GitHub), then tell the agent to continue with the import and the generation.

### Run of 11 Nov, second part (after Sri signed in with GitHub)

* Import: the file upload tool was refused for the local path (outside the folders the session may read), so the spec was imported from the public raw GitHub URL at https://app.apimatic.io (onboarding page, "Paste API Spec URL"). APIMatic accepted `clearwake-console.openapi.yaml`.
* What APIMatic reported (API score screen, nothing else was changed): API Score 74 out of 100, "394 issues found", label "Needs improvement". Surface scores: SDK generation 100/100, Documentation generation 87/100, AI tool generation 88/100. For comparison it showed Adyen 90, Twilio 92, JP Morgan 83. The per issue list (the 394 issues) was not opened, so no individual warning or correction text is recorded, and APIMatic did not report that it corrected anything. The options offered were "Proceed As Is", "Audit / Fix Your Spec" and "Upload a Different Spec". "Proceed As Is" was chosen, so the spec was not altered.
* Project: APIMatic then showed "Your project is ready" at https://onboarding.apimatic.io/setup. Portal, SDK and AI tooling generation there is a local CLI flow: install `@apimatic/cli@2` (needs Node.js 24 or later; this machine has Node 22.15.0), download the project files, unzip, run `apimatic quickstart`. The "Download Files" step and the CLI sign in were not done by the agent (a download and a global install were outside what the agent may do without Sri's go ahead). The dash.apimatic.io page showed only "Publish SDKs", with no generate button reached.
* Earlier record, superseded by the sections below. Not done at that time: Python SDK generation, API portal generation. There is no portal URL and no SDK file name. The SDK snippet was not run against the local console on port 8845 because no SDK exists; nothing was started on that port. Whether the free trial allows generation is not known, since the block was the local CLI route, not a plan limit.
* Next step for Sri: upgrade Node to 24 or later, run `npm install -g @apimatic/cli@2`, `apimatic auth login`, press Download Files on https://onboarding.apimatic.io/setup, unzip, run `apimatic quickstart`.

### Run of 11 Nov, third part: per issue list not reachable

The 394 issue list could not be opened. After "Proceed As Is" the web app goes to https://onboarding.apimatic.io/setup (CLI steps only); opening /onboarding again redirects there, and Publishing Center and Settings did not lead to an issue list or a new import form. The score screen with "Audit / Fix Your Spec" appeared only once, right after the import. So no category breakdown exists, the spec was not edited for APIMatic, and no new score was recorded. Score stays 74 out of 100 with 394 issues (SDK 100, documentation 87, AI tool 88). The CLI (`apimatic api validate`) would list the issues; that is the "needs Sri" step.

### Run of 11 Nov, fourth part: spec examples added, score not re-measured

APIMatic's own issue list could not be opened (third part), so the file was improved on our own judgment, with true additions only. The spec already had a summary, description, camelCase operationId and tag on every operation, the cookie plus `X-Clearwake-CSRF` security schemes, enums and patterns, and the 400, 403, 404, 409 and 429 responses with `Retry-After`. Added, all copied from real responses of a local console on port 8845 (killed afterwards): response examples for `buy`, `getNegotiation`, `negotiate`, `getTotals` and `reset`; request examples for `approve` and `reconcile`; error body examples for 400, 403 and 404 (the real messages the server returned). The 409 and 429 bodies were not provoked, so they carry no example.

Checks after the edit: `python openapi/check_openapi.py` and `python openapi/check_openapi.py --live` both pass (11 operations, 22 schemas, routes match `clearwake/server.py`).

The APIMatic score of the improved file was not re-measured. It is still 74 out of 100 with 394 issues for the earlier file. Re-measuring needs a new import (after the lead pushes) or the CLI step that needs Sri.

### Run of 11 Nov, fifth part: CLI route (approved by Sri), spec improved, SDK and portal generated

How it ran: a temporary Node 24 and the APIMatic CLI through `npx -y -p node@24 -p @apimatic/cli@2 apimatic ...` (CLI 2.2.0, node v24.22.2), from `build/apimatic/`. Nothing was installed globally and no PATH or registry setting changed. `apimatic auth login` opened the browser; Sri's signed in browser session completed it. No password or key was typed or stored by the agent. `build/` is not in `.gitignore`: do not commit it (it holds the generated SDK, portal and a Python virtual environment) or add it to `.gitignore` first.

Validation with `apimatic api validate --file=openapi/clearwake-console.openapi.yaml` (no errors in any run; every finding is a warning or information):

| Run | Findings | What they were |
| --- | --- | --- |
| Before | 382 | 189 "example or default value is missing", 160 "schema should include a non-empty description", 10 inline complex schema, 7 media type example missing, 6 request body description missing, 5 inline enum, 2 header example missing, 1 file name convention, 1 schema key and property name conflict, 1 server environment information |
| After | 104 | 80 "example or default value is missing", 10 inline complex schema, 5 inline enum, 4 "example does not conform" on the large real response examples (state, case, approve, reconcile), 2 media type example missing, 1 file name convention, 1 schema key and property name conflict (the `Error` schema has a property named `error`; renaming the schema breaks `openapi/check_openapi.py`, so it stays), 1 server environment information |

The web import score screen had said 74 out of 100 with 394 issues (SDK 100, documentation 87, AI tool 88). The CLI count is 382 for the same file. The score of the improved file was not re-shown, because the web import form is gone; only the CLI counts above are measured.

Spec edits (true additions only; no route or field added): descriptions on every schema and property that lacked one, request body descriptions, and examples taken from real responses of a local console on port 8845. `python openapi/check_openapi.py` and `--live` pass after the edit (11 operations, 22 schemas). The YAML was rewritten by a script, so its layout changed (same content). Copies: `build/apimatic/spec-before-enrich.yaml` (before) and the scripts `enrich_spec.py`, `enrich2.py`, `enrich3.py` in the same folder.

SDK: `apimatic sdk generate -l python -i ./project -d ./sdk` produced `build/apimatic/sdk` (package `clearwake-console-api` 0.6.1, module `clearwake_console_api`, MIT, Python 3.10 or later). Installed into `build/apimatic/venv` with `pip install ./sdk`.

Portal: `apimatic portal generate -i ./project -d ./portal` needs `src/apimatic.json`; the file used is `{"version":"1.0","languages":{"python":{}},"portal":{}}` in `build/apimatic/project/src`. The first run failed with a connection reset in the prerender step; the second run succeeded. Result: a static site of 6.3 MB in `build/apimatic/portal` (open `index.html`; set `404.html` as the error document on a static host). The CLI offers no publish command for the portal, so there is no APIMatic hosted URL. The portal is a static folder; hosting it is a step for Sri.

SDK snippet, run on 11 Nov 2026 against `python -m clearwake --port 8845` (the process was stopped by PID afterwards); the file is `build/apimatic/sdk_call.py`:

```python
from clearwake_console_api import ClearwakeConsoleApiClient

BASE = "http://127.0.0.1:8845"
anon = ClearwakeConsoleApiClient(base_url=BASE)
raw = anon.session_api.with_raw_response.get_session()
session = raw.payload
cookie = raw.headers["set-cookie"].split(";")[0].split("=", 1)[1]
print("label:", session.label)

client = ClearwakeConsoleApiClient(base_url=BASE, console_session=cookie, csrf_token=session.csrf)
purchase = client.buyer_agent.buy(body={"request": "a pack of three A5 notebooks"})
print("buy allowed:", purchase.allowed, "-", purchase.reason)
run = client.merchant_agent.run_case(body={"case": "n"})
print("case n:", run.entries[0].state, "-", run.entries[0].detail)
```

Output seen:

```
label: local run data
buy allowed: True - Inside the mandate.
case n: VERIFIED - Settled, no fee: PayPal shows RESOLVED (RESOLVED_WITH_PAYOUT) at the INQUIRY stage, never a claim.
```

Earlier record, superseded by the run record at the end of this file. At that point the Context Plugin for PayPal (Step A) was not run: `apimatic plugin` generates context plugins for our own SDK, which is a different thing and was not run either.

## API portal: published (11 November 2026)

* URL: https://clearwake-api.vercel.app (Vercel free scope, project `clearwake-api`, production deployment `clearwake-5q2o5kflh-sriharsans-projects.vercel.app`).
* Date: 11 November 2026, deployed from a cleaned copy of the APIMatic generated static portal (`build/apimatic/portal`).
* What it shows: the Clearwake console API reference with 11 operations in 6 groups: session (getSession), buyer agent (buy), merchant agent (negotiate, getNegotiation, runCase, approve, reconcile), ledger and receipts (getState, getReceipts, getTotals), run (reset). The home page, the llms.txt index and the per operation pages load; an unknown path returns the 404 page.
* Scan before publishing: no secrets, tokens, local paths or personal data found. Two example values in the generated pages carried words the project does not use; they now read `clearwake-sandbox-store` and `sandbox run`, in the deployed copy only. The server address in the reference is the local console, `http://127.0.0.1:8810`.

## Context Plugin: run record

* Date: 11 November 2026.
* Install, approved by Sri: marketplace `context-plugins`, plugin `paypal` 0.4.1, user scope, telemetry off. For this review the agent only read the plugin's Markdown skills from the local plugin cache. It installed nothing, downloaded nothing and ran no pip.
* What the plugin is: skills that teach a coding agent to use the APIMatic generated PayPal Server SDK in C#, Python and TypeScript. The Python skills read were python-authentication, python-calling-endpoints, python-client-initialization, python-configuration-resilience, python-error-handling, python-getting-started, python-integrate-paypal, python-models, python-testing, python-event-streams and python-file-handling. The SDK map with routes and body shapes is not part of the plugin (it sits in the SDK repository), so request and response shapes could not be compared.
* What the review covered: the PayPal calls in `clearwake/paypal.py` against the authentication flow, token handling, headers, retry guidance, timeouts and error handling the skills state. The log table above holds the call by call result.
* Confirmed by the skills: the OAuth 2.0 client credentials flow against `/v1/oauth2/token`, the sandbox host, a lazily fetched token cached in memory under a lock and renewed about 30 seconds before expiry, GET reads retried up to three times with waits of 1 and 2 seconds, a POST sent once and reconciled when the answer is uncertain, the split between a request that never left and one that may have landed, and a 30 second timeout that bounds each wait.
* Not covered by the skills: `PayPal-Request-Id`, `Prefer`, the dispute routes (list, get, send message, make offer, provide evidence, provide supporting info, accept claim, adjudicate), the tracking body and the evidence multipart layout. For these the log says so and no correction is claimed.
* Differences found, none changed (`clearwake/paypal.py` was not edited): the cached token is not dropped on a 401, so a revoked token would keep failing until it expires; id and secret are not percent-encoded before base64 (line 136); a 429 is not retried and `Retry-After` is not read (lines 96 to 103).
* Result: no code change and no correction to the Postman collection came from this review. This record replaces the earlier statements in this file that the Context Plugin was not run.
