# Clearwake demo video script (under 3 minutes)

Record the browser and one terminal only. Every shot gets a caption that says how it ran: **Real sandbox**, **Injected fault in sandbox**, **Rehearsal**, **Rehearsal, buyer step simulated** or **Scripted, not AI**. Never caption a rehearsal shot as sandbox. Upload publicly to YouTube with no music and no third party logos. Do not call the hosted site air gapped.

Screen names below match the console at `/console` (tabs **1 Buyer agent**, **2 Merchant control room**, **3 Receipt verifier**) as of 31 October.

## Before recording

```
python -m clearwake --port 8810                              # then open http://127.0.0.1:8810/console
python scripts\cases.py                                      # rehearsal: must print 14 PASS
python scripts\cases.py --sandbox                            # c, d, e must print PASS (keys in .env)
python scripts\airgap.py                                     # case m: must print PASS (Docker running)
```

If the sandbox buyer has opened a dispute at the INQUIRY stage (item not received, paid from the PayPal balance), also run `python scripts\cases.py --sandbox --only n --dispute <id>`, accept the offer as the sandbox buyer in the Resolution Center, and run it again. If it prints PASS with "real sandbox", use it at 0:25 with a **Real sandbox** caption. Otherwise use the rehearsal case n with **Rehearsal, buyer step simulated**.

## Shots

| Time | Show | Exact clicks or command | On screen caption |
| --- | --- | --- | --- |
| 0:00 | The dispute pile and the 1.5% line | **Merchant control room**, scroll to **Dispute ledger and fee leak**: the rate bar with the 1.50% line, the sales count, the ledger | "PayPal charges no dispute fee when a case is settled with the buyer before it becomes a claim. Above 1.5% and 100 sales, the fee doubles. PayPal Help Center help350; PayPal Merchant Fees, US." |
| 0:15 | Settled in conversation, inside the limit, PayPal's record confirms | **Run a rehearsal case**: case n. Point at the ledger row: stage INQUIRY, policy decision settle_by_offer next to the model's proposal, offer USD 2.50, PayPal record RESOLVED, "yes, no fee". Point at fee avoided USD 0.00 and say why | "Rehearsal, buyer step simulated. In the sandbox the buyer accepts in PayPal's Resolution Center. Settled, no fee only when PayPal's record says RESOLVED as an inquiry. Below USD 30 PayPal charges no Standard fee anyway, so nothing is counted as avoided." |
| 0:40 | A case worth fighting: evidence before the deadline | Terminal: the **i.** line for dispute `PP-R-SLI-10195419` from docs/SANDBOX_RUN.md (tracker from PayPal's order record, read back from PayPal). Then case k in the console: a near deadline dispute in the **Approval inbox** with its countdown | Terminal: "Real sandbox." Console: "Rehearsal. Close to the deadline, the owner decides." |
| 1:20 | Agent order disputed as unauthorised: the signed mandate verifies offline | **Run a rehearsal case**: case j. Point at the mandate receipt digest in the dispute. **Receipt verifier**: verify the buyer log | "Rehearsal dispute. The buyer agent's cart mandate, signed and linked to the PayPal order, verified offline." |
| 1:05 | Dispatch proof (about 15 seconds) | **Run a rehearsal case**: case o. Point at the ledger row: **Dispatch proof** "3 of 3 notebook-a5 counted, sealed, receipt ..., tracking shipped", policy decision fight_with_evidence, PayPal record UNDER_REVIEW. Then in the terminal `python scripts\dispatch.py show` for the signed receipt. When a real SAM count exists, show the photo with its numbered boxes and the model, device and time from the receipt | Rehearsal until a real SAM run exists: "Rehearsal. Scripted count, not SAM." After a real run: "Counted by SAM 3 on this machine, CPU, offline." |
| 1:45 | Cable pulled mid batch | Terminal running `python scripts\airgap.py`: the boundary lines (no route out, example.com 403), "network cut", the held lines, "network restored", the PASS line with the refund IDs | "Real sandbox, network isolated containers. Nothing moves while offline. On reconnect PayPal's record is read first. No duplicate." |
| 2:30 | Receipts verified with no network | The airgap output lines "receipts verified in a container with networking disabled". Then the public site's **Verify** on the case m receipts, then **Change one line, then verify** (fails) | "Checked with networking disabled, and in this browser. Nothing uploaded." |
| 2:50 | Close | Repo link https://github.com/Sriharsan/clearwake | "MIT. One command to run. Sandbox only, no real money." |

## Notes

* Do not show `.env`, the PayPal developer dashboard credentials page or any key.
* Case m uses scripted rules for the refund decisions; the local model drafts inside the boundary. Caption the drafting line "qwen2.5-coder:3b via Ollama, inside the boundary".
* The hosted site shows a recorded sandbox run. Caption it "Recorded sandbox run, 31 Oct", never live.
