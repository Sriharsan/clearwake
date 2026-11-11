"""scripts/fill_placeholders.py on temporary files: derived values, the rules for which run file counts, dry run, apply and check."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fill_placeholders", ROOT / "scripts" / "fill_placeholders.py")
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)


def batch(mode="sandbox", error=0, settled=6, name_rows=None):
    rows = name_rows or [
        {"n": 1, "scenario": "delivered with proof", "outcome": "evidence_sent", "dispute_id": "PP-R-AAA-1", "paypal_status": "UNDER_REVIEW"},
        {"n": 2, "scenario": "not shipped", "outcome": "settled_inquiry_no_fee", "dispute_id": "PP-R-BBB-2", "page_dispute_id": "PP-R-BBB-2", "paypal_status": "RESOLVED"},
        {"n": 3, "scenario": "lost", "outcome": "settled_inquiry_no_fee", "dispute_id": "PP-R-CCC-3", "paypal_status": "RESOLVED"},
    ]
    if error:
        rows = rows + [{"n": 4, "scenario": "x", "outcome": "error"}]
    return {"mode": mode, "merchant_agent": "qwen3.5:4b via Ollama", "cases": rows, "logs": {"merchant": "m.ndjson"},
            "summary": {"cases": 10, "settled_inquiry_no_fee": settled, "evidence_sent": 2, "escalated_to_buyer_owner": 0, "escalated_to_merchant_owner": 1,
                        "handled_by_mandate": 1, "error": error, "refunds_confirmed_by_paypal": 6, "seconds_per_case": 41.256,
                        "result": {"fees": 0, "double_refunds": 0, "text": "6 of 10 settled by agents inside the limits, 4 correctly handed to a person, 0 fees, 0 double refunds, median 0.7 minutes"}}}


def model_call(dispute, proposed, decided, overridden):
    return json.dumps({"action_id": "clearwake.model.call", "params": {"dispute": dispute, "proposed": proposed, "decided": decided, "overridden": overridden}})


class Fill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runs = self.root / "data" / "runs"
        self.runs.mkdir(parents=True)
        (self.root / "docs").mkdir()

    def write(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
        return p

    def run_json(self, name, data):
        return self.write(f"data/runs/{name}", json.dumps(data))

    def src(self, **kw):
        return fp.Source(self.root, self.runs, **kw)

    def go(self, *argv, files=("a.md",)):
        lines = []
        code = fp.run(list(argv), root=self.root, runs=self.runs, files=files, out=lines.append)
        return code, "\n".join(lines)

    # which batch counts ---------------------------------------------------------------------------------------------
    def test_no_batch_file_says_which_file_is_missing(self):
        with self.assertRaises(fp.Missing) as why:
            self.src().batch()
        self.assertIn("batch-sandbox-*.json", str(why.exception))

    def test_a_local_run_batch_never_counts(self):
        self.run_json("batch-local-20261111-100000.json", batch(mode="local"))
        self.run_json("batch-sandbox-20261111-110000.json", batch(mode="local"))
        with self.assertRaises(fp.Missing) as why:
            self.src().batch()
        self.assertIn("not the real sandbox", str(why.exception))

    def test_the_newest_batch_with_error_rows_is_skipped_for_an_older_clean_one(self):
        self.run_json("batch-sandbox-20261111-090000.json", batch(settled=7))
        self.run_json("batch-sandbox-20261111-120000.json", batch(error=1))
        path, _ = self.src().batch()
        self.assertEqual(path.name, "batch-sandbox-20261111-090000.json")
        self.assertEqual(self.src().summary("settled_inquiry_no_fee"), 7)

    def test_the_newest_clean_batch_wins(self):
        self.run_json("batch-sandbox-20261111-090000.json", batch(settled=5))
        self.run_json("batch-sandbox-20261111-120000.json", batch(settled=8))
        self.assertEqual(self.src().summary("settled_inquiry_no_fee"), 8)

    def test_derived_batch_values(self):
        self.run_json("batch-sandbox-20261111-120000.json", batch())
        values = fp.derive(self.src(), {})
        self.assertEqual(values["BATCH_TOTAL"][0], "10")
        self.assertEqual(values["BATCH_SETTLED"][0], "6")
        self.assertEqual(values["BATCH_ESCALATED"][0], "2")
        self.assertEqual(values["BATCH_SECONDS_PER_CASE"][0], "41.3")
        self.assertEqual(values["BATCH_FEES"][0], "0")
        self.assertEqual(values["HERO_DISPUTE_ID"][0], "PP-R-BBB-2")
        self.assertEqual(values["BATCH_RUN_FILE"][0], "data/runs/batch-sandbox-20261111-120000.json")
        self.assertTrue(values["BATCH_RESULT_LINE"][0].startswith("6 of 10 settled"))

    def test_a_missing_field_is_named_and_never_filled(self):
        data = batch()
        del data["summary"]["evidence_sent"]
        self.run_json("batch-sandbox-20261111-120000.json", data)
        value, note = fp.derive(self.src(), {})["BATCH_EVIDENCE"]
        self.assertIsNone(value)
        self.assertIn("summary.evidence_sent", note)

    # the overruled model call ---------------------------------------------------------------------------------------
    def test_overruled_example_comes_from_the_merchant_log(self):
        self.run_json("batch-sandbox-20261111-120000.json", batch())
        self.write("data/runs/m.ndjson", "\n".join([model_call("PP-R-AAA-1", "fight_with_evidence", "fight_with_evidence", False),
                                                    model_call("PP-R-CCC-3", "settle_by_offer", "escalate", True)]))
        example, caption = self.src().overruled()
        self.assertIn("case 3", example)
        self.assertIn("PP-R-CCC-3", example)
        self.assertEqual(caption, "The model proposed settle_by_offer. The policy stopped it and decided escalate.")

    def test_no_overruled_call_is_not_invented(self):
        self.run_json("batch-sandbox-20261111-120000.json", batch())
        self.write("data/runs/m.ndjson", model_call("PP-R-AAA-1", "a", "a", False))
        self.assertIsNone(fp.derive(self.src(), {})["OVERRULED_EXAMPLE"][0])

    # model ----------------------------------------------------------------------------------------------------------
    def eval_file(self, name, totals, mode="local"):
        self.run_json(name, {"mode": mode, "totals": totals})

    def test_model_values_come_from_the_newest_ai_eval_and_skip_the_real_record(self):
        self.eval_file("ai-eval-local-20261110-070000.json", {"old:1b": {"calls": 5, "total_ms": 50}})
        self.eval_file("ai-eval-local-20261111-070000.json", {"qwen3.5:4b": {"calls": 42, "total_ms": 1030000}})
        self.eval_file("ai-eval-real-record-20261111-090000.json", {"other:9b": {"calls": 1, "total_ms": 1}}, mode="real sandbox record, read only")
        values = fp.derive(self.src(), {})
        self.assertEqual(values["MODEL_NAME"][0], "qwen3.5:4b")
        self.assertEqual(values["MODEL_TAG"][0], "qwen3.5-4b")
        self.assertEqual(values["MODEL_CALLS"][0], "42")
        self.assertEqual(values["MODEL_MS_PER_CALL"][0], "24,524")

    def test_two_models_need_a_choice(self):
        self.eval_file("ai-eval-local-20261111-070000.json", {"a:1b": {"calls": 1, "total_ms": 1}, "b:2b": {"calls": 2, "total_ms": 2}})
        self.assertIsNone(fp.derive(self.src(), {})["MODEL_NAME"][0])
        self.assertEqual(fp.derive(self.src(model="b:2b"), {})["MODEL_CALLS"][0], "2")

    def test_a_model_that_differs_from_the_results_page_is_warned(self):
        self.eval_file("ai-eval-local-20261111-070000.json", {"small:3b": {"calls": 1, "total_ms": 1}})
        self.write("docs/RESULTS.md", "The model used is big:4b: it proposed the right action.\n")
        source = self.src()
        source.model_stats()
        self.assertTrue(any("big:4b" in w for w in source.warnings))

    # tests ----------------------------------------------------------------------------------------------------------
    def final_check(self, name, status_py="PASS", count_py=420):
        self.run_json(name, {"checks": [{"id": "1a", "name": "Python tests", "status": status_py, "summary": "s", "data": {"count": count_py}},
                                         {"id": "1b", "name": "Node tests", "status": "PASS", "summary": "s", "data": {"count": 14}}]})

    def test_test_counts_come_from_the_newest_final_check_only_when_it_passed(self):
        self.final_check("final-check-20261110-100000.json", count_py=300)
        self.final_check("final-check-20261111-100000.json", status_py="FAIL", count_py=417)
        values = fp.derive(self.src(), {})
        self.assertIsNone(values["TESTS_PY"][0])
        self.assertIn("FAIL", values["TESTS_PY"][1])
        self.assertEqual(values["TESTS_UI"][0], "14")
        self.final_check("final-check-20261111-110000.json", count_py=420)
        self.assertEqual(fp.derive(self.src(), {})["TESTS_PY"][0], "420")

    def test_test_output_parsers(self):
        self.assertEqual(fp.parse_unittest("....\nRan 420 tests in 3.1s\n\nOK\n"), 420)
        self.assertIsNone(fp.parse_unittest("Ran 420 tests in 3.1s\n\nFAILED (failures=1)\n"))
        self.assertEqual(fp.parse_node("# tests 14\n# pass 14\n# fail 0\n"), 14)
        self.assertIsNone(fp.parse_node("# tests 14\n# pass 13\n# fail 1\n"))

    # owners ---------------------------------------------------------------------------------------------------------
    def test_constants_and_people_owned_values(self):
        values = fp.derive(self.src(), {})
        self.assertEqual(values["RENDER_URL"][0], "https://clearwake-console.onrender.com")
        self.assertEqual(values["SITE_URL"][0], "https://clearwake-mu.vercel.app")
        for name in ("VIDEO_URL", "APIMATIC_PORTAL_URL", "APIMATIC_RESULT", "APIMATIC_EXPERIENCE", "POSTMAN_RUN"):
            self.assertIsNone(values[name][0])
            self.assertIn("needs Sri", values[name][1])
        self.assertIn("needs the lead", values["TOOLKIT_TOOLS_CONFIRMED"][1])

    # files ----------------------------------------------------------------------------------------------------------
    def test_dry_run_changes_nothing_and_apply_fills_only_what_is_known(self):
        self.run_json("batch-sandbox-20261111-120000.json", batch())
        text = "Settled [BATCH_SETTLED] of [BATCH_TOTAL] at [RENDER_URL]/console. Video [VIDEO_URL]. <!-- keep [BATCH_TOTAL] -->\r\n"
        a = self.write("a.md", text)
        code, out = self.go()
        self.assertEqual(code, 0)
        self.assertEqual(a.read_bytes().decode("utf-8"), text)
        self.assertIn("DRY RUN", out)
        self.assertIn("needs Sri: VIDEO_URL", out)
        code, out = self.go("--apply")
        self.assertEqual(a.read_bytes().decode("utf-8"),
                         "Settled 6 of 10 at https://clearwake-console.onrender.com/console. Video [VIDEO_URL]. <!-- keep [BATCH_TOTAL] -->\r\n")

    def test_apply_without_a_batch_file_leaves_the_batch_brackets(self):
        a = self.write("a.md", "[BATCH_SETTLED] of [BATCH_TOTAL] at [RENDER_URL]\n")
        code, out = self.go("--apply")
        self.assertEqual(a.read_text(encoding="utf-8"), "[BATCH_SETTLED] of [BATCH_TOTAL] at https://clearwake-console.onrender.com\n")
        self.assertIn("batch-sandbox-*.json", out)

    def test_set_fills_a_value_a_person_owns_and_rejects_unknown_names(self):
        a = self.write("a.md", "Video [VIDEO_URL]\n")
        self.assertEqual(self.go("--apply", "--set", "VIDEO_URL=https://youtu.be/abc")[0], 0)
        self.assertEqual(a.read_text(encoding="utf-8"), "Video https://youtu.be/abc\n")
        self.assertEqual(self.go("--apply", "--set", "NOT_A_NAME=x")[0], 2)

    def test_a_missing_file_is_noted_not_fatal(self):
        code, out = self.go(files=("nowhere.md",))
        self.assertEqual(code, 0)
        self.assertIn("file not found", out)

    def test_unregistered_bracket_is_reported(self):
        self.write("a.md", "See [SOME_NEW_THING] now\n")
        code, out = self.go()
        self.assertIn("NOT REGISTERED", out)
        self.assertEqual(self.go("--check")[0], 1)

    def test_check_passes_when_only_sri_owned_brackets_remain(self):
        self.write("a.md", "Video [VIDEO_URL] and [POSTMAN_RUN] <!-- [BATCH_TOTAL] -->\n")
        code, out = self.go("--check")
        self.assertEqual(code, 0)
        self.assertIn("needs Sri: [VIDEO_URL]", out)

    def test_check_fails_on_a_batch_or_lead_bracket(self):
        self.write("a.md", "Settled [BATCH_SETTLED]\n")
        code, out = self.go("--check")
        self.assertEqual(code, 1)
        self.assertIn("OPEN (auto): [BATCH_SETTLED]", out)
        self.write("a.md", "Tools [TOOLKIT_TOOLS_CONFIRMED]\n")
        self.assertEqual(self.go("--check")[0], 1)

    def test_every_placeholder_in_the_real_files_is_registered(self):
        for name in fp.FILES:
            path = fp.resolve_files([name], ROOT)[0]
            if path.is_file():
                for found in fp.scan(path):
                    self.assertIn(found, fp.BY_NAME, f"{found} in {path}")


if __name__ == "__main__":
    unittest.main()
