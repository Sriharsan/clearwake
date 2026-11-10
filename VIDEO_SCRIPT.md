# Clearwake demo video script (under 3 minutes, Sri speaks)

Record the browser and one terminal only. Speak in your own words; the lines below are a guide of about 330 words, which fits 2 minutes 50 seconds at a calm pace. Every shot gets one short caption that says how it ran: **Real sandbox**, **Injected fault in sandbox**, **Recorded sandbox run** or **Rehearsal**. Never caption a rehearsal shot as sandbox. Upload publicly to YouTube, no music, no third party logos. Do not call the hosted pages network isolated.

Placeholders in brackets (`[BATCH_SETTLED]` and so on) are numbers from the batch run; the lead fills them from `docs/RESULTS.md` before recording. Do not say a number that is still in brackets.

## Before recording

```
python -m clearwake --port 8810                 # console at http://127.0.0.1:8810/console
python scripts\cases.py                         # rehearsal: must print PASS for a to o
python scripts\airgap.py                        # case m: must print PASS (Docker running)
```

Have ready, in tabs: the console (tabs 1 Buyer agent, 2 Merchant control room, 3 Receipt verifier); PayPal's sandbox Resolution Center logged in as the sandbox buyer (log in by hand before recording; never show the login, the email or any key); the AG Grid ledger after the batch; a terminal with `python scripts\show_dispute.py [HERO_DISPUTE_ID]` typed for the settled dispute; the public site Verify page. Do not show `.env` or the PayPal developer credentials page.

## Shots

| Time | Show | Say | Caption |
| --- | --- | --- | --- |
| 0:00 | Console, **Buyer agent**: the request "three A5 notebooks", the mandate check passing, the signed mandate receipt | "An AI agent just bought a parcel for its owner: three notebooks, inside a budget the owner signed. The purchase is a signed receipt linked to the PayPal order." | Real sandbox order, receipt signed offline |
| 0:20 | PayPal sandbox Resolution Center: the buyer agent opens the dispute, "Only 2 of 3 notebooks arrived" | "One notebook is missing. The buyer's own agent opens the dispute in PayPal's Resolution Center. The owner is not asked." | Real sandbox, buyer agent through a local browser |
| 0:40 | Console, **Merchant control room**: the dispute row in the AG Grid ledger, stage INQUIRY, the model's proposal next to the policy decision, the dispatch proof "3 of 3 counted, sealed, tracking shipped" | "The merchant's agent reads the message. A local model proposes. The policy file decides, and code checks every amount. It checks its dispatch proof: three counted at packing, sealed, shipped. It offers a refund inside the owner's limit through PayPal's own message and offer calls." | Real sandbox. Local model `[MODEL_NAME]`; the policy decides |
| 1:10 | Buyer agent step: the offer is read, the dispute rule ("accept any refund of 80 percent or more for a missing item") is applied, the buyer accepts | "The buyer's agent compares the offer with the rule its owner signed, and accepts." | Real sandbox, within the buyer's signed rule |
| 1:25 | Terminal: `python scripts\show_dispute.py [HERO_DISPUTE_ID]`, PayPal's record: status RESOLVED, stage INQUIRY, fee line | "PayPal's own record now reads resolved, at the inquiry stage. No claim, no dispute fee. Clearwake says settled only when PayPal says it." | Real sandbox, read from PayPal's record |
| 1:45 | AG Grid ledger after the batch: filter by stage, the countdown cells, the CSV export button | "That was one. Here are ten, bought and disputed by the same agent: [BATCH_SETTLED] settled with no fee, [BATCH_EVIDENCE] answered with evidence, [BATCH_ESCALATED] sent to the owner, [BATCH_REFUNDS] refunds confirmed by PayPal's record, [BATCH_SECONDS_PER_CASE] seconds a case." | Real sandbox batch of [BATCH_TOTAL], ledger as read from PayPal |
| 2:05 | Terminal running `python scripts\airgap.py`: boundary lines, "network cut", held lines, "network restored", the PASS line with the refund ids | "I pull the cable in the middle of a batch. Nothing moves while it is offline. On reconnect PayPal is read first, and there is no duplicate." | Real sandbox, network isolated containers |
| 2:25 | Public site, **Verify** on the case m receipts, then change one line and verify again (it fails) | "Every step is a signed receipt. Change one line, and the chain breaks. This runs in the browser, with nothing uploaded." | Recorded sandbox run, verified in this browser |
| 2:40 | The Render URL in the address bar, the console loading, then the repository link | "The console is live on Render, labelled hosted, not network isolated. Run one negotiation yourself. The code is MIT on GitHub, sandbox only, no real money." | Hosted on Render, not network isolated |

## Notes

* Total is about 2 minutes 50 seconds. If a take runs long, cut the filter and CSV words at 1:45 first, then the second sentence at 2:25.
* If the buyer step could not run for real on the day (the sandbox showed a CAPTCHA or blocked the browser), do not stage it: record the owner doing that step by hand, say so in one sentence, and caption it "Real sandbox, buyer step done by hand". Never get past a CAPTCHA.
* Case m uses scripted rules for the refund decisions; a local model drafts inside the boundary. If you mention it, say "a local model drafts inside the boundary".
* The public site shows a recorded sandbox run. Caption it "Recorded sandbox run, 31 Oct", never live.
* Keep to plain speech and the public text rules in the build brief.
