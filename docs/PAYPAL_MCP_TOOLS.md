# PayPal MCP server and Agent Toolkit: every tool

How this was obtained: read from the published npm package source, 11 Nov 2026. Nothing here was run against PayPal.

| Package | Version |
|---|---|
| @paypal/mcp (the MCP server, `dist/index.js`) | 1.8.1 |
| @paypal/agent-toolkit (the tool definitions, `mcp/index.js`) | 1.11.0 |
| @modelcontextprotocol/sdk (in the same install) | 1.32.2 |

Both are Apache 2.0. The files were read from the local npm cache the package was downloaded into with Sri's approval. The machine readable form of this page is `docs/paypal_mcp_tools.json`.

## Counts

| | Read | Write | Money | Total |
|---|---:|---:|---:|---:|
| Agent Toolkit 1.11.0 (all tools defined) | 18 | 21 | 8 | 47 |
| `@paypal/mcp --tools=all` (what an MCP client sees) | 14 | 9 | 5 | 28 |

Kinds: read changes nothing at PayPal. Write changes PayPal state (drafts, catalogue, tracking, subscriptions, orders) and does not itself move money. Money moves money or sends a payment request or reminder to a customer. The kind is our reading of each tool's description and endpoint.

The MCP server's `--tools=all` enables only the 28 actions in its `ACCEPTED_TOOLS` list. The toolkit defines 19 more (recurring invoice series, record payment and refund for an invoice, update subscription, update plan, update shipment tracking, merchant insights and others). They exist in the toolkit for other frameworks and are not offered by the MCP server.

## Money moving tools in the MCP server

| Tool | What it does | Guard |
|---|---|---|
| `accept_dispute_claim` | Accepts liability; the dispute closes for the customer and PayPal refunds from the merchant account. Fields: dispute_id, note | Enforced |
| `create_refund` | Refunds a capture. Fields: capture_id, amount (optional; omitted means the full captured amount), invoice_id, note_to_payer | Enforced |
| `pay_order` | Captures an order. Field: id | Receipted, forwarded (held with `--strict`) |
| `send_invoice` | Sends an invoice to its recipients | Receipted, forwarded (held with `--strict`) |
| `send_invoice_reminder` | Sends a reminder for an unpaid invoice | Receipted, forwarded (held with `--strict`) |

## Dispute and tracking tools

Dispute tools: three. `list_disputes` (read), `get_dispute` (read), `accept_dispute_claim` (money). There is no tool to send a message, make an offer, provide evidence, appeal or escalate a dispute, in the MCP server or in the toolkit. Everything beyond accepting a claim is outside what an MCP client can do through this package.

Tracking tools: `create_shipment_tracking` (write), `get_shipment_tracking` (read) in the MCP server; `update_shipment_tracking` (write) in the toolkit only.

## Facts from the source that matter to a guard

- A tool result is one text block holding the JSON of PayPal's reply. A PayPal error is also a normal result (`isError` is not set): text JSON `{"ok": false, "status": 422, "code": "PAYPAL_API_HTTP_ERROR", "message": ...}`, or `{"error": {"message": ..., "type": "paypal_error"}}` for other failures.
- The MCP server never sets `PayPal-Request-Id`. The toolkit adds it only when its context carries `request_id`, and `@paypal/mcp` does not pass one. A tool call cannot set it.
- The calls use axios with no retry. `accept_dispute_claim` posts `{note}` and also passes its arguments as query parameters.
- `accept_dispute_claim.note` must match `^[A-Za-z0-9_-]{1,255}$`: no spaces. `get_dispute.dispute_id` has the same pattern. `create_refund.capture_id` must match `^[A-Za-z0-9_-]{15,32}$`.
- `create_refund` with no amount refunds the full captured amount.
- The only gate inside the server is the `--tools` list (on or off per action). No amount or count limit exists.
- `get_merchant_insights` refuses in sandbox mode.

## All tools

Columns: tool, kind, in `--tools=all`, toolkit action, description (first sentence), first input fields. The JSON file lists every field and which are required.

