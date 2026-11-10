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

This table is empty on purpose. It is filled by hand from what the plugin actually said. Do not copy anything into it that the plugin did not say.

| Date | PayPal call | What the plugin said | What was changed in the code or the collection | Commit |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |

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
2. Fill `[APIMATIC_PORTAL_URL]` and the APIMatic answer in `docs/DEVPOST_FORM.md`.
3. Run `python openapi/check_openapi.py --live` after any change to the console routes. It compares the spec with `clearwake/server.py` and fails when they differ.

## Developers page lines (for agent C's pass)

* Section title: `API reference and SDKs`
* Body line: `The console API is described in OpenAPI 3.1. Download the spec, open the API portal, or generate a client with APIMatic.`
* Links in this order: `OpenAPI spec (YAML)` to `https://github.com/Sriharsan/clearwake/blob/main/openapi/clearwake-console.openapi.yaml`; `API portal` to `[APIMATIC_PORTAL_URL]`; `Postman collection` to `https://github.com/Sriharsan/clearwake/blob/main/postman/clearwake-paypal.postman_collection.json`.
* Code block: the Python SDK snippet above, once it has run.
* The spec and Postman links can go in now. Add the portal link and the snippet only after the portal exists and the snippet has run.
