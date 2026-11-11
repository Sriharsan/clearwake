# PayPal contribution and verification record

## Boundary

Clearwake is a separate public PayPal hackathon extension. New implementation
began 28 October 2026 Asia/Kolkata and continued 29 October. Git records actual
publication times. The organizer determines eligibility; repository creation
does not reset the age of reused work or prove acceptance.

Reused public work: Relayloom 3668d316878e578223b8255622300c5d6131e5e3, its
shared controller/scheduler, permission/session/CSRF/SSE, base UI and optional Meta
adapter. It stays as a pinned MIT submodule with its original history/license.
No private Verdock implementation, history, credentials or records were imported.
On 30 October the pin moved to e4654fa807182d646f4029835fcfcc7f87f8c2b3, which
changes only the Relayloom README; the reused code is the same.

## New implementation ledger

| New work | Paths | Verification boundary |
| --- | --- | --- |
| Sandbox-only PayPal adapter and durable local provider | clearwake/paypal.py | Local HTTP tests; no live sandbox call |
| Separate exact refund grants and revocation | clearwake/controller.py | Current owner/session/CSRF/revision/scope/expiry and preflight-race tests |
| Reserved request identity and unknown/restart holds | clearwake/controller.py | Parallel duplicate, restart, pending/unknown and correlated-record tests |
| Payment case/evidence UI | web/*, clearwake/server.py | Real HTTP asset tests and offline UI state tests; rendered acceptance separately recorded |
| Runnable CLI and pinned public-core extension | clearwake/__main__.py, __init__.py, server.py | Clean-checkout command, real loopback HTTP/core boundary tests |
| Optional local AI | clearwake/local_ai.py, tests/test_local_ai.py | Parent-owned addition; its actual evidence is recorded separately, not inferred here |
| Repeatable local run on the local provider (30 October) | DEMO.md, demo.ps1, scripts/check_demo.*, scripts/show_provider_record.py | Four local run cases PASS through the real controller and the local gateway; UI steps 1 to 3 clicked through on loopback. No sandbox call |

The payment UI is injected into the pinned base HTML; three reviewed runtime
hooks publish state/session/clear events. Source anchors are checked so an
upstream change requires review. The pinned core itself was not modified.

## Current verification checkpoint

The payment branch's 21 Python offline tests passed on Python 3.13.3, together
with five parent-added local AI tests (26 total). Four
dependency-free payment UI tests and node syntax checking passed on Node 22.
Initial Windows validation exposed unclosed SQLite context-manager connections;
the local gateway/test connections now explicitly close, and the rerun passed.
These counts do not include upstream tests. Nine upstream UI tests passed.
An additional upstream Python run passed 26/27; its HTTP415 test hit Windows
socket abort 10053. One focused rerun of that exact test passed. This transient
failure is retained here; it is not relabelled as a clean 27-test full run.
Final commit, independent CI, browser acceptance and any live trial must be
recorded at release, not retroactively assumed from this checkpoint.

## Remaining live/submission gates

No live PayPal sandbox capture/refund/read has been performed by the payment
worker. No provider credential, paid model request, account/card/subscription
change or credit claim was made. Live local AI, if separately approved and run
by the parent, is a distinct result; it cannot stand in for PayPal acceptance.

Real sandbox+AI video, current event requirement check, public under-three-minute
YouTube video, final English submission and organizer eligibility remain
separate gates. Founder facts, customers, savings and production readiness are
not fabricated. The video should identify the PayPal-specific new work above.
