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
| 2026-10-31 11:51 | `8753970` | PayPal dispute path in the merchant swarm, with rehearsal disputes |
| 2026-10-31 11:54 | `d86176b` | Case runner for a to l and a capture preflight before every swarm refund |
| 2026-10-31 15:35 | `44386c3` | Case i runs against a real open sandbox dispute when one exists, with tracking read from PayPal's order |
| 2026-10-31 15:48 | `0910bc8` | Third party credits and the built versus planned vision |
| 2026-10-31 15:56 | `e458cc0` | Answer OPEN dispute inquiries and report PayPal refusals as refused, not UNKNOWN |
| 2026-10-31 16:01 | `5212635` | Results page from the recorded runs only |
| 2026-10-31 16:01 | `5e1d271` | README: dispute positioning, honest status, AI tools, verdock-core and where this goes |
| 2026-10-31 16:01 | `72d6c18` | Submission notes: APIs, observed limits, run labels, criteria and awards |
| 2026-10-31 16:01 | `6f7d742` | Video script for the dispute story with sandbox and rehearsal captions |

## Relayloom core (pinned submodule, `vendor/relayloom`, public MIT repository)

Clearwake extends this shared workroom core. It is Sri's own public project, also started during the period.

| Date (IST) | Commit | Change |
| --- | --- | --- |
| 2026-10-27 00:05 | `ec6dc51` | Initialize Relayloom hackathon scope and contribution record |
| 2026-10-27 00:06 | `4c13989` | Clarify integrated autonomous operations and governed improvement direction |
| 2026-10-27 00:16 | `c6ea062` | Record verified credit terms and current submission guidance |
| 2026-10-28 18:38 | `3668d31` | Build shared revision workroom and guarded Meta adapter |
| 2026-10-30 18:02 | `e4654fa` | README: open with what Relayloom does and the single run command |

## verdock-core engine (pinned submodule, `vendor/verdock-core`, tag v0.1.0, public MIT repository)

The shared engine under the merchant swarm and the buyer agent: policy, approvals, swarm invariants, outcome states and signed receipts with an offline verifier. It is Sri's own public project (https://github.com/Sriharsan/verdock-core), built during the period and pinned at `478998c` (v0.1.0).

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

## How to check

```
git log --reverse --format='%h %ad %s' --date=iso
git -C vendor/relayloom log --reverse --format='%h %ad %s' --date=iso
git -C vendor/verdock-core log --reverse --format='%h %ad %s' --date=iso
```
