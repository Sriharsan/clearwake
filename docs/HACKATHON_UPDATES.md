# Changes during the submission period

The PayPal AI Hackathon submission period opened on 1 October 2026 (9:15 am Pacific Time). Everything below comes from git history only (`git log`), with commit dates as recorded. Every commit in Clearwake and in both pinned submodules is dated after 1 October 2026, so the whole project was built during the submission period.

## Clearwake (this repository)

| Date (IST) | Commit | Change |
| --- | --- | --- |
| 2026-10-30 20:47 | `5586442` | Clearwake: shared refund workroom extending the pinned Relayloom core |
| 2026-10-30 20:49 | `389d343` | Pin Relayloom to e4654fa (README only change) |
| 2026-10-30 21:26 | `1fbf0be` | Add real PayPal sandbox setup and four case sandbox check |
| 2026-10-30 21:37 | `b68f331` | Add autonomy policy with recorded approvals |
| 2026-10-30 21:37 | `0cb9e83` | Redesign the payment view as a dark control room |
| 2026-10-30 21:45 | `d12de52` | README, submission notes and video script with honest run labels |
| 2026-10-30 21:45 | `8d0dda6` | Record changes during the submission period from git history |
| 2026-10-31 10:24 | `25a980b` | Sandbox setup starts a fresh order when the previous one expired |
| 2026-10-31 10:50 | `1f475cb` | Optional sandbox setup with PayPal's published test card |
| 2026-10-31 10:56 | `e6dfa5c` | Record the PayPal sandbox run: four of four cases passed on 31 October |
| 2026-10-31 10:57 | `78ada7e` | Refresh the submission period change log from git history |
| 2026-10-31 11:09 | `f690c63` | Refuse to run unless PAYPAL_BASE_URL is exactly the PayPal sandbox |
| 2026-10-31 11:10 | `cd9b40a` | Record design decisions: receipts format, shared core, toolkit, disputes, payments, models |
| 2026-10-31 11:11 | `bde9eeb` | Buyer agent with an owner's spending mandate and one model adapter with three backends |
| 2026-10-31 11:14 | `45f6ec8` | Record checked sources for impact claims; drop the two that could not be confirmed |
| 2026-10-31 11:15 | `b0f3533` | Disputes in the sandbox adapter: list, read, provide evidence, accept claim, settle, add tracking |
| 2026-10-31 11:16 | `01ea17d` | Evidence agent and deadline watch for PayPal disputes |
| 2026-10-31 11:44 | `e0fdf83` | Pin the shared verdock-core engine v0.1.0 as a submodule |
| 2026-10-31 11:47 | `0f139d4` | Merchant swarm on verdock-core |
| 2026-10-31 11:48 | `1c7fca1` | Signed mandate receipt from the buyer agent, linked to the PayPal order |
| 2026-10-31 11:51 | `8753970` | PayPal dispute path in the merchant swarm, with local run disputes |
| 2026-10-31 11:54 | `d86176b` | Case runner for a to l and a capture preflight before every swarm refund |
| 2026-10-31 15:35 | `44386c3` | Case i runs against a real open sandbox dispute when one exists, with tracking read from PayPal's order |
| 2026-10-31 15:48 | `0910bc8` | Third party credits and the built versus planned vision |
| 2026-10-31 15:56 | `e458cc0` | Answer OPEN dispute inquiries and report PayPal refusals as refused, not UNKNOWN |
| 2026-10-31 16:01 | `5212635` | Results page from the recorded runs only |
| 2026-10-31 16:01 | `5e1d271` | README: dispute positioning, honest status, AI tools, verdock-core and where this goes |
| 2026-10-31 16:01 | `72d6c18` | Submission notes: APIs, observed limits, run labels, criteria and awards |
| 2026-10-31 16:01 | `6f7d742` | Video script for the dispute story with sandbox and local run captions |
| 2026-10-31 16:01 | `a9b9ba2` | Refresh the submission period change log, with the verdock-core submodule |
| 2026-10-31 16:02 | `582c222` | Answer disputes under review with supporting info PayPal offers, verified by read-back |
| 2026-10-31 16:03 | `8dda0b3` | Drop an unused tau2-bench row from third-party notices |
| 2026-10-31 16:06 | `379a2cb` | Results: case i passed on a real sandbox dispute; current test counts |
| 2026-10-31 16:06 | `f71a2f7` | Console controller and /console API: buyer mandate, local run cases c to l, approval inbox and reconcile behind a CSRF token |
| 2026-10-31 16:06 | `7be2d9f` | Console screens: buyer agent, merchant control room and in-browser receipt verifier |
| 2026-10-31 16:06 | `6fae634` | Console screenshots at 390 and 1440 wide |
| 2026-10-31 16:08 | `b7035f0` | Record what PayPal's agent toolkit does on the lost response, split and injection cases |
| 2026-10-31 22:13 | `ab113c7` | Approved dispute escalations now act on the one step they named; refused POSTs no longer reset the socket on Windows |
| 2026-10-31 22:23 | `2776a66` | Settle disputes in conversation before they become claims, held offline when the network is cut |
| 2026-10-31 22:38 | `864e6e8` | Network isolated run for case m, cases n and m in the runner, and the fee leak gauge |
| 2026-10-31 22:46 | `aba64d2` | AG Grid dispute ledger with the fee leak gauge, and console cases n and m |
| 2026-10-31 22:47 | `0db2441` | Keep vendored AG Grid files byte for byte |
| 2026-10-31 22:54 | `12ebb23` | Public site for Vercel: the fee leak with sources, side by side, the boundary, the recorded sandbox run and an in-browser receipt verifier |
| 2026-10-31 22:54 | `f60871e` | Keep receipt logs byte for byte so their signatures verify after any checkout |
| 2026-10-31 23:00 | `a2c9cd4` | Docs for the fee leak position: README, submission notes, video script, results, sandbox runs and sources |
| 2026-10-31 23:00 | `71395ad` | Refresh the submission period change log from git history |
| 2026-10-31 23:03 | `6dd2f07` | Keep the local virtual environment out of the container image |
| 2026-10-31 23:21 | `a4cde6d` | Public site URL in the README and submission notes |
| 2026-11-01 10:38 | `1d087a2` | Console screenshots show the dispute ledger and the fee leak gauge |
| 2026-11-01 10:58 | `7f52a0e` | Read only helpers for the video: show a sandbox dispute, print a saved network cut run, and a boundary only check |
| 2026-11-01 11:22 | `426a0f5` | Dispatch proof: signed packing record, strong or weak check against a buyer's claim, evidence with the photo, case o |
| 2026-11-01 11:32 | `0f79321` | Dispatch proof: validate order ids before they touch the file system, widen the ledger column, record case o in the docs, refresh screenshots and the change log |

