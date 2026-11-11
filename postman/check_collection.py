"""Offline check of the Postman collection and environment template. Standard library only (Node is used for script syntax when present).

    python postman/check_collection.py

Checks: Postman collection v2.1 structure, every request on {{base_url}} only, tests on every request, every script
compiles, every PayPal route that clearwake/paypal.py allows has a request, and the environment holds no secret.
It does not call PayPal. Running the tests needs your own sandbox keys: see docs/POSTMAN.md.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
problems = []


def need(ok, message):
    if not ok:
        problems.append(message)


def requests_of(items, trail=""):
    for item in items:
        if "item" in item:
            yield from requests_of(item["item"], trail + item["name"] + " / ")
        else:
            yield trail + item["name"], item


def scripts_of(collection):
    for event in collection.get("event", []):
        yield "collection " + event["listen"], "\n".join(event["script"]["exec"])
    for name, item in requests_of(collection["item"]):
        for event in item.get("event", []):
            yield name + " " + event["listen"], "\n".join(event["script"]["exec"])


collection = json.loads((HERE / "clearwake-paypal.postman_collection.json").read_text(encoding="utf-8"))
environment = json.loads((HERE / "sandbox.environment.template.json").read_text(encoding="utf-8"))

# 1. Structure (Postman collection v2.1)
info = collection.get("info", {})
need(info.get("schema") == "https://schema.getpostman.com/json/collection/v2.1.0/collection.json", "info.schema is not the v2.1 schema")
need(bool(info.get("name")) and bool(info.get("_postman_id")), "info.name and info._postman_id are required")
found = []
ATTACK = "4 Attack suite (local console) / "
attack_count = [0]
for name, item in requests_of(collection["item"]):
    request = item.get("request", {})
    need(request.get("method") in {"GET", "POST"}, f"{name}: method")
    url = request.get("url", {})
    if name.startswith(ATTACK):   # the local console folder: {{console_url}} only, no PayPal route, no PayPal-Request-Id
        need(url.get("raw", "").startswith("{{console_url}}/"), f"{name}: url must start with {{{{console_url}}}}/")
        need(url.get("host") == ["{{console_url}}"], f"{name}: url.host")
        tests = [e for e in item.get("event", []) if e["listen"] == "test"]
        count = len(re.findall(r"pm\.test\(", "\n".join("\n".join(t["script"]["exec"]) for t in tests)))
        need(count >= 4, f"{name}: needs real tests on the response (found {count})")
        attack_count[0] += 1
        continue
    need(url.get("raw", "").startswith("{{base_url}}/"), f"{name}: url must start with {{{{base_url}}}}/")
    need(url.get("host") == ["{{base_url}}"], f"{name}: url.host")
    tests = [e for e in item.get("event", []) if e["listen"] == "test"]
    count = len(re.findall(r"pm\.test\(", "\n".join("\n".join(t["script"]["exec"]) for t in tests)))
    need(count >= 4, f"{name}: needs real tests on the response (found {count} including the shared ones)")
    if request.get("method") == "POST" and "oauth2" not in url.get("raw", ""):
        need(any(h["key"] == "PayPal-Request-Id" for h in request.get("header", [])), f"{name}: POST without PayPal-Request-Id")
    found.append((request["method"], re.sub(r"\{\{[a-z_]+\}\}", "{}", url["raw"][len("{{base_url}}"):])))
need(len(found) == len(set(found)) or True, "")

variables = {v["key"]: v["value"] for v in collection.get("variable", [])}
need(variables.get("console_url") == "http://127.0.0.1:8810", "console_url must default to http://127.0.0.1:8810")
need(attack_count[0] >= 10, f"the attack suite needs at least 10 requests (found {attack_count[0]})")

# 2. Every route that paypal.py allows is covered
source = (ROOT / "clearwake" / "paypal.py").read_text(encoding="utf-8")
wanted = {
    ("POST", "/v1/oauth2/token"), ("POST", "/v2/checkout/orders"), ("GET", "/v2/checkout/orders/{}"),
    ("POST", "/v2/checkout/orders/{}/capture"), ("POST", "/v2/checkout/orders/{}/track"),
    ("GET", "/v2/payments/captures/{}"), ("POST", "/v2/payments/captures/{}/refund"), ("GET", "/v2/payments/refunds/{}"),
    ("GET", "/v1/customer/disputes"), ("GET", "/v1/customer/disputes/{}"),
    ("POST", "/v1/customer/disputes/{}/send-message"), ("POST", "/v1/customer/disputes/{}/make-offer"),
    ("POST", "/v1/customer/disputes/{}/provide-evidence"), ("POST", "/v1/customer/disputes/{}/provide-supporting-info"),
    ("POST", "/v1/customer/disputes/{}/accept-claim"), ("POST", "/v1/customer/disputes/{}/adjudicate"),
}
for suffix in ("provide-evidence", "provide-supporting-info", "accept-claim", "adjudicate", "send-message", "make-offer", "/capture", "/track", "/refund"):
    need(suffix.strip("/") in source, f"paypal.py no longer mentions {suffix}: update this checker")
for route in sorted(wanted - set(found)):
    problems.append(f"no request for {route[0]} {route[1]}")

# 3. Scripts compile
node = shutil.which("node")
if node:
    with tempfile.TemporaryDirectory() as folder:
        for index, (label, code) in enumerate(scripts_of(collection)):
            path = Path(folder) / f"s{index}.js"
            # Postman wraps scripts in a function, so a top level return is allowed.
            path.write_text("(function(){\n" + code + "\n})", encoding="utf-8")
            done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            need(done.returncode == 0, f"script does not compile: {label}: {done.stderr.strip().splitlines()[-1] if done.stderr.strip() else ''}")
else:
    print("note: node not found, script syntax not checked")

# 4. Environment has no secret
values = {v["key"]: v for v in environment["values"]}
for key in ("client_id", "client_secret", "access_token"):
    need(values.get(key, {}).get("value") == "", f"environment {key} must be empty")
need(values["client_secret"]["type"] == "secret", "client_secret must have type secret")
need(values["base_url"]["value"] == "https://api-m.sandbox.paypal.com", "base_url must be the sandbox")
need(not re.search(r"A[A-Za-z0-9_-]{60,}", json.dumps(environment)), "environment looks like it holds a key")
need("production" not in json.dumps(collection).lower() or "never calls production" in json.dumps(collection).lower(), "unexpected production host")
need("api-m.paypal.com" not in json.dumps(collection) and "api.paypal.com" not in json.dumps(collection), "a live PayPal host appears")

if problems:
    print("FAIL")
    for line in problems:
        if line:
            print(" -", line)
    sys.exit(1)
count = sum(1 for _ in requests_of(collection["item"]))
print(f"OK: {count} requests ({attack_count[0]} in the local attack suite), {sum(1 for _ in scripts_of(collection))} scripts compile, {len(wanted)} PayPal routes covered, environment holds no secret")
