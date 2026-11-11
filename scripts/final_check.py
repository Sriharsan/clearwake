"""The final gate before submission. One command, ten checks, one verdict.

  python scripts/final_check.py                 run everything, in order
  python scripts/final_check.py --only 4,6      run only the listed groups (1 to 10)
  python scripts/final_check.py --skip 9        skip groups (the clean clone takes the longest)

Prints one PASS or FAIL line per check (NOTE for facts that are reported, not judged), then a summary with counts, exits 1 on any
failure and writes data/runs/final-check-<timestamp>.json with every detail. Nothing here changes the repository: it reads files,
runs the existing test, verify and check scripts, and builds its clean clone in a temporary folder outside the repo, deleted afterwards.
Secret values are never printed: a hit shows the file, the line, the rule and the length of the value, nothing else.

Groups
  1  Python tests, Node tests (with counts)
  2  Secret scan (working tree and git index), and the ignore rules for .env, buyer profile, voice certificates, *.sqlite3
  3  Author check: one author, no co-author or generated-with lines in any commit message
  4  Word scan of the public text (strong words only, no dashes as punctuation, no exclamation marks)
  5  Receipts: every signed log in Python, every buyer and merchant pair, the browser verifier run in Node
  6  Numbers: site/data/totals.json re-derived, README and site quantities traced to data/runs/, open placeholders
  7  openapi/check_openapi.py and postman/check_collection.py
  8  Links in README.md and docs/*.md, assets of every site page, the CSP header file and the AG Grid style hashes
  9  Clean clone of the local repo (submodules from the local checkouts, no network): tests, --help, node tests
  10 Docker availability (reported, nothing is started)

ALLOW LISTS (everything the scans skip is named here, with the reason)
  Secret scan   SECRET_ALLOW: vendor bundles (AG Grid), fonts, test fixtures, and one entry per known harmless pattern. Values that
                contain a placeholder marker (your, xxx, example, placeholder, changeme, redacted, <) are skipped. Names that say
                public, hash, digest, signature or sha are skipped: those hold public keys and checksums.
  Word scan     ALLOW_PHRASES: the prize name. QUOTE_FILES: quoted third party text in the named docs (blockquote lines and
                quoted spans). IDENT rule: a word inside a file name, path, flag, code identifier or option (demo.ps1, check_demo.py,
                --rehearsal) is a technical identifier and is skipped. Fenced code blocks in Markdown are commands and output, not
                prose, so words and exclamation marks are not checked there (dashes still are). Vendor files, fonts and
                docs/FINAL_CHECK.md (it names the rules it checks) are not scanned. The word 'unguarded' is the baseline run's own
                label and is not a banned word here. JavaScript, CSS and JSON are checked in their strings and comments only.
"""
import argparse
import base64
import datetime as dt
import hashlib
import html.parser
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
RUNS = ROOT / "data" / "runs"
AUTHOR = "Sriharsan B S <bssriharsan@gmail.com>"
PY = sys.executable
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", GIT_TERMINAL_PROMPT="0")
ENV.pop("PYTHONPATH", None)

PASS, FAIL, NOTE = "PASS", "FAIL", "NOTE"


class Check:
    def __init__(self, cid, name, status, summary, details=None, data=None):
        self.cid, self.name, self.status, self.summary = cid, name, status, summary
        self.details, self.data = list(details or []), data or {}

    def as_dict(self):
        return {"id": self.cid, "name": self.name, "status": self.status, "summary": self.summary, "details": self.details, "data": self.data}


def run(cmd, cwd=ROOT, timeout=1800, input_text=None):
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=ENV, input=input_text)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout} s"
    except FileNotFoundError as e:
        return 127, f"{e}"


def git(*args, cwd=ROOT):
    return run(["git", *args], cwd=cwd, timeout=300)


