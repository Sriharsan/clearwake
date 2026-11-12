# Clearwake video: dialogue script (2:55 maximum, Sri speaks, captions on)

**When an AI agent buys something and it never arrives, Clearwake lets the buyer's agent and the seller's agent settle it inside PayPal within an hour, with proof, before it becomes a claim or a fee, and nothing is paid twice.**

**When an agent's order goes missing, agents fix it.**

**Real PayPal sandbox run, 11 November 2026.** 10 orders bought by an agent, 10 item not received disputes. 4 settled by the two agents at INQUIRY, before a claim, USD 20.00 refunded. USD 0.00 overpaid against USD 2,633.25 for an agent on the PayPal Agent Toolkit alone.

Format: **SAY** is what Sri says, **[click]** is what to do on screen, **CAPTION** is the burned in caption, **TAG** is the small label top left of every shot. Record the browser and one terminal only. Upload publicly to YouTube, captions on, no music, no third party logos. Speak in your own words; the lines are 404 words over 2:55, which is 138 words a minute with one claim per sentence. Sri decides the final cut, the face or phone footage and every video choice; this file is a draft.

Shape, taken from the winning videos: the real result is on screen in the first frame, no title card. The bad outcome comes first and the same action is stopped second. The key number is spoken while its proof is on screen. Every shot carries a tag that says how it ran: **Real PayPal sandbox run**, **Planted failure**, **Verified in your browser**, **Local run**. Hold each proof screen 4 to 5 seconds and cut at the end of a sentence. The outcomes are counted aloud.

The one line, spoken at 0:12: "When an AI agent buys something and it never arrives, Clearwake lets the buyer's agent and the seller's agent settle it inside PayPal within an hour, with proof, before it becomes a claim or a fee, and nothing is paid twice."

Every number comes from a run file: `data/runs/batch-sandbox-20261111-132948.json` (the batch), `data/runs/settle-times-20261111.json` (settle times), `data/runs/baseline-20261110-172506.json` (the 200 episodes). Do not say a number that is not in those files.

## Before recording

```
python -m clearwake --port 8810              # console: http://127.0.0.1:8810/console
python -m clearwake --phone                  # only for the voice shot; wait for "Speech model ready"
python scripts\cases.py --only e,g           # both must print PASS
python scripts\verify_pair.py data\runs\batch-sandbox-20261111-132948.json
```

Tabs ready: the console (1 Buyer agent, 2 Merchant control room, 3 Receipt verifier, 4 Voice); PayPal's sandbox Resolution Center logged in as the sandbox buyer (log in by hand before recording, never show the login or email); `docs/BASELINE.md` and `docs/TOOLKIT_FAILURE_CASES.md` open; the Render link `https://clearwake-console.onrender.com/console`; a terminal with `python scripts\show_dispute.py PP-R-ISN-10198775` typed. Never show `.env` or the PayPal developer credentials page.

## 0:00 to 0:12 The real result, first frame (line spoken, number on screen)

**[click]** PayPal's record of dispute `PP-R-ISN-10198775` on screen from the first frame: status RESOLVED, stage INQUIRY, refund USD 5.00.

**TAG:** Real PayPal sandbox run, case 3

**SAY:** "An AI agent bought something. It never arrived. Five dollars. PayPal's own record reads resolved, at the inquiry stage."

**CAPTION:** PayPal's record: RESOLVED at INQUIRY

## 0:12 to 0:25 The claim, then the bad outcome

**SAY:** "When an AI agent buys something and it never arrives, Clearwake lets the buyer's agent and the seller's agent settle it inside PayPal within an hour, with proof, before it becomes a claim or a fee, and nothing is paid twice. First, what happens without it."

**[click]** Browser on `docs/BASELINE.md`, the total row: an agent using PayPal's Agent Toolkit directly, 200 episodes. Then `docs/TOOLKIT_FAILURE_CASES.md`, the lost response table.

**TAG:** Planted failure, local run, PayPal Agent Toolkit 1.11.0

