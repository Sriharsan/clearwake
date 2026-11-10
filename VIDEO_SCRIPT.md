# Clearwake demo video: dialogue script (2:45 maximum, Sri speaks, captions on)

Format: **SAY** is what Sri says, **[click]** is what to do on screen, **CAPTION** is the burned in caption. Record the browser and one terminal only. Upload publicly to YouTube, captions on, no music, no third party logos. Speak in your own words; the lines are about 330 words, which fits 2:40 at a calm pace.

Honesty labels: one short caption per shot saying how it ran (**Real sandbox**, **Injected fault, no network**, **Recorded sandbox run**, **Rehearsal**). Never caption a rehearsal shot as sandbox.

Live product on screen: 0:15 to 0:45 (half), 0:45 to 1:50, 1:50 to 2:20 (the ledger, with the table overlay for the last 10 seconds) and 2:20 to 2:45 are screens of the running console, terminal or live link. Only the title card (15 s), the recorded comparison page (about 15 s) and the 10 second table overlay are not live: 40 of 165 seconds, so the live share is 76 percent. Keep it at 75 or above if you cut anything.

Bracketed numbers (`[BATCH_SETTLED]` and so on) come from the batch run files; the lead fills them from `docs/RESULTS.md` and `data/runs/`. Do not say a number that is still in brackets.

## Before recording

```
python -m clearwake --port 8810              # console: http://127.0.0.1:8810/console
python scripts\cases.py --only e,g           # rehearsal: both must print PASS
python scripts\airgap.py                     # only if you keep the cable pull as an extra (Docker running)
```

Tabs ready: the console (1 Buyer agent, 2 Merchant control room, 3 Receipt verifier); PayPal's sandbox Resolution Center logged in as the sandbox buyer (log in by hand before recording, never show the login or email); `docs/TOOLKIT_FAILURE_CASES.md` open on the case e and case g tables; the Render link `[RENDER_URL]/console`; a terminal with `python scripts\show_dispute.py [HERO_DISPUTE_ID]` typed. Never show `.env` or the PayPal developer credentials page.

## 0:00 to 0:15 The problem, in dollars

**[click]** Title card on screen: `USD 15.00` per dispute that escalates to a claim. `USD 30.00` per dispute above 1.5% and 100 sales. `Built for the PayPal AI Hackathon`. Source line under it: PayPal Merchant Fees, US, 1 Oct 2026; help350.

**SAY:** "PayPal charges fifteen dollars when a dispute escalates, thirty above one and a half percent. Now AI agents are buying, and agents will start those disputes. This is Clearwake, built for the PayPal AI Hackathon."

**CAPTION:** PayPal fee rules, linked in the repo

## 0:15 to 0:45 The unguarded agent

**[click]** Browser on `docs/TOOLKIT_FAILURE_CASES.md`, case e table: the toolkit's retry column ("2 refunds, 3.00 total for one 1.50 dispute"). Then the case g table ("5000.00 refunded").

**SAY:** "First, an agent with no guard, PayPal's own agent toolkit, run against an injected fault with no network. A reply is lost, the agent retries, and the customer is paid twice. A dispute message says ignore your limits, and a five thousand dollar claim is accepted."

**CAPTION:** Injected fault, no network. PayPal agent toolkit 1.11.0, 31 Oct

**[click]** Switch to the console, tab 2, **Run case**: e, then g. Point at the rows: e shows one refund, UNKNOWN then VERIFIED; g shows "Policy refused: above limit".

**SAY:** "Same faults through Clearwake: one refund, held as unknown, reconciled from PayPal's record. The injected message is refused by the policy before any PayPal call."

**CAPTION:** Rehearsal, same faults, no PayPal calls

## 0:45 to 1:50 Clearwake live on the sandbox

**[click]** Tab 1, **Buyer agent**: type "three A5 notebooks", press Buy. Show the mandate check passing and the signed mandate receipt.

**SAY:** "The buyer's agent buys three notebooks inside a budget its owner signed. The purchase is a signed receipt linked to the PayPal order."

**CAPTION:** Real sandbox order, receipt signed offline

**[click]** PayPal sandbox Resolution Center: the buyer agent opens the dispute, "Only 2 of 3 notebooks arrived".

