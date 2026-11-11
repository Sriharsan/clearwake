# Built during the hackathon

The PayPal AI Hackathon submission period opened on 1 October 2026. Everything here comes from `git log` in this repository and in the two public components it pins. No commit in any of the three is dated before 1 October 2026 (`git log --before=2026-10-01` returns nothing in each). Times are IST (+0530), as recorded.

| Repository | First commit | Pinned at | Commits (9 Nov 2026 check; this repository counted on 10 Nov) |
| --- | --- | --- | --- |
| This repository (Clearwake) | 30 Oct 2026, 20:47, `5586442` | n/a | 60 |
| Relayloom, `vendor/relayloom`, MIT, Sri's own | 27 Oct 2026, 00:05, `ec6dc51` (scope files); the workroom code is `3668d31`, 28 Oct 2026, 18:38 | `e4654fa`, 30 Oct 2026 | 5 |
| verdock-core, `vendor/verdock-core`, MIT, Sri's own | 31 Oct 2026, 11:20, `39b8c52` | `f7ac784`, tag v0.2.0, 31 Oct 2026 | 13 |

To check it yourself: `git log --reverse --format='%h %ad %s' --date=iso`, and the same with `git -C vendor/relayloom` and `git -C vendor/verdock-core`. The full dated list is in [docs/HACKATHON_UPDATES.md](docs/HACKATHON_UPDATES.md).

## Milestones in this repository

| Date (IST) | Commits | What was built |
| --- | --- | --- |
| 27 to 28 Oct | Relayloom `ec6dc51` to `3668d31` | The shared workroom core that Clearwake extends: sessions, CSRF, server, base UI |
| 30 Oct | `5586442` to `8d0dda6` | The first Clearwake build on Relayloom: the refund workroom, the real PayPal sandbox setup, the four case sandbox check, an autonomy policy with recorded approvals |
| 31 Oct, morning | `25a980b` to `f690c63` | The sandbox run recorded (4 of 4 cases); the adapter refuses any base URL except the PayPal sandbox |
| 31 Oct, 11:00 to 12:00 | verdock-core `39b8c52` to `478998c`; Clearwake `bde9eeb` to `d86176b` | verdock-core published (policy, approvals, invariants, outcome states, Ed25519 receipts, verifier). In Clearwake: the buyer agent with an owner's mandate, the Disputes calls in the adapter, the Evidence agent, the merchant swarm, the signed mandate receipt, the dispute path and the case runner a to l |
| 31 Oct, afternoon | `44386c3` to `b7035f0` | First real sandbox dispute answered (case i), refusals reported as refused, the results page, the console and its three screens, the comparison with PayPal's agent toolkit on three failure cases |
| 31 Oct, evening | verdock-core `fcd4aef`, `f7ac784`; Clearwake `ab113c7` to `a4cde6d` | Settling in conversation (`send-message`, `make-offer`), the egress gateway and held queue, the network isolated run (case m), the fee leak gauge, the AG Grid dispute ledger, the public site |
| 1 Nov | `1d087a2` to `0f79321` | Dispatch proof: signed packing record, strong or weak check against a buyer's claim, case o |
| 3 Nov | `0f884b6` to `a70a542` | Dispatch proof run for real with SAM 3 on the CPU and accepted by the sandbox; the offer goes first and alone; real case n recorded (settled, RESOLVED at INQUIRY); real receipts published on the site |
| 9 Nov | `ce2d0c7`, `23fb2b6` | The editorial public site (home, control room, developers) and restyled console |
| 10 Nov | `2f1c00a` and the work after it | The v6 build: the buyer agent's driver for PayPal's Resolution Center, the agent to agent batch, guard rails, the AG Grid ledger on the site and console, the Postman collection, the OpenAPI spec, the Render files. The story narrowed to one problem, item not received, end to end: rules said once in plain words (`clearwake/rules_nl.py`), voice for the merchant (`clearwake/voice.py`, phone mode `python -m clearwake --phone`), the baseline of 200 episodes against an agent using PayPal's Agent Toolkit directly, and the ten case agent to agent batch |

## What is not new work

Python's standard library, AG Grid Community, SAM 3, Ollama and the model weights, Playwright, and the PayPal APIs are used as dependencies or tools, not written here. Licences and versions are in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md). The IETF draft for receipts and RFC 8032 were implemented from their text in verdock-core, with no code copied.
