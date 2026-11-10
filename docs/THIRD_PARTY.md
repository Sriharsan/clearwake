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
| AG Grid Community 35.3.1 (npm `ag-grid-community`, published 2 June 2026), Copyright (c) 2015-2026 AG GRID LTD | Vendored unchanged in `web/vendor/` (console, Render) and `site/vendor/` (Control Room on Vercel) for the dispute ledger, with the package's `ag-grid-community-LICENSE.txt` next to it. Community edition only, no Enterprise module. Details and CSP in `docs/THIRD_PARTY_UI.txt` | MIT | https://www.npmjs.com/package/ag-grid-community |
| Figtree (web font) | Self hosted variable woff2 in `web/fonts/` and `site/fonts/`, served from the same origin (`font-src 'self'`). By Erik Kennedy; used and redistributed unmodified under the SIL Open Font License 1.1 | OFL 1.1 | https://fonts.google.com/specimen/Figtree , https://openfontlicense.org/ |
| Postman collection format v2.1 | `postman/clearwake-paypal.postman_collection.json` and the environment template. Written for Postman; no Postman code is included. Run with the Postman CLI or Newman (Apache 2.0), which are not dependencies and were not installed for the checks | Format: Postman schema v2.1; Newman: Apache 2.0 | https://learning.postman.com/docs/collections/collections-overview/ , https://github.com/postmanlabs/newman |
| OpenAPI Specification 3.1 | `openapi/clearwake-console.openapi.yaml` follows the specification. The offline check uses PyYAML and jsonschema if they are present, and installs nothing | Apache 2.0 (specification) | https://spec.openapis.org/oas/v3.1.0 |
| APIMatic Context Plugin for PayPal, APIMatic CLI | Developer tools used on the author's machine to review the PayPal calls and to generate an SDK and an API portal from the OpenAPI spec. Not dependencies of Clearwake. Generated output, if committed, is APIMatic output and is marked as such here | APIMatic terms | https://context.apimatic.io/ , https://docs.apimatic.io/apimatic-cli/intro-and-install/ |
| Render (hosting) | `render.yaml` and `Dockerfile.render` deploy the console. Render is a service, not code in the repository | Render terms | https://render.com |
| Playwright for Python (optional) | Drives the sandbox buyer's browser in PayPal's Resolution Center on the owner's own machine with a persistent profile. Installed by the user, not bundled | Apache 2.0 | https://github.com/microsoft/playwright-python |
| Python 3.13 slim and Ollama 0.12.6 container images | Base images for the network isolated run (`compose.airgap.yml`). Not bundled | PSF and MIT | https://hub.docker.com/_/python, https://hub.docker.com/r/ollama/ollama |
| SAM 3 (Segment Anything with Concepts), Meta | Optional: counts items in packing photos on the merchant's machine for the dispatch proof, through `tools/sam/` in its own environment. Not bundled, not redistributed; weights are gated on Hugging Face. Still photos use SAM 3; SAM 3.1 is the video tracker and is not claimed. Carion et al., arXiv:2511.16719, 2025 | SAM License (https://github.com/facebookresearch/sam3/blob/main/LICENSE, 19 Nov 2025) | https://github.com/facebookresearch/sam3 , https://huggingface.co/facebook/sam3 |
| "Notebooks and trinkets (Unsplash)", Jeff Sheldon (ugmonk) | The CC0 test photo in `fixtures/dispatch/photos/` that the dispatch proof was run on. Scaled down, otherwise unchanged. Not a photo of a real parcel | CC0 1.0 | https://commons.wikimedia.org/wiki/File:Notebooks_and_trinkets_(Unsplash).jpg |
| qwen2.5-coder:3b through Ollama | Optional local open weights model for agent proposals. Not bundled | Model license per Ollama listing | https://ollama.com/library/qwen2.5-coder |

User interface libraries, if any, are listed with versions in `docs/THIRD_PARTY_UI.txt`.

No private Verdock source, history, credentials or records are included in this repository.

## Artwork

* Katsushika Hokusai, Under the Wave off Kanagawa (The Great Wave), ca. 1830 to 1832. The Metropolitan Museum of Art, H. O. Havemeyer Collection, Bequest of Mrs. H. O. Havemeyer, 1929. Public domain, Open Access (CC0), https://www.metmuseum.org/art/collection/search/45434. Used in `site/img/hokusai-great-wave.jpg`, resized to 2000 px wide.
