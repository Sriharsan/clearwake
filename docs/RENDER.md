# Render: host the live console

Label on the page and in every answer: **hosted on Render, not network isolated.** The network isolated run (`python scripts/airgap.py`, case m) stays the local proof.

Files: `render.yaml` (Blueprint) and `Dockerfile.render`. Neither holds a secret. `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` are declared with `sync: false`, so Render asks for them in its dashboard and they live only there.

## What the hosted console does

| Setting | Value | Why |
| --- | --- | --- |
| `CLEARWAKE_HOSTED` | `1` | Hosted mode in `clearwake/server.py`: the Render host is allowed by name (`RENDER_EXTERNAL_HOSTNAME`, set by Render), cookies get `Secure`, every client address is rate limited, and Reset deletes earlier run folders |
| `CLEARWAKE_RATE_READ`, `CLEARWAKE_RATE_WRITE` | `120`, `20` per minute per address | Reads are page loads and polling; a write runs a purchase or a case. A refused request gets 429 with `Retry-After` |
| `CLEARWAKE_SANDBOX_ACK`, `PAYPAL_BASE_URL` | `I_CONFIRM_SANDBOX_ONLY`, `https://api-m.sandbox.paypal.com` | The PayPal gateway refuses to start without both, and refuses any other base URL |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | set in the dashboard | Sandbox app keys only |
| Reset | the console's Reset button, `POST /console/api/reset` | Starts a clean run so the next judge sees an empty ledger |

## Two code items to settle before the deploy (lead and agent C)

Found while writing the Blueprint on 9 November 2026. Without them the Render service will not start or will not reach PayPal.

1. **Binding.** `vendor/relayloom/relayloom/server.py` `LocalServer` refuses any address other than loopback, and `clearwake/__main__.py` has no `--host` flag. Render needs the process to listen on `0.0.0.0` and `$PORT`. `Dockerfile.render` already calls `python -m clearwake --host 0.0.0.0 --port ${PORT:-10000}`; that flag has to exist and hosted mode has to be the only way it is accepted (`CLEARWAKE_HOSTED=1`). The pinned Relayloom check cannot be edited in the submodule, so `ClearwakeServer` has to bind without calling it.
2. **Sandbox on the hosted console.** `clearwake/console.py` runs on the rehearsal gateway today. The keys in Render are used only once the hosted console builds a `SandboxGateway.from_environment()`. Until then the hosted console is a rehearsal and must say so in its one mode line. Do not say "against the PayPal sandbox" on the page or in the Devpost answers until a hosted case has really read a PayPal record.

## Steps for Sri (needs Sri's Render login)

1. Sign in to https://dashboard.render.com (GitHub sign in is simplest).
2. New, then Blueprint. Connect the public repository `Sriharsan/clearwake`, branch `main`. Render finds `render.yaml` and shows one web service, `clearwake-console`.
3. Render asks for the two values marked `sync: false`. Paste the sandbox client id and the sandbox secret from your own PayPal developer dashboard (Apps and credentials, Sandbox). Type them in the Render page yourself. Do not put them in any file or message.
4. Apply. The first build takes a few minutes. It clones the two pinned submodules with the repository and the Dockerfile fails the build if they are missing.
5. Copy the service URL, for example `https://clearwake-console.onrender.com` (Render adds a suffix if the name is taken). Put it in `[RENDER_URL]` in `docs/DEVPOST_FORM.md`, `README.md`, `SUBMISSION_PAYPAL.md`, `VIDEO_SCRIPT.md` and `D:\paypal hackathon\DEVPOST_ENTRY.md`, and in the OpenAPI `servers` entry.
6. Check from a fresh browser window (no cookies): open `<URL>/console`, buy an item, run case n, open the dispute ledger, press Reset. Open the browser developer tools Network tab and confirm the `Set-Cookie` of `/console/api/session` carries `Secure` and `HttpOnly`.
7. Check the rate limit once: press Run case more than 20 times in a minute; the 21st reply must be 429 with a `Retry-After` header.
8. Free web services on Render spin down after a period without traffic and take a short time to wake. Open the URL a minute before a judge or a recording needs it, or pick a paid plan in the dashboard for the judging weeks (1 to 15 December).
9. If a custom domain is added, set `CLEARWAKE_ALLOWED_HOSTS` to that host name (comma separated for several) in the Render dashboard. Requests with any other `Host` are refused.

## Why Render, in one line

Judges run one agent to agent negotiation in a browser against a public URL, and watch the AG Grid ledger update. That is what the Render prize asks for and what the Best Demo Delivery criterion needs.
