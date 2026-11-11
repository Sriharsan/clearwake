"""Every code block on the Developers page and on Break it runs, with no network.

Python blocks are run as written, except that the line `gw = SandboxGateway.from_environment()` is replaced by the local provider
(clearwake.paypal.LocalGateway), so a block that reads or moves money touches a local file and nothing else. Names a block uses
must be defined in it (or in the block it says it continues), and every import must be used. Shell blocks are parsed by bash -n;
the curl blocks are also run with curl replaced by a function that prints its arguments, and each JSON body must parse with the
variables expanded (a variable inside single quotes would stay as the text $NAME and fail here).
"""
import ast
import builtins
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from clearwake.paypal import LocalGateway
from verdock_core.policy import load_policy

ROOT = Path(__file__).resolve().parent.parent
GATEWAY_LINE = "gw = SandboxGateway.from_environment()"
SHELL_VARIABLES = {"ACCESS_TOKEN": "tok", "REQUEST_ID": "6f1c3a52-9d5e-4c3f-8a41-0b1d2e3f4a5b", "CAPTURE_ID": "1PH921107B839311S", "DISPUTE_ID": "PP-R-OBG-10196144",
                   "ORDER_ID": "7RV99265V1496281G", "NOTE": "We offer you USD 2.50 back.", "NOTES": "Shipped by UPS.", "TRACKING": "1Z999AA10123456784"}
GIVEN = ("paypal_toolkit_tools", "paypal_tools", "paypal_reader", "dispute_id", "note")   # names a block may use without defining: what the reader already has
BASH = next((p for p in ("C:/Program Files/Git/bin/bash.exe", shutil.which("bash")) if p and Path(p).exists()), None)


