# Devpost form: ready answers for every field

Draft only. Sri pastes, checks and submits. Nothing here was entered on Devpost, and the eligibility and terms boxes are for Sri to tick himself.

Deadlines: full draft by 12 Nov, 6:00 PM IST. Freeze 12 Nov, 11:00 PM IST. Devpost closes 12 Nov, 12:00 PM PT, which is 13 Nov, 1:30 AM IST.

Note on the field list: the Devpost page (https://paypalaihackathon.devpost.com/ and its rules page) returned HTTP 403 to automated fetching on 9 November 2026, so the field list below comes from the build brief and the standard Devpost project form, and the rules were checked through the PayPal developer blog and two listing pages. Compare this file with the live form once and add anything the form asks that is not here. The section "Fields the live form may add" has answers for the most likely extras.

## Placeholders to fill before pasting

| Placeholder | Where it comes from |
| --- | --- |
| `[RENDER_URL]` | The Render service URL after the deploy (docs/RENDER.md) |
| `[VIDEO_URL]` | The public YouTube link |
| `[APIMATIC_PORTAL_URL]` | The APIMatic portal link (docs/APIMATIC.md) |
| `[APIMATIC_EXPERIENCE]` | Sri's own words, after using APIMatic (below) |
| `[BATCH_TOTAL]`, `[BATCH_SETTLED]`, `[BATCH_EVIDENCE]`, `[BATCH_ESCALATED]`, `[BATCH_REFUNDS]`, `[BATCH_SECONDS_PER_CASE]` | The agent to agent batch, from docs/RESULTS.md (agent B) |
| `[HERO_DISPUTE_ID]` | The dispute id of the single buyer agent to merchant agent case in the video |
| `[MODEL_NAME]`, `[MODEL_TAG]`, `[MODEL_CALLS]`, `[MODEL_MS_PER_CALL]` | docs/RESULTS.md "Model calls" (agent A) |
| `[TESTS_PY]`, `[TESTS_UI]` | The final `python -m unittest discover -s tests` and `node --test` counts |
| `[POSTMAN_RUN]` | The result of Sri's Newman or Postman CLI run (docs/POSTMAN.md) |

## 1. Project name

Clearwake

## 2. Elevator pitch (195 characters, limit 200)

When an AI agent buys, Clearwake settles what goes wrong: the buyer's agent and the merchant's agent negotiate inside PayPal's dispute conversation, within signed limits, before a claim or a fee.

## 3. About the project (Markdown, paste as is)

```markdown
## Inspiration

PayPal charges no Standard Dispute Fee (USD 15.00 in the US) when a case is resolved directly between seller and buyer and is not escalated to a claim. A seller with more than 100 sales in the previous 3 months and a dispute rate of 1.5% or more pays USD 30.00 on every dispute. Both rules are in PayPal's own fee pages (Merchant Fees, US, updated 1 October 2026, and Help Center article help350).

Now that AI agents buy things for people, the dispute has two agents in it. The buyer's agent holds a mandate its owner signed. The merchant's agent works inside limits its owner signed. Today the complaint goes into an inbox and escalates, and the fee is charged. We wanted the two agents to settle it themselves, inside PayPal's own dispute conversation, while the case is still an inquiry, and to leave proof on both sides.

## What it does

When an AI agent buys, Clearwake settles what goes wrong.

1. The buyer's agent buys a parcel inside a mandate its owner signed: budget, per item cap, store, categories. The mandate is a signed receipt linked to the PayPal order.
2. One item is missing. The buyer's agent opens the dispute in PayPal's Resolution Center as the sandbox buyer, through a browser on the owner's own machine.
3. The merchant's agent reads the dispute and the buyer's message. A local model proposes settle, fight or escalate. The policy file decides. Code checks every amount and every cited id. The agent checks its dispatch proof (SAM 3 counted the items at packing, the parcel was sealed, tracking shows it shipped) and offers a refund inside the owner's limit through PayPal's `send-message` and `make-offer`.
4. The buyer's agent compares the offer with the dispute rule in its mandate (for example: accept any refund of 80 percent or more for a missing item) and accepts, counters or escalates.
5. Clearwake says "settled, no fee" only when PayPal's own dispute record reads RESOLVED at the INQUIRY stage. A refund counts only when PayPal's refund record matches. Every step on both sides is a signed, hash chained receipt that anyone can verify offline, in Python or in a browser.

We ran a batch: [BATCH_TOTAL] sandbox orders bought by the buyer agent and disputed by it for mixed reasons (item not received, missing items with dispatch proof, not as described). Read back from PayPal: [BATCH_SETTLED] settled at INQUIRY with no fee, [BATCH_EVIDENCE] answered with evidence, [BATCH_ESCALATED] escalated to an owner, [BATCH_REFUNDS] refunds confirmed by PayPal's record, [BATCH_SECONDS_PER_CASE] seconds per case, [MODEL_CALLS] model calls.

The merchant's control room has an AG Grid ledger of every dispute: stage, the model's proposal next to the policy's decision, PayPal's status, a deadline countdown, settled before escalation, and fee avoided. It counts a fee as avoided only where PayPal's rule would have charged one.

## How we built it

* Python standard library only. PayPal Orders v2, Payments v2 and Disputes v1 are called through one adapter that allows only the PayPal sandbox host and a list of reviewed routes.
* The merchant agent uses a local open weights model, `[MODEL_NAME]`, through Ollama, inside a network isolated Docker network. One egress gateway is the only way out, reaches only `api-m.sandbox.paypal.com`, and signs a receipt for every request. We cut the network in the middle of a batch: money actions wait as "held, offline", and on reconnect PayPal is read first and nothing is sent twice.
* The buyer agent drives PayPal's Resolution Center with Playwright on the owner's machine, using a browser profile the owner logs into by hand. No credentials are in code or files. If the sandbox shows a CAPTCHA, the step stops and the owner does it; it is never bypassed.
* Policy, approvals, per capture and per customer caps, outcome checks, receipts, the gateway and the held queue come from verdock-core, our own MIT library pinned as a submodule. The server and session layer come from Relayloom, also ours and MIT.
* AG Grid Community 35.3.1 draws the dispute ledger under a strict Content Security Policy. Render hosts the live console. We wrote an OpenAPI 3.1 spec of the console API and a Postman collection of every PayPal call, with tests on PayPal's responses.

## Challenges

* PayPal does not let a merchant app open a dispute for a buyer (HTTP 400 "No permissions to set target_client_id"), and the app's token cannot accept an offer as the buyer. So the buyer agent works through the Resolution Center like a person would.
* PayPal refuses things a naive client would send: an offer right after a message (422), one evidence entry per item (ITEM_ID_IS_MANDATORY_FOR_MULTIPLE_EVIDENCES), a refund on a pending capture. Clearwake reads the actions PayPal offers on the dispute, sends the offer alone, and records every refusal in a receipt.
* A lost reply must not become a second refund. Each action keeps one request id, a lost reply stays UNKNOWN, and PayPal's record decides.
* Counting items in a photo with SAM 3 on a laptop without a GPU: 15 s to load and 56 s to count, through a 20 line CPU patch.
* AG Grid 33 and later set styles at run time, which a strict Content Security Policy blocks. We pass a nonce and allow its 14 fixed load time style blocks by exact hash, with no unsafe-inline.

## What we learned

A model is useful as a proposer and unsafe as a decider, so the limits sit in a policy file that no message can edit and its hash is in every receipt. "Done" has to come from the provider's own record, not from the agent that sent the request. And the useful half of the Disputes API is the part that talks (`send-message`, `make-offer`), because that is where the fee is avoided.

## What is next

The same boundary for every daily operation, not only the demo cases. Dispatch proof on photos of real packed parcels. Shared context for teams of people and agents. Receipts that payment platforms accept as proof.

## What is real

Everything ran in the PayPal sandbox with test money: no live PayPal, no real money, no customers. The public site shows a recorded sandbox run and verifies its receipts in the visitor's browser. The console on Render is hosted on Render, not network isolated; the network isolated run is the local proof.
```

## 4. Built with (up to 25 tags; Devpost takes them comma separated)

python, paypal, paypal-orders-api, paypal-payments-api, paypal-disputes-api, paypal-sandbox, ollama, `[MODEL_TAG]`, sam-3, playwright, ag-grid, render, apimatic, openapi, postman, docker, sqlite, ed25519, webcrypto, javascript, vercel

That is 21 tags with the model tag filled in. Four spare.

## 5. "Try it out" links

* Live console (hosted on Render, not network isolated): `[RENDER_URL]/console`
* Public site, recorded sandbox run and in browser receipt verifier: https://clearwake-mu.vercel.app
* Code: https://github.com/Sriharsan/clearwake
* OpenAPI 3.1 spec: https://github.com/Sriharsan/clearwake/blob/main/openapi/clearwake-console.openapi.yaml
* API portal (APIMatic): `[APIMATIC_PORTAL_URL]`
* Postman collection: https://github.com/Sriharsan/clearwake/blob/main/postman/clearwake-paypal.postman_collection.json

## 6. Image gallery (3:2, each under 5 MB, from real screens)

Devpost wants a 3:2 ratio. Export 1500 by 1000 pixels (or 1800 by 1200), PNG or JPG, and check the size. Each image is a screenshot of the running thing.

From agent C (made for the repository; crop or letterbox to 3:2 if they are not already):

1. `docs/img/console-merchant.png`: the merchant control room with the AG Grid dispute ledger (first image, it is the thumbnail).
2. `docs/img/site-home.png`: the public site home page.

To capture by hand, after the batch (all from the live or local console unless noted):

3. Buyer agent tab: the mandate and one purchase with its signed receipt.
4. The ledger with a row opened: the model's proposal next to the policy decision and PayPal's record.
5. PayPal's sandbox Resolution Center, the dispute `[HERO_DISPUTE_ID]` showing RESOLVED. Crop out the account email and name.
6. The receipt verifier showing a chain that fails after one edited line.
7. The terminal after `python scripts/airgap.py`: network cut, held lines, restored, PASS with the refund ids.
8. The Render URL in the address bar with the console loaded.

Never include `.env`, the PayPal developer credentials page or a key.

## 7. Video demo link

`[VIDEO_URL]` (public YouTube, under 3 minutes, no music, no logos you do not own). Script: `VIDEO_SCRIPT.md`.

## 8. Submitter type

Individual

## 9. Country

India

## 10. Canada (the residency question)

N/A

## 11. Organization

N/A

## 12. New or existing project

New.

Answer text if a free text box follows: Clearwake is new work from 30 October 2026, after the submission period opened on 1 October 2026. The first commit in the repository is 30 Oct 2026, 20:47 IST. It pins two of the author's own public MIT components, both also started after 1 October: Relayloom (first commit 27 Oct 2026, 00:05 IST; the workroom code 28 Oct 2026) and verdock-core (first commit 31 Oct 2026, 11:20 IST, tagged v0.2.0 the same day). Every commit, in all three repositories, is dated in `docs/HACKATHON_UPDATES.md`, from `git log`.

Checked against git on 9 November 2026: `git log --reverse` in the repository shows 5586442 dated 2026-10-30 20:47:28 +0530 as the first of 59 commits; in `vendor/relayloom` the first commit ec6dc51 is dated 2026-10-27 00:05:53 +0530 (and 3668d31, the first with workroom code, 2026-10-28 18:38:33 +0530); in `vendor/verdock-core` the first commit 39b8c52 is dated 2026-10-31 11:20:58 +0530. The pinned submodule commits are e4654fa and f7ac784 (v0.2.0).

## 13. Main technology requirement: how Clearwake uses PayPal and AI

The one requirement is that a project meaningfully uses both PayPal and AI.

**PayPal (sandbox only, base URL fixed to `https://api-m.sandbox.paypal.com`)**

| API | Calls | What it does in Clearwake |
| --- | --- | --- |
| OAuth 2.0 | `POST /v1/oauth2/token` | Server side token, never sent to a browser |
| Orders v2 | `POST /v2/checkout/orders`, `GET /v2/checkout/orders/{id}`, `POST .../capture`, `POST .../track` | The buyer agent's purchase, the capture, and the tracking the evidence step reads back |
| Payments v2 | `GET /v2/payments/captures/{id}`, `POST .../refund`, `GET /v2/payments/refunds/{id}` | A capture read before every refund, one refund with a stable `PayPal-Request-Id` and `custom_id`, then the check that decides whether the refund counts |
| Disputes v1 | `GET /v1/customer/disputes`, `GET .../{id}`, `POST .../send-message`, `POST .../make-offer`, `POST .../provide-evidence`, `POST .../provide-supporting-info`, `POST .../accept-claim`, `POST .../adjudicate` (sandbox only) | Read the dispute and the actions PayPal offers, settle in conversation with a message and an offer, answer with evidence or supporting info, accept a claim with a refund, finish a test dispute |

**AI**

| Model | Where it runs | What it does |
| --- | --- | --- |
| `[MODEL_NAME]` through Ollama | Locally, in a container on the network isolated Docker network | The merchant agent: reads each dispute and the buyer's message, proposes settle, fight or escalate, writes the reply and the offer note. It can only propose. The policy file decides and code checks every amount and cited id. `[MODEL_CALLS]` recorded calls. |
| The buyer agent's model (`[MODEL_NAME]` or the one named in docs/RESULTS.md) | Locally | Chooses a product inside the mandate and decides to accept, counter or escalate an offer inside the owner's dispute rule. The mandate check and the rule check are code. |
| SAM 3 (`facebook/sam3`, Meta, open weights) | Locally, on the CPU, offline | Counts the items in the packing photo for the dispatch proof. Counted 3 of 3 notebooks in a CC0 test photo. Not a real parcel. |
| `qwen2.5-coder:3b` through Ollama | Locally, inside the isolated network | Drafted proposals while the network was cut in case m (6.3 to 13.1 s each). |
| Scripted fallback | Locally | Fixed rules, labelled "scripted, not AI" in every run file, used when no model is running. |

AI tools used to write the code: Claude Code helped write code and documents; every commit is reviewed and authored by Sri.

## 14. Sponsor tools selected

* **AG Grid** (Community 35.3.1, MIT): the dispute ledger on the local console, on Render and on the public Control Room.
* **Render**: hosts the live console.
* **APIMatic**: OpenAPI 3.1 spec of the console API, SDK and portal, Context Plugin review of the PayPal calls.
* **Postman**: collection of every PayPal call with tests on PayPal's responses, and an environment template with no secrets. (Postman is listed as a partner with no prize; tick it if the form has a box.)
* **Channel3**: not selected. Its catalog returns real retailers' products, and the buyer agent's order is a PayPal sandbox order at one sandbox merchant, so a Channel3 result could not be bought and would change no outcome (`docs/CHANNEL3.md`).
* **Bryntum, Elastic, KERNEL, Zapier, Astropods**: not selected, with reasons in `docs/DESIGN_DECISIONS.md`.

## 15. Repository URL

https://github.com/Sriharsan/clearwake (public, MIT licence shown in About)

## 16. Demo URLs

* `[RENDER_URL]/console` (hosted on Render, not network isolated)
* https://clearwake-mu.vercel.app (static, recorded sandbox run)

## 17. Testing instructions for judges (paste as is)

```text
Three ways, fastest first. Everything is PayPal sandbox with test money. No account or key is needed for 1 and 2.

1. In a browser, no install: open [RENDER_URL]/console (hosted on Render, not network isolated; the first load can take a moment while the service wakes).
   a. Press Reset.
   b. Tab "1 Buyer agent": type "a pack of three A5 notebooks" and press Buy. The mandate check and a signed receipt appear.
   c. Tab "2 Merchant control room": run case n (settled in conversation). In the AG Grid dispute ledger the new row shows stage INQUIRY, the model's proposal next to the policy decision, and PayPal's status. Use the stage filter and the CSV export.
   d. Tab "3 Receipt verifier": press Verify on both logs (it passes). Edit one character of a log and verify again (it fails).
   The page states how each run was made. The hosted console is rate limited per address; if you see a 429, wait the number of seconds shown.

2. Public site, no install: https://clearwake-mu.vercel.app . It shows a recorded sandbox run of the network cut (case m) and verifies its receipts in your browser. Use "Change one line, then verify" to see the chain break.

3. Run it yourself (Python 3.12 or newer, nothing to install; Docker only for the network isolated run):
   git clone --recurse-submodules https://github.com/Sriharsan/clearwake.git
   cd clearwake
   python -m clearwake --port 8810        # open http://127.0.0.1:8810/console
   python scripts/cases.py                # cases a to o in rehearsal, prints PASS or FAIL for each, no network
   python -m unittest discover -s tests   # offline tests
   python openapi/check_openapi.py --live # the OpenAPI spec checked against the running console
   python postman/check_collection.py     # the Postman collection, offline
   python scripts/airgap.py               # case m: network isolated containers, cut and restore (needs Docker and your own sandbox keys in .env)

With your own PayPal sandbox keys (copy .env.example to .env): python scripts/cases.py --sandbox runs the real sandbox cases. A dispute has to be opened by the sandbox buyer in PayPal's Resolution Center (PayPal does not let a merchant app open one); then run python scripts/cases.py --sandbox --only n --dispute <dispute id>.

Recorded results with PayPal sandbox ids are in docs/RESULTS.md and docs/SANDBOX_RUN.md.
```

## 18. AG Grid experience (write only what happened; items in brackets are for Sri to confirm with the final console)

What happened, from the repository:

* We used AG Grid Community 35.3.1 (npm `ag-grid-community`, published 2 June 2026, MIT), vendored unchanged as one script file with its licence beside it, so the console loads nothing from another host.
* The first problem was our Content Security Policy. AG Grid 33 and later positions rows and cells through the CSS object model and takes a `styleNonce` for the style blocks it adds, but the bundle also writes 14 fixed style blocks while it loads, before it can know the nonce. We serve a fresh nonce per page response and allow those 14 blocks by exact SHA-256 in the policy, with no `unsafe-inline`. We checked it in Chromium on 31 October 2026: zero CSP violations and rows drawn correctly. The icon font is embedded as a `data:` URI, so only the console page allows `data:` fonts.
* The grid is the dispute ledger: one row per PayPal dispute with the reason, amount, stage and PayPal's status read from the record, the model's proposal next to the policy decision, the deadline, whether it settled before escalation and the fee avoided. Rows have stable ids (the dispute id) so a refresh updates a row instead of redrawing the table. The ledger exports to CSV with `api.exportDataAsCsv`, with cell values made safe against spreadsheet formulas, for the accountant.
* [Confirm against the final build before pasting: the stage filter, the deadline countdown cell, and how a row's detail shows PayPal's raw record. Master/detail is an Enterprise feature, so if the detail is a custom panel under the row, say that.]
* If AG Grid does not load, the page falls back to a plain table, so the ledger still reads.
* What we would tell the AG Grid team: the style handling changes in v33 are the part that cost the most time under a strict policy, and a documented list of the fixed load time style blocks (or a way to give them the nonce before the bundle runs) would save the next team the hash work. [Sri: keep this only if it is your own view.]

## 19. APIMatic experience (fill in by Sri; nothing below has happened yet)

`[APIMATIC_EXPERIENCE]`

Write only what actually happened, using the two log tables in `docs/APIMATIC.md`:

* What the Context Plugin for PayPal said about each PayPal call, and what it corrected, if anything. If it corrected nothing, say it confirmed the calls. The calls in `clearwake/paypal.py` were written between 30 October and 3 November 2026, before the plugin was installed, so describe it as a review.
* What `apimatic api validate` reported on `openapi/clearwake-console.openapi.yaml`, and what you changed.
* Which SDK languages you generated, whether the snippet ran against the local console, and the portal link.
* What was easy and what was not, in your words.

## Fields the live form may add

| Likely field | Answer |
| --- | --- |
| Team members | Sriharsan B S (sole author) |
| Repository access / is the repo public | Yes, public, MIT |
| Which sponsor prizes should this be considered for | AG Grid, Render, APIMatic. Postman if a box exists. Not Channel3, not Bryntum |
| Which prize categories | Best Use of PayPal + AI, Best Use of Agentic Commerce, Best Demo Delivery, Most Creative, Most Impactful |
| Did you use AI coding tools | Yes: Claude Code helped write code and documents. Every commit is reviewed and authored by Sri |
| What was updated during the submission period (for existing projects) | Not applicable, the project is new (see field 12) |
| Additional info for judges | The line in field 17, plus: no live PayPal, no real money, no customers, no revenue. Results are in the PayPal sandbox |
| Video language / captions | English, spoken by Sri |
| Does the project need a login or special access | No for the Render console and the public site. Running the sandbox cases needs your own PayPal sandbox keys |

## Rules reminders (apply to every answer above)

Every number comes from `docs/RESULTS.md` or a run file, none made up. No dashes as punctuation, no exclamation marks, none of the banned words from the build brief. One mode line per page. Never call a refund or dispute done until PayPal's record says so. Never open, save or submit anything on Devpost from a script.
