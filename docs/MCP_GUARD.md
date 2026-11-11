# MCP guard: Clearwake between your agent and PayPal's MCP server

One line of labelling: the outcomes on this page are measured on a local run with a local PayPal MCP server that answers with the real tool names and result shapes (`clearwake/mcp_local_upstream.py`). The guard was not run against the live PayPal MCP server.

`clearwake/mcp_guard.py` is a stdio proxy. Any MCP client (Claude, ChatGPT, an agent framework) talks to it as it would to PayPal's server. It starts the real server as a child, forwards everything, and applies the signed policy (`policy/merchant.yaml`) to the money moving tools. It is Clearwake's own code and not a PayPal product.

## The one line change

Before: `npx -y @paypal/mcp --tools=all`
After: `python -m clearwake.mcp_guard -- npx -y @paypal/mcp --tools=all`

`examples/mcp_config.json` shows both forms of a client configuration. Offline: `python -m clearwake.mcp_guard --dry-run` starts the local PayPal MCP server instead of a command.

## What it does

| Message | Behaviour |
|---|---|
| `initialize`, `tools/list`, notifications, ping | Forwarded line for line. Schemas and descriptions are never changed. |
| Read only tools (`get_dispute`, `list_disputes`, `list_transactions`, `get_order` and the rest) | Forwarded untouched. No receipt. |
| `accept_dispute_claim` | Reads PayPal's dispute first (`get_dispute`). The amount comes from that record and the policy, never from arguments or message text. Above the `accept_claim` limit: an MCP error result, held for a person, nothing sent. Between the approval threshold and the limit: a person approves that exact move. |
| `create_refund` | Reads PayPal's record of the capture first. Checks the amount (or, when none is given, the rest of the capture) against the `refund` limit and against what the record shows is left. |
| Both | One request id from the SHA-256 of the payload (tool, target, amount, currency). A durable ledger (SQLite, survives a restart). A lost response marks the move UNKNOWN; the next call reads PayPal's record first and sends nothing if the move applied. One money move at a time inside the proxy. |
| Order giving text in a note or a buyer message | Receipted as `clearwake.model.injection_attempt`. It changes nothing: no text is ever used as an amount or target, and a refund note that gives orders is not sent. |
| Every guarded call | A signed, hash chained receipt in the format of `verdock_core.receipts`, with the policy hash. `python -m clearwake.mcp_guard verify` checks it offline. |
| `pay_order`, `send_invoice`, `send_invoice_reminder` | The policy has no operation for them. Receipted and forwarded; held with `--strict`. |

What the client sees when a call is stopped: a normal tool result with `isError` true and a JSON text `{"clearwake_guard": {"state", "detail", "sent", "request_id", "approval_id"}}`. A call that went through returns PayPal's own reply unchanged. A person approves with `python -m clearwake.mcp_guard approve APPROVAL_ID --by NAME`; `pending` lists the open requests.

Options: `--policy`, `--data-dir` (ledger, approvals, receipts), `--timeout` seconds (default 60), `--strict`.

## Measured, offline

A refund of 1.50 on a capture, the response lost after PayPal applied it, the agent calls again (local run, `--stand-in-fault drop_answer:1`):

| | Money moves applied |
|---|---:|
| Agent straight to the local PayPal MCP server | 2 (3.00 for a 1.50 refund) |
| Same agent through the guard | 1 (1.50) |

`tests/test_mcp_guard.py` runs the proxy over stdio and checks: framing (a line that is not JSON gets a parse error and the proxy keeps serving), `tools/list` identical to the server's, read only passthrough with no receipt, refusal above the limit with nothing sent, the amount taken from PayPal's record and not from arguments, a lost response then a retry (also across a restart) paying once, two identical calls in flight paying once, approval used once, injected text receipted, and receipts that verify offline and fail after a line is changed.

## Scope and limits

- It enforces the money tool `docs/TOOLKIT_FAILURE_CASES.md` documents (`accept_dispute_claim`) and `create_refund`. The other three money tools in the MCP server are receipted and, with `--strict`, held. See `docs/PAYPAL_MCP_TOOLS.md` for all 28.
- It was written from the published package source and tested against a local PayPal MCP server. It was not run against the live PayPal server or the PayPal sandbox. The record reads (`get_dispute`, `list_transactions`) follow PayPal's published response shapes and are untested live.
- The MCP server sends no `PayPal-Request-Id` and a tool call cannot set one, so the protection against a repeat comes from the ledger and from reading PayPal's record before any retry, not from PayPal deduplicating.
- A refund of the same amount on the same capture is treated as the same move. A refund of another amount is a new move.
- The refund total on a capture is read from transaction search over the last 31 days. An older refund is not seen.
- `accept_dispute_claim.note` must have no spaces in the server's schema. The guard rewrites a note that does not fit before sending.
- The injection pattern check is a flag, not the defence. A sentence no pattern matches is still limited by the amount rule.
- It holds what is above the limit for a person. It does not settle by offer or send evidence: PayPal's MCP server has no tool for either.

Files: `clearwake/mcp_guard.py`, `clearwake/mcp_local_upstream.py`, `tests/test_mcp_guard.py`, `examples/mcp_config.json`, `docs/PAYPAL_MCP_TOOLS.md`, `docs/paypal_mcp_tools.json`.
