**When an AI agent buys something and it never arrives, Clearwake lets the buyer's agent and the seller's agent settle it inside PayPal in minutes, with proof, before it becomes a claim or a fee, and nothing is ever paid twice.**

![Two agents and PayPal's own record of dispute PP-R-ISN-10198775: offer of USD 5.00, two signed receipts 1c6bed15c803 and fc8f566c85ef, RESOLVED at INQUIRY, no fee](docs/img/hero-thread.svg)

## Judge in 60 seconds

1. **Live.** [Site](https://clearwake-mu.vercel.app), [Break it page](https://clearwake-mu.vercel.app/break), [Render console](https://clearwake-console.onrender.com/console), [repo](https://github.com/Sriharsan/clearwake), [video]([VIDEO_URL]). No keys needed to open any of them.
2. **Run.** `git clone --recurse-submodules https://github.com/Sriharsan/clearwake.git && cd clearwake && python -m clearwake --port 8810`, then open http://127.0.0.1:8810/console. Python 3.12 or newer, nothing to install.
3. **Verify.** `python scripts/verify_pair.py data/runs/batch-sandbox-20261111-132948.json` checks both signed logs and the same dispute ids. The receipt verifier also runs in the browser (console tab 3, or the Developers page of the site).
4. **Proof.** 4 of 10 settled by agents inside the limits, 3 correctly handed to a person, 4 moved by PayPal to the CHARGEBACK stage once tracking was on the order, 0 double refunds on the PayPal sandbox. Over 200 episodes, USD 0.00 overpaid by Clearwake against USD 2,633.25 by an agent using PayPal's Agent Toolkit directly. Over 80 attack episodes, USD 0.00 against USD 1,228.00 with the guard.
5. **Built with.** PayPal Orders v2, Payments v2, Disputes v1 (send message, make offer, provide evidence) and Add Tracking. AG Grid Community draws the ledger, Render hosts the console. APIMatic: [APIMATIC_RESULT]. Postman: [POSTMAN_RUN].

| Over 200 recorded episodes | An agent using PayPal's Agent Toolkit directly | Clearwake |
| --- | ---: | ---: |
| USD overpaid | USD 2,633.25 | **USD 0.00** |
| Double refunds | 61 | **0** |
| Wrongly accepted claims | 160 | **0** |
| Episodes ending as the owner intended | 40 of 200 | **200 of 200** |

| The guard, 80 attack episodes (20 each: lost response, injected instruction, over limit request, duplicate delivery) | Without the guard | With the guard |
| --- | ---: | ---: |
| USD overpaid | USD 1,228.00 | **USD 0.00** |
| Double refunds | 61 | **0** |
| Held for a person | n/a | 40 |

PayPal's MCP server, read from the published source (`@paypal/mcp` 1.8.1, [docs/PAYPAL_MCP_TOOLS.md](docs/PAYPAL_MCP_TOOLS.md)):

* It offers 28 tools, and five of them move money: `accept_dispute_claim`, `create_refund`, `pay_order`, `send_invoice`, `send_invoice_reminder`.
* Its dispute tools are `list_disputes`, `get_dispute` and `accept_dispute_claim`: get and accept only. Sending a message, making an offer and providing evidence are what Clearwake adds.

Sources: `data/runs/baseline-20261110-172506.json` (seed 20261110, [docs/BASELINE.md](docs/BASELINE.md)) and [docs/TOOLKIT_GUARD.md](docs/TOOLKIT_GUARD.md), run on the local PayPal layer. Case n in the picture is a real sandbox run. Models: 85 recorded calls on local models, the policy decided correctly on all 84 scored prompts, and voice rules were heard correctly in 11 of 11 clips ([docs/RESULTS.md](docs/RESULTS.md)). **License:** MIT.

## Run it yourself

No keys needed. Without keys the console is a local run on the local provider with no PayPal calls; every PayPal sandbox run is listed in the results below with its ids. Sandbox means PayPal's test environment with test money. No live PayPal, no real money.

* **Break it page.** https://clearwake-mu.vercel.app/break replays the recorded episodes in your browser: pick an attack, press Run, see both outcomes, and verify the guarded receipts.
* **Render console.** https://clearwake-console.onrender.com/console, hosted, the AG Grid dispute ledger and the fee leak gauge. It is not network isolated.
* **Local run.** `python -m clearwake --port 8810`, then `/console`. Windows: `.\demo.ps1`. macOS or Linux: `./demo.sh`. The network cut run (case m) needs Docker: `python scripts/airgap.py`.
* **Phone.** Scan the QR code on the site Home page to open the hosted console, or speak to the local one with `python -m clearwake --phone`, which prints a link and a QR code ([docs/VOICE.md](docs/VOICE.md)).

Cases, one command each:

```sh
python scripts/cases.py                         # local run, a to o, no network
python scripts/cases.py --sandbox               # real sandbox where PayPal allows it (keys in .env)
python scripts/cases.py --sandbox --only i --dispute <dispute id>   # one real dispute, read by id
python scripts/cases.py --sandbox --order <order id>                # case a after a sandbox buyer approval
python scripts/airgap.py                        # case m: network isolated containers, cut and restore (Docker, keys in .env)
python -m unittest discover -s tests            # offline tests
python openapi/check_openapi.py --live          # the OpenAPI spec against the running console
python postman/check_collection.py              # the Postman collection, offline
```

Every line prints PASS, FAIL or SKIPPED with how it ran, and the run is saved to `data/runs/`. Sandbox setup: copy `.env.example` to `.env`, add your own sandbox app keys, then run `scripts/sandbox_setup.ps1` once and approve the order as the sandbox personal buyer.

Also here: the [OpenAPI 3.1 spec](openapi/clearwake-console.openapi.yaml) and the [Postman collection](postman/clearwake-paypal.postman_collection.json). Submission notes: [SUBMISSION_PAYPAL.md](SUBMISSION_PAYPAL.md).

## How it works

![The loop: rules said once, tracking added at dispatch, buyer agent opens the case, merchant agent reads PayPal, the model drafts and the policy decides, PayPal's record reads RESOLVED with two signed receipts](docs/img/loop.svg)

Item not received, end to end, in one sequence. Every feature below is a step in it.

0. **Rules, set once, in plain words.** The merchant says the rules out loud (typing is the fallback). A local model turns them into a policy, the system reads it back in plain words, the merchant says yes, and it is signed. The buyer does the same for their agent. After that the model can propose anything and can never go past the signed policy.
1. **Prevention.** When the merchant ships, Clearwake adds the tracking to PayPal through the Add Tracking API, so the order is ready to defend before any dispute exists.
2. **The buyer's agent watches.** It bought inside a mandate its owner signed (budget, per item cap, store, categories). When the tracking stalls past the expected date it opens the item not received dispute in PayPal's Resolution Center as the sandbox buyer, through a browser on the owner's own machine, inside that mandate. It can only claim for orders its mandate covers.
3. **The merchant's agent reads** the dispute, the order, the tracking on PayPal and the signed dispatch record, with the photo count where there is one.
4. **The model drafts, the rules decide.** Delivered with proof: send the evidence. In transit: message the buyer's agent with the tracking and a date. Not shipped, lost or short shipped: offer a refund or a partial settlement inside the merchant's limits, sent alone through PayPal's `make-offer`. The buyer's agent accepts only what its mandate allows.
5. **Both sides read PayPal's record until it says RESOLVED.** A lost response is never retried blindly. "Settled, no fee" is said only when PayPal's record reads RESOLVED at the INQUIRY stage.
6. **Two signed receipts**, one from each side, both naming the same PayPal dispute id, verified offline in Python or in a browser.

### Scope

Built for item not received. Clearwake settles item not received and nothing else: every other dispute reason is escalated to the owner untouched, with nothing sent. The agent to agent batch path sets `swarm.only_item_not_received` (`clearwake/batch.py`) to hold that line. The person and the merchant each set their rules once; agents act only inside them; anything outside goes to a person with the evidence ready.

### Rules in plain words, by voice

The merchant says: "Settle an item that has not arrived on its own up to USD 5.00. Ask me from USD 5.01 up to USD 9.00. Never more. Send evidence when the records answer the claim. Every other dispute reason goes to me untouched." The buyer says: "Claim only for an order this agent placed, up to its amount." Speech to text runs on the laptop with local Whisper; no cloud speech service is used. A local model turns the sentence into a policy, code checks every field and every figure against the sentence, the readback in plain words is written by code, and the signed receipt records the SHA-256 of the transcript. The merchant can also ask by voice what happened today (answered from the receipts only, no model writes it) and approve by voice only when the signed policy allows it. Details: [docs/PLAIN_WORDS_RULES.md](docs/PLAIN_WORDS_RULES.md), [docs/VOICE.md](docs/VOICE.md). Measured: Whisper small.en on this laptop's CPU heard 11 of 11 spoken clips as the right intent, mean word error 0.036 (`data/runs/voice-20261110-223540.json`).

### The money leak

PayPal's own rules ([help350](https://history.paypal.com/uk/cshelp/article/how-is-the-dispute-rate-calculated-and-how-do-i-avoid-being-charged-a-dispute-fee-help350), UK edition; fees from [PayPal Merchant Fees, US](https://www.paypal.com/us/business/paypal-business-fees), updated 1 Oct 2026; both in [docs/SOURCES.md](docs/SOURCES.md)):

1. No Standard Dispute Fee (USD 15.00 in the US) is charged when a case is resolved directly between seller and buyer and not escalated to a claim. Sellers who answer late, or only with evidence, let cases escalate.
2. A seller with more than 100 sales in the previous 3 months and a dispute rate of 1.5% or more pays the High Volume Dispute Fee (USD 30.00 in the US) on every dispute.
3. A refund sent twice, or one that silently failed, costs money or a customer. Clearwake gives each refund one stable request id, holds what it cannot confirm as UNKNOWN, and checks PayPal's record before calling it done.

The Standard fee is not charged on claims below twice the fee or on unauthorised transactions, so the fee leak gauge counts a fee avoided only when PayPal's rule would otherwise have charged one.

### Without Clearwake and with it

| Moment | Without Clearwake | With Clearwake |
| --- | --- | --- |
| An agent's order goes wrong | The buyer's complaint waits in an inbox; the owner of the agent finds out later | The buyer's agent opens the dispute and negotiates inside its owner's rule |
| A buyer opens a case | No reply in time; the case escalates and the dispute fee is charged | Settled in conversation: `send-message` and `make-offer` inside the owner's limit while the case is an inquiry; "settled, no fee" only when PayPal's record shows it RESOLVED at the INQUIRY stage |
| A case worth fighting | Deadline missed; evidence never sent | Tracking and order facts from PayPal's records, sent before the deadline; near deadlines go to the owner with a countdown |
| A refund reply is lost | Sent twice, or marked done when it failed | One request id, held as UNKNOWN, reconciled from PayPal's record |
| Dispute text and buyer details | Pasted into an outside AI service | Read by a local model inside the merchant's network |
| The network drops mid batch | Retries fire blindly | Money actions wait as "held, offline"; on reconnect PayPal is read first, then they finish with no duplicate |

### Dispatch proof

Some disputes are about what was in the box. At packing the merchant photographs the open parcel. SAM, an open weights model from Meta, runs on the merchant's own machine, counts the items and writes one signed receipt into the same receipt chain: the PayPal order id and capture id, the items ordered and counted, the SHA-256 of each photo, whether the parcel was sealed, how it was counted, and the policy hash. Nothing goes to an outside AI.

When a buyer says some items did not arrive, the Evidence agent finds that receipt in the verified log and checks it against the order and the tracking:

* **Strong proof** (the count matches the order, the parcel is sealed, tracking shows it shipped, and the log verifies) is sent as evidence through `provide-evidence` before the deadline, with the photo attached. The Checker reads PayPal's dispute back and says whether PayPal's record shows the dispatch proof.
* **Weak proof** is never sent. The policy settles by offer while the case is an inquiry, refunds within the limit, or escalates to the owner.
* The buyer's words are read only as a claim to check, for example "only 2 of 3 arrived". They never decide an amount or an action.

```sh
python scripts/dispatch.py pack --order <order id> --capture <capture id> --item notebook-a5=3:notebook --photo parcel.jpg --sealed
python scripts/cases.py --only o       # local run: strong proof sends evidence, weak proof settles by offer
```

Still photos use **SAM 3** (`facebook/sam3`). Meta's SAM 3.1 checkpoint is the video tracker, and Clearwake does not claim to count photos with it. The model name, device and milliseconds are written into every receipt. SAM and its weights are gated on Hugging Face and need a one time setup that you run yourself: [tools/sam/README.md](tools/sam/README.md). SAM Materials are under the SAM License; credits are in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md). What is real: SAM 3 counted three notebooks in a CC0 test photo offline on this laptop's CPU (15 s to load, 56 s to count), the signed receipt was written, and PayPal's sandbox accepted the evidence with the photo on dispute `PP-R-UKF-10195772`.

## What was built during the hackathon

The submission period opened on 1 October 2026. No commit in this repository, in Relayloom or in verdock-core is dated before it. Dates are IST, from `git log`; the full list is in [BUILT_DURING_HACKATHON.md](BUILT_DURING_HACKATHON.md) and [docs/HACKATHON_UPDATES.md](docs/HACKATHON_UPDATES.md).

| Date (IST) | What was built |
| --- | --- |
| 27 to 28 Oct | Relayloom, the shared workroom core Clearwake extends: sessions, CSRF, server, base UI |
| 30 Oct | The first Clearwake build: the refund workroom, the real PayPal sandbox setup, the four case sandbox check, an autonomy policy with recorded approvals. First commit of this repository, 30 Oct 2026, 20:47 |
| 31 Oct | verdock-core published (policy, approvals, invariants, outcome states, Ed25519 receipts, verifier). The buyer agent with an owner's mandate, the Disputes calls, the Evidence agent, the merchant swarm, the first real sandbox dispute (case i), settling in conversation (`send-message`, `make-offer`), the egress gateway and the network isolated run (case m), the fee leak gauge, the AG Grid ledger, the public site |
| 1 Nov | Dispatch proof: signed packing record, strong or weak check against a buyer's claim, case o |
| 3 Nov | Dispatch proof run for real with SAM 3 on the CPU and accepted by the sandbox; the offer goes first and alone; real case n recorded (settled, RESOLVED at INQUIRY); real receipts published on the site |
| 9 Nov | The editorial public site (home, control room, developers) and restyled console |
| 10 to 11 Nov | The v6 build: the buyer agent's driver for PayPal's Resolution Center, the agent to agent batch, rules in plain words (`clearwake/rules_nl.py`), voice for the merchant (`clearwake/voice.py`, `python -m clearwake --phone`), the 200 episode baseline against an agent using PayPal's Agent Toolkit directly, the Postman collection, the OpenAPI spec, the Render files, the MCP guard and the Break it page |

Python's standard library, AG Grid Community, SAM 3, Ollama and the model weights, Playwright and the PayPal APIs are dependencies or tools, not written here. Licences and versions: [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

## Measured results

Every number is in [docs/RESULTS.md](docs/RESULTS.md) and [docs/SANDBOX_RUN.md](docs/SANDBOX_RUN.md), from the run files in `data/runs/` and `data/airgap/`.

* **4 of 10** agent bought item not received cases on the PayPal sandbox settled by the two agents at the INQUIRY stage with no fee, as PayPal's record reads, with 0 answered with evidence and 3 correctly handed to the owner.
* **USD 0.00 overpaid and 0 double refunds by Clearwake in 200 episodes, against USD 2,633.25 and 61 double refunds for an agent using PayPal's Agent Toolkit directly** on the same cases and faults, on the local PayPal layer (`data/runs/baseline-20261110-172506.json`, [docs/BASELINE.md](docs/BASELINE.md)).
* **85 model calls** on local models in the recorded runs, and the policy decided correctly on all 84 prompts it was scored on, overriding the model's proposal 21 times.

| What | How it ran | Result |
| --- | --- | --- |
| Agent to agent batch: 10 sandbox orders bought and disputed by the buyer agent | real sandbox, buyer agent through a local browser, merchant agent with a local model | 4 settled at INQUIRY with no fee, 0 evidence sent, 3 escalated to the owner, 4 refunds confirmed by PayPal's record. A bracket means that run is not recorded yet |
| Merchant agent, model calls | recorded run files | 42 model calls with `qwen3.5:4b`, timings in [docs/RESULTS.md](docs/RESULTS.md) |
| Case n, settled in conversation | **real sandbox**, dispute `PP-R-OBG-10196144` | PASS: offer of USD 2.50, PayPal paid the settlement (refund `0TB11858A85953644`), the case read RESOLVED at the INQUIRY stage, never a claim, no fee. The sandbox buyer opened it and accepted by hand |
| Case o, dispatch proof | **real sandbox**, SAM 3 on the CPU, CC0 test photo | PASS (3 November): 3 of 3 counted, receipt `8b92abb9e53a6244`; dispute `PP-R-UKF-10195772`; PayPal's record shows the dispatch proof, tracking and photo from the seller. First send refused by PayPal, second lost and held UNKNOWN, third accepted |
| Case m, network cut mid batch (`scripts/airgap.py`) | real sandbox, network isolated containers, egress gateway | PASS: refund `6PX35920F4587564U` before the cut; two refunds held offline; after reconnect `76C086475Y724052F` and `9C434129FA2384059` VERIFIED, no duplicate; receipts verified with networking disabled |
| Case i (real PayPal dispute) | real sandbox | PASS on `PP-R-SLI-10195419`: tracking sent as the supporting info PayPal offered, read back VERIFIED |
| Cases c, d, e (`scripts/cases.py --sandbox`) | real sandbox; e is an injected fault in sandbox | PASS, twice on 31 October. Latest refunds `6SN41486G5579815G` and `2NB27940EC188891M` VERIFIED |
| Four refund cases (`scripts/check_sandbox.ps1`) | real sandbox | 4 of 4 PASS. Refunds `79R527888E694933F` and `7A545589JM079780C` COMPLETED |
| Cases a to o (`scripts/cases.py`) | local run, no PayPal calls | 15 of 15 PASS (1 November) |
| Cases k, l (a dispute near its deadline, ten at once) | real sandbox | Not run on the sandbox on their own: k needs a dispute close to its deadline. The batch above replaces l |
| Console (`/console`), AG Grid dispute ledger and fee leak gauge | local run locally; hosted at https://clearwake-console.onrender.com | runs |
| Public site, https://clearwake-mu.vercel.app | static on Vercel, recorded sandbox run | verifies the real case m receipts in the browser |
| Tests | offline | [TESTS_PY] Python and [TESTS_UI] UI tests pass |
| Postman collection, 18 requests | checked offline; run against the sandbox by Sri | structure and scripts verified ([docs/POSTMAN.md](docs/POSTMAN.md)); sandbox run [POSTMAN_RUN] |

## What we use and what we add

PayPal's Agent Toolkit gives a developer a tool layer: it turns an agent's tool call into one PayPal request and returns whatever PayPal answers. We read the source of `paypal-agent-toolkit` 1.11.0 and ran it against a local PayPal layer; the record is in [docs/TOOLKIT_FAILURE_CASES.md](docs/TOOLKIT_FAILURE_CASES.md). The money returning dispute action it records is `accept_dispute_claim`, which sends the dispute id and a note. Toolkit tool list: 47 tools, listed one by one in [docs/PAYPAL_MCP_TOOLS.md](docs/PAYPAL_MCP_TOOLS.md), read from the published package source.

What that page documents the toolkit does not do, and what Clearwake adds:

| In the toolkit, as recorded | Clearwake adds |
| --- | --- |
| No `PayPal-Request-Id` on the request | One stable request id per action, kept across any retry (`clearwake/paypal.py`) |
| No timeout passed, no retry, no record of an unknown outcome | A lost reply is held as UNKNOWN and never retried blindly; PayPal's record decides |
| The amount and limit a caller passes are dropped; the only gate is on or off per action | Limits in a signed policy file, checked before any PayPal call, per capture and per customer per day |
| Nothing checks the result afterwards | A separate read of PayPal's record before a refund or a settlement counts as done |

The toolkit is built to be a tool layer and does not claim to enforce limits. Over 200 seeded item not received episodes with lost responses, an injected instruction in a buyer's message and over limit requests, an agent using it directly overpaid USD 2,633.25 with 61 double refunds, and Clearwake USD 0.00 with 0 ([docs/BASELINE.md](docs/BASELINE.md), on the local PayPal layer). Clearwake also adds what the toolkit has no part in: the conversation (`send-message`, `make-offer`, `provide-evidence`) that settles a case before it becomes a claim, Add Tracking at dispatch, the buyer's agent with its own mandate, and signed receipts on both sides.

**PayPal APIs used:** Orders v2, Payments v2, Disputes v1 (send message, make offer, provide evidence) and Add Tracking.

**Sponsor tools actually used:**

| Tool | What it does here |
| --- | --- |
| AG Grid Community 35.3.1 (MIT) | The dispute ledger: stage filter, deadline countdown, model proposal next to the policy decision, PayPal's raw record in the row detail, CSV export for the accountant |
| Render | Hosts the live console ([docs/RENDER.md](docs/RENDER.md)) |
| APIMatic | OpenAPI 3.1 spec of the console API, SDK and portal, Context Plugin review of the PayPal calls ([docs/APIMATIC.md](docs/APIMATIC.md)) |
| Postman | A collection of every PayPal call Clearwake makes, with tests on PayPal's responses ([docs/POSTMAN.md](docs/POSTMAN.md)) |

Tools that were considered and left out, each with its reason, are in [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md).

**AI tools used:**

* **Merchant agent: a local model through Ollama, qwen3.5:4b.** It reads each dispute and buyer message, proposes settle, fight or escalate, and writes the reply and the offer note. It runs in its own container inside the isolated network. The policy decides; code checks every amount and cited id. Each call is recorded in the signed receipts.
* **Buyer agent.** Picks a product and handles the dispute inside the owner's mandate and dispute rule. Every step is receipted and linked to the mandate receipt.
* **SAM 3** counts items in packing photos on the merchant's machine for the dispatch proof.
* **Whisper small.en** (local, through faster-whisper) turns the merchant's spoken rules, questions and approvals into text on the laptop. The local model then turns rules text into a policy; code validates it.
* **Scripted fallback.** Fixed rules, labelled "scripted, not AI" on screen and in every run file, used when no model is running.

Models only propose. The limits live in [policy/merchant.yaml](policy/merchant.yaml), read by the server and never by a model: refunds up to USD 2.00 run alone, up to USD 5.00 need an approval, anything above is refused; offers to settle up to USD 3.00 run alone, up to USD 5.00 need an approval, and above that a partial offer of USD 5.00 goes to the owner; one customer is capped at USD 6.00 a day.

**Shared engine: verdock-core.** Policy decisions, approvals, swarm invariants (locks, caps per capture and per customer per day, one stable request id per action), outcome states with reconciliation, signed receipts with an offline verifier, the egress gateway and the held queue all come from [verdock-core](https://github.com/Sriharsan/verdock-core) v0.2.0, MIT, pinned as a git submodule at `vendor/verdock-core`. It uses the Python standard library only. Clearwake adds the PayPal adapter, the agents and the screens. The server, sessions and CSRF protection come from [Relayloom](https://github.com/Sriharsan/relayloom), also MIT and pinned at `vendor/relayloom`. `clearwake/controller.py` and the refund screens are an internal module inherited from it, not part of the product.

## Fail closed

The model proposes. The signed policy decides. Separate approval records say who allowed what. The receipts verify offline.

* **Least privilege.** The merchant agent can only reach the reviewed PayPal routes on the sandbox host, and only inside limits in `policy/merchant.yaml`, which the server reads and no model or buyer message can edit. The buyer's agent holds a mandate (budget, per item cap, store, categories) and can claim only for orders it covers.
* **Fail closed.** A missing amount, an unreadable limit, an answer that does not match the offer, a reply that never arrived, a network that is down: each one ends as refused, held or handed to the owner, never as money sent. "Settled, no fee" is said only when PayPal's record reads RESOLVED at the INQUIRY stage.
* **Slow and lost answers.** Reads retry up to 3 times at 30 s; a write waits 45 s and is never repeated; a lost or slow write answer is recorded as UNKNOWN and reconciled from PayPal's record by its stable `PayPal-Request-Id`, so a lost response never pays twice ([measured waits](docs/RESULTS.md)).
* **Approvals apart from traces.** An approval is its own record, kept apart from the model's trace: one exact action and amount, an approver who is not the requester, an expiry, and a single use. A model's reasoning is never the record of an approval.
* **Receipts that verify without us.** Every step is a signed link in a hash chain, checked offline in Python or in a browser. Change one line and the chain breaks.
* **Measured.** The policy overrode the model's proposal 21 times in the recorded runs and decided correctly on all 84 scored prompts.

### The boundary

The live system runs in a network isolated Docker network (`compose.airgap.yml`, `internal: true`) on the merchant's own machine. The egress gateway from [verdock-core](https://github.com/Sriharsan/verdock-core) is the only service with a route out. It allows only the hosts in [policy/merchant.yaml](policy/merchant.yaml) (`api-m.sandbox.paypal.com`) and signs a receipt for every request it sees, allowed or blocked. The hosted console on Render and the public site on Vercel are not part of this boundary.

| Stays inside | Crosses the gateway | Why |
| --- | --- | --- |
| Dispute text, buyer messages, evidence drafts | Only what PayPal's API needs for the step: a message, an offer amount, tracking facts | Customer data and dispute evidence stay inside the merchant's environment |
| Policy file, approvals, limits | Nothing | A buyer message or a model reply cannot change a limit |
| Signed receipts and the verifier | Nothing | Proof that does not depend on any outside service |
| The model (Ollama, in its own container on the isolated network) | Nothing | Dispute text never goes to an outside AI |
| Sandbox keys | Inside the TLS tunnel only; the gateway sees host names and byte counts | The gateway can log every request without reading it |

A request the gateway refuses before it leaves (403 off the allowlist, 502 when its own network is down) is known not to have happened, so Clearwake holds it as "held, offline" instead of UNKNOWN. Case m cuts the gateway's network mid batch and restores it; see [docs/SANDBOX_RUN.md](docs/SANDBOX_RUN.md).

### Uncertain outcomes

Unknown, pending or interrupted money actions keep their original `PayPal-Request-Id`. There is no automatic refund retry, second request identity, or "reverse a refund" action. Reconciliation is an explicit read of a known refund id that validates amount, USD currency, the sandbox capture link, the request correlation and the final status. A verified outcome needs `COMPLETED` from that read. Never delete a real sandbox ledger or switch databases to get around a held payment: unresolved cases need explicit operator review.

## MCP guard

`python -m clearwake.mcp_guard -- npx -y @paypal/mcp --tools=all` sits between any MCP client and PayPal's MCP server. It forwards the tool list unchanged and applies the signed policy to the money moving tools `accept_dispute_claim` and `create_refund`: the amount is read from PayPal's record, an amount above the limit is held for a person, a retry after a lost response never repeats the money move, and every call writes a signed receipt that verifies offline. On a local run, a lost response followed by a retry moved money twice straight to the server and once through the guard. It is not a PayPal product and was not run against the live PayPal server. For agents that call the toolkit directly, `clearwake/toolkit_guard.py` does the same in three lines ([docs/TOOLKIT_GUARD.md](docs/TOOLKIT_GUARD.md)). See [docs/MCP_GUARD.md](docs/MCP_GUARD.md) and [docs/PAYPAL_MCP_TOOLS.md](docs/PAYPAL_MCP_TOOLS.md).

## Repo map

The full grouped list of documents is in [docs/INDEX.md](docs/INDEX.md).

| Path | What is there |
| --- | --- |
| `clearwake/` | The agents, the swarm, the PayPal adapter, the console server, the MCP guard, the toolkit guard, rules in plain words, voice |
| `policy/` | The signed limits (`merchant.yaml`) that no model can edit |
| `scripts/` | Case runner, batch, baseline, airgap run, verifiers, `final_check.py`, `fill_placeholders.py` |
| `site/` | The public site: home, control room, developers, Break it page, recorded receipts in `site/receipts/` |
| `web/` | The console screens |
| `data/runs/` | Every recorded run file that the numbers come from |
| `docs/` | Results, sandbox record, baseline, PayPal integration, security notes: start at [docs/INDEX.md](docs/INDEX.md) |
| `openapi/`, `postman/` | The OpenAPI 3.1 spec and the Postman collection, each with an offline check |
| `tests/` | Python and UI tests |
| `vendor/` | verdock-core and Relayloom, pinned submodules |
| [SECURITY.md](SECURITY.md), [AGENTS.md](AGENTS.md), [BUILT_DURING_HACKATHON.md](BUILT_DURING_HACKATHON.md), [NOTICE.md](NOTICE.md) | Security boundary, contributor instructions, dated build record, upstream notice |

Where this goes: built on PayPal today are agent to agent settling inside the dispute conversation, the per dispute policy decision, the fee leak gauge, agents in a network isolated environment with one receipted gateway, limits outside the model, recorded approvals, swarm invariants, a separate check of every money movement against PayPal's record, and signed receipts on both sides. Next: shared context for teams of people and agents, continuous daily operations, and receipts accepted by payment platforms as proof ([docs/VISION.md](docs/VISION.md)).
