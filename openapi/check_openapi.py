"""Offline check of openapi/clearwake-console.openapi.yaml. Needs PyYAML and jsonschema (both already common); nothing is installed or downloaded.

    python openapi/check_openapi.py            # structure, references, schemas, routes against clearwake/server.py
    python openapi/check_openapi.py --live     # also start the console on 127.0.0.1:8844 and validate real responses

Structural checks follow OpenAPI 3.1: version, info, paths, one operationId each, every $ref resolves, every schema is valid
JSON Schema 2020-12, every security scheme named exists, every POST route in clearwake/server.py has an operation and the other way round.
"""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
spec = yaml.safe_load((ROOT / "openapi" / "clearwake-console.openapi.yaml").read_text(encoding="utf-8"))
problems = []


def need(ok, message):
    if not ok:
        problems.append(message)


need(str(spec.get("openapi", "")).startswith("3.1."), "openapi must be 3.1.x")
for key in ("title", "version"):
    need(bool(spec.get("info", {}).get(key)), f"info.{key} is required")
need(bool(spec.get("paths")), "paths is required")

# References
text = json.dumps(spec)
for ref in sorted(set(re.findall(r'"\$ref": "([^"]+)"', text))):
    node = spec
    ok = ref.startswith("#/")
    for part in ref[2:].split("/") if ok else []:
        ok = ok and isinstance(node, dict) and part in node
        node = node.get(part) if ok else None
    need(ok, f"unresolved $ref {ref}")

# Operations
ids, operations = set(), {}
schemes = set(spec["components"].get("securitySchemes", {}))
for path, item in spec["paths"].items():
    need(path.startswith("/"), f"path {path} must start with /")
    for method, op in item.items():
        if method not in {"get", "post", "put", "patch", "delete"}:
            continue
        operations[(method.upper(), path)] = op
        need(op.get("operationId") not in ids, f"duplicate operationId {op.get('operationId')}")
        ids.add(op.get("operationId"))
        need(bool(op.get("responses")), f"{method} {path}: responses required")
        need(bool(op.get("summary")), f"{method} {path}: summary required")
        for requirement in op.get("security", []):
            for name in requirement:
                need(name in schemes, f"{method} {path}: unknown security scheme {name}")
        if method == "post":
            need("requestBody" in op, f"{method} {path}: requestBody required")
        if method == "post":
            need(any(r.get("csrfToken") is not None for r in op.get("security", [])), f"{method} {path}: POST must require csrfToken")

# Schemas are valid JSON Schema 2020-12
for name, schema in spec["components"]["schemas"].items():
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        problems.append(f"schema {name}: {str(error).splitlines()[0]}")

# Routes against the server source
server = (ROOT / "clearwake" / "server.py").read_text(encoding="utf-8")
posts = set(re.findall(r'action == "([a-z]+)"', server))
gets = set(re.findall(r'path == "/console/api/([a-z]+)"', server))
documented_posts = {p.rsplit("/", 1)[1] for (m, p) in operations if m == "POST"}
documented_gets = {p.rsplit("/", 1)[1] for (m, p) in operations if m == "GET"}
need(posts == documented_posts, f"POST routes differ: server {sorted(posts)} spec {sorted(documented_posts)}")
need(gets == documented_gets, f"GET routes differ: server {sorted(gets)} spec {sorted(documented_gets)}")
need("429" not in server or any("429" in op["responses"] for op in operations.values()),
     "server.py now returns 429: add the rate limit response to the spec (agent C added rate limits)")

defs = copy.deepcopy(spec["components"]["schemas"])
document = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": defs}
document_text = json.dumps(document).replace("#/components/schemas/", "#/$defs/")
document = json.loads(document_text)


def validate(name, value, where):
    validator = Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": document["$defs"]})
    for error in sorted(validator.iter_errors(value), key=lambda e: list(e.path))[:3]:
        problems.append(f"live {where}: {'/'.join(map(str, error.path))}: {error.message[:160]}")


def live():
    port = 8844
    folder = tempfile.mkdtemp(prefix="clearwake-openapi-")
    process = subprocess.Popen([sys.executable, "-m", "clearwake", "--port", str(port), "--database", os.path.join(folder, "c.sqlite3")],
                               cwd=ROOT, stdout=subprocess.DEVNULL)
    origin = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(origin + "/console/api/session", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        opener = urllib.request.build_opener()

        def call(method, path, body=None, headers=None):
            request = urllib.request.Request(origin + path, data=json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None),
                                             method=method, headers={"Origin": origin, "Content-Type": "application/json", **(headers or {})})
            try:
                with opener.open(request, timeout=30) as reply:
                    return reply.status, json.loads(reply.read() or b"{}"), reply.headers
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read() or b"{}"), error.headers

        status, session, headers = call("GET", "/console/api/session")
        validate("Session", session, "session")
        cookie = headers.get("Set-Cookie", "").split(";")[0]
        auth = {"Cookie": cookie, "X-Clearwake-CSRF": session["csrf"]}
        status, purchase, _ = call("POST", "/console/api/buy", {"request": "a pack of three A5 notebooks"}, auth)
        need(status == 200, f"live buy returned {status}")
        validate("Purchase", purchase, "buy")
        status, error, _ = call("POST", "/console/api/buy", {"request": "x"}, {"Cookie": cookie, "X-Clearwake-CSRF": "bad"})
        need(status == 403, f"live bad csrf returned {status}, spec says 403")
        validate("Error", error, "403 body")
        for key in ("c", "d", "n"):
            status, run, _ = call("POST", "/console/api/case", {"case": key}, auth)
            need(status == 200, f"live case {key} returned {status}")
            validate("CaseRun", run, f"case {key}")
        status, error, _ = call("POST", "/console/api/case", {"case": "z"}, auth)
        need(status == 400, f"live bad case returned {status}, spec says 400")
        approval = next((e for e in call("GET", "/console/api/state")[1]["inbox"] if e["status"] == "PENDING"), None)
        if approval:
            status, entry, _ = call("POST", "/console/api/approve", {"approval_id": approval["id"], "approver": "Owner Name"}, auth)
            need(status == 200, f"live approve returned {status}")
            validate("Entry", entry, "approve")
        status, state, _ = call("GET", "/console/api/state")
        validate("State", state, "state")
        status, receipts, _ = call("GET", "/console/api/receipts")
        validate("Receipts", receipts, "receipts")
        status, reset, _ = call("POST", "/console/api/reset", {}, auth)
        need(status == 200, f"live reset returned {status}")
        validate("ResetResult", reset, "reset")
        return True
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()


did_live = False
if "--live" in sys.argv:
    did_live = live()

if problems:
    print("FAIL")
    for line in problems:
        print(" -", line)
    sys.exit(1)
print(f"OK: OpenAPI {spec['openapi']}, {len(operations)} operations, {len(spec['components']['schemas'])} schemas, routes match clearwake/server.py"
      + (", real responses validated against the schemas" if did_live else ""))
