"""List, fill and check every [PLACEHOLDER] in the submission text.

  python scripts/fill_placeholders.py                       dry run: every placeholder, its value, where it is used
  python scripts/fill_placeholders.py --apply               write the derived values into the files
  python scripts/fill_placeholders.py --apply --set VIDEO_URL=https://youtu.be/...   fill one that a person owns
  python scripts/fill_placeholders.py --check               exit 1 if any bracket is left, except those Sri owns
  python scripts/fill_placeholders.py --run-tests           count the tests by running them instead of reading a final-check file

Every value comes from a recorded file under data/runs/ or from a constant below. Nothing is made up: a value that cannot
be derived stays in brackets and the script says which file or field is missing. Placeholders inside HTML comments are left alone.
"""
from dataclasses import dataclass
from pathlib import Path
import argparse
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
ENTRY = Path(r"D:\paypal hackathon\DEVPOST_ENTRY.md")
FILES = ("README.md", "SUBMISSION_PAYPAL.md", "docs/DEVPOST_FORM.md", ENTRY, "VIDEO_SCRIPT.md", "BUILT_DURING_HACKATHON.md", "docs/RENDER.md")

RENDER_URL = "https://clearwake-console.onrender.com"
SITE_URL = "https://clearwake-mu.vercel.app"

TOKEN = re.compile(r"(<!--.*?-->)|\[([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\]", re.S)   # group 1 is a comment, left alone
STAMP = re.compile(r"(\d{8}-\d{6})")


class Missing(Exception):
    """A value cannot be derived. The message says which file or field is missing."""


def newest_first(paths):
    def key(p):
        found = STAMP.search(p.name)
        return (found.group(1) if found else "", p.stat().st_mtime)
    return sorted(paths, key=key, reverse=True)


def digits(n):
    return f"{int(n):,}"


