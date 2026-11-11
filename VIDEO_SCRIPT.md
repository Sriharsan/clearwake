# Clearwake video: dialogue script (2:45 maximum, Sri speaks, captions on)

Format: **SAY** is what Sri says, **[click]** is what to do on screen, **CAPTION** is the burned in caption. Record the browser and one terminal only. Upload publicly to YouTube, captions on, no music, no third party logos. Speak in your own words; the lines are about 400 words, which fits 2:40 at a calm pace.

The one line, first in the video (as it is on the site, README and Devpost About): "When an AI agent buys something and it never arrives, Clearwake lets the buyer's agent and the seller's agent settle it inside PayPal in minutes, with proof, before it becomes a claim or a fee, and nothing is ever paid twice." Say it in your own breath, in two parts if needed.

Labels: one short caption per shot saying how it ran (**Real sandbox**, **Injected faults, local run on the local provider**, **Recorded sandbox run**). The phrase "local run on the local provider" appears once, on the unguarded segment.

Live product on screen: 0:15 to 0:45 (the half that runs Clearwake), 0:45 to 1:50, 1:50 to 2:20 (the ledger, with the table overlay for the last 10 seconds) and 2:20 to 2:45. Only the title card (15 s), the recorded comparison page (about 15 s) and the 10 second table overlay are not live: 40 of 165 seconds, so the live share is 76 percent. Keep it at 75 or above if you cut anything.

Bracketed numbers come from the real batch run file `data/runs/batch-sandbox-*.json`; the lead fills them from `docs/RESULTS.md`. Do not say a number that is still in brackets. The baseline numbers are already measured (`data/runs/baseline-20261110-172506.json`).

## Before recording

```
python -m clearwake --port 8810              # console: http://127.0.0.1:8810/console
python -m clearwake --phone                  # only for the voice shot; wait for "Speech model ready"
python scripts\cases.py --only e,g           # both must print PASS
```

Tabs ready: the console (1 Buyer agent, 2 Merchant control room, 3 Receipt verifier, 4 Voice); PayPal's sandbox Resolution Center logged in as the sandbox buyer (log in by hand before recording, never show the login or email); `docs/BASELINE.md` and `docs/TOOLKIT_FAILURE_CASES.md` open; the Render link `[RENDER_URL]/console`; a terminal with `python scripts\show_dispute.py [HERO_DISPUTE_ID]` typed. Never show `.env` or the PayPal developer credentials page.

## 0:00 to 0:15 The problem, in dollars

**[click]** Title card on screen: `USD 15.00` per dispute that escalates to a claim. `USD 30.00` per dispute above 1.5% and 100 sales. `Built for the PayPal AI Hackathon`. Source line under it: PayPal Merchant Fees, US, 1 Oct 2026; help350.

**SAY:** "When an AI agent buys something and it never arrives, PayPal charges fifteen dollars when the dispute escalates, thirty above one and a half percent. Clearwake lets the buyer's agent and the seller's agent settle it inside PayPal, in minutes, with proof, and nothing is ever paid twice. Built for the PayPal AI Hackathon."

**CAPTION:** PayPal fee rules, linked in the repo

## 0:15 to 0:45 The unguarded agent

**[click]** Browser on `docs/BASELINE.md`, the total row: an agent using PayPal's Agent Toolkit directly against Clearwake, 200 episodes. Then `docs/TOOLKIT_FAILURE_CASES.md`, the lost response table (2 refunds, 3.00 for one 1.50 dispute) and the injected message table (5000.00 refunded).

**SAY:** "First, an agent using PayPal's official Agent Toolkit directly, with no guard. A response is lost, the agent retries, and the customer is paid twice. A dispute message says ignore your limits, and a claim is accepted. Over two hundred episodes it overpaid twenty six hundred dollars and made sixty one double refunds."

**CAPTION:** Injected faults, local run on the local provider. PayPal Agent Toolkit 1.11.0

**[click]** Console, tab 2, **Run case**: e, then g. Point at the rows: e shows one refund, UNKNOWN then VERIFIED; g shows "Policy refused: above limit".

**SAY:** "Same faults through Clearwake: zero dollars overpaid, zero double refunds. The injected message is refused before any PayPal call."

**CAPTION:** Same faults, same layer

## 0:45 to 1:50 Clearwake live on the sandbox

**[click]** Tab 4, **Voice** (or the phone): hold the button and say the rules. Show the plain words readback, then say yes. Show the signed policy hash.