**SAY:** "A response is lost, the agent retries, and the customer is paid twice. A message says ignore your limits, and a claim is accepted. Over two hundred episodes: twenty six hundred and thirty three dollars overpaid, sixty one double refunds."

**CAPTION:** 200 episodes: USD 2,633.25 overpaid, 61 double refunds

## 0:25 to 0:40 The same action, stopped

**[click]** Console, tab 2, **Run case**: e, then g. Point at e (one refund, UNKNOWN then VERIFIED) and g ("Policy refused: above limit"). Cut to the baseline row for Clearwake.

**TAG:** Planted failure, same faults, same layer

**SAY:** "Same faults through Clearwake. Zero dollars overpaid. Zero double refunds. The injected message is refused before any PayPal call."

**CAPTION:** Clearwake: USD 0.00 overpaid, 0 double refunds, 200 of 200 as the owner intended

## 0:40 to 1:00 Rules said once, in Sri's own voice (face or phone slot, then the screen)

**0:40 to 0:45, face or phone slot.** **[click]** Sri on camera, or his phone in his hand, saying the rule aloud. One take of real footage in his real voice, 5 seconds, nothing staged around it. Sri decides face or phone and records it himself.

**TAG:** Real PayPal sandbox run, rules said by the owner

**SAY:** "Settle an item that has not arrived on its own, up to five dollars. Ask me up to nine. Never more."

**0:45 to 1:00, the screen.** **[click]** Tab 4, **Voice** (or the phone): the plain words readback, say yes, show the signed policy hash.

**SAY:** "The system reads it back in plain words. I say yes, and it is signed. The model can propose anything now. It can never go past this."

**CAPTION:** Settle up to USD 5.00. Ask up to USD 9.00. Never more.

## 1:00 to 1:30 Anatomy: one dispute, six layers (30 seconds)

Source: `ANATOMY_DIAGRAM_SPEC.md`, the exploded view. One dispute runs through every layer: case 3, `PP-R-ISN-10198775`, USD 5.00, shown as one bead on a thread. The stack is on screen at the first frame of the segment, no fade in. Top left tag for the whole segment: **Real PayPal sandbox run, case 3**; any step shown from a recorded run carries **Replay of a recorded run** instead.

