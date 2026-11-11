# Documentation index

Every document in `docs/`, grouped by what a reader needs it for. Back to the [README](../README.md).

## Start here

* [RESULTS.md](RESULTS.md): every measured number, by case and by run file.
* [SANDBOX_RUN.md](SANDBOX_RUN.md): the real PayPal sandbox runs with their ids.
* [BASELINE.md](BASELINE.md): an agent using PayPal's Agent Toolkit directly versus Clearwake over 200 episodes.
* [VISION.md](VISION.md): what is built on PayPal today and what comes next.
* [HACKATHON_UPDATES.md](HACKATHON_UPDATES.md): the dated list of changes during the submission period.

## Results and proof

* [RESULTS.md](RESULTS.md): cases a to o, model calls and cost, real sandbox money movements, disputes.
* [BASELINE.md](BASELINE.md): the 200 episode comparison, episode by episode.
* [TOOLKIT_FAILURE_CASES.md](TOOLKIT_FAILURE_CASES.md): the recorded behaviour of `paypal-agent-toolkit` 1.11.0 on three failure cases.
* [FINAL_CHECK.md](FINAL_CHECK.md): the ten checks of `scripts/final_check.py` and what each one reads.
* [PROVENANCE.md](PROVENANCE.md): the PayPal contribution and verification record.

## PayPal integration

* [PAYPAL_MCP_TOOLS.md](PAYPAL_MCP_TOOLS.md): all 28 tools of PayPal's MCP server and the toolkit's 47, by read, write and money. Machine readable form: [paypal_mcp_tools.json](paypal_mcp_tools.json).
* [REFERENCES.md](REFERENCES.md): the official PayPal API references reviewed.
* [SOURCES.md](SOURCES.md): the sources for the dispute fee and impact claims.
* [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md): what was chosen, and the tools left out with the reason for each.
* [CHANNEL3.md](CHANNEL3.md): Channel3 facts and the decision.

## Security and receipts

* [../SECURITY.md](../SECURITY.md): the security boundary.
* [TOOLKIT_GUARD.md](TOOLKIT_GUARD.md): three lines of guard for agents that call the toolkit, with the 80 attack episodes side by side.
* [MCP_GUARD.md](MCP_GUARD.md): the proxy between an MCP client and PayPal's MCP server.
* [SANDBOX_RUN.md](SANDBOX_RUN.md): case m, the network cut run, and the signed egress gateway log.

## Developer tools: Postman, OpenAPI, APIMatic, MCP guard

* [POSTMAN.md](POSTMAN.md): the collection of every PayPal call Clearwake makes, with tests on PayPal's responses. Run record: [postman-run-2026-11-11.json](postman-run-2026-11-11.json).
* [APIMATIC.md](APIMATIC.md): the OpenAPI 3.1 spec, SDK, portal and Context Plugin review.
* [RENDER.md](RENDER.md): hosting the live console on Render.
* [MCP_GUARD.md](MCP_GUARD.md): run the guard in front of `@paypal/mcp`.
* The OpenAPI spec is `openapi/clearwake-console.openapi.yaml` and the collection is `postman/clearwake-paypal.postman_collection.json`.

## Voice and rules

* [PLAIN_WORDS_RULES.md](PLAIN_WORDS_RULES.md): rules said once in plain words, read back, checked by code, signed.
* [VOICE.md](VOICE.md): local Whisper for the merchant, phone mode, QR code, measured word error.

## Study notes

* [DEVPOST_FORM.md](DEVPOST_FORM.md): the ready answers for each Devpost field.
* [THIRD_PARTY.md](THIRD_PARTY.md): third party work, licences and versions. UI assets: [THIRD_PARTY_UI.txt](THIRD_PARTY_UI.txt).
* [REFERENCES.md](REFERENCES.md) and [SOURCES.md](SOURCES.md): the reading behind the design.
