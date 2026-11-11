# Final check

One command runs the whole gate before submission:

```sh
python scripts/final_check.py            # all ten groups, in order
python scripts/final_check.py --only 4,6 # only some groups
python scripts/final_check.py --skip 9   # skip the clean clone, the slowest group
```

It prints one PASS or FAIL line per check (NOTE for facts that are reported, not judged), then a summary with counts, exits 1 on any failure, and writes `data/runs/final-check-<timestamp>.json` with every detail. It changes nothing in the repository. Secret values are never printed: a hit shows file, line, rule and value length only. The scanners have their own tests in `tests/test_final_check.py`.

## The checks

| Group | What it does |
| --- | --- |
| 1 | Python tests (`python -m unittest discover -s tests`) and Node tests, each with its count |
| 2 | Secret scan of tracked files and the git index (private key blocks, PayPal secrets, Hugging Face tokens, Channel3 key values, Sarvam keys, long credentials assigned to names holding secret, token, key or password). Then: `.env`, `data/buyer-profile`, `data/voice-tls` and `*.sqlite3` are git ignored and not tracked |
| 3 | Exactly one author, Sriharsan B S, and no commit message with a co-author or generated-with line |
| 4 | Strong word scan of the public text, with file and line for every hit (the banned list is the `BRIEF_WORDS` and `RULE_WORDS` constants in the script), plus em and en dashes, spaced hyphen dashes and exclamation marks in prose |
| 5 | Every signed log in `site/receipts/` and in the saved batch log folders with `verdock_core` `verify_log`; every buyer and merchant pair with `scripts/verify_pair.py`; the browser verifier `site/verify.js` run in Node (WebCrypto) over the same logs and compared with Python |
| 6 | `site/data/totals.json` re-derived with `scripts/build_site_data.py` and compared; each total found in its run file; every quantity in README.md and the site pages traced to a number in `data/runs/`; open placeholders such as `[BATCH_SETTLED]` and the lead's working note |
| 7 | `openapi/check_openapi.py` and `postman/check_collection.py` |
| 8 | Local links in README.md and `docs/*.md`; every local `href`, `src` and CSS `url()` of the site pages; `site/vercel.json` parses, the strict policy has no hashes, and the 14 fixed AG Grid style blocks, recomputed from the vendored file, are in both `site/vercel.json` and `AG_GRID_STYLE_HASHES` in `clearwake/server.py` |
| 9 | `git clone` of the local repo into a temporary folder outside the repo (submodules from the local checkouts, no network), then the Python tests, `python -m clearwake --help` and the Node tests in the clone; the folder is deleted afterwards |
| 10 | `docker --version`. Nothing is started |

## What the scans skip (allow lists)

All of it is named at the top of `scripts/final_check.py`.

* Secrets: vendored AG Grid bundles, fonts, test fixtures, pinned submodules, signed receipt logs (public keys and signatures), and the gate's own files. Values with a placeholder marker, and names that say public, hash, digest or signature, are skipped.
* Words: the prize name; words inside file names, paths, flags and code identifiers; fenced code blocks (dashes are still checked there); quoted third party text (blockquote lines and quoted spans) in `docs/TOOLKIT_FAILURE_CASES.md`, `docs/SOURCES.md`, `docs/REFERENCES.md`, `docs/THIRD_PARTY.md`; vendor files and fonts; this file. JavaScript, CSS and JSON are checked in strings and comments, not in identifiers or keys.

## Limits

* The clean clone holds the last commit. Uncommitted and ignored files are not in it, so run the gate again after the lead commits. Because `data/` is git ignored, tests that read `data/runs/` cannot pass in a clone; that is reported, not hidden.
* The 14 fixed AG Grid style blocks are recomputed; the other hashes in `site/vercel.json` cover blocks the grid writes after load and can only be rechecked in a browser.
* Docker is only detected. The network cut run (`scripts/airgap.py`) and the Dockerfiles are not exercised here.

