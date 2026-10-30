# Clearwake contributor instructions

Read README.md, SECURITY.md and docs/PROVENANCE.md once before changing behavior.
Use concise Markdown checkpoints for handoffs. Do not import private Verdock
source, credentials, traces, account identifiers or customer records.

The public Relayloom core is a pinned MIT Git submodule. Extend its actual
controller, shared state, authorization, scheduler and UI; do not create a new
generic executor or silently modify the submodule. Retain its license/notices.
Record new PayPal-specific work separately from reused work and event ideas.

Default mode must make zero provider/model calls. Network PayPal is sandbox-only,
explicit opt-in, bounded USD 5, one configured capture and one durable operation.
Production, proxies, arbitrary URLs and redirects are prohibited. Live AI needs
separate explicit opt-in. Credentials stay in ignored server environment files.
Do not claim free credits or grant entitlement from published offers.

Artifact permission is never refund permission. Fresh owner authority, current
revision, exact amount/currency/capture, expiry and valid plan remain mandatory
at dispatch. Revocation is first-class before dispatch. Sent/uncertain operations
remain held; never retry blindly or replace their request identity. Verify known
provider records before completion. Models cannot grant money authority.

Use synthetic data, no real money/card/subscription/account actions. Tests use
fake transports. Distinguish working rehearsal, offline adapter tests, real
local AI, and unrun PayPal sandbox/hosted acceptance. Never fabricate customers,
savings, security certification, funding readiness or event eligibility.

Original commits use the founder's configured identity without co-author
trailers. Parent reviews publication; do not rewrite history or expose secrets.
