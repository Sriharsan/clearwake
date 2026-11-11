# Clearwake security boundary

This is a test, loopback-only payment-operations prototype. Run it on a
trusted local machine, not as an internet service. Room/session cookies,
same-origin checks, body limits, CSRF, scoped roles, invitation expiry and shared
state are inherited from the pinned public Relayloom core.

The separate payment boundary requires current owner membership/session, exact
room revision, a current validated published plan, explicit amount/currency/
capture acknowledgement, five-minute grant and fresh final dispatch checks.
Artifact publication does not grant payment authority. Model text or votes do
not authorize money. Editors/viewers cannot grant, revoke, send or reconcile.

The current case is USD only, at most 5.00, one configured capture per database.
The durable operation and stable request ID are committed before any refund
POST. Final dispatch holds the database write boundary while checking authority
and sending, so revocations/intent changes linearize before or after the send.
This deliberately favors conservative local correctness over throughput.
The transport has bounded 15-second socket timeouts; these are not universal
wall-clock deadlines. An in-flight POST may delay another write/revocation.

A revoked/expired/stale grant cannot start a send. Already sent or uncertain
effects cannot be undone by local revocation. Crashed reservations become
UNKNOWN and remain held, with no automatic POST retry or new request identity.
Known provider reads validate refund ID, amount, currency, capture link,
custom request correlation and status before VERIFIED. Missing/mismatched
evidence fails closed. Reconciliation does not need a still-active financial
grant because it is owner-only read/reconciliation, never a payment send.

PayPal credentials are server environment only. Network mode is explicit and
restricted to the reviewed official sandbox host/routes. Redirect following
and ambient proxy routing are disabled. Provider errors are sanitized and payer
details are not retained in receipts. Provider links are checked as data and
never followed. No full-refund empty payload or production URL is supported.

SQLite state is local and unencrypted; protect its folder with OS permissions.
Do not use real customer data, publish ledgers or delete unknown reservations to
make a fresh attempt. The single-operation guard applies to this persistent
database; it cannot control refunds made by another app or a different ledger.
External merchant activity and provider idempotency retention are separate
boundaries. No universal exactly-once guarantee is claimed.

Paid inference, credits, account/card changes and real-money transactions are
outside this build/test task. Optional model adapters stay off by default.
The public build has not undergone a full independent security audit, broad
multi-tenant hosting review, or real sandbox acceptance. Report concerns through
the repository's security reporting controls where available; do not publish
credentials or private payment records in an issue.