| Tool | Kind | MCP | Action | Description | Input fields |
|---|---|---|---|---|---|
| `create_invoice` | write | yes | invoices.create | Create Invoices on PayPal. | currency_code, invoice_number, invoice_date, reference, note, invoicer_business_name, invoicer_given_name, invoicer_surname ... |
| `create_recurring_series` | write | no | invoices.createRecurringSeries | Create a recurring invoice series on PayPal. | interval_unit, interval_count, start_series_date, total_cycles, reference, currency_code, note, invoicer_business_name ... |
| `activate_recurring_series` | money | no | invoices.activateRecurringSeries | Activate a recurring invoice series on PayPal. | recurring_series_id |
| `get_recurring_series` | read | no | invoices.getRecurringSeries | Get a recurring invoice series from PayPal. | recurring_series_id |
| `cancel_recurring_series` | write | no | invoices.cancelRecurringSeries | Cancel a recurring invoice series on PayPal. | recurring_series_id |
| `delete_recurring_series` | write | no | invoices.deleteRecurringSeries | Delete a recurring invoice series on PayPal. | recurring_series_id |
| `list_invoices` | read | yes | invoices.list | List invoices from PayPal. | page, page_size, total_required |
| `get_invoice` | read | yes | invoices.get | Get an invoice from PayPal. | invoice_id |
| `send_invoice` | money | yes | invoices.send | Send an invoice to the recipient(s). | invoice_id, note, send_to_recipient, additional_recipients |
| `send_invoice_reminder` | money | yes | invoices.sendReminder | Send a reminder for an invoice. | invoice_id, subject, note, additional_recipients |
| `cancel_sent_invoice` | write | yes | invoices.cancel | Cancel a sent invoice. | invoice_id, note, send_to_recipient, additional_recipients |
| `delete_invoice` | write | no | invoices.delete | Delete a draft or scheduled invoice on PayPal. | invoice_id |
| `setup_invoice_auto_reminders` | write | no | invoices.setupReminders | Initialize the invoice auto reminder configuration for the merchant's PayPal account. | configurations |
| `update_invoice_auto_reminder` | write | no | invoices.updateReminder | Update an existing invoice auto reminder configuration by its configuration ID. | reminder_configuration_id, type, status, interval, repetition, notification |
| `search_invoicing` | read | no | invoices.search | Search for invoices or recurring invoice series on PayPal. | resource_type, page, page_size, total_required, invoice_filters, recurring_series_filters |
| `update_invoicing` | write | no | invoices.update | Update an existing invoice or recurring invoice series on PayPal. | resource_type, invoice_update, recurring_series_update |
| `cancel_invoice_auto_reminder` | write | no | invoices.cancelReminders | Cancel all scheduled automatic reminders for an invoice. | invoice_id |
| `generate_invoice_qr_code` | read | yes | invoices.generateQRC | Generate a QR code for an invoice. | invoice_id, width, height |
| `generate_invoice_number` | read | no | invoices.generateInvoiceNumber | Generate the next invoice number available to the merchant. |  |
| `record_payment_for_invoice` | money | no | invoices.recordPayment | Record a payment for an invoice on PayPal. | invoice_id, payment_id, payment_date, payment_date_time, method, note, amount, shipping_info |
| `record_refund_for_invoice` | money | no | invoices.recordRefund | Record a refund for an invoice on PayPal. | invoice_id, refund_date, amount, method |
| `create_conditional_rules_for_invoice` | write | no | invoices.createConditionalRules | Create conditional rules for an invoice on PayPal. | invoice_id, rules |
| `create_product` | write | yes | products.create | Create a product in PayPal using product catalog - create products API. | name, type, description, category, image_url, home_url |
| `list_products` | read | yes | products.list | List products from PayPal. | page, page_size, total_required |
| `update_product` | write | yes | products.update | Update a product in PayPal. | product_id, operations |
| `show_product_details` | read | yes | products.show | List products from PayPal. | product_id |
| `create_subscription_plan` | write | yes | subscriptionPlans.create | Create a subsctiption plan in PayPal using subscription - create plan API. | product_id, name, description, billing_cycles, payment_preferences, taxes |
| `list_subscription_plans` | read | yes | subscriptionPlans.list | List subscription plans from PayPal. | product_id, page, page_size, total_required |
| `show_subscription_plan_details` | read | yes | subscriptionPlans.show | Show subscription plan details from PayPal. | plan_id |
| `create_subscription` | write | yes | subscriptions.create | Create a subscription in PayPal using the subscription - create subscription API. | plan_id, quantity, shipping_amount, subscriber, application_context |
| `show_subscription_details` | read | yes | subscriptions.show | Show subscription details from PayPal. | subscription_id, get_additional_details |
| `cancel_subscription` | write | yes | subscriptions.cancel | Cancel a customer subscription in PayPal. | subscription_id, payload |
| `update_subscription` | write | no | subscriptions.update | Update a customer subscription in PayPal. | subscription_id, currency_code, outstanding_balance, custom_id, fixed_price, payment_failure_threshold, auto_bill_outstanding, taxes_inclusive ... |
| `create_shipment_tracking` | write | yes | shipment.create | Create a shipment for a transaction in PayPal. | order_id, tracking_number, transaction_id, status, carrier |
| `get_shipment_tracking` | read | yes | shipment.get | Get tracking information for a shipment by ID. | order_id, transaction_id |
| `update_shipment_tracking` | write | no | shipment.update | Update tracking information for a shipment by ID and status. | transaction_id, tracking_number, new_tracking_number, status, carrier |
| `create_order` | write | yes | orders.create | Create an order in PayPal. | currencyCode, items, discount, shippingCost, shippingAddress, notes, returnUrl, cancelUrl |
| `get_order` | read | yes | orders.get | Retrieves the order details from PayPal for a given order ID. | id |
| `pay_order` | money | yes | orders.capture | Capture a payment for an order. | id |
| `list_disputes` | read | yes | disputes.list | List disputes from PayPal. | disputed_transaction_id, dispute_state, page_size, page |
| `get_dispute` | read | yes | disputes.get | Get details for a specific dispute from PayPal. | dispute_id |
| `accept_dispute_claim` | money | yes | disputes.create | Accept liability for a dispute claim. | dispute_id, note |
| `list_transactions` | read | yes | transactions.list | List transactions from PayPal. | transaction_id, transaction_status, start_date, end_date, search_months, page_size, page |
| `update_plan` | write | no | plan.update | Update a billing plan in PayPal using the Plans API (PATCH). | plan_id, description, auto_bill_outstanding, percentage, payment_failure_threshold, setup_fee, setup_fee_failure_action, name ... |
| `create_refund` | money | yes | payments.createRefund | Initiate a refund for a PayPal payment capture. | capture_id, amount, invoice_id, note_to_payer |
| `get_refund` | read | yes | payments.getRefunds | Retrieve detailed information about a PayPal payment refund. | refund_id |
| `get_merchant_insights` | read | no | insights.get | Retrieve business intelligence metrics and analytics for a merchant, filtered by start date, end date, insight type, and time interval. | start_date, end_date, insight_type, time_interval |

## What could not be run

- `npx -y @paypal/mcp --tools=all` did not answer `initialize` and printed nothing. The cause is in the npx cache: the installed tree lacks the packages `ajv`, `mathjs`, `axios` and `supports-color`, so the server cannot load. Nothing was installed to repair it.
- The tool list and input schemas above were taken from the real `PayPalAgentToolkit` class of the cached package, loaded in Node with those four packages replaced by empty stand-ins and asked `tools/list` over an in-memory MCP transport with the same action map that `--tools=all` builds. That is the package's own code answering, not the stdio server, and not a confirmed `tools/list` from a running stdio server. A `tools/list` run against the stdio server was not done.
- No call reached PayPal. Result shapes come from the source of each function (it returns `response.data`) and from PayPal's published API shapes.
