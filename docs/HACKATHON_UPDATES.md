# Changes during the submission period

The PayPal AI Hackathon submission period opened on 1 October 2026 (9:15 am Pacific Time). Everything below comes from git history only (`git log`), with commit dates as recorded. Every commit in both repositories is dated after 1 October 2026, so the whole project was built during the submission period.

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

## Relayloom core (pinned submodule, `vendor/relayloom`, public MIT repository)

Clearwake extends this shared workroom core. It is Sri's own public project, also started during the period.

| Date (IST) | Commit | Change |
| --- | --- | --- |
| 2026-10-27 00:05 | `ec6dc51` | Initialize Relayloom hackathon scope and contribution record |
| 2026-10-27 00:06 | `4c13989` | Clarify integrated autonomous operations and governed improvement direction |
| 2026-10-27 00:16 | `c6ea062` | Record verified credit terms and current submission guidance |
| 2026-10-28 18:38 | `3668d31` | Build shared revision workroom and guarded Meta adapter |
| 2026-10-30 18:02 | `e4654fa` | README: open with what Relayloom does and the single run command |

## How to check

```
git log --reverse --format='%h %ad %s' --date=iso
git -C vendor/relayloom log --reverse --format='%h %ad %s' --date=iso
```
