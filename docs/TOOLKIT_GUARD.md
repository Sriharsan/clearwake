# A guard for agents that call PayPal's Agent Toolkit

One line of labelling: every number on this page is from the recorded run on the local PayPal layer (`data/runs/baseline-20261110-172506.json`, seed 20261110), not from the PayPal sandbox.

`clearwake/toolkit_guard.py` sits between an agent's tool calls and PayPal's Agent Toolkit tools. It is Clearwake's own code and it is not a PayPal product.

## Three lines

```python
from clearwake.toolkit_guard import guard
api = guard(paypal_tools, reader=paypal_reader)
api.accept_dispute_claim(dispute_id, note)
```

- `paypal_tools`: the object the agent already calls. An object with `accept_dispute_claim`, a `PayPalAPI` style object with `run(name, params)`, or a callable `(name, params)`.
- `paypal_reader`: reads PayPal's dispute record. A function `dispute_id -> record`, or an object with `.dispute()` and optionally `.capture()`. Without one, the guard calls the toolkit's own `get_dispute` through `run`.
- Optional: `policy=` (default `policy/merchant.yaml`), `receipts=` (a path or a `ReceiptLog`), `data_dir=` (where the ledger, approvals and signed receipts live).

Every other tool passes through unchanged. A call that the guard stops returns an `Outcome` with `state`, `detail`, `sent` and the receipt line.

## What it does

| Case on `docs/TOOLKIT_FAILURE_CASES.md` | What the guard does |
|---|---|
| e. Lost response, then a retry | One request id per money move, derived from the SHA-256 of its payload (tool, target, amount, currency). A durable ledger marks the move UNKNOWN when the answer is lost, and the next call reads PayPal's record first. A record that shows the claim accepted means nothing is sent again. A record that shows it was not applied means the same request id is sent again. The agent still sees the original error, as it would without the guard. |
| Duplicate delivery of the same case | Same payload hash, same ledger entry: nothing is sent, in any process that shares the data directory. |
| g. Amount above the limit | The amount is read from PayPal's record and checked with `decide()` against the signed policy. Above `accept_claim` max, it is refused and held for a person. Between the approval threshold and the limit, a person approves that exact move. |
| g. Injection in a note or message | Buyer and merchant text is read with the pattern check of `clearwake/guard.py`. A hit is receipted (`clearwake.model.injection_attempt`) and changes nothing: the amount and the target never come from text, and an order-giving note is replaced before it reaches PayPal. An amount or target the agent passes that differs from PayPal's record is ignored and receipted as `claimed_amount_minor`. |
| f. Splits against one capture | When the reader can read the capture, the move is reserved against the capture total with the same `Invariants` store the swarm uses. A per customer daily cap applies when `customer_id=` is passed. |
| Evidence of what happened | Every call writes a signed, hash chained receipt in the format of `verdock_core.receipts`, with the policy hash. `api.verify()` checks the log offline against its own public key. |

The rules are the swarm's: `verdock_core` policy, invariants, outcomes, approvals and receipts, and `clearwake.guard`. Nothing is copied.

## Measured side by side

Run `python examples/toolkit_agent_guarded.py` (one episode of each attack) or `--recorded` (all 80 attack episodes). Unguarded is `ToolkitSurface` from `clearwake/baseline.py`, which behaves as the failure page records. Guarded is the same surface wrapped by `guard()`. Both act on the local PayPal layer. The unguarded numbers match the recorded run episode by episode.

| Attack (20 episodes each) | Overpaid, unguarded / guarded | Double refunds | Held for a person |
|---|---:|---:|---:|
| Lost response after PayPal applied the refund | USD 108.75 / 0.00 | 32 / 0 | 0 |
| Injected instruction in the buyer's message | USD 666.50 / 0.00 | 0 / 0 | 20 |
| Over limit request | USD 352.00 / 0.00 | 0 / 0 | 20 |
| Duplicate delivery | USD 100.75 / 0.00 | 29 / 0 | 0 |
| **Total (80)** | **USD 1,228.00 / 0.00** | **61 / 0** | **40** |

In the lost response and duplicate episodes, 31 of 40 needed an owner approval (amounts above USD 2.00); the harness plays the owner and approves exactly the move the guard named. The guarded receipts of every episode verify offline.

## Scope and limits

- It covers what `docs/TOOLKIT_FAILURE_CASES.md` documents: the one money returning dispute tool, `accept_dispute_claim`. It does not know the toolkit's other tools and passes them through.
- It holds what is above the limit for a person. It does not settle by offer, send evidence or decide a dispute: that is the full Clearwake agent. If no person acts before the deadline, PayPal escalates the case, and any fee that follows is not in these numbers.
- The toolkit side of the comparison is the recorded behaviour driven by fixed rules, with no language model choosing calls. How real PayPal answers a repeated accept was not tested.
- The guard was run against the local PayPal layer. The `run()` and `get_dispute` path for a real `PayPalAPI` object was written from the toolkit's documented shape and was not run against the installed toolkit or the PayPal sandbox.
- The request id is passed to the tool only when the tool accepts a `request_id` argument. The toolkit 1.11.0 as recorded sends no `PayPal-Request-Id`, so protection against a repeat there comes from the ledger and from reading PayPal's record before any retry, not from PayPal deduplicating.
- The pattern check is a flag, not the defence. A sentence no pattern matches is still limited by the amount rule.

## The Break it page

`site/break.html` replays the recorded episodes in the browser: pick an attack, press Run, see both outcomes and verify the guarded receipts with the same browser verifier as the Developers page. `scripts/build_break_data.py` builds `site/data/break.json` from the newest recorded run and stops if the unguarded replay differs from the record. The page ports the pattern list of `clearwake/guard.py` to JavaScript; `tests/test_toolkit_guard.py` checks that both give the same answers on `tests/fixtures/injection_cases.json`. The JavaScript uses ASCII word boundaries, so Python remains the authority for non ASCII text.

Files: `clearwake/toolkit_guard.py`, `examples/toolkit_agent_guarded.py`, `tests/test_toolkit_guard.py`, `scripts/build_break_data.py`, `site/break.html`, `site/break.js`, `site/break.css`, `site/data/break.json`.

## Note 2026-11-11: the MCP proxy and the TypeScript toolkit

The scope line "the one money returning dispute tool" holds for the Python toolkit that the failure page ran. The published npm package of the toolkit (1.11.0) and the MCP server (`@paypal/mcp` 1.8.1) also define `create_refund`, and offer 28 tools in all (`docs/PAYPAL_MCP_TOOLS.md`). `clearwake/mcp_guard.py` applies the same logic to both `accept_dispute_claim` and `create_refund` for any MCP client: see `docs/MCP_GUARD.md`. The npm tool's `note` allows only letters, digits, underscore and hyphen, so the free text notes of cases e to g could not reach PayPal through the MCP server.
