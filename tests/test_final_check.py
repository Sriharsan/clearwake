"""The final gate's own scanners: they must catch what they claim to catch and skip only what the allow lists name.
Look-alike secrets are built from pieces so this file never holds one whole."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("final_check", ROOT / "scripts" / "final_check.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)

BANNED = ["de" + "mo", "mo" + "ck", "fa" + "ke", "sim" + "ple", "ear" + "ly", "be" + "ta", "pro" + "totype", "seam" + "less", "lever" + "age", "ro" + "bust", "ma" + "gic", "re" + "hearsal"]
EM, EN = "—", "–"


def scan(name, text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_text(text, encoding="utf-8")
        return fc.scan_public_file(p)


def labels(hits):
    return [h[1] for h in hits]


class SecretScan(unittest.TestCase):
    def rules(self, text, path="src/app.py"):
        return [r for _l, r, _n in fc.scan_secret_text(path, text)]

    def test_private_key_block_is_caught(self):
        text = "-" * 5 + "BEGIN RSA PRIVATE KEY" + "-" * 5 + "\nabc\n"
        self.assertIn("private key block", self.rules(text))

    def test_hugging_face_token_is_caught_and_a_short_one_is_not(self):
        self.assertIn("Hugging Face token", self.rules("t = '" + "hf" + "_" + "a" * 24 + "'"))
        self.assertEqual(self.rules("t = '" + "hf" + "_" + "a" * 5 + "'"), [])

    def test_paypal_secret_shape_and_assignment(self):
        self.assertIn("PayPal secret shape", self.rules("x = " + "E" + "A1b2" * 19 + "ZZZ"))
        self.assertIn("PayPal client secret assigned", self.rules("PAYPAL_CLIENT_" + "SECRET=" + "q" * 30))

    def test_channel3_and_sarvam_values(self):
        self.assertIn("Channel3 key value", self.rules("CHANNEL3_API_" + "KEY=" + "k" * 20))
        self.assertIn("Sarvam key", self.rules("k = " + "sk" + "_" + "a1" * 12))
        self.assertIn("Sarvam key assigned", self.rules("SARVAM_API_" + "KEY=" + "z" * 24))

    def test_empty_and_placeholder_values_pass(self):
        self.assertEqual(self.rules("PAYPAL_CLIENT_" + "SECRET="), [])
        self.assertEqual(self.rules("CHANNEL3_API_" + "KEY=your-key-here-please"), [])
        self.assertEqual(self.rules("HF_" + "TOKEN="), [])

    def test_long_base64_assigned_to_a_secret_name(self):
        value = "Ab3/" * 12
        self.assertIn("long credential assigned", self.rules('api_' + 'token = "' + value + '"'))
        self.assertEqual(self.rules('public_' + 'key = "' + "a" * 64 + '"'), [])
        self.assertEqual(self.rules('file_' + 'hash = "' + "a" * 64 + '"'), [])

    def test_allow_list_skips_vendor_and_fixtures_only(self):
        text = "t = '" + "hf" + "_" + "a" * 24 + "'"
        self.assertEqual(fc.scan_secret_text("site/vendor/x.js", text), [])
        self.assertEqual(fc.scan_secret_text("tests/fixtures/x.json", text), [])
        self.assertTrue(fc.scan_secret_text("clearwake/x.py", text))

    def test_a_hit_never_carries_the_value(self):
        value = "hf" + "_" + "S" * 26
        hits = fc.scan_secret_text("a.py", "t = '" + value + "'")
        self.assertTrue(hits)
        self.assertNotIn(value, json.dumps(hits))
        self.assertEqual(hits[0][2], len(value))

    def test_ignore_rule_regex(self):
        for bad in (".env", ".env.local", "data/buyer-profile/state.json", "data/voice-tls/k.pem", "x.sqlite3", "data/a.sqlite3-wal"):
            self.assertTrue(fc.TRACKED_BAD.match(bad), bad)
        for fine in (".env.example", "docs/env.md", "clearwake/store.py"):
            self.assertFalse(fc.TRACKED_BAD.match(fine), fine)


class WordScan(unittest.TestCase):
    def test_every_banned_word_is_caught_in_markdown_prose(self):
        for w in BANNED:
            self.assertTrue(any(l.startswith("word") for l in labels(scan("a.md", f"This is a {w} for you.\n"))), w)

    def test_multiword_terms(self):
        for phrase in ("game " + "changer", "cutting " + "edge", "next " + "gen", "AI " + "powered", "AI-" + "powered"):
            self.assertTrue(scan("a.md", f"A {phrase} tool.\n"), phrase)

    def test_dashes_and_exclamation(self):
        self.assertIn("dash", labels(scan("a.md", f"one {EM} two\n")))
        self.assertIn("dash", labels(scan("a.md", f"one {EN} two\n")))
        self.assertIn("exclamation", labels(scan("a.md", "It works!\n")))
        self.assertIn("spaced dash", labels(scan("a.md", "one - two\n")))

    def test_clean_prose_and_markup_that_is_not_prose(self):
        text = "# Title\n\n- a list item\n| a | b |\n|---|---|\n![img](x.png)\n<!-- note -->\n`a != b` and not equal\n"
        self.assertEqual(scan("a.md", text), [])

    def test_identifiers_paths_and_the_prize_name_are_allowed(self):
        w = BANNED[0]
        text = f"Run `{w}.ps1` or scripts/check_{w}.py or --{BANNED[-1]} or the Best Demo Delivery prize.\n"
        self.assertEqual(scan("a.md", text), [])

    def test_fenced_code_skips_words_and_bangs_but_not_dashes(self):
        text = f"```sh\necho {BANNED[0]} now!\n```\n"
        self.assertEqual(scan("a.md", text), [])
        self.assertIn("dash", labels(scan("a.md", f"```\na {EM} b\n```\n")))

    def test_quoted_third_party_text_is_allowed_only_in_the_named_files(self):
        w = BANNED[1]
        quoted = f'> The vendor says {w} everywhere.\nShe wrote "{w} data" there.\n'
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs"
            docs.mkdir()
            p = docs / "TOOLKIT_FAILURE_CASES.md"
            p.write_text(quoted, encoding="utf-8")
            old = fc.ROOT
            fc.ROOT = Path(d)
            try:
                self.assertEqual(fc.scan_public_file(p), [])
                q = docs / "OTHER.md"
                q.write_text(quoted, encoding="utf-8")
                self.assertTrue(fc.scan_public_file(q))
            finally:
                fc.ROOT = old

    def test_html_scripts_and_styles_are_not_prose_but_visible_attributes_are(self):
        w = BANNED[0]
        page = f'<html><head><style>.{w}{{color:red}}</style><script>var {w}=1;</script></head><body><p>Fine words.</p><img alt="a {w} image" src="x.png"></body></html>'
        got = scan("a.html", page)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][1], "word: " + w)

    def test_html_reports_the_right_line(self):
        got = scan("a.html", "<p>ok</p>\n<p>\nhere is a " + BANNED[3] + " thing\n</p>\n")
        self.assertEqual([h[0] for h in got], [3])

    def test_js_checks_strings_not_identifiers_and_flags_dashes_anywhere(self):
        w = BANNED[0]
        js = f"const {w}Mode = 1;\nconst label = 'A {w} view';\nconst x = '{w}_mode';\n// a {EM} b\n"
        got = scan("a.js", js)
        self.assertEqual(sorted((h[0], h[1]) for h in got), [(2, "word: " + w), (4, "dash")])

    def test_json_keys_are_skipped_and_values_are_checked(self):
        w = BANNED[0]
        got = scan("a.json", json.dumps({w: "fine", "label": f"a {w} run"}, indent=1))
        self.assertEqual([h[1] for h in got], ["word: " + w])

    def test_css_comments_are_checked_selectors_are_not(self):
        w = BANNED[1]
        got = scan("a.css", f".{w}-box {{ color: red; }}\n/* a {w} colour */\n")
        self.assertEqual([h[0] for h in got], [2])

    def test_the_documentation_file_for_this_gate_is_not_scanned(self):
        self.assertIn("docs/FINAL_CHECK.md", fc.NOT_SCANNED)


class Numbers(unittest.TestCase):
    def test_quantities_found_and_traced(self):
        pool = {fc.to_dec("5").normalize(), fc.to_dec("10").normalize()}
        self.assertEqual(fc.untraced("5 of 10 settled\n", pool), [])
        bad = fc.untraced("7 of 10 settled and 3 episodes\n", pool)
        self.assertEqual(len(bad), 2)

    def test_pool_includes_minor_unit_conversion(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "run.json"
            p.write_text(json.dumps({"summary": {"overpaid_minor": 263325, "a": 1, "b": 2}}), encoding="utf-8")
            pool = fc.number_pool([p])
        self.assertIn(fc.to_dec("2633.25").normalize(), pool)
        self.assertIn(fc.to_dec("3").normalize(), pool)  # 1 + 2 inside one summary

    def test_placeholder_pattern(self):
        self.assertTrue(fc.PLACEHOLDER.search("filled from [BATCH_SETTLED] later"))
        self.assertFalse(fc.PLACEHOLDER.search("see [docs](docs/x.md) and [1]"))


class Parsers(unittest.TestCase):
    def test_unittest_output(self):
        out = "FAIL: test_a (tests.test_x.T)\nERROR: test_b (tests.test_y.T)\n\nRan 12 tests in 1.0s\n\nFAILED (failures=1, errors=1)\n"
        count, ok, failing = fc.parse_unittest(out)
        self.assertEqual((count, ok, len(failing)), (12, False, 2))
        self.assertTrue(fc.parse_unittest("Ran 3 tests in 0.1s\n\nOK\n")[1])

    def test_node_output(self):
        out = "# tests 12\n# pass 12\n# fail 0\n"
        self.assertEqual(fc.parse_node(out), (12, 12, 0))
        self.assertEqual(fc.parse_node("ℹ tests 7\nℹ pass 6\nℹ fail 1\n"), (7, 6, 1))


class Links(unittest.TestCase):
    def test_markdown_link_pattern(self):
        got = fc.MD_LINK.findall("see [a](docs/A.md), ![i](img/x.png \"t\") and [web](https://x.y)")
        self.assertEqual(got, ["docs/A.md", "img/x.png", "https://x.y"])

    def test_site_targets_follow_clean_urls(self):
        self.assertTrue(fc.site_target_exists(fc.SITE / "index.html", "/control-room"))
        self.assertTrue(fc.site_target_exists(fc.SITE / "index.html", "developers"))
        self.assertFalse(fc.site_target_exists(fc.SITE / "index.html", "/no-such-page"))


class StyleHashes(unittest.TestCase):
    def test_template_cooking(self):
        bs = chr(92)
        self.assertEqual(fc.cook_template("a" + bs + "nb" + bs + bs + "c" + bs + "u0041"), "a\nb" + bs + "cA")

    def test_the_fixed_blocks_of_the_vendored_grid_are_found(self):
        hashes = fc.ag_grid_static_hashes(ROOT / "site" / "vendor" / "ag-grid-community-35.3.1.min.js")
        self.assertEqual(len(hashes), 14)


if __name__ == "__main__":
    unittest.main()