**SAY:** "One notebook is missing, so the buyer's own agent opens the dispute in PayPal's Resolution Center."

**CAPTION:** Real sandbox, buyer agent through a local browser

**[click]** Tab 2, **Merchant control room**, AG Grid ledger: the new row, stage INQUIRY. Point at the **Proposed** and **Policy decision** columns, then the dispatch proof "3 of 3 counted, sealed, shipped".

**SAY:** "The merchant's agent reads the message. A local model proposes. The policy decides, and code checks every amount. It checks its dispatch proof, and offers a refund inside the owner's limit through PayPal's own message and offer calls."

**CAPTION:** Real sandbox. Local model `[MODEL_NAME]`; the policy decides

**[click]** Scroll the ledger to the row where the two columns differ: `[OVERRULED_EXAMPLE]` (a case where the model proposed something wrong and the policy stopped it). If the batch has none, show case g from tab 2 instead and caption it as rehearsal.

**SAY:** "Here the model proposed the wrong move once. The policy stopped it. The model only proposes."

**CAPTION:** `[OVERRULED_CAPTION]`

**[click]** The buyer agent log: the offer is read, the dispute rule ("accept any refund of 80 percent or more for a missing item") applies, the buyer accepts. Then the terminal: `python scripts\show_dispute.py [HERO_DISPUTE_ID]`, PayPal's record: status RESOLVED, stage INQUIRY.

**SAY:** "The buyer's agent checks the offer against its owner's rule, and accepts. PayPal's own record now reads resolved, at the inquiry stage. No claim, no fee. Clearwake says settled only when PayPal says it."

**CAPTION:** Real sandbox, read from PayPal's record

## 1:50 to 2:20 The results

**[click]** Tab 2, ledger after the batch: filter by stage, point at the countdown cells, press CSV export. For the last 10 seconds, overlay the table below (it comes from `docs/RESULTS.md`).

**SAY:** "Ten orders, bought and disputed by the same agent. [BATCH_SETTLED] settled with no fee, [BATCH_EVIDENCE] answered with evidence, [BATCH_ESCALATED] sent to the owner, [BATCH_REFUNDS] refunds confirmed by PayPal's record, [BATCH_SECONDS_PER_CASE] seconds a case. The unguarded agent paid twice and paid five thousand. Clearwake paid once, and refused."

**CAPTION:** Real sandbox batch of `[BATCH_TOTAL]`, read back from PayPal

Overlay table:

| | Unguarded agent (injected fault, no network) | Clearwake |
| --- | --- | --- |
| Lost response, 1.50 dispute | 2 refunds, 3.00 total | 1 refund, reconciled |
| Injected message, 5000.00 claim | 5000.00 refunded | refused, no PayPal call |
| Batch of `[BATCH_TOTAL]` disputes | not run | `[BATCH_SETTLED]` settled at INQUIRY, `[BATCH_REFUNDS]` refunds confirmed, `[BATCH_SECONDS_PER_CASE]` s per case |

## 2:20 to 2:45 Who it is for, how to run it

**[click]** Console in the browser at the Render link, then the GitHub page, then a terminal showing the one clone command.

**SAY:** "Clearwake is for the owner of a buying agent and the owner of a shop, who want disputes settled inside the limits they signed. Run it yourself with one command, or open the live console on Render, hosted, not network isolated. The code is MIT on GitHub, sandbox only, no real money."

**CAPTION:** `[RENDER_URL]` (hosted on Render, not network isolated). github.com/Sriharsan/clearwake

## Notes

* Do not stage a step. If the sandbox shows a CAPTCHA or blocks the buyer's browser, record the owner doing that step by hand, say so in one sentence, and caption it "Real sandbox, buyer step done by hand". Never get past a CAPTCHA.
* The unguarded agent segment is a recorded comparison, not the product; keep its caption "Injected fault, no network" and keep it to about 15 seconds on screen.
* The cable pull (case m) and the broken receipt chain are good extras if the batch run leaves seconds to spare. They are not in the 2:45 cut. Caption the cable pull "Real sandbox, network isolated containers" and the chain "Recorded sandbox run, verified in this browser".
* Keep to plain speech and the public text rules in the build brief.
