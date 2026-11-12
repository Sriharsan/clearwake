# Documentation index

**When an AI agent buys something and it never arrives, Clearwake lets the buyer's agent and the seller's agent settle it inside PayPal within an hour, with proof, before it becomes a claim or a fee, and nothing is paid twice.**

**When an agent's order goes missing, agents fix it.**

**Real PayPal sandbox run, 11 November 2026.** 10 orders bought by an agent, 10 item not received disputes. 4 settled by the two agents at INQUIRY, before a claim, USD 20.00 refunded. USD 0.00 overpaid against USD 2,633.25 for an agent on the PayPal Agent Toolkit alone.

Every document in `docs/`, grouped by what a reader needs it for. Back to the [README](../README.md).

## Start here

**Real PayPal sandbox run, 11 November 2026:** 10 orders bought by a buyer agent, 10 item not received disputes. 4 settled at INQUIRY, before a claim (24 to 62 minutes from filing to RESOLVED in PayPal's timestamps, `data/runs/settle-times-20261111.json`), 3 answered with proof and now under PayPal review, 2 awaiting the merchant owner, 1 refused by the buyer's mandate. 0 double refunds. PayPal moved 4 cases to CHARGEBACK once tracking was on the order. The run file is `data/runs/batch-sandbox-20261111-132948.json`.

**Planted failure, 200 episodes:** USD 2,633.25 overpaid by an agent using PayPal's Agent Toolkit directly, USD 0.00 with Clearwake.

Run it with one command: `git clone --recurse-submodules https://github.com/Sriharsan/clearwake.git && cd clearwake && python -m clearwake --port 8810`, then open `/console`. Built during the hackathon: dated in [HACKATHON_UPDATES.md](HACKATHON_UPDATES.md) and [../BUILT_DURING_HACKATHON.md](../BUILT_DURING_HACKATHON.md).

Tags used on every page, each item carries one: **Real PayPal sandbox run**, **Planted failure**, **Verified in your browser**, **Local run**.

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

* [POSTMAN.md](POSTMAN.md): the collection of 29 requests (11 local attack suite, 18 PayPal sandbox), with tests on PayPal's responses. Run record: [postman-run-2026-11-11.json](postman-run-2026-11-11.json).
* [APIMATIC.md](APIMATIC.md): the OpenAPI 3.1 spec, CLI validation from 382 findings to 104, Python SDK 0.6.1 and the static portal.
* [RENDER.md](RENDER.md): hosting the live console on Render.
* [MCP_GUARD.md](MCP_GUARD.md): run the guard in front of `@paypal/mcp`.
* The OpenAPI spec is `openapi/clearwake-console.openapi.yaml` and the collection is `postman/clearwake-paypal.postman_collection.json`.

## Voice and rules

* [PLAIN_WORDS_RULES.md](PLAIN_WORDS_RULES.md): rules said once in plain words, read back, checked by code, signed.
* [VOICE.md](VOICE.md): local Whisper for the merchant, phone mode, QR code, measured word error.

## Submission texts and notes

* [DEVPOST_FORM.md](DEVPOST_FORM.md): the ready answers for each Devpost field.
* [../SUBMISSION_PAYPAL.md](../SUBMISSION_PAYPAL.md) and [../VIDEO_SCRIPT.md](../VIDEO_SCRIPT.md): the submission notes and the video script.
* [THIRD_PARTY.md](THIRD_PARTY.md): third party work, licences and versions. UI assets: [THIRD_PARTY_UI.txt](THIRD_PARTY_UI.txt).
* [REFERENCES.md](REFERENCES.md) and [SOURCES.md](SOURCES.md): the reading behind the design.