## Last run

Run on 11 Nov 2026, 06:36 (file `data/runs/final-check-20261111-063643.json`), on the working tree while other agents were still editing.

**SUMMARY: 21 checks, 15 passed, 4 failed, 2 noted. FAILED: 1a, 4, 6b, 9a**

Passed: Node tests (14), secret scan (0 hits), ignore rules, author check (65 commits, one author), signed logs (14 of 14 verify in Python and in `site/verify.js` on Node), buyer and merchant pairs (5 of 5), numbers trace to run files, OpenAPI, Postman, local links (27 of 27), site assets (72 of 72), CSP hashes (14 of 14), clean clone `--help` and Node tests. Docker 28.1.1 is available (not used).

### Failures to chase

1. **1a Python tests: 417 ran, 1 failed.** `test_site_data.SiteDataTests.test_totals_come_from_the_run_files_and_a_rehearsal_batch_stays_out_of_the_public_set` expects different totals from the run files than `scripts/build_site_data.py` now derives. An earlier run of the gate also showed `test_console.ProductScopeTests.test_the_case_runner_labels_the_recorded_cases_outside_the_product_scope`; that one passes now.
2. **4 Word scan: 24 hits in 60 public files** (rehearsal 13, tried 5, attempt 2, demo 2, basic 1, try 1):
   * demo: `docs/CHANNEL3.md:37`, `docs/HACKATHON_UPDATES.md:58`
   * rehearsal: `docs/HACKATHON_UPDATES.md:29,37,42`; `site/docs.css:65` and `web/console.css:258` (comments); `web/console.js:209,252,286`; `web/payment.js:57,58,66,71` (mode label strings shown on the page)
   * tried: `docs/DESIGN_DECISIONS.md:13`, `docs/RESULTS.md:39`, `docs/THIRD_PARTY_UI.txt:35`, `site/control-room.html:212`, `site/developers.html:173`
   * attempt: `docs/CHANNEL3.md:19`, `docs/PLAIN_WORDS_RULES.md:32`
   * basic: `docs/REFERENCES.md:7` (Basic authentication, a quoted protocol name; add to the allow list if it stays)
   * try: `web/voice.js:180` ("Try again closer to the microphone")
   * Full list with line text: the JSON file.
3. **6b Open placeholders: 104.** README.md (`[BATCH_*]`, `[RENDER_URL]`, `[VIDEO_URL]`, `[MODEL_CALLS]`, `[MODEL_NAME]`, `[TESTS_PY]`, `[TESTS_UI]`, `[POSTMAN_RUN]`, and the working note for the lead at line 2), SUBMISSION_PAYPAL.md, and others. Full list in the JSON file.
4. **9a Clean clone Python tests: 354 ran, 3 failed.** All three are in `tests/test_site_data.py`:
   * `test_ledger_rows_are_the_recorded_sandbox_cases_with_proposals_read_from_receipts` and `test_totals_come_from_the_run_files_and_a_rehearsal_batch_stays_out_of_the_public_set` read `data/runs/`, which is git ignored, so they depend on untracked files.
   * `test_ag_grid_is_the_licensed_unchanged_vendor_build` fails in the clone only because the clone converted line endings of one vendored copy (a Windows `core.autocrlf` effect of the clone, not a repo difference). Adding `*.js -text` for the vendor files in `.gitattributes` would make it stable.
   * 38 modified and 13 untracked files are not in the clone because they are not committed yet.

### Fixed during this run

`openapi/check_openapi.py` failed because the spec lacked `GET /console/api/negotiation`, `GET /console/api/totals` and `POST /console/api/negotiate`. The three operations and the `Negotiation` and `Total` schemas were added to `openapi/clearwake-console.openapi.yaml` from `clearwake/server.py` and `clearwake/console.py`; the check now passes, including `--live` against real responses.