def rel(path):
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def read(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------------------------------------------- 1. tests

def parse_unittest(output):
    m = re.search(r"Ran (\d+) tests? in", output)
    count = int(m.group(1)) if m else 0
    ok = bool(re.search(r"(?m)^OK\b", output))
    failing = re.findall(r"(?m)^(?:FAIL|ERROR): (.+)$", output)
    return count, ok, failing


def parse_node(output):
    def num(name):
        m = re.search(rf"(?m)^(?:#|\S)?\s*{name} (\d+)\s*$", output)
        return int(m.group(1)) if m else None
    return num("tests"), num("pass"), num("fail")


def python_tests(cwd=ROOT, cid="1a"):
    code, out = run([PY, "-m", "unittest", "discover", "-s", "tests"], cwd=cwd)
    count, ok, failing = parse_unittest(out)
    if code == 0 and ok:
        return Check(cid, "Python tests", PASS, f"{count} tests, all passed", data={"count": count})
    tail = [l for l in out.splitlines() if l.strip()][-6:]
    return Check(cid, "Python tests", FAIL, f"{count} ran, {len(failing)} failed or errored", [f"failing: {f}" for f in failing[:60]] + ["tail:"] + tail, {"count": count, "failing": failing})


def node_tests(cwd=ROOT, cid="1b"):
    code, out = run(["node", "--test", "tests/console.test.cjs", "tests/payment.test.cjs"], cwd=cwd)
    tests, passed, failed = parse_node(out)
    if code == 0 and tests:
        return Check(cid, "Node tests", PASS, f"{tests} tests, {passed} passed", data={"count": tests})
    tail = [l for l in out.splitlines() if l.strip()][-12:]
    return Check(cid, "Node tests", FAIL, f"{tests} ran, {failed} failed (exit {code})", tail, {"count": tests})


# --------------------------------------------------------------------------------------------------------------- 2. secrets

P = lambda s: re.compile(s)
PH = ("your", "xxx", "example", "placeholder", "changeme", "redacted", "<", "...", "${", "{{")
NAME_SKIP = re.compile(r"(?i)public|pub_|hash|digest|signature|sha|checksum|integrity|nonce|request_?id|step_?id|dispute|order|capture")
SECRET_RULES = [
    ("private key block", P(r"-{5}BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|ENCRYPTED|PGP|OPENSSH)[A-Z0-9 ]*-{5}"), None),
    ("key block header", P(r"-{5}BEGIN "), None),
    ("PayPal secret shape", P(r"\bE[A-Za-z0-9_-]{79}\b"), None),
    ("PayPal client secret assigned", P(r"(?i)PAYPAL_?\w*SECRET\w*[\"']?\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{20,})"), 1),
    ("Hugging Face token", P(r"\bhf_[A-Za-z0-9]{20,}"), None),
    ("Channel3 key value", P(r"(?i)CHANNEL3\w*KEY\w*[\"']?\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{12,})"), 1),
    ("Sarvam key", P(r"\bsk_[A-Za-z0-9_]{16,}"), None),
    ("Sarvam key assigned", P(r"(?i)SARVAM\w*[\"']?\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{16,})"), 1),
    ("long credential assigned", P(r"(?i)\b(\w*(?:secret|token|key|password)\w*)[\"']?\s*[=:]\s*[\"']([A-Za-z0-9+/=_\-]{40,})[\"']"), 2),
    ("long credential in env style", P(r"(?im)^\s*(\w*(?:secret|token|key|password)\w*)\s*=\s*([A-Za-z0-9+/=_\-]{40,})\s*$"), 2),
]
# (path prefix or glob, rule name or None for all rules, reason)
SECRET_ALLOW = [
    ("site/vendor/", None, "vendored AG Grid bundle, unchanged"),
    ("web/vendor/", None, "vendored AG Grid bundle, unchanged"),
    ("vendor/", None, "pinned submodules, scanned in their own repositories"),
    ("site/fonts/", None, "font files"),
    ("web/fonts/", None, "font files"),
    ("tests/fixtures/", None, "test fixtures"),
    ("fixtures/", None, "test fixtures"),
    ("site/receipts/", "long credential assigned", "signed receipt logs hold public keys and signatures"),
    ("scripts/final_check.py", None, "this file holds the patterns"),
    ("tests/test_final_check.py", None, "tests build their own look-alike strings"),
]
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".zip", ".gz", ".wav", ".mp3", ".mp4", ".webm", ".onnx", ".bin", ".pyc"}


def allowed_secret(path, rule):
    for prefix, only, _why in SECRET_ALLOW:
        if (path == prefix or path.startswith(prefix)) and (only is None or only == rule):
            return True
    return False


def scan_secret_text(path, text):
    """Returns [(line, rule, length)]. The value itself is never returned."""
    hits = []
    lines = text.splitlines()
    for rule, rx, group in SECRET_RULES:
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            if group is None:
                value = m.group(0)
            else:
                value = m.group(group)
                if rule.startswith("long credential") and NAME_SKIP.search(m.group(1)):
                    continue
            context = lines[line - 1] if line - 1 < len(lines) else ""
            low = (value + " " + context).lower()
            if any(p in low for p in PH) and not rule.endswith("block") and rule != "key block header":
                continue
            if rule == "key block header" and re.search(r"-{5}BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|ENCRYPTED|PGP|OPENSSH)", context):
                continue
            if allowed_secret(path, rule):
                continue
            hits.append((line, rule, len(value)))
    return hits


def is_binary(path, data):
    return Path(path).suffix.lower() in BINARY_EXT or b"\0" in data[:4096]