| Time | On screen | SAY | CAPTION |
| --- | --- | --- | --- |
| 1:00 to 1:03 | The assembled unit: six sheets stacked on one axis, the thread through them, the bead parked at the top | "One dispute. Six layers." | One dispute. Six layers. |
| 1:03 to 1:08 | Sheets separate top first; the skeleton lights (layer 1, owner's spoken rules: waveform, rule text, Read back, Signed). The bead drops onto it | "The skeleton is the owner's rule, said once and signed." | The owner says the rule once. It is signed. |
| 1:08 to 1:15 | The muscles: layer 2, the buyer agent's claim card (Item not received, PP-R-ISN-10198775, USD 5.00), then layer 3, the merchant agent's reply card with the proof attached | "The muscles are two agents. The buyer's files the claim and cannot pay itself. The merchant's answers with proof." | Buyer agent files. Merchant agent answers with proof. |
| 1:15 to 1:20 | The skin and the seal: layer 4, the policy gate, chip Proposed: refund USD 5.00 turns to Allowed; layer 5, four receipt blocks chain in, each stamps Signed | "The skin is the policy gate, which checks every action before money moves. The seal is the signed receipts." | Checked before money moves. Each receipt checks the one before. |
| 1:20 to 1:27 | The heart and the blood: layer 6, PayPal's record for the same case id opens, a match line draws from the last receipt, chip Matches PayPal's record; the USD 5.00 line pulses once as the bead lands | "The heart is PayPal's record. The blood is the five dollars, and it moves once." | PayPal's record is the judge. It matches. |
| 1:27 to 1:30 | Sheets close back into the assembled stack, bottom first; the bead glows; end line over the stack | "Case 3. Settled inside PayPal. Paid once." | Settled inside PayPal. Paid once. USD 5.00. |

Hold each layer long enough to read it muted; one thing moves at a time except the 0.25 second stagger of the separation. Never show a token, an account id or private data on any sheet; `PP-R-ISN-10198775` is the only identifier. The two layer names the spec calls Rules and Policy gate keep those labels on the sheets; skeleton, muscles, skin, seal, heart and blood are the spoken anchors.

## 1:30 to 1:48 The two agents settle it, live

**[click]** Tab 1, **Buyer agent**: the order inside its signed mandate. PayPal's Resolution Center: the dispute opened. Tab 2, AG Grid ledger: the new row, stage INQUIRY, the **Proposed** and **Policy decision** columns. Then the ledger row where the two columns differ, case 1, `PP-R-YYA-10198768`.

**TAG:** Real PayPal sandbox run, buyer agent through a local browser

**SAY:** "The model drafts. The rules decide. The offer goes alone, through PayPal's own offer call. Here the model proposed the wrong move once, and the owner's rule stopped it."

**CAPTION:** Model proposed counter. The owner's rule decided wait.

## 1:48 to 2:03 Do not trust us. Check it.

**[click]** Terminal: `python scripts\show_dispute.py PP-R-ISN-10198775`, then tab 3, **Receipt verifier**: the two receipts, same dispute id, Verify. Then edit one character of a log and verify again: it fails.

**TAG:** Verified in your browser

**SAY:** "Two signed receipts, one from each side, the same dispute id. Verify them offline. Change one line and the chain breaks."

**CAPTION:** Two receipts, one dispute id. Change one line, the chain breaks.

## 2:03 to 2:33 All ten cases, counted aloud

**[click]** Tab 2, ledger after the batch: stage filter, deadline countdown, CSV export. For the last 10 seconds overlay the table below (from `docs/RESULTS.md`).

**TAG:** Real PayPal sandbox run, batch of 10, read back from PayPal

**SAY:** "Ten cases on the real sandbox. Four settled at inquiry, before a claim, in twenty four to sixty two minutes in PayPal's timestamps. Three answered with proof and are under PayPal review. Two are waiting for the merchant owner. One was refused by the buyer's mandate: twenty dollars claimed on a nine dollar order. PayPal moved four cases to chargeback once tracking was on the order. Zero double refunds."

**CAPTION:** 4 settled, 3 under PayPal review, 2 awaiting the owner, 1 refused by the mandate

Overlay table:

| | Agent using PayPal's Agent Toolkit directly | Clearwake |
| --- | --- | --- |
| Overpaid, 200 episodes | USD 2,633.25 | USD 0.00 |
| Double refunds | 61 | 0 |
| Wrongly accepted claims | 160 | 0 |
| Episodes ended as the owner intended | 40 of 200 | 200 of 200 |
| Real sandbox batch of 10 | not run | 4 settled at INQUIRY, 0 double refunds |

## 2:33 to 2:55 End card: numbers, one command, links

**[click]** Console in the browser at the Render link, then the GitHub page, then a terminal showing the one clone command. End card: three numbers and the command.

**TAG:** Verified in your browser

**SAY:** "Four of ten settled before a claim. Zero dollars overpaid against twenty six hundred. Zero double refunds against sixty one. One command runs it, or open the live console on Render. MIT, sandbox only, no real money."

**CAPTION:** 4 of 10 settled. USD 0.00 against USD 2,633.25. 0 against 61 double refunds. clearwake-console.onrender.com  github.com/Sriharsan/clearwake

## Notes

* Do not stage a step. If the sandbox shows a CAPTCHA or blocks the buyer's browser, record the owner doing that step by hand, say so in one sentence, and caption it "Real sandbox, buyer step done by hand". Never get past a CAPTCHA.
* The unguarded agent segment is a recorded comparison on the local PayPal layer; keep it under 20 seconds.
* The network cut (case m) and the broken receipt chain are extras if the cut leaves seconds to spare. Caption the cut "Real PayPal sandbox run, network isolated containers" and the chain "Verified in your browser".
* Keep to plain speech and the public text rules in the build brief.