## Relayloom core (pinned submodule, `vendor/relayloom`, public MIT repository)

Clearwake extends this shared workroom core. It is Sri's own public project, also started during the period.

| Date (IST) | Commit | Change |
| --- | --- | --- |
| 2026-10-27 00:05 | `ec6dc51` | Initialize Relayloom hackathon scope and contribution record |
| 2026-10-27 00:06 | `4c13989` | Clarify integrated autonomous operations and governed improvement direction |
| 2026-10-27 00:16 | `c6ea062` | Record verified credit terms and current submission guidance |
| 2026-10-28 18:38 | `3668d31` | Build shared revision workroom and guarded Meta adapter |
| 2026-10-30 18:02 | `e4654fa` | README: open with what Relayloom does and the single run command |

## verdock-core engine (pinned submodule, `vendor/verdock-core`, tag v0.2.0, public MIT repository)

The shared engine under the merchant swarm and the buyer agent: policy, approvals, swarm invariants, outcome states, signed receipts with an offline verifier, the egress gateway and the held queue. It is Sri's own public project (https://github.com/Sriharsan/verdock-core), built during the period and pinned at `f7ac784` (v0.2.0).

| Date (IST) | Commit | Change |
| --- | --- | --- |
| 2026-10-31 11:20 | `39b8c52` | Add MIT license and gitignore |
| 2026-10-31 11:20 | `ec2ea1a` | Add package skeleton, shared errors and SQLite helpers |
| 2026-10-31 11:20 | `ef6a802` | Add policy loading, YAML subset parser, policy hash and decide |
| 2026-10-31 11:20 | `cf2db6c` | Add approval store with exact match, expiry and single use |
| 2026-10-31 11:20 | `fc869fc` | Add invariants: group caps, customer daily caps, locks, request ids |
| 2026-10-31 11:20 | `f20d410` | Add outcome states, compare, may_retry and outcome log |
| 2026-10-31 11:20 | `3ffcc26` | Add pure Python Ed25519 from RFC 8032 |
| 2026-10-31 11:20 | `441c102` | Add signed receipt log and verifier with draft Appendix A vectors |
| 2026-10-31 11:20 | `eee63df` | Add verify command line |
| 2026-10-31 11:21 | `5797f0e` | Add browser verifier with node tests |
| 2026-10-31 11:21 | `478998c` | Add README, changelog and third party notes |
| 2026-10-31 22:17 | `fcd4aef` | Egress gateway with a policy host allowlist and signed receipts, and a held queue for offline actions |
| 2026-10-31 22:21 | `f7ac784` | Close the held queue's setup connection |

## How to check

```
git log --reverse --format='%h %ad %s' --date=iso
git -C vendor/relayloom log --reverse --format='%h %ad %s' --date=iso
git -C vendor/verdock-core log --reverse --format='%h %ad %s' --date=iso
```
