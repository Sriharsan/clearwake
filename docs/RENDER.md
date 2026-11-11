# Render: host the live console

Label on the page and in every answer: **hosted on Render, not network isolated.** The network isolated run (`python scripts/airgap.py`, case m) stays the local proof.

Files: `render.yaml` (Blueprint) and `Dockerfile.render`. Neither holds a secret, and the hosted console needs no PayPal key: it runs on the local provider and calls no PayPal API.

## What the hosted console does

| Setting | Value | Why |
| --- | --- | --- |
| `CLEARWAKE_HOSTED` | `1` | Hosted mode in `clearwake/server.py`: the Render host is allowed by name (`RENDER_EXTERNAL_HOSTNAME`, set by Render), cookies get `Secure`, every client address is rate limited, and Reset deletes earlier run folders |
| `CLEARWAKE_RATE_READ`, `CLEARWAKE_RATE_WRITE` | `120`, `20` per minute per address | Reads are page loads and polling; a write runs a purchase or a case. A refused request gets 429 with `Retry-After` |
| `CLEARWAKE_SANDBOX_ACK`, `PAYPAL_BASE_URL` | `I_CONFIRM_SANDBOX_ONLY`, `https://api-m.sandbox.paypal.com` | The PayPal gateway refuses to start without both, and refuses any other base URL |
| PayPal keys | none | The hosted console never calls PayPal. The real sandbox runs are recorded in the ledger |
| Reset | the console's Reset button, `POST /console/api/reset` | Starts a clean run so the next judge sees an empty ledger |

## What the hosted console is

It binds to `0.0.0.0` and `$PORT` through `python -m clearwake --host 0.0.0.0` and only with `CLEARWAKE_HOSTED=1`. It is a local run on the local provider, with the recorded sandbox runs in the ledger. The page says so in its one mode line, and the Devpost text does not say it ran against the PayPal sandbox.

## Steps for Sri (needs Sri's Render login)

1. Sign in to https://dashboard.render.com (GitHub sign in is simplest).
2. New, then Blueprint. Connect the public repository `Sriharsan/clearwake`, branch `main`. Render finds `render.yaml` and shows one web service, `clearwake-console`.
3. Render asks for no secret. Do not add PayPal keys to the service.
4. Apply. The first build takes a few minutes. It clones the two pinned submodules with the repository and the Dockerfile fails the build if they are missing.
5. Copy the service URL. `scripts/fill_placeholders.py` already writes `https://clearwake-console.onrender.com` for `RENDER_URL` in every file. If Render adds a suffix because the name was taken, change `RENDER_URL` in that script and in the OpenAPI `servers` entry, then run `python scripts/fill_placeholders.py --apply`.
6. Check from a fresh browser window (no cookies): open `<URL>/console`, buy an item, run case n, open the dispute ledger, press Reset. Open the browser developer tools Network tab and confirm the `Set-Cookie` of `/console/api/session` carries `Secure` and `HttpOnly`.
7. Check the rate limit once: press Run case more than 20 times in a minute; the 21st reply must be 429 with a `Retry-After` header.
8. Free web services on Render spin down after a period without traffic and take a short time to wake. See the hosted console note below.
9. If a custom domain is added, set `CLEARWAKE_ALLOWED_HOSTS` to that host name (comma separated for several) in the Render dashboard. Requests with any other `Host` are refused.

## Why Render, in one line

Judges run one agent to agent negotiation in a browser against a public URL, and watch the AG Grid ledger update. That is what the Render prize asks for and what the Best Demo Delivery criterion needs.

## Hosted console note: keep it alive from 1 to 15 December

Judging runs from 1 to 15 December and winners are announced about 21 December. The hosted console has to answer for the whole window, and the form's rules ask that hosted projects and any test access stay active until winners are announced.

* **The service must stay up.** Do not delete, rename or suspend `clearwake-console` in the Render dashboard before 21 December, and do not push a build after the freeze.
* **Free instances sleep.** Render spins a free web service down after a period without traffic (about 15 minutes) and the next request waits while it starts. A judge who meets a cold start may leave.
* **The keep-warm line.** Ping the health check every 10 minutes from any scheduler that you control, for example a scheduled task on a machine that stays on, or a free uptime monitor: `curl -fsS https://clearwake-console.onrender.com/healthz`. `/healthz` returns no data, skips the origin check and is never rate limited, so the ping cannot use up a judge's quota. Alternatively set a paid plan in the dashboard for the judging window.
* **Nothing expires.** The hosted console uses no PayPal token and holds no key, so there is no sandbox token to refresh and no secret to rotate. PayPal's sandbox tokens last about nine hours; this service never asks for one.
* **To restart.** Render dashboard, service `clearwake-console`, then Manual Deploy with Clear build cache and deploy latest commit, or Restart service. Then open `/healthz` (it answers when the process is up), open `/console`, press Reset, and run one case. Reset also deletes earlier run folders, so do it after a restart and not during a judge's session.
* **Check once a day** from a fresh browser window with no cookies: `/healthz`, `/console`, one case, the ledger, the receipt verifier.
