# Third party work used by Clearwake

Every item was read for its license before use. Clearwake depends on code instead of copying it wherever it can.

| Name | How it is used | License | Source |
| --- | --- | --- | --- |
| Relayloom (Sri's own project) | Pinned git submodule `vendor/relayloom`: shared workroom controller, sessions, CSRF, base UI | MIT | https://github.com/Sriharsan/relayloom |
| verdock-core (Sri's own project) | Pinned git submodule `vendor/verdock-core` v0.2.0: policy, approvals, swarm invariants, outcome checks, signed receipts, offline verifier, egress gateway, held queue | MIT | https://github.com/Sriharsan/verdock-core |
| IETF draft-sahu-agent-action-receipts-00 | Receipt format, implemented from the text in verdock-core. No code copied | IETF Trust (document) | https://datatracker.ietf.org/doc/draft-sahu-agent-action-receipts/ |
| RFC 8032 (Ed25519) | Signature algorithm, implemented from the RFC in verdock-core. No code copied | IETF Trust (document) | https://www.rfc-editor.org/rfc/rfc8032 |
| PayPal REST APIs (Orders v2, Payments v2, Disputes v1, OAuth) | Called directly in the sandbox through `clearwake/paypal.py` with a route allowlist | PayPal developer terms | https://developer.paypal.com/ |
| paypal/agent-toolkit 1.11.0 | Not a dependency. Used only in a separate environment for the toolkit comparison | Apache 2.0 | https://github.com/paypal/agent-toolkit |
| AG Grid Community 35.3.1 | Vendored unchanged in `web/vendor/` for the dispute ledger (details and CSP in `docs/THIRD_PARTY_UI.txt`) | MIT | https://www.npmjs.com/package/ag-grid-community |
| Python 3.13 slim and Ollama 0.12.6 container images | Base images for the network isolated run (`compose.airgap.yml`). Not bundled | PSF and MIT | https://hub.docker.com/_/python, https://hub.docker.com/r/ollama/ollama |
| qwen2.5-coder:3b through Ollama | Optional local open weights model for agent proposals. Not bundled | Model license per Ollama listing | https://ollama.com/library/qwen2.5-coder |

User interface libraries, if any, are listed with versions in `docs/THIRD_PARTY_UI.txt`.

No private Verdock source, history, credentials or records are included in this repository.
