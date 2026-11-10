# Postman collection: every PayPal call Clearwake makes

Files: `postman/clearwake-paypal.postman_collection.json` (18 requests in four folders) and `postman/sandbox.environment.template.json` (no secrets: `client_id` and `client_secret` are empty).

| Folder | Requests |
| --- | --- |
| 0 Authentication | OAuth client credentials token |
| 1 Orders (Orders v2) | create order (PayPal wallet), create order (sandbox test card), get order, capture order, add tracking |
| 2 Payments v2 | get capture, refund capture, get refund |
| 3 Disputes v1 | list, get, send message, make offer, provide evidence, provide supporting info, accept claim, adjudicate (sandbox only), get again |

Each request carries tests on PayPal's response: status code, id shape, status values, USD amounts with two decimals, the `up` link of a refund, the actions PayPal offers on a dispute. POSTs send a fresh `PayPal-Request-Id`, as Clearwake does. The collection refuses any `base_url` other than `https://api-m.sandbox.paypal.com`.

## Checked offline

```sh
python postman/check_collection.py
```

It checks the Postman v2.1 structure, that every request stays on `{{base_url}}`, that every request has tests, that all 30 scripts compile with Node, that every PayPal route in `clearwake/paypal.py` has a request, and that the environment holds no secret. It does not call PayPal.

## Run it in Newman or the Postman CLI

Neither the Postman CLI (`postman`) nor Newman was installed on the build machine on 9 November 2026 (`npx --no-install newman --version` reported the package missing), and nothing was installed. The tests have therefore not been run against the sandbox yet. Sri runs this once, with his own sandbox keys. Copy `postman/sandbox.environment.template.json` to `postman/sandbox.environment.local.json`, fill `client_id`, `client_secret` and `capture_id` there (that file is kept out of git), then:

```sh
npx newman run postman/clearwake-paypal.postman_collection.json -e postman/sandbox.environment.local.json --folder "0 Authentication" --folder "2 Payments v2 (capture and refund)"
```

With the Postman CLI the same run is `postman login`, then `postman collection run postman/clearwake-paypal.postman_collection.json -e postman/sandbox.environment.local.json`.

State the folders need: an approved order before Capture order, and an open dispute opened by the sandbox buyer for folder 3. Neither can be created by API for this app. Write the run result (requests, assertions, failures) in `docs/RESULTS.md` only after it has happened.