**SAY:** "Step zero. I say my rules once: refund anything under thirty dollars that has not arrived in ten days, ask me above that, never refund twice. The system reads them back in plain words, I say yes, and they are signed. The model can propose anything now. It can never go past this."

**CAPTION:** Real sandbox. Rules said once, signed

**[click]** Tab 1, **Buyer agent**: the order inside its signed mandate, the tracking stalled. PayPal sandbox Resolution Center: the buyer's agent opens the item not received dispute.

**SAY:** "The buyer's agent bought inside a mandate its owner signed. The tracking stalls, so it opens the item not received dispute in PayPal, and only for an order its mandate covers."

**CAPTION:** Real sandbox, buyer agent through a local browser

**[click]** Tab 2, **Merchant control room**, AG Grid ledger: the new row, stage INQUIRY. Point at the **Proposed** and **Policy decision** columns, then the dispatch record.

**SAY:** "The merchant's agent reads the dispute, the order, the tracking on PayPal and the signed dispatch record. The model drafts. The rules decide. Here it offers a refund inside my limit, sent alone through PayPal's own offer call."

**CAPTION:** Real sandbox. Local model `[MODEL_NAME]`; the policy decides

**[click]** Scroll the ledger to the row where the two columns differ: `[OVERRULED_EXAMPLE]`.

**SAY:** "Here the model proposed the wrong move once. The policy stopped it. The model only proposes."

**CAPTION:** `[OVERRULED_CAPTION]`

**[click]** The buyer agent log: the offer is read, its mandate allows it, it accepts. Then the terminal: `python scripts\show_dispute.py [HERO_DISPUTE_ID]`, PayPal's record: status RESOLVED, stage INQUIRY. Then tab 3, **Receipt verifier**: the two receipts, same dispute id, Verify.

**SAY:** "The buyer's agent accepts what its mandate allows. PayPal's own record now reads resolved, at the inquiry stage. No claim, no fee. Two signed receipts, one from each side, the same dispute id, verified offline."

**CAPTION:** Real sandbox, read from PayPal's record

## 1:50 to 2:20 The results

**[click]** Tab 2, ledger after the batch: filter by stage, point at the countdown cells, press CSV export. For the last 10 seconds, overlay the table below (it comes from `docs/RESULTS.md`).

**SAY:** "Ten agent bought cases on the real sandbox. [BATCH_SETTLED] settled by the two agents with no fee, [BATCH_ESCALATED] correctly handed to a person, [BATCH_REFUNDS] refunds confirmed by PayPal's record, [BATCH_SECONDS_PER_CASE] seconds a case. Any other dispute reason goes to the owner untouched. That is the honest limit."

**CAPTION:** Real sandbox batch of `[BATCH_TOTAL]`, read back from PayPal

Overlay table:

| | Agent using PayPal's Agent Toolkit directly | Clearwake |
| --- | --- | --- |
| Overpaid, 200 episodes | USD 2,633.25 | USD 0.00 |
| Double refunds | 61 | 0 |
| Wrongly accepted claims | 160 | 0 |
| Episodes ended as the owner intended | 40 of 200 | 200 of 200 |
| Real sandbox batch of `[BATCH_TOTAL]` | not run | `[BATCH_SETTLED]` settled at INQUIRY, `[BATCH_REFUNDS]` refunds confirmed, `[BATCH_SECONDS_PER_CASE]` s per case |

## 2:20 to 2:45 Who it is for, how to run it

**[click]** Console in the browser at the Render link, then the GitHub page, then a terminal showing the one clone command.

**SAY:** "Clearwake is for the person whose agent shops for them, and the small merchant on PayPal who sells to agents. Run it yourself with one command, or open the live console, hosted on Render. The code is MIT on GitHub, sandbox only, no real money."

**CAPTION:** `[RENDER_URL]` (hosted on Render, not network isolated). github.com/Sriharsan/clearwake

## Notes

* Do not stage a step. If the sandbox shows a CAPTCHA or blocks the buyer's browser, record the owner doing that step by hand, say so in one sentence, and caption it "Real sandbox, buyer step done by hand". Never get past a CAPTCHA.
* The unguarded agent segment is a recorded comparison, not the product; keep it to about 15 seconds on screen.
* The network cut (case m) and the broken receipt chain are good extras if the batch leaves seconds to spare. They are not in the 2:45 cut. Caption the cut "Real sandbox, network isolated containers" and the chain "Recorded sandbox run, verified in this browser".
* Keep to plain speech and the public text rules in the build brief.