class Blocks(HTMLParser):
    """Every <pre><code> block of a page: its text, its attributes, and the label of its figure."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self._pre, self._label, self._depth, self._text = [], None, "", 0, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "figure":
            self._label = ""
        if tag == "span" and (self._depth or "cb-label" in (a.get("class") or "")):
            self._depth += 1
        if tag == "pre":
            self._pre, self._text = {"attrs": a, "label": self._label.strip(), "figure": a}, []

    def handle_endtag(self, tag):
        if tag == "span" and self._depth:
            self._depth -= 1
        if tag == "pre" and self._pre is not None:
            self._pre["text"] = "".join(self._text)
            self.blocks.append(self._pre)
            self._pre = None

    def handle_data(self, data):
        if self._depth:
            self._label += data
        if self._pre is not None:
            self._text.append(data)


def blocks_of(path):
    parser = Blocks()
    parser.feed(Path(path).read_text(encoding="utf-8"))
    return parser.blocks


def classify(block):
    text, attrs, label = block["text"].strip("\n"), block["attrs"], block["label"].lower()
    cls = attrs.get("class") or ""
    if "rp" in cls.split() or label.startswith(("one line of", "verified on", "settled by offer,", "dispatch proof,", "network cut,")):
        return None
    if text.startswith("pip install"):
        return "mixed"
    if attrs.get("data-p") == "py" or "data-continues" in attrs or label.startswith("python"):
        return "python"
    if attrs.get("data-p") == "curl" or label.startswith("shell"):
        return "shell"
    return None


def developers_blocks():
    out = []
    for block in blocks_of(ROOT / "site" / "developers.html"):
        kind = classify(block)
        if kind:
            out.append((kind, block["text"].strip("\n"), "continues" if "data-continues" in block["attrs"] else ""))
    return out


def break_blocks():
    out = []
    for block in blocks_of(ROOT / "site" / "break.html"):
        text = block["text"].strip("\n")
        if "codeblock" in (block["attrs"].get("class") or "") and ("from clearwake" in text or text.startswith("pip install")):
            out.append(("mixed" if text.startswith("pip install") else "python", text, "continues" if "data-continues" in block["attrs"] else ""))
    return out


def doc_blocks(path):
    out = []
    for match in re.finditer(r"```(python|shell|bash)\n(.*?)```", Path(path).read_text(encoding="utf-8"), re.S):
        text = match.group(2).strip("\n")
        out.append(("mixed" if text.startswith("pip install") else "shell" if match.group(1) != "python" else "python", text, ""))
    return out


def names_problems(code, free=()):
    """Names a block uses without defining, and imports it never uses."""
    tree = ast.parse(code)
    bound, imported = set(free) | set(dir(builtins)), {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                imported[name] = node.lineno
                bound.add(name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    loaded = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return sorted(loaded - bound), sorted(set(imported) - loaded)


def load_tests_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider(LocalGateway):
    """The local provider, plus the two order calls the page uses that LocalGateway does not have: a tracker is kept in memory."""

    def __init__(self, path):
        super().__init__(path)
        self.orders = {}

    def add_tracking(self, order_id, capture_id, tracking_number, carrier, request_id):
        self.orders.setdefault(order_id, {"id": order_id, "trackers": []})["trackers"].append({"tracking_number": tracking_number, "carrier": carrier, "status": "SHIPPED"})
        return {"id": order_id}

    def order(self, order_id):
        return self.orders.get(order_id, {"id": order_id, "trackers": []})


class Snippets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="dev-snippets-"))
        cls.old = Path.cwd()
        os.chdir(cls.dir)
        (cls.dir / "packing.jpg").write_bytes(b"\xff\xd8\xff\xe0 local photo bytes")
        subprocess.run([sys.executable, "-m", "clearwake.guard_api", "policy"], cwd=cls.dir, env={**os.environ, "PYTHONPATH": str(ROOT)}, stdout=(cls.dir / "policy.yaml").open("wb"), check=True)
        cls.provider = Provider(cls.dir / "provider.sqlite3")
        everything = developers_blocks() + break_blocks() + doc_blocks(ROOT / "docs" / "TOOLKIT_GUARD.md")
        for dispute_id in sorted(set(re.findall(r"PP-R-[A-Z]+-\d+", "\n".join(t for _, t, _ in everything)))):   # the ids the blocks name, as open disputes at INQUIRY
            body = {"dispute_id": dispute_id, "status": "WAITING_FOR_SELLER_RESPONSE", "dispute_life_cycle_stage": "INQUIRY", "dispute_amount": {"currency_code": "USD", "value": "2.50"},
                    "links": [{"rel": rel, "method": "POST"} for rel in ("send_message", "make_offer", "accept_claim")], "messages": [],
                    "disputed_transactions": [{"seller_transaction_id": "1PH921107B839311S"}]}
            with cls.provider._disputes_db() as db:
                db.execute("INSERT INTO disputes VALUES(?,?)", (dispute_id, json.dumps(body)))
        store = load_tests_module("test_guard_api")
        layer = load_tests_module("test_toolkit_guard").Layer()   # one dispute, D-1, for the single object form
        cls.given = {"paypal_toolkit_tools": store.toolkit(store.Store()), "paypal_tools": layer, "paypal_reader": layer, "dispute_id": "D-1", "note": "Accepted."}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.old)
        shutil.rmtree(cls.dir, True)

    # python -------------------------------------------------------------------------------------------------------------------
    def run_python(self, label, blocks):
        namespace, defined, namespaces = None, set(), []
        for number, (kind, text, continues) in enumerate(blocks, 1):
            if kind not in ("python", "mixed"):
                continue
            code = "\n".join(text.splitlines()[1:]) if kind == "mixed" else text
            free = set(GIVEN) | (defined if continues else set())
            undefined, unused = names_problems(code, free)
            self.assertEqual(undefined, [], f"{label} block {number} uses names it does not define:\n{code}")
            self.assertEqual(unused, [], f"{label} block {number} has imports it never uses:\n{code}")
            if namespace is None or not continues:
                namespace = {"__name__": "__snippet__", **self.given}
            namespace["LOCAL_PROVIDER"] = self.provider
            run = code.replace(GATEWAY_LINE, "gw = LOCAL_PROVIDER")
            try:
                exec(compile(run, f"<{label} block {number}>", "exec"), namespace)
            except Exception as error:
                self.fail(f"{label} block {number} failed with {type(error).__name__}: {error}\n{code}")
            defined = {k for k in namespace if not k.startswith("__")}
            namespaces.append(namespace)
        return namespaces

    def test_python_blocks_on_the_developers_page_run(self):
        blocks = developers_blocks()
        self.assertGreaterEqual(sum(1 for b in blocks if b[0] in ("python", "mixed")), 9)
        found = [n["tools"] for n in self.run_python("developers", blocks) if "tools" in n]
        self.assertTrue(found and found[0].verify()["ok"])   # the toolkit block wrote a receipt log that verifies

    def test_python_blocks_on_break_it_run(self):
        blocks = break_blocks()
        self.assertTrue(blocks)
        self.run_python("break", blocks)

    def test_python_blocks_in_the_guard_doc_run(self):
        blocks = doc_blocks(ROOT / "docs" / "TOOLKIT_GUARD.md")
        self.assertTrue([b for b in blocks if b[0] in ("python", "mixed")])
        self.run_python("TOOLKIT_GUARD.md", blocks)

    def test_the_page_checks_find_a_missing_name_and_an_unused_import(self):
        self.assertEqual(names_problems("import uuid\nprint(note)"), (["note"], ["uuid"]))

    def test_the_three_line_snippet_is_exactly_what_the_task_says(self):
        wanted = ["pip install git+https://github.com/Sriharsan/clearwake", "from clearwake import guard", 'tools = guard(paypal_toolkit_tools, policy="policy.yaml")']
        for label, blocks in (("developers", developers_blocks()), ("break", break_blocks())):
            self.assertTrue(any(t.splitlines()[:3] == wanted for k, t, _ in blocks if k == "mixed"), label)

    # shell --------------------------------------------------------------------------------------------------------------------
    def shell_blocks(self):
        return [(t, c) for k, t, c in developers_blocks() + break_blocks() + doc_blocks(ROOT / "docs" / "TOOLKIT_GUARD.md") if k in ("shell", "mixed")]

    @unittest.skipUnless(BASH, "bash is not installed")
    def test_every_shell_block_parses(self):
        checked = 0
        for text, _ in self.shell_blocks():
            if text.lstrip().startswith(".\\"):   # a Windows PowerShell line
                continue
            script = text.splitlines()[0:1] if text.startswith("pip install") else text.splitlines()
            result = subprocess.run([BASH, "-n"], input="\n".join(script), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, f"bash -n failed:\n{text}\n{result.stderr}")
            checked += 1
        self.assertGreaterEqual(checked, 12)

    @unittest.skipUnless(BASH, "bash is not installed")
    def test_every_curl_block_expands_its_variables_into_valid_json(self):
        shim = 'curl() { for a in "$@"; do echo "ARG:$a"; if [ "$a" = "@-" ]; then echo "STDIN:$(cat)"; fi; done; }\nset -u\n'
        ran = 0
        for text, _ in self.shell_blocks():
            if "curl" not in text:
                continue
            work = Path(tempfile.mkdtemp(prefix="curl-", dir=self.dir))
            (work / "packing.jpg").write_bytes(b"photo")
            env = {**os.environ, **SHELL_VARIABLES}
            result = subprocess.run([BASH, "-s"], input=shim + text + "\n", text=True, capture_output=True, cwd=work, env=env)
            self.assertEqual(result.returncode, 0, f"{text}\n{result.stderr}")
            bodies = [line.split(":", 1)[1] for line in result.stdout.splitlines() if line.startswith(("ARG:{", "STDIN:{"))]
            if (work / "input.json").exists():
                bodies.append((work / "input.json").read_text(encoding="utf-8"))
            self.assertTrue(bodies or "-F" not in text, f"no JSON body found in:\n{text}")
            for body in bodies:
                self.assertNotIn("$", body, f"a variable was not expanded:\n{text}")
                json.loads(body)
            self.assertNotRegex(text, r"-[dF] '[^']*\$[A-Z_]+", f"a variable inside single quotes does not expand:\n{text}")
            ran += 1
        self.assertGreaterEqual(ran, 7)

    def test_the_policy_block_on_the_page_is_the_repository_policy(self):
        page = [b["text"] for b in blocks_of(ROOT / "site" / "developers.html") if b["text"].startswith("version: 1")]
        self.assertEqual(len(page), 1)
        policy = self.dir / "page-policy.yaml"
        policy.write_text(page[0], encoding="utf-8")
        self.assertEqual(load_policy(policy), load_policy(ROOT / "policy" / "merchant.yaml"))


if __name__ == "__main__":
    unittest.main()
