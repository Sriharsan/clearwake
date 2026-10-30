# Clearwake demo video script (under 3 minutes)

Record the browser and one terminal only. Use **Rehearsal** captions for rehearsal shots and **PayPal sandbox** captions only for shots that really ran against the sandbox. Upload publicly to YouTube with no music or third party logos.

Before recording, run once and keep both terminals ready:
```
.\scripts\check_demo.ps1        # rehearsal: must print 4 PASS
.\scripts\check_sandbox.ps1     # sandbox: must print 4 PASS (needs keys and setup)
```

| Time | Show | Exact clicks or command | On screen caption |
| --- | --- | --- | --- |
| 0:00 | Title card, then the empty workroom | `.\demo.ps1` opens http://127.0.0.1:8810 | "An AI agent saying a refund is done is not a receipt." |
| 0:15 | Refund under the limit, checked against the record | **Create a workroom** (name `Sri`), **Run specialists**, tick **Allow artifact publication**, **Publish verified artifact**, tick the approval sentence, **Grant exact refund**, **Simulate one refund**, **Check provider record**. Point at the gauge (USD 1.00 of USD 5.00), the approval record line and the timeline ending in **Settled** | "Rehearsal, invented records. Owner approves one exact amount. Settled only when the provider record matches." |
| 0:35 | The same case against PayPal | Terminal: `.\scripts\check_sandbox.ps1`, show line **a. PASS** with the sandbox refund ID | "PayPal sandbox. A real USD 1.00 sandbox refund, checked against PayPal's refund record." |
| 0:45 | Lost response goes to UNKNOWN | Stop the server, run `.\demo.ps1 -Outcome lost-response`, repeat the clicks up to **Simulate one refund**. Point at the pulsing **UNKNOWN** node and the disabled send button | "Rehearsal. The provider recorded the refund but the reply was lost. Held as UNKNOWN. Not retried." |
| 1:10 | The sandbox version | Terminal: line **b. PASS** (`sandbox refund POSTs=1`) | "PayPal sandbox, injected fault: the real refund was sent, its reply withheld. One POST only." |
| 1:20 | Reconciliation resolves it | Second terminal: `.\.venv\Scripts\python.exe scripts\show_provider_record.py data\demo-lost-response-<time>`, paste the ID, **Check provider record**. The UNKNOWN node turns into **Response lost, resolved** and **Settled** | "Rehearsal. A read only check of the provider record. Nothing is resent." |
| 1:40 | The sandbox version | Terminal: line **c. PASS** | "PayPal sandbox. UNKNOWN resolved by reading PayPal's refund record." |
| 1:50 | Over limit refused | Terminal: line **d. PASS** (USD 6.00 refused at setup and at send) | "Refused before any money moves. The limit lives in policy/autonomy.json, not in a prompt." |
| 2:10 | Autonomy levels | Point at the strip: Draft, Execute with Approval, Execute within Limits | "Autonomy where it is safe. Approval where it matters. Proof after every action." |
| 2:20 | What is real | Show SUBMISSION_PAYPAL.md "What ran" table | "Sandbox: what ran against PayPal. Rehearsal: invented records. Next: more providers and payouts." |
| 2:45 | Repo link | https://github.com/Sriharsan/clearwake | "MIT. One command to run." |

If the sandbox check has not passed yet, cut the 0:35, 1:10 and 1:40 shots and say "sandbox run pending" rather than showing rehearsal as sandbox.