class Source:
    def __init__(self, root=ROOT, runs=None, model=None, run_tests=False):
        self.root, self.runs = Path(root), Path(runs) if runs else Path(root) / "data" / "runs"
        self.model, self.run_tests = model, run_tests
        self.warnings, self._cache = [], {}

    def load(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def files(self, pattern):
        return newest_first(p for p in self.runs.glob(pattern) if p.is_file())

    # batch ----------------------------------------------------------------------------------------------------------
    def batch(self):
        if "batch" in self._cache:
            return self._cache["batch"]
        found = self.files("batch-sandbox-*.json")
        if not found:
            raise Missing(f"no {self.runs}/batch-sandbox-*.json yet (the real ten case batch has not been recorded)")
        reasons = []
        for path in found:
            try:
                data = self.load(path)
            except (OSError, ValueError) as error:
                reasons.append(f"{path.name}: unreadable ({error})")
                continue
            rows = data.get("cases") or []
            summary = data.get("summary") or {}
            if data.get("mode") != "sandbox":
                reasons.append(f"{path.name}: mode is {data.get('mode')!r}, not the real sandbox")
            elif not rows or not summary:
                reasons.append(f"{path.name}: no case rows or no summary")
            elif summary.get("error") or any(r.get("outcome") == "error" for r in rows):
                reasons.append(f"{path.name}: has error rows")
            else:
                self._cache["batch"] = (path, data)
                return self._cache["batch"]
        raise Missing("no eligible batch-sandbox-*.json (needs mode sandbox and no error rows): " + "; ".join(reasons))

    def summary(self, *keys):
        path, data = self.batch()
        node = data.get("summary") or {}
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                raise Missing(f"field summary.{'.'.join(keys)} is missing in {path.name}")
            node = node[key]
        return node

    def settled_row(self):
        path, data = self.batch()
        rows = [r for r in data["cases"] if r.get("outcome") == "settled_inquiry_no_fee" and r.get("dispute_id")]
        if not rows:
            raise Missing(f"no settled case row with a dispute_id in {path.name}")
        rows.sort(key=lambda r: (r.get("paypal_status") != "RESOLVED", r.get("n", 0)))
        return rows[0]

    def overruled(self):
        """The first model call the policy overrode: from the merchant receipts of the batch, else the buyer agent's model rows."""
        path, data = self.batch()
        rows = {}
        for r in data["cases"]:
            for key in ("dispute_id", "page_dispute_id"):
                if r.get(key):
                    rows[r[key]] = r
        log = (data.get("logs") or {}).get("merchant")
        if log and (path.parent / log).is_file():
            for line in (path.parent / log).read_text(encoding="utf-8").splitlines():
                try:
                    receipt = json.loads(line)
                except ValueError:
                    continue
                p = receipt.get("params") or {}
                if receipt.get("action_id") == "clearwake.model.call" and p.get("overridden") and p.get("dispute") in rows:
                    row = rows[p["dispute"]]
                    return (f"case {row['n']} ({row.get('scenario', '')}), dispute {p['dispute']}",
                            f"The model proposed {p.get('proposed')}. The policy stopped it and decided {p.get('decided')}.")
        for r in data["cases"]:
            for m in r.get("buyer_model") or []:
                if m.get("proposed") != m.get("final"):
                    return (f"case {r['n']} ({r.get('scenario', '')}), dispute {r.get('dispute_id', '')}",
                            f"The buyer agent's model proposed {m['proposed']}. The owner's rule stopped it and decided {m['final']}.")
        raise Missing(f"no model proposal overridden by the policy in {path.name} or its merchant log")

    # model ----------------------------------------------------------------------------------------------------------
    def model_stats(self):
        if "model" in self._cache:
            return self._cache["model"]
        found = [p for p in self.files("ai-eval-*.json") if "real" not in p.name]
        if not found:
            raise Missing(f"no {self.runs}/ai-eval-*.json")
        path = found[0]
        totals = self.load(path).get("totals") or {}
        if self.model:
            if self.model not in totals:
                raise Missing(f"model {self.model} is not in {path.name} (it holds {', '.join(totals) or 'nothing'})")
            name = self.model
        elif len(totals) == 1:
            name = next(iter(totals))
        else:
            raise Missing(f"{path.name} holds {len(totals)} models ({', '.join(totals)}): name one with --model")
        self._cache["model"] = (path, name, totals[name])
        results = self.root / "docs" / "RESULTS.md"
        if results.is_file():
            said = re.search(r"The model used is ([\w.:\-]+?)[:.,]?\s", results.read_text(encoding="utf-8"))
            if said and said.group(1) != name:
                self.warnings.append(f"docs/RESULTS.md says the model used is {said.group(1)!r} but the newest ai-eval model is {name!r}")
        try:
            agent = self.batch()[1].get("merchant_agent", "")
            if agent and not agent.startswith(name):
                self.warnings.append(f"the batch merchant agent is {agent!r} but the newest ai-eval model is {name!r}")
        except Missing:
            pass
        return self._cache["model"]

    def model_field(self, key):
        path, name, stats = self.model_stats()
        if key not in stats:
            raise Missing(f"field totals.{name}.{key} is missing in {path.name}")
        return stats[key]

    # tests ----------------------------------------------------------------------------------------------------------
    def tests(self, check_id, name, command, parser):
        if self.run_tests:
            done = subprocess.run(command, cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            count = parser(done.stdout + done.stderr)
            if done.returncode != 0 or count is None:
                raise Missing(f"{name} did not pass when run ({' '.join(command)}, exit {done.returncode})")
            return str(count)
        found = self.files("final-check-*.json")
        if not found:
            raise Missing(f"no {self.runs}/final-check-*.json (run scripts/final_check.py, or use --run-tests)")
        data = self.load(found[0])
        check = next((c for c in data.get("checks", []) if c.get("id") == check_id), None)
        if not check:
            raise Missing(f"check {check_id} is not in {found[0].name}")
        if check.get("status") != "PASS":
            raise Missing(f"{found[0].name} check {check_id} ({name}) is {check.get('status')}: {check.get('summary')}. Fix it and rerun scripts/final_check.py, or use --run-tests")
        return str((check.get("data") or {}).get("count") or "")


def parse_unittest(text):
    ran = re.search(r"^Ran (\d+) tests?", text, re.M)
    return int(ran.group(1)) if ran and re.search(r"^OK", text, re.M) else None


def parse_node(text):
    tests = re.search(r"^\W*(?:#|ℹ)\s*tests\s+(\d+)", text, re.M)
    passed = re.search(r"^\W*(?:#|ℹ)\s*pass\s+(\d+)", text, re.M)
    return int(tests.group(1)) if tests and passed and tests.group(1) == passed.group(1) else None


@dataclass(frozen=True)
class Placeholder:
    name: str
    owner: str            # auto (a run file), constant, sri, lead
    source: str           # where the value comes from, in words
    fmt: str
    resolve: object = None   # callable(Source) -> str, or None when a person owns it


def _batch_run_file(s):
    path, _ = s.batch()
    try:
        return path.relative_to(s.root).as_posix()
    except ValueError:
        return f"data/runs/{path.name}"


def _escalated(s):
    return str(sum(int(s.summary(k)) for k in ("escalated_to_buyer_owner", "escalated_to_merchant_owner", "handled_by_mandate")))


REGISTRY = (
    Placeholder("BATCH_TOTAL", "auto", "newest batch-sandbox-*.json, mode sandbox, no error rows: summary.cases", "integer", lambda s: str(s.summary("cases"))),
    Placeholder("BATCH_SETTLED", "auto", "same file: summary.settled_inquiry_no_fee", "integer", lambda s: str(s.summary("settled_inquiry_no_fee"))),
    Placeholder("BATCH_EVIDENCE", "auto", "same file: summary.evidence_sent", "integer", lambda s: str(s.summary("evidence_sent"))),
    Placeholder("BATCH_ESCALATED", "auto", "same file: summary.escalated_to_buyer_owner + escalated_to_merchant_owner + handled_by_mandate", "integer", _escalated),
    Placeholder("BATCH_REFUNDS", "auto", "same file: summary.refunds_confirmed_by_paypal", "integer", lambda s: str(s.summary("refunds_confirmed_by_paypal"))),
    Placeholder("BATCH_FEES", "auto", "same file: summary.result.fees", "integer", lambda s: str(s.summary("result", "fees"))),
    Placeholder("BATCH_DOUBLE_REFUNDS", "auto", "same file: summary.result.double_refunds", "integer", lambda s: str(s.summary("result", "double_refunds"))),
    Placeholder("BATCH_SECONDS_PER_CASE", "auto", "same file: summary.seconds_per_case", "one decimal", lambda s: f"{float(s.summary('seconds_per_case')):.1f}"),
    Placeholder("BATCH_RESULT_LINE", "auto", "same file: summary.result.text", "sentence", lambda s: str(s.summary("result", "text"))),
    Placeholder("BATCH_RUN_FILE", "auto", "the eligible batch file itself", "path under data/runs/", _batch_run_file),
    Placeholder("HERO_DISPUTE_ID", "auto", "same file: dispute_id of the first case row that settled at INQUIRY", "PayPal dispute id", lambda s: str(s.settled_row()["dispute_id"])),
    Placeholder("OVERRULED_EXAMPLE", "auto", "the merchant log of the batch: first clearwake.model.call with overridden true (else the buyer model rows)", "case, scenario, dispute id", lambda s: s.overruled()[0]),
    Placeholder("OVERRULED_CAPTION", "auto", "same receipt: proposed and decided", "sentence", lambda s: s.overruled()[1]),
    Placeholder("MODEL_NAME", "auto", "newest ai-eval-*.json (not the real record file): the model in totals", "Ollama model name", lambda s: s.model_stats()[1]),
    Placeholder("MODEL_TAG", "auto", "same model name", "lower case, colon becomes a dash", lambda s: re.sub(r"[^a-z0-9.]+", "-", s.model_stats()[1].lower()).strip("-")),
    Placeholder("MODEL_CALLS", "auto", "same file: totals.<model>.calls", "integer", lambda s: str(s.model_field("calls"))),
    Placeholder("MODEL_MS_PER_CALL", "auto", "same file: totals.<model>.total_ms divided by calls", "integer with thousands comma", lambda s: digits(round(s.model_field("total_ms") / s.model_field("calls")))),
    Placeholder("TESTS_PY", "auto", "newest final-check-*.json check 1a (must be PASS), or --run-tests", "integer",
                lambda s: s.tests("1a", "Python tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"], parse_unittest)),
    Placeholder("TESTS_UI", "auto", "newest final-check-*.json check 1b (must be PASS), or --run-tests", "integer",
                lambda s: s.tests("1b", "Node tests", ["node", "--test", "--test-reporter=tap", "tests/console.test.cjs", "tests/payment.test.cjs"], parse_node)),
    Placeholder("RENDER_URL", "constant", "docs/RENDER.md: the service name in render.yaml", "https URL, no slash", lambda s: RENDER_URL),
    Placeholder("SITE_URL", "constant", "the Vercel project", "https URL, no slash", lambda s: SITE_URL),
    Placeholder("VIDEO_URL", "sri", "the public YouTube link, after Sri uploads", "https URL", None),
    Placeholder("APIMATIC_PORTAL_URL", "sri", "Sri's APIMatic portal link", "https URL", None),
    Placeholder("APIMATIC_RESULT", "sri", "what Sri's APIMatic run showed (docs/APIMATIC.md log tables)", "one or two sentences", None),
    Placeholder("APIMATIC_EXPERIENCE", "sri", "Sri's own words on using APIMatic", "a short paragraph", None),
    Placeholder("POSTMAN_RUN", "sri", "result of Sri's Newman or Postman CLI run (docs/POSTMAN.md)", "one line with counts", None),
    Placeholder("TOOLKIT_TOOLS_CONFIRMED", "lead", "the lead's captured tools/list output of PayPal's toolkit server", "one sentence", None),
)
BY_NAME = {p.name: p for p in REGISTRY}


def resolve_files(files, root):
    out = []
    for f in files:
        p = Path(f)
        out.append(p if p.is_absolute() else Path(root) / p)
    return out


def scan(path):
    """Placeholder names in a file, outside HTML comments, in order."""
    text = Path(path).read_text(encoding="utf-8", newline="")
    return [m.group(2) for m in TOKEN.finditer(text) if m.group(2)]


def derive(source, overrides):
    """name -> (value or None, note). A person's value from --set beats a derived one."""
    out = {}
    for p in REGISTRY:
        if p.name in overrides:
            out[p.name] = (overrides[p.name], "set by hand")
        elif p.resolve is None:
            out[p.name] = (None, f"needs {'Sri' if p.owner == 'sri' else 'the lead'}: {p.source}")
        else:
            try:
                out[p.name] = (p.resolve(source), "derived")
            except Missing as why:
                out[p.name] = (None, f"unfilled: {why}")
            except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as error:
                out[p.name] = (None, f"unfilled: {type(error).__name__}: {error}")
    return out


def apply_file(path, values):
    text = Path(path).read_text(encoding="utf-8", newline="")
    count = [0]

    def swap(m):
        if m.group(1) or values.get(m.group(2)) in (None, ""):
            return m.group(0)
        count[0] += 1
        return values[m.group(2)]
    new = TOKEN.sub(swap, text)
    if new != text:
        Path(path).write_text(new, encoding="utf-8", newline="")
    return count[0]


def run(argv=None, root=ROOT, runs=None, files=FILES, out=print):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the values into the files (the default is a dry run)")
    ap.add_argument("--check", action="store_true", help="exit 1 if a bracket is left, except those Sri owns")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="a value a person supplies, for example VIDEO_URL=https://...")
    ap.add_argument("--model", help="the model to report when the newest ai-eval holds several")
    ap.add_argument("--run-tests", action="store_true", help="count tests by running them instead of reading a final-check file")
    args = ap.parse_args(argv)
    paths = resolve_files(files, root)
    present = [p for p in paths if p.is_file()]
    for p in paths:
        if not p.is_file():
            out(f"note: file not found, skipped: {p}")
    if args.check:
        return check(present, out)
    overrides = {}
    for item in args.set:
        name, _, value = item.partition("=")
        if name not in BY_NAME or not value.strip():
            out(f"error: --set needs NAME=VALUE with a registered name, got {item!r}")
            return 2
        overrides[name] = value.strip()
    source = Source(root, runs, args.model, args.run_tests)
    values = derive(source, overrides)
    uses = {p.name: {} for p in REGISTRY}
    unregistered = {}
    for f in present:
        for name in scan(f):
            table = uses[name] if name in uses else unregistered.setdefault(name, {})
            table[f.name] = table.get(f.name, 0) + 1
    out(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(REGISTRY)} registered placeholders in {len(present)} file(s)")
    for p in REGISTRY:
        value, note = values[p.name]
        where = ", ".join(f"{n} x{c}" for n, c in uses[p.name].items()) or "not used in any file"
        out(f"  [{p.name}] ({p.owner}) {'= ' + value if value is not None else note}")
        out(f"      from: {p.source}; format: {p.fmt}; used in: {where}")
    for name, where in unregistered.items():
        out(f"  [{name}] NOT REGISTERED, add it to REGISTRY; used in: {', '.join(f'{n} x{c}' for n, c in where.items())}")
    for w in source.warnings:
        out(f"warning: {w}")
    if args.apply:
        usable = {k: v for k, (v, _) in values.items() if v}
        for f in present:
            n = apply_file(f, usable)
            out(f"  wrote {n} value(s) into {f}" if n else f"  no change in {f}")
    left = {k: v for k, (v, _) in values.items() if not v}
    sri = [k for k in left if BY_NAME[k].owner == "sri"]
    lead = [k for k in left if BY_NAME[k].owner == "lead"]
    other = [k for k in left if k not in sri and k not in lead]
    if sri:
        out("needs Sri: " + ", ".join(sri) + "  (fill with --apply --set NAME=VALUE)")
    if lead:
        out("needs the lead: " + ", ".join(lead))
    if other:
        out("not derivable yet: " + ", ".join(other))
    return 0


def check(present, out):
    open_ = {}
    for f in present:
        for name in scan(f):
            open_.setdefault(name, {}).setdefault(f.name, 0)
            open_[name][f.name] += 1
    sri, blocking = [], []
    for name, where in open_.items():
        (sri if name in BY_NAME and BY_NAME[name].owner == "sri" else blocking).append((name, where))
    for name, where in sri:
        out(f"needs Sri: [{name}] in {', '.join(f'{n} x{c}' for n, c in where.items())}")
    for name, where in blocking:
        owner = BY_NAME[name].owner if name in BY_NAME else "unregistered"
        out(f"OPEN ({owner}): [{name}] in {', '.join(f'{n} x{c}' for n, c in where.items())}")
    out(f"{len(blocking)} open placeholder(s) to close, {len(sri)} for Sri")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
