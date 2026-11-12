# Clearwake video: dialogue script (2:42, under the 2:45 limit, Sri speaks, captions on)

**When an AI agent buys something and it never arrives, Clearwake lets the buyer's agent and the seller's agent settle it inside PayPal within an hour, with proof, before it becomes a claim or a fee, and nothing is paid twice.**

**When an agent's order goes missing, agents fix it.**

**Real PayPal sandbox run, 11 and 12 November 2026.** 10 orders bought by an agent, 10 item not received claims. 5 resolved inside PayPal, 4 of them at INQUIRY with no fee. 4 answered with proof, under PayPal review. 1 refused by the buyer agent's mandate before it was filed with PayPal. USD 0.00 overpaid against USD 2,633.25 for an agent on the PayPal Agent Toolkit alone.

This file matches the real footage. The nine clips are in `D:\paypal hackathon\video\`, one file per scene, screen only, no narration, product sounds and the two Sarvam Bulbul voices kept. `timing.json` there lists every clip with its slot and Sri's line. Sri speaks the narration over the clips in his own words; the lines below are a draft, and he decides the final cut, any face or phone footage and every video choice.

Shape, from the winning videos: the real result is on screen in the first frame, no title card. The bad outcome comes first, the same action stopped second, the key number spoken while its proof is on screen. Every shot carries a tag that says how it ran. Hold each proof screen and cut at the end of a sentence.

Every number comes from a run file: `data/runs/batch-sandbox-20261111-132948.json` (the batch), `data/runs/voice-decisions-20261112.json` (the two voice decisions), `data/runs/settle-times-20261111.json` (settle times), `data/runs/baseline-20261110-172506.json` (the 200 episodes). Do not say a number that is not in those files.

## Clips and slots (total 2:42)

| Scene | Slot | File | Length | Tag |
| --- | --- | --- | --- | --- |
| 01 | 0:00 to 0:12 | scene-01-real-result.mp4 | 12 s | Real PayPal sandbox run, case 3 |
| 02 | 0:12 to 0:23 | scene-02-claim-and-bad-outcome.mp4 | 11 s | Planted failure, local run, PayPal Agent Toolkit |
| 03 | 0:23 to 0:35 | scene-03-same-action-stopped.mp4 | 12 s | Planted failure, same faults, same layer |
| 04 | 0:35 to 1:00 | scene-04-rules-by-voice.mp4 | 25 s | Rules said by the owner, Sarvam voice |
| 05 | 1:00 to 1:22 | scene-05-anatomy.mp4 | 22 s | Real PayPal sandbox run, case 3 |
| 06 | 1:22 to 1:58 | scene-06-two-agents-settle.mp4 | 36 s | Real PayPal sandbox run, two voice decisions |
| 07 | 1:58 to 2:10 | scene-07-verify-it.mp4 | 12 s | Verified in your browser |
| 08 | 2:10 to 2:30 | scene-08-ten-cases.mp4 | 20 s | Real PayPal sandbox run, read back from PayPal |
| 09 | 2:30 to 2:42 | scene-09-end-card.mp4 | 11 s | Verified in your browser |

## 0:00 to 0:12 The real result, first frame

PayPal's record of case 3 on screen from the first frame: RESOLVED at INQUIRY, USD 5.00.

**SAY:** "An AI agent bought something. It never arrived. Five dollars. PayPal's own record reads resolved, at the inquiry stage."

**CAPTION:** PayPal's record: RESOLVED at INQUIRY

## 0:12 to 0:23 The claim, then the bad outcome

The Break it page, the lost response attack on the unguarded agent: the response is lost, the agent retries, the customer is paid twice.

**SAY:** "When an agent buys and it never arrives, a lost response makes the agent retry, and the customer is paid twice. Over two hundred episodes on the Agent Toolkit alone: twenty six hundred and thirty three dollars overpaid, sixty one double refunds."

**CAPTION:** 200 episodes: USD 2,633.25 overpaid, 61 double refunds

## 0:23 to 0:35 The same action, stopped

Break it again, an over limit request through the guard: zero paid, held for a person, the signed receipts below.

**SAY:** "Same faults through Clearwake. Zero dollars overpaid. Zero double refunds. The injected message is refused before any PayPal call."

**CAPTION:** Clearwake: USD 0.00 overpaid, 0 double refunds, 200 of 200 as the owner intended

## 0:35 to 1:00 Rules said once, by voice

The voice page: the owner's voice (label "Owner's voice: Sarvam Bulbul") says "Refund anything under 5 US dollars that has not arrived in 10 days. Ask me above that. Never refund twice." Sarvam Saaras hears it, the words show on screen, Clearwake reads the rules back in plain words, the owner presses Yes, and Clearwake's reply plays in its own voice (label "Clearwake's voice: Sarvam Bulbul"). The page shows source: voice and the policy hash.

If Sri wants his own voice here, he records the first 5 seconds on his phone and cuts it in over the opening of this clip.

**SAY:** "I say the rule once, out loud. The system reads it back in plain words. I say yes, and it is signed. The model can propose anything now. It can never go past this."

**CAPTION:** Under USD 5.00, settle. Above that, ask me. Never refund twice.

## 1:00 to 1:22 Anatomy: one dispute, six layers

The Proof page, the exploded view: one dispute, case 3, through the six layers, then the layer switch to the receipts and to PayPal's record.

**SAY:** "One dispute, six layers. The owner's rule, said once and signed. The buyer's agent files the claim and cannot pay itself. The merchant's agent answers with proof. The policy gate checks every action before money moves. Signed receipts chain each step to the one before. And PayPal's record is the judge."

**CAPTION:** Settled inside PayPal. Paid once. USD 5.00.

## 1:22 to 1:58 Two real decisions by voice

Real PayPal sandbox, run once on 12 November 2026, three parts in one clip.

* **1:22 to 1:30.** The owner's voice says "Approve case 4". Case 4 is a chargeback under review, so PayPal allows only accept claim with a refund; no offer is possible and none is sent. The decision runs through the signed policy and the approval record.
* **1:30 to 1:38.** PayPal's record read back: RESOLVED at CHARGEBACK, one refund of USD 5.00, written once, with a USD 0.77 settlement fee. PayPal still showed UNDER_REVIEW for the first 9 reads over 56 seconds; the agent did not resend, it read the record again. That wait is cut from the clip and is in the raw take.
* **1:38 to 1:58.** The owner's voice says "Don't pay case 9, send the proof". No money moves. A sandbox test tracking number goes on the order, the proof goes to the dispute once, and PayPal's record reads UNDER_REVIEW at INQUIRY.

**SAY:** "Two commands by voice, through the signed policy and an approval record. Approve case 4: one refund of five dollars, written once, PayPal's record reads resolved. Don't pay case 9, send the proof: no money moves, the proof is in, PayPal has it under review. Every receipt says the command came by voice, and which voice."

**CAPTION:** Case 4 RESOLVED, USD 5.00, written once. Case 9 proof sent, no money moved.

## 1:58 to 2:10 Do not trust us. Check it.

Home page: the Verify button runs on load and checks every signed log in the browser. Hold on the result.

**SAY:** "Signed receipts, one from each side, the same dispute id. Verified here, in this browser. Change one line and the chain breaks."

**CAPTION:** Verified in your browser. Change one line, the chain breaks.

## 2:10 to 2:30 All ten cases, counted aloud

The Control Room: the counted tally, the ten case cards, the dispute ledger with its stage filter.

**SAY:** "Ten orders on the real sandbox, ten claims. Five resolved inside PayPal, four of them at inquiry with no fee. Four answered with proof and under PayPal review. None waiting for the owner. One was refused by the buyer's mandate before it was filed: twenty dollars claimed on a nine dollar order. Zero double refunds."

**CAPTION:** 5 of 10 resolved, 4 answered with proof, 1 refused by the mandate

| | Agent using PayPal's Agent Toolkit directly | Clearwake |
| --- | --- | --- |
| Overpaid, 200 episodes | USD 2,633.25 | USD 0.00 |
| Double refunds | 61 | 0 |
| Wrongly accepted claims | 160 | 0 |
| Episodes ended as the owner intended | 40 of 200 | 200 of 200 |

## 2:30 to 2:42 End card

Three numbers, one command, the links.

**SAY:** "Zero dollars overpaid against twenty six hundred. Zero double refunds against sixty one. One command runs it, or open the live console. MIT, sandbox only, no real money."

**CAPTION:** USD 0.00 against USD 2,633.25. 0 against 61 double refunds. clearwake-console.onrender.com  github.com/Sriharsan/clearwake

## Notes

* Sarvam Bulbul speaks both voices inside the product (owner Kabir, Clearwake Advait); Sarvam Saaras v4 hears the owner. The on screen label "Owner's voice: Sarvam Bulbul" shows whenever the owner voice plays. Browser speech stays as the fallback.
* Case 7 stays a refusal: the buyer agent claimed USD 20.00 on a USD 9.00 order and its mandate stopped it before it was filed with PayPal, so PayPal has no record of it. It is counted in the ten as refused, never as resolved.
* No sign in, email or key is on any clip. Never show `.env`.
* Scenes 01 to 05 and 07 to 09 are trimmed from the end of their recordings; the untrimmed takes are in `video\_work\full`.
