# Clearwake local run

Everything in this local run is **local**: a local payment provider, local records and no network or model calls. The page shows "Local run" and "Local gateway · no PayPal calls". Target length: under 3 minutes (under 2 for hackathon cuts).

## Setup once

```powershell
cd "D:\my startup\clearwake"
git submodule update --init --recursive
py -3.12 -m venv .venv
```

No package install is needed. Check all four cases before recording:

```powershell
.\scripts\check_run.ps1
```

It prints PASS or FAIL for each step below and exits non zero on any FAIL.

## The four steps

### 1. A refund under the limit succeeds and is checked against the record

```powershell
.\run.ps1
```

Opens http://127.0.0.1:8810 on a fresh case.

1. Click **Create a workroom**. Your name: `Sri`. Workroom name: `Local refund`. Click **Create workroom**.
2. Point at the top right badge: **Local run**, and the payment card badge **Local gateway · no PayPal calls**.
3. Scroll to **The team**. Click **▶ Run specialists**. Product and Engineering finish in parallel, then Support.
4. In **Outcome** on the right, tick **Allow artifact publication**, then click **Publish verified artifact**. Say: publishing a plan does not allow a payment.
5. Scroll up to **Payment operations**. Tick **I approve one sandbox refund of USD 1.00 …**. Click **Grant exact refund**.
6. Click **Simulate one refund**. Provider outcome shows it was sent but not yet verified.
7. Click **Check provider record**. Show the rows: amount matched, matched reserved identity, **COMPLETED**, final outcome **Verified from provider record**.

### 2. The provider response is lost. The refund goes to UNKNOWN and is not retried

Stop the server (Ctrl+C), then:

```powershell
.\run.ps1 -Outcome lost-response
```

1. Repeat clicks 1 to 5 from step 1.
2. Click **Simulate one refund**. The provider recorded the refund but its reply was lost. **Provider outcome** shows **unknown** and the page says the request identity stays held until a known provider record is checked.
3. Point at **Simulate one refund**: it is now disabled. Nothing can be resent from here, and the server refuses a second send for the same capture (`check_run.ps1` step 2 checks this).

### 3. Reconciliation resolves the UNKNOWN to its true state

Keep the step 2 server running. In a second terminal, read the local provider's own record (the local run folder is printed when `run.ps1` starts, as `data\local-lost-response-<time>`):

```powershell
.\.venv\Scripts\python.exe scripts\show_provider_record.py data\local-lost-response-<time>
```

1. Copy the printed refund ID into **Known provider refund ID**.
2. Click **Check provider record**. UNKNOWN becomes **Verified from provider record**. Say: this is a read only check, it never resends the refund.

### 4. An over limit refund is refused before any money moves

The case is fixed at USD 1.00 with a hard cap of USD 5.00. The page has no way to type another amount, so show this step from the check:

```powershell
.\scripts\check_run.ps1
```

Point at line 4: a USD 6.00 case is refused at setup, a USD 6.00 send is refused, and nothing is reserved or sent.

## Recording notes

* Record the browser window and one terminal only. Close other tabs.
* Do not show `.env` files, the database files or any real account.
* Narration is added later. Leave a one second pause after each click.
