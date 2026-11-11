# Postman collection: every PayPal call Clearwake makes

Files: `postman/clearwake-paypal.postman_collection.json` (29 requests in five folders: 18 PayPal sandbox requests and 11 requests against the local console) and `postman/sandbox.environment.template.json` (no secrets: `client_id` and `client_secret` are empty).

| Folder | Requests |
| --- | --- |
| 0 Authentication | OAuth client credentials token |
| 1 Orders (Orders v2) | create order (PayPal wallet), create order (sandbox test card), get order, capture order, add tracking |
| 2 Payments v2 | get capture, refund capture, get refund |
| 3 Disputes v1 | list, get, send message, make offer, provide evidence, provide supporting info, accept claim, adjudicate (sandbox only), get again |
| 4 Attack suite (local console) | health, session cookie and CSRF token, six refused attacks, negotiate, read the negotiation steps, receipts |

Each request carries tests on PayPal's response: status code, id shape, status values, USD amounts with two decimals, the `up` link of a refund, the actions PayPal offers on a dispute. POSTs send a fresh `PayPal-Request-Id`, as Clearwake does. The collection refuses any `base_url` other than `https://api-m.sandbox.paypal.com`.

## Checked offline

```sh
python postman/check_collection.py
```

It checks the Postman v2.1 structure, that every PayPal request stays on `{{base_url}}` and every attack request on `{{console_url}}`, that every request has tests, that all 42 scripts compile with Node, that every PayPal route in `clearwake/paypal.py` has a request, and that the environment holds no secret. It does not call PayPal.

## Run it in Newman

Newman runs from `npx -y newman` (no install step). Copy `postman/sandbox.environment.template.json` to `postman/sandbox.environment.local.json`, fill `client_id`, `client_secret` and `capture_id` there (that file is kept out of git), then:

```sh
npx -y newman run postman/clearwake-readonly.postman_collection.json -e postman/sandbox.environment.local.json
```

`postman/clearwake-readonly.postman_collection.json` holds only the three requests that change nothing at PayPal: token, List disputes, Get dispute. The full collection also holds create order, capture, refund, send message, make offer, evidence, tracking and adjudicate; run those only on purpose, one folder at a time. Folder 3 needs an open dispute opened by the sandbox buyer; Capture order needs an approved order. Neither can be created by API for this app.

## Run of 11 Nov

Real run against `https://api-m.sandbox.paypal.com`, read only requests, newman cli and json reporters. The saved report is `docs/postman-run-2026-11-11.json`: names, status codes, assertions and timings only. Request bodies, Authorization headers and the access token are removed.

| Request | Status | Assertions passed | Response ms |
| --- | --- | --- | --- |
| Get access token | 200 | 6 of 6 | 1261 |
| List disputes | 200 | 5 of 5 | 447 |
| Get dispute | 200 | 9 of 9 | 1735 |
| Total | 3 requests, 0 failed | 20 of 20, 0 failed | run 3.9 s, average 1148 |

The first run of the same three requests passed 19 of 20: the USD amount test used a regex with a doubled backslash (`\.`), so PayPal's `9.00` did not match. That was a mistake in the test, not in PayPal's answer. It is fixed in both collections (four places) and the run above is the run after the fix. Not run, on purpose: create order (two), get order, capture order, add tracking, get capture, refund capture, get refund, send message, make offer, provide evidence, provide supporting info, accept claim, adjudicate, get dispute again. They create or change sandbox state, or need an approved order.

## Attack suite against the local console

Folder 4 replays the Break it attacks against the local console only. It needs no PayPal keys and no environment file. A judge runs:

```sh
python -m clearwake --port 8810
npx -y newman run postman/clearwake-paypal.postman_collection.json --folder "4 Attack suite (local console)"
```

The 11 requests: health check, session (HttpOnly SameSite=Strict cookie scoped to /console and a 64 hex CSRF token), negotiate with no token (403), with a forged token (403), from a foreign Origin (403), flagged cross-site (403), an unknown action (404), a path traversal to `.env` (refused, no key names in the answer), negotiate with cookie and token (200), read the negotiation steps after a 6 s wait (decision, offer, settlement; the first settlement step is a recorded lost response and the last step succeeds), and the receipts (no private key or token). Every response is also checked for the security headers and the content security policy. The collection pre-request script refuses any `console_url` that is not `http://127.0.0.1` or `localhost`, so the suite cannot be pointed at a hosted site. To use another local port, add `--env-var console_url=http://127.0.0.1:8845`.

Run on 11 Nov on a local console (port 8845, scripted model, no Ollama call): 11 requests, 75 assertions, 0 failed, run time 7.0 s, average response 10 ms.

With the Postman CLI the same run is `postman login`, then `postman collection run postman/clearwake-readonly.postman_collection.json -e postman/sandbox.environment.local.json`.
