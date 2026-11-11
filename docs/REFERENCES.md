# Official API references reviewed

Reviewed 28 to 29 October 2026 for the bounded adapter. No API action was taken by
reading these resources.

- [OAuth authentication](https://developer.paypal.com/api/rest/authentication/):
  server client-credentials exchange, Basic authentication and bearer token use.
- [Refund captured payment](https://developer.paypal.com/api/payments/v2/captures-refund):
  partial amount object, custom_id, PayPal-Request-Id and full representation.
- [Capture details](https://developer.paypal.com/api/payments/v2/captures-get):
  current sandbox capture ID/status/currency/amount preflight.
- [Refund details](https://developer.paypal.com/api/payments/v2/refunds-get):
  explicit known-refund read and final status/capture evidence.
- [Idempotency](https://developer.paypal.com/api/rest/reference/idempotency/):
  stable request identity, endpoint-specific retention and concurrent requests.
- [Official Payments v2 schema](https://developer.paypal.com/api/payments/v2/schema.json):
  sandbox server, refund amount/status/link/custom correlation fields.

The controller is intentionally stricter than PayPal's broad API: USD ≤5,
one immutable capture, one held operation and no automatic POST retry. It does
not assume that provider idempotency retention is unlimited. Missing custom
correlation/capture evidence remains unverified rather than silently accepted.

Event resources: [rules](https://paypalaihackathon.devpost.com/rules),
[resources](https://paypalaihackathon.devpost.com/resources),
[FAQs](https://paypalaihackathon.devpost.com/details/faqs).
Live PayPal+AI use and the required public video are separate acceptance
and submission gates; offline adapter tests do not establish eligibility.