def index_blobs():
    code, out = run(["git", "ls-files", "-s", "-z"])
    if code != 0:
        return {}
    entries = []
    for rec in out.split("\0"):
        if not rec.strip():
            continue
        meta, _, path = rec.partition("\t")
        mode, sha = meta.split()[0], meta.split()[1]
        if mode != "160000":
            entries.append((path, sha))
    blobs = {}
    try:
        p = subprocess.run(["git", "cat-file", "--batch"], cwd=str(ROOT), input="".join(s + "\n" for _p, s in entries).encode(), capture_output=True, timeout=300, env=ENV)
        buf, pos = p.stdout, 0
        for path, _sha in entries:
            nl = buf.index(b"\n", pos)
            header = buf[pos:nl].split()
            size = int(header[2]) if len(header) == 3 else 0
            blobs[path] = buf[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1
    except Exception:
        pass
    return blobs


def secret_scan():
    code, out = git("ls-files", "-z")
    tracked = [p for p in out.split("\0") if p]
    hits = {}
    scanned = 0
    for path in tracked:
        f = ROOT / path
        if not f.is_file():
            continue
        data = f.read_bytes()
        if is_binary(path, data):
            continue
        scanned += 1
        for line, rule, n in scan_secret_text(path, data.decode("utf-8", errors="replace")):
            hits.setdefault((path, line, rule, n), set()).add("working tree")
    staged = index_blobs()
    for path, data in staged.items():
        if is_binary(path, data):
            continue
        for line, rule, n in scan_secret_text(path, data.decode("utf-8", errors="replace")):
            hits.setdefault((path, line, rule, n), set()).add("git index")
    details = [f"{p}:{l}  {r}  (value length {n}, not shown)  [{', '.join(sorted(src))}]" for (p, l, r, n), src in sorted(hits.items())]
    status = FAIL if hits else PASS
    return Check("2a", "Secret scan", status, f"{len(hits)} hit(s) in {scanned} tracked text files and {len(staged)} index entries", details,
                 {"scanned_files": scanned, "index_entries": len(staged), "hits": len(hits)})


IGNORE_PATHS = [".env", "data/buyer-profile/state.json", "data/voice-tls/key.pem", "data/clearwake.sqlite3", "x.sqlite3"]
TRACKED_BAD = re.compile(r"^(?:\.env(?:\.(?!example$).*)?|data/buyer-profile/.*|data/voice-tls/.*|.*\.sqlite3(?:-.*)?)$")


def ignore_rules():
    details, bad = [], 0
    for p in IGNORE_PATHS:
        code, _ = git("check-ignore", "-q", p)
        if code != 0:
            bad += 1
            details.append(f"not git ignored: {p}")
    code, out = git("ls-files", "-z")
    tracked = [p for p in out.split("\0") if p]
    code, staged = git("ls-files", "-s", "-z")
    for p in tracked:
        if TRACKED_BAD.match(p.replace("\\", "/")):
            bad += 1
            details.append(f"tracked, must not be: {p}")
    return Check("2b", "Ignore rules", FAIL if bad else PASS, "ignored and untracked: .env, data/buyer-profile, data/voice-tls, *.sqlite3" if not bad else f"{bad} problem(s)", details)


# ---------------------------------------------------------------------------------------------------------------- 3. author

def author_check():
    code, out = git("log", "--format=%an <%ae>")
    authors = sorted(set(l for l in out.splitlines() if l.strip()))
    details = []
    if authors != [AUTHOR]:
        details.append(f"authors found: {authors}")
    code, out = git("log", "--format=%H%x00%cn <%ce>%x00%B%x01")
    committers, bad_bodies, total = set(), [], 0
    for rec in out.split("\x01"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        total += 1
        parts = rec.split("\x00", 2)
        if len(parts) < 3:
            continue
        sha, committer, body = parts
        committers.add(committer.strip())
        if re.search(r"(?i)co-authored-by|generated with", body):
            bad_bodies.append(sha.strip()[:10])
    if bad_bodies:
        details.append(f"commit messages with Co-Authored-By or 'Generated with': {', '.join(bad_bodies)}")
    ok = not details
    return Check("3", "Author check", PASS if ok else FAIL, f"{total} commits, one author, no co-author lines" if ok else "author or message problem",
                 details + [f"committer(s): {sorted(committers)}"], {"commits": total, "authors": authors})


# ---------------------------------------------------------------------------------------------------------------- 4. words

BRIEF_WORDS = ["demo", "demonstration", "invented", "synthetic", "fake", "mock", "simulated", "dummy", "toy", "learning", "prototype", "simple", "early",
               "beta", "student", "hopefully", "seamless", "leverage", "revolutionary", "game changer", "cutting edge", "next gen", "empower",
               "unlock", "robust", "supercharge", "AI powered", "magic", "effortless", "believed", "rehearsal"]
RULE_WORDS = ["learn", "learned", "sample data", "simply", "basic", "just", "maybe", "try", "tries", "tried", "attempt"]
SUFFIX = r"(?:s|es|d|ed|ing|al|ally)?"


def word_rx(w):
    parts = re.split(r"[\s-]+", w)
    return re.compile(r"(?i)\b" + r"[\s-]+".join(re.escape(p) for p in parts) + SUFFIX + r"\b")


WORD_RULES = [(w, word_rx(w)) for w in BRIEF_WORDS + RULE_WORDS]
ALLOW_PHRASES = [re.compile(r"Best Demo Delivery"), re.compile(r"===? *['\"]rehearsal['\"]"), re.compile(r"['\"]rehearsal['\"] *:"), re.compile(r"['\"]rehearsal['\"] *\?"), re.compile(r"payment-mode \$\{[^}]*rehearsal"), re.compile(r"Basic authentication")]
QUOTE_FILES = {"docs/TOOLKIT_FAILURE_CASES.md", "docs/SOURCES.md", "docs/REFERENCES.md", "docs/THIRD_PARTY.md"}
NOT_SCANNED = {"docs/FINAL_CHECK.md"}
DASH_RX = re.compile("[\u2014\u2013]")
SPACED_DASH_RX = re.compile(r"(?<=\S) (?:-|--) (?=\S)")
BANG_RX = re.compile(r"(?<![<\w])!(?!\[|=)(?=[\s\"')\]*_]|$)|\w!(?=[\s\"')\]*_]|$)")


def is_ident(tok):
    t = tok.strip("\"'()[]{}<>,;:*!?`")
    t = t.rstrip(".")
    if not t:
        return False
    if re.search(r"[_/\\=]|::|\(\)", t):
        return True
    if re.fullmatch(r"[\w-]+\.[A-Za-z0-9]{1,6}", t):
        return True
    return t.startswith(("--", ".", "#", "$", "@"))


def mask_identifiers(line):
    return re.sub(r"\S+", lambda m: " " * len(m.group(0)) if is_ident(m.group(0)) else m.group(0), line)


def mask_phrases(line):
    for rx in ALLOW_PHRASES:
        line = rx.sub(lambda m: " " * len(m.group(0)), line)
    return line


def mask_quotes(line):
    if line.lstrip().startswith(">"):
        return " " * len(line)
    return re.sub(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d|`[^`]*`", lambda m: " " * len(m.group(0)), line)


def word_hits(line):
    probe = mask_identifiers(mask_phrases(line))
    return [(w, m.start()) for w, rx in WORD_RULES for m in rx.finditer(probe)]


def blank_keep_lines(text):
    return re.sub(r"[^\n]", " ", text)


def html_text(src):
    """The visible and user facing text of an HTML page with line numbers kept: scripts and styles removed, tags dropped, the
    attributes people see (title, alt, aria-label, placeholder, content, value, label) kept."""
    src = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", lambda m: blank_keep_lines(m.group(0)), src)

    def tag(m):
        t = m.group(0)
        if t.startswith("<!--"):
            return t[4:-3] if t.endswith("-->") else t
        keep = re.findall(r"(?is)\b(?:title|alt|aria-label|placeholder|content|value|label)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", t)
        text = " ".join(a or b for a, b in keep)
        return text + "\n" * t.count("\n")
    return re.sub(r"(?s)<!--.*?-->|<[^>]+>", tag, src)


def js_segments(text, comments):
    """(line, text) for every string literal, and optionally every comment, with the line it starts on."""
    out = []
    rx = re.compile(r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`" + (r"|//[^\n]*|/\*.*?\*/" if comments else ""), re.S)
    for m in rx.finditer(text):
        seg = m.group(0)
        line = text.count("\n", 0, m.start()) + 1
        if seg[0] in "\"'`":
            tail = text[m.end():m.end() + 12].lstrip(" \t")
            if tail.startswith(":") and not tail.startswith("::") and seg[0] in "\"'":
                continue  # an object key
            if seg[0] == "`":
                seg = re.sub(r"\$\{[^}]*\}", "", seg)  # code inside a template literal is not user text
            seg = seg[1:-1]
            if seg.strip() == "rehearsal":
                continue  # the mode value the server sends and the CSS class name: an identifier, not wording
        for i, l in enumerate(seg.split("\n")):
            out.append((line + i, l))
    return out


def md_lines(text):
    """(line number, line, in_fence)."""
    fence = False
    for i, l in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*(```|~~~)", l):
            fence = not fence
            yield i, l, True
            continue
        yield i, l, fence


def scan_public_file(path):
    """Returns [(line, label, snippet)] for one file."""
    rp = rel(path)
    text = read(path)
    ext = Path(path).suffix.lower()
    hits = []
    quote_mode = rp in QUOTE_FILES

    def add(line, label, snippet):
        hits.append((line, label, snippet.strip()[:90]))

    def check_prose(i, l, words=True, bangs=True, dashes=True, spaced=False):
        probe = mask_quotes(l) if quote_mode else l
        if dashes:
            for m in DASH_RX.finditer(probe):
                add(i, "dash", l[max(0, m.start() - 25):m.start() + 25])
            if spaced:
                bare = re.sub(r"`[^`]*`|https?://\S+", lambda m: " " * len(m.group(0)), probe)
                for m in SPACED_DASH_RX.finditer(bare):
                    add(i, "spaced dash", l[max(0, m.start() - 25):m.start() + 25])
        if words:
            for w, pos in word_hits(probe):
                add(i, f"word: {w}", l[max(0, pos - 25):pos + 35])
        if bangs:
            clean = re.sub(r"`[^`]*`|https?://\S+", lambda m: " " * len(m.group(0)), probe)
            if BANG_RX.search(clean):
                add(i, "exclamation", l)

    if ext in (".md", ".txt"):
        for i, l, fence in md_lines(text):
            if fence:
                check_prose(i, l, words=False, bangs=False)
            else:
                table = l.lstrip().startswith("|")
                check_prose(i, l, spaced=not table)
    elif ext in (".html", ".htm"):
        for i, l in enumerate(html_text(text).splitlines(), 1):
            check_prose(i, l)
    elif ext in (".js", ".mjs", ".cjs"):
        for i, l in enumerate(text.splitlines(), 1):
            for m in DASH_RX.finditer(l):
                add(i, "dash", l[max(0, m.start() - 25):m.start() + 25])
        for i, l in js_segments(text, comments=False):
            check_prose(i, l, dashes=False)
    elif ext == ".css":
        for i, l in enumerate(text.splitlines(), 1):
            for m in DASH_RX.finditer(l):
                add(i, "dash", l[max(0, m.start() - 25):m.start() + 25])
        for i, l in js_segments(text, comments=True):
            check_prose(i, l, dashes=False, bangs=False)
    elif ext == ".json":
        for i, l in enumerate(text.splitlines(), 1):
            for m in DASH_RX.finditer(l):
                add(i, "dash", l[max(0, m.start() - 25):m.start() + 25])
        for i, l in js_segments(text, comments=False):
            check_prose(i, l, dashes=False)
    seen, uniq = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def public_files():
    pats = ["README.md", "SUBMISSION_PAYPAL.md", "VIDEO_SCRIPT.md", "BUILT_DURING_HACKATHON.md", "docs/*.md", "docs/*.txt", "site/*.html", "site/*.js", "site/*.css",
            "site/data/*.json", "site/dispatch/*.html", "web/*.html", "web/voice*.js", "web/console*.js", "web/payment*.js", "web/*.css"]
    files = []
    for pat in pats:
        files += sorted(ROOT.glob(pat))
    return [f for f in dict.fromkeys(files) if f.is_file() and rel(f) not in NOT_SCANNED]


def word_scan():
    files = public_files()
    details, per_word, total = [], {}, 0
    for f in files:
        for line, label, snip in scan_public_file(f):
            total += 1
            per_word[label] = per_word.get(label, 0) + 1
            details.append(f"{rel(f)}:{line}  {label}  | {snip}")
    counts = ", ".join(f"{k.replace('word: ', '')} {v}" for k, v in sorted(per_word.items(), key=lambda kv: -kv[1]))
    return Check("4", "Word scan", FAIL if total else PASS, f"{total} hit(s) in {len(files)} public files" + (f" ({counts})" if counts else ""), details,
                 {"files": len(files), "hits": total, "by_label": per_word})


# -------------------------------------------------------------------------------------------------------------- 5. receipts

def load_verify_log():
    sys.path.insert(0, str(ROOT))
    import clearwake  # noqa: F401  (puts vendor/verdock-core on the path)
    from verdock_core.receipts import verify_log
    return verify_log


def gather_logs():
    """[(label, path, key)] for the site receipts and every batch run's saved logs."""
    logs, problems = [], []
    manifest = SITE / "receipts" / "manifest.json"
    listed = set()
    if manifest.is_file():
        for entry in json.loads(read(manifest)).get("logs", []):
            p = SITE / entry["file"]
            listed.add(p.resolve())
            logs.append((f"site/{entry['file']}", p, entry["public_key"]))
    else:
        problems.append("site/receipts/manifest.json is missing")
    for p in sorted((SITE / "receipts").glob("*.ndjson")):
        if p.resolve() not in listed:
            problems.append(f"site/receipts/{p.name} is not listed in the manifest (no trust anchor)")
    ledger = SITE / "data" / "ledger.json"
    if ledger.is_file():
        try:
            for row in json.loads(read(ledger)).get("rows", []):
                r = row.get("receipts")
                if r and (SITE / r).resolve() not in listed:
                    problems.append(f"ledger row {row.get('dispute') or row.get('id')} names {r}, which is not in the manifest")
        except ValueError:
            problems.append("site/data/ledger.json does not parse")
    reports = []
    for rp in sorted(RUNS.glob("*.json")):
        try:
            body = json.loads(read(rp))
        except ValueError:
            continue
        if isinstance(body, dict) and isinstance(body.get("logs"), dict) and body["logs"].get("buyer"):
            reports.append(rp)
            lg = body["logs"]
            logs.append((f"data/runs/{lg['buyer']}", RUNS / lg["buyer"], lg["buyer_key"]))
            logs.append((f"data/runs/{lg['merchant']}", RUNS / lg["merchant"], lg["merchant_key"]))
    named = {Path(p).resolve().parent for _l, p, _k in logs}
    for d in sorted(RUNS.glob("*-logs")):
        if d.is_dir() and d.resolve() not in named:
            problems.append(f"data/runs/{d.name} is a log folder that no run report names")
    return logs, reports, problems


def receipts_python(logs, problems):
    verify_log = load_verify_log()
    details, bad, results = list(problems), len(problems), {}
    for label, path, key in logs:
        if not Path(path).is_file():
            bad += 1
            details.append(f"{label}: file is missing")
            continue
        r = verify_log(str(path), key)
        results[label] = (bool(r["ok"]), len(r["failures"]))
        if not r["ok"]:
            bad += 1
            f = r["failures"][0] if r["failures"] else {}
            details.append(f"{label}: does not verify, line {f.get('line')}: {f.get('reason')}")
    return Check("5a", "Signed logs verify (Python, verdock_core)", FAIL if bad else PASS, f"{bad} problem(s) among {len(logs)} logs" if bad else f"{len(logs)} logs verify", details, {"logs": len(logs)}), results


def receipts_pairs(reports):
    details, bad = [], 0
    for rp in reports:
        code, out = run([PY, "scripts/verify_pair.py", str(rp)], timeout=300)
        first = out.strip().splitlines()[0] if out.strip() else ""
        if code != 0:
            bad += 1
            details.append(f"{rel(rp)}: {first}")
    return Check("5b", "Buyer and merchant pairs (scripts/verify_pair.py)", FAIL if bad else PASS, f"{len(reports) - bad} of {len(reports)} pairs verify", details, {"pairs": len(reports)})


NODE_RUNNER = """import { readFileSync } from 'node:fs';
import { verifyLog } from './verify.mjs';
const jobs = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = {};
for (const j of jobs) {
  try {
    const r = await verifyLog(readFileSync(j.path, 'utf8'), j.key);
    out[j.label] = { ok: r.ok, failures: r.failures.length, count: r.count };
  } catch (e) { out[j.label] = { ok: false, failures: -1, error: String(e.message || e) }; }
}
console.log(JSON.stringify(out));
"""


def receipts_browser(logs, py_results):
    verify_js = SITE / "verify.js"
    if not verify_js.is_file():
        return Check("5c", "Browser verifier (site/verify.js in Node)", FAIL, "site/verify.js is missing")
    tmp = Path(tempfile.mkdtemp(prefix="clearwake-verifyjs-"))
    try:
        shutil.copyfile(verify_js, tmp / "verify.mjs")
        (tmp / "runner.mjs").write_text(NODE_RUNNER, encoding="utf-8")
        jobs = [{"label": l, "path": str(p), "key": k} for l, p, k in logs if Path(p).is_file()]
        (tmp / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
        code, out = run(["node", "runner.mjs", "jobs.json"], cwd=tmp, timeout=300)
        if code != 0:
            return Check("5c", "Browser verifier (site/verify.js in Node)", FAIL, f"node exited {code}", out.strip().splitlines()[-6:])
        try:
            got = json.loads(out.strip().splitlines()[-1])
        except ValueError:
            return Check("5c", "Browser verifier (site/verify.js in Node)", FAIL, "no JSON result", out.strip().splitlines()[-6:])
        details, bad = [], 0
        for label, r in got.items():
            want = py_results.get(label)
            if not r["ok"]:
                bad += 1
                details.append(f"{label}: verify.js rejects it ({r.get('failures')} failure(s) {r.get('error', '')})")
            elif want and want[0] != r["ok"]:
                bad += 1
                details.append(f"{label}: Python and verify.js disagree")
        return Check("5c", "Browser verifier (site/verify.js in Node)", FAIL if bad else PASS, f"{len(got) - bad} of {len(got)} logs verify in site/verify.js with WebCrypto on Node", details, {"logs": len(got)})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------- 6. numbers

NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
QUANT = [re.compile(p, re.I) for p in (
    r"USD\s?[\d,]+(?:\.\d+)?", r"\b\d+\s+of\s+\d+\b", r"\b\d[\d,]*(?:\.\d+)?\s*(?:model calls?|calls|episodes|cases|prompts|disputes|receipts|double refunds|times|seconds|tests)\b",
    r"\b\d+(?:\.\d+)?\s?s\b(?!\w)", r"\b\d+(?:\.\d+)?%")]


def to_dec(s):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(s.replace(",", "").replace("USD", "").strip())
    except InvalidOperation:
        return None


def flat_numbers(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            flat_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            flat_numbers(v, out)


def number_pool(files=None):
    from decimal import Decimal
    pool = set()
    paths = files if files is not None else sorted(RUNS.glob("*.json")) + sorted(RUNS.glob("*.txt"))
    for p in paths:
        text = read(p)
        for tok in NUM.findall(text):
            d = to_dec(tok)
            if d is not None:
                pool.add(d.normalize())
        try:
            body = json.loads(text)
        except ValueError:
            continue
        if isinstance(body, dict):
            for key in ("summary", "totals"):
                nums = []
                flat_numbers(body.get(key), nums)
                nums = [Decimal(str(n)) for n in nums][:60]
                for i, a in enumerate(nums):
                    for b in nums[i:]:
                        pool.add((a + b).normalize())
    for d in list(pool):
        pool.add((d / 100).normalize())
        pool.add((d * 100).normalize())
    return pool


def quantities(text):
    found = []
    for i, l in enumerate(text.splitlines(), 1):
        for rx in QUANT:
            for m in rx.finditer(l):
                found.append((i, m.group(0)))
    return found


def untraced(text, pool):
    bad = []
    for line, q in quantities(text):
        nums = [to_dec(n) for n in NUM.findall(q)]
        nums = [n for n in nums if n is not None]
        if nums and not all(n.normalize() in pool for n in nums):
            bad.append((line, q, [str(n) for n in nums if n.normalize() not in pool]))
    return bad


def strip_fences(text):
    return "\n".join("" if fence else l for _i, l, fence in md_lines(text))


def load_builder():
    spec = importlib.util.spec_from_file_location("build_site_data", ROOT / "scripts" / "build_site_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def numbers_check():
    details, bad = [], 0
    pool = number_pool()
    totals_path = SITE / "data" / "totals.json"
    try:
        builder = load_builder()
        derived = builder.totals(builder.build()["rows"])
        written = json.loads(read(totals_path))
        for section in ("public", "local"):
            if derived.get(section) != written.get(section):
                bad += 1
                details.append(f"site/data/totals.json '{section}' differs from a fresh derivation (run scripts/build_site_data.py): written {[x['value'] for x in written.get(section, [])]}, derived {[x['value'] for x in derived.get(section, [])]}")
        for section, items in written.items():
            for item in items:
                src = item.get("source", "")
                if not src or not (ROOT / src).is_file():
                    bad += 1
                    details.append(f"totals.json {section} '{item.get('value')}': source {src!r} does not exist")
                elif src.startswith("data/runs/"):
                    miss = [n for n in (to_dec(x) for x in NUM.findall(item["value"])) if n is not None and n.normalize() not in number_pool([ROOT / src])]
                    if miss:
                        bad += 1
                        details.append(f"totals.json {section} '{item['value']}': {[str(m) for m in miss]} not found in {src}")
                else:
                    details.append(f"note: totals.json {section} '{item['value']}' comes from {src}, not from data/runs/ (re-derived above)")
    except Exception as e:  # noqa: BLE001
        bad += 1
        details.append(f"could not re-derive totals: {type(e).__name__}: {e}")
    for name in ("README.md",):
        text = strip_fences(read(ROOT / name))
        for line, q, missing in untraced(text, pool):
            bad += 1
            details.append(f"{name}:{line}  '{q}' has no run file source (number(s) {', '.join(missing)})")
    for page in sorted(SITE.glob("*.html")) + sorted(SITE.glob("dispatch/*.html")):
        text = html_text(read(page))
        site_pool = pool | number_pool([SITE / "data" / "ledger.json", SITE / "data" / "totals.json"]) if (SITE / "data" / "ledger.json").is_file() else pool
        for line, q, missing in untraced(text, site_pool):
            bad += 1
            details.append(f"{rel(page)}:{line}  '{q}' has no run file source (number(s) {', '.join(missing)})")
    return Check("6a", "Numbers trace to run files", FAIL if bad else PASS, f"{bad} number(s) without a source" if bad else "totals.json re-derived and every README and site quantity traced to data/runs/", details, {"pool_size": len(pool)})


PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\]")


def placeholders():
    details = []
    files = [ROOT / n for n in ("README.md", "SUBMISSION_PAYPAL.md", "VIDEO_SCRIPT.md", "BUILT_DURING_HACKATHON.md")] + sorted((ROOT / "docs").glob("*.md")) + sorted(SITE.glob("*.html"))
    for f in files:
        if not f.is_file() or rel(f) in NOT_SCANNED:
            continue
        for i, l in enumerate(read(f).splitlines(), 1):
            for m in PLACEHOLDER.finditer(l):
                details.append(f"{rel(f)}:{i}  open placeholder {m.group(0)}")
            if re.search(r"Notes for the lead", l):
                details.append(f"{rel(f)}:{i}  working note for the lead is still in the file")
    return Check("6b", "No open placeholders in public files", FAIL if details else PASS, f"{len(details)} open placeholder(s) or notes" if details else "none", details)


# ----------------------------------------------------------------------------------------------------------------- 7. specs

def spec_checks():
    out = []
    for cid, name, script in (("7a", "OpenAPI spec", "openapi/check_openapi.py"), ("7b", "Postman collection", "postman/check_collection.py")):
        code, text = run([PY, script], timeout=300)
        lines = [l for l in text.strip().splitlines() if l.strip()]
        out.append(Check(cid, f"{name} ({script})", PASS if code == 0 else FAIL, (lines[-1] if lines else "no output") if code == 0 else f"exit {code}", [] if code == 0 else lines[-12:]))
    return out


# ----------------------------------------------------------------------------------------------------------------- 8. links

LOCAL_SKIP = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|#|//)")
MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def resolves_file(base_dir, target, root_dir):
    target = urllib.parse.unquote(re.split(r"[?#]", target)[0])
    if not target:
        return True
    p = (root_dir / target.lstrip("/")) if target.startswith("/") else (base_dir / target)
    p = Path(os.path.normpath(p))
    return p.exists()


def md_links():
    details, n = [], 0
    files = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))
    for f in files:
        if not f.is_file():
            continue
        for i, l, fence in md_lines(read(f)):
            if fence:
                continue
            for m in MD_LINK.finditer(l):
                t = m.group(1)
                if LOCAL_SKIP.match(t) or "[" in t or "$" in t:
                    continue
                n += 1
                if not resolves_file(f.parent, t, ROOT):
                    details.append(f"{rel(f)}:{i}  link target not found: {t}")
    return Check("8a", "Local links in README.md and docs/*.md", FAIL if details else PASS, f"{n - len(details)} of {n} local links resolve", details, {"links": n})


class Refs(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("href", "src", "poster", "data-src"):
            if a.get(key):
                self.refs.append((self.getpos()[0], tag, a[key]))
        if a.get("srcset"):
            for part in a["srcset"].split(","):
                if part.strip():
                    self.refs.append((self.getpos()[0], tag, part.strip().split()[0]))


def site_target_exists(page, target):
    t = urllib.parse.unquote(re.split(r"[?#]", target)[0])
    if not t:
        return True
    base = SITE if t.startswith("/") else page.parent
    p = Path(os.path.normpath(base / t.lstrip("/")))
    return p.is_file() or Path(str(p) + ".html").is_file() or (p.is_dir() and (p / "index.html").is_file())


def site_assets():
    details, n = [], 0
    pages = sorted(p for p in SITE.rglob("*.html") if "vendor" not in p.parts)
    for page in pages:
        parser = Refs()
        parser.feed(read(page))
        for line, tag, t in parser.refs:
            if LOCAL_SKIP.match(t) or t.startswith(("mailto:", "tel:")):
                continue
            n += 1
            if not site_target_exists(page, t):
                details.append(f"{rel(page)}:{line}  <{tag}> target not found: {t}")
    for css in sorted(SITE.glob("*.css")):
        for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", read(css)):
            t = m.group(1)
            if LOCAL_SKIP.match(t):
                continue
            n += 1
            if not site_target_exists(css, t):
                details.append(f"{rel(css)}  url() target not found: {t}")
    return Check("8b", "Site page assets resolve", FAIL if details else PASS, f"{n - len(details)} of {n} local references resolve in {len(pages)} pages and the CSS", details, {"references": n})


def cook_template(s):
    simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}

    def sub(m):
        g = m.group(1)
        if g[0] == "u":
            return chr(int(g[2:-1] if g[1] == "{" else g[1:], 16))
        if g[0] == "x":
            return chr(int(g[1:], 16))
        if g == "\n":
            return ""
        return simple.get(g, g)
    return re.sub(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", sub, s, flags=re.S)


def ag_grid_static_hashes(path):
    """The fixed style blocks AG Grid writes while its bundle loads: the template strings it assigns to a style element's textContent."""
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"\.textContent=`(.*?)`,document\.head\.appendChild\(e\)", text, re.S)
    return [base64.b64encode(hashlib.sha256(cook_template(b).encode("utf-8")).digest()).decode() for b in blocks]


def csp_check():
    details, bad = [], 0
    try:
        cfg = json.loads(read(SITE / "vercel.json"))
    except ValueError as e:
        return Check("8c", "CSP header file and AG Grid style hashes", FAIL, f"site/vercel.json does not parse: {e}")
    rules = {r["source"]: {h["key"]: h["value"] for h in r["headers"]} for r in cfg.get("headers", [])}
    room = next((v["Content-Security-Policy"] for k, v in rules.items() if "Content-Security-Policy" in v and k == "/control-room"), "")
    strict = next((v["Content-Security-Policy"] for k, v in rules.items() if "Content-Security-Policy" in v and "control-room)" in k), "")
    if not room or not strict:
        return Check("8c", "CSP header file and AG Grid style hashes", FAIL, "the control-room rule or the strict rule is missing from site/vercel.json")
    for label, csp in (("strict", strict), ("control-room", room)):
        if "unsafe" in csp or "nonce" in csp:
            bad += 1
            details.append(f"{label} policy contains unsafe or nonce")
    if "sha256" in strict:
        bad += 1
        details.append("the strict policy for the other pages contains a hash")
    room_hashes = set(re.findall(r"'sha256-([A-Za-z0-9+/=]{44})'", room))
    vendor_site, vendor_web = SITE / "vendor" / "ag-grid-community-35.3.1.min.js", ROOT / "web" / "vendor" / "ag-grid-community-35.3.1.min.js"
    if vendor_site.read_bytes() != vendor_web.read_bytes():
        bad += 1
        details.append("site/vendor and web/vendor AG Grid files differ")
    static = ag_grid_static_hashes(vendor_site)
    server_hashes = set(re.findall(r'"([A-Za-z0-9+/]{43}=)"', read(ROOT / "clearwake" / "server.py")))
    missing = [h for h in static if h not in room_hashes]
    if missing:
        bad += 1
        details.append(f"{len(missing)} of {len(static)} style blocks in the vendored AG Grid file have no hash in site/vercel.json: {', '.join(missing[:3])}")
    missing_srv = [h for h in static if h not in server_hashes]
    if missing_srv:
        bad += 1
        details.append(f"{len(missing_srv)} of {len(static)} style blocks have no hash in AG_GRID_STYLE_HASHES (clearwake/server.py)")
    if not server_hashes <= room_hashes:
        bad += 1
        details.append(f"{len(server_hashes - room_hashes)} hash(es) in clearwake/server.py are not in site/vercel.json")
    details.append(f"note: {len(room_hashes)} hashes in site/vercel.json; {len(static)} are the fixed blocks recomputed here from the vendored file, "
                   f"{len(room_hashes) - len(set(static) & room_hashes)} more are blocks the grid writes after load and can only be rechecked in a browser")
    return Check("8c", "CSP header file and AG Grid style hashes", FAIL if bad else PASS,
                 f"{len(static)} fixed style blocks recomputed and present in both policies" if not bad else f"{bad} problem(s)", details, {"static_hashes": len(static), "policy_hashes": len(room_hashes)})


# ------------------------------------------------------------------------------------------------------------ 9. clean clone

def rmtree_force(path):
    def onerr(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerr)


def clean_clone():
    tmp = Path(tempfile.mkdtemp(prefix="clearwake-clean-clone-"))
    out_checks = []
    try:
        dest = tmp / "clearwake"
        code, out = run(["git", "clone", "--no-recurse-submodules", str(ROOT), str(dest)], cwd=tmp, timeout=600)
        if code != 0:
            return [Check("9", "Clean clone", FAIL, "git clone failed", out.strip().splitlines()[-6:])]
        names = run(["git", "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"], cwd=dest)[1]
        for line in names.splitlines():
            key, _, path = line.partition(" ")
            name = key[len("submodule."):-len(".path")]
            git("config", f"submodule.{name}.url", str(ROOT / path.strip()), cwd=dest)  # the clone's own config: point at the local checkout, no network
        code, out = run(["git", "-c", "protocol.file.allow=always", "submodule", "update", "--init", "--recursive"], cwd=dest, timeout=600)
        if code != 0:
            return [Check("9", "Clean clone", FAIL, "submodules could not be cloned from the local checkouts", out.strip().splitlines()[-6:])]
        status = git("status", "--porcelain")[1].splitlines()
        untracked = [l[3:] for l in status if l.startswith("??")]
        modified = [l[3:] for l in status if not l.startswith("??")]
        note = [f"the clone holds the last commit: {len(modified)} modified and {len(untracked)} untracked file(s) in the working tree are not in it"]
        note += [f"  uncommitted: {p}" for p in (modified + untracked)[:25]]
        py = python_tests(dest, "9a")
        py.name = "Clean clone: Python tests"
        out_checks.append(py)
        code, text = run([PY, "-m", "clearwake", "--help"], cwd=dest, timeout=120)
        out_checks.append(Check("9b", "Clean clone: python -m clearwake --help", PASS if code == 0 else FAIL, "prints help" if code == 0 else f"exit {code}", [] if code == 0 else text.strip().splitlines()[-8:]))
        nd = node_tests(dest, "9c")
        nd.name = "Clean clone: Node tests"
        out_checks.append(nd)
        out_checks.append(Check("9d", "Clean clone: what the clone does not contain", NOTE, note[0], note[1:]))
        if py.status == FAIL:
            py.details.insert(0, "a failure here that passes in the working tree depends on an untracked, ignored or uncommitted file")
        return out_checks
    finally:
        rmtree_force(tmp)


def docker_note():
    code, out = run(["docker", "--version"], timeout=30)
    if code == 0:
        return Check("10", "Docker boundary", NOTE, f"Docker is available: {out.strip().splitlines()[0]}. Nothing was started; python scripts/airgap.py (case m) and the Dockerfiles stay unchecked here.")
    return Check("10", "Docker boundary", NOTE, "Docker is not available: the network cut run (scripts/airgap.py), Dockerfile and Dockerfile.render are not checked here", [out.strip()[:200]])


# -------------------------------------------------------------------------------------------------------------------- main

def groups():
    def g1():
        return [python_tests(), node_tests()]

    def g2():
        return [secret_scan(), ignore_rules()]

    def g5():
        logs, reports, problems = gather_logs()
        a, results = receipts_python(logs, problems)
        return [a, receipts_pairs(reports), receipts_browser(logs, results)]

    def g6():
        return [numbers_check(), placeholders()]

    def g8():
        return [md_links(), site_assets(), csp_check()]

    return {1: g1, 2: g2, 3: lambda: [author_check()], 4: lambda: [word_scan()], 5: g5, 6: g6, 7: spec_checks, 8: g8, 9: clean_clone, 10: lambda: [docker_note()]}


def parse_set(s):
    return {int(x) for x in s.split(",") if x.strip()} if s else set()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Final check before submission.")
    ap.add_argument("--only", default="", help="comma separated group numbers to run")
    ap.add_argument("--skip", default="", help="comma separated group numbers to skip")
    ap.add_argument("--no-write", action="store_true", help="do not write data/runs/final-check-<timestamp>.json")
    args = ap.parse_args(argv)
    only, skip = parse_set(args.only), parse_set(args.skip)
    started = dt.datetime.now().astimezone()
    results = []
    for number, fn in groups().items():
        if (only and number not in only) or number in skip:
            continue
        try:
            checks = fn()
        except Exception as e:  # noqa: BLE001
            checks = [Check(str(number), f"group {number}", FAIL, f"the check itself crashed: {type(e).__name__}: {e}")]
        for c in checks:
            results.append(c)
            print(f"{c.status}  {c.cid:<3} {c.name}: {c.summary}", flush=True)
            if c.status != PASS:
                for d in c.details[:40]:
                    print(f"        {d}")
                if len(c.details) > 40:
                    print(f"        ... {len(c.details) - 40} more in the JSON file")
    passed = sum(c.status == PASS for c in results)
    failed = [c for c in results if c.status == FAIL]
    notes = sum(c.status == NOTE for c in results)
    print(f"\nSUMMARY: {len(results)} checks, {passed} passed, {len(failed)} failed, {notes} noted" + (f". FAILED: {', '.join(c.cid for c in failed)}" if failed else ". All clear."))
    if not args.no_write:
        RUNS.mkdir(parents=True, exist_ok=True)
        path = RUNS / f"final-check-{started.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps({"started": started.isoformat(timespec="seconds"), "finished": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                                    "summary": {"checks": len(results), "passed": passed, "failed": len(failed), "noted": notes, "failed_ids": [c.cid for c in failed]},
                                    "checks": [c.as_dict() for c in results]}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("written", rel(path))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
