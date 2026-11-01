"""Case m for real: Clearwake in a network isolated Docker network, the network cut mid batch, then restored.

  python scripts/airgap.py            needs Docker, the sandbox keys in .env and a local Ollama model folder
  python scripts/airgap.py --boundary-only   only the boundary checks (steps 1 and 2), leaving the stack up: no sandbox call, no refund

1. Builds the image and starts the egress gateway (the only service with a route out) and Ollama (inside only).
2. Checks the boundary from inside: no direct route out, a host off the allowlist is blocked and receipted,
   the local model answers inside.
3. Runs case m against the PayPal sandbox through the gateway. When the first refund is verified it disconnects the
   gateway from the outside network (the cable pull), waits for the held actions, reconnects and lets it finish.
4. Verifies every receipt log in a container with networking disabled.
Results go to data/airgap/airgap-<time>.json. Keys never leave .env except as run time variables of one container.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
AIRGAP = ROOT / "data" / "airgap"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.airgap.yml")]
OUTSIDE, GATEWAY = "clearwake-airgap_outside", "clearwake-airgap-egress-1"

PROBE_DIRECT = "import socket\ntry:\n socket.create_connection(('api-m.sandbox.paypal.com',443),5); print('REACHED')\nexcept OSError as e: print('NO ROUTE', type(e).__name__)"
PROBE_BLOCKED = ("import socket\ns=socket.create_connection(('egress',8080),5)\ns.sendall(b'CONNECT example.com:443 HTTP/1.1\\r\\nHost: example.com\\r\\n\\r\\n')\n"
                 "print(s.recv(100).split(b'\\r\\n')[0].decode())")
PROBE_MODEL = ("import json,urllib.request\nprint([m['name'] for m in json.load(urllib.request.build_opener(urllib.request.ProxyHandler({}))"
               ".open('http://ollama:11434/api/tags',timeout=30))['models']])")
VERIFY_ALL = """
import sys, pathlib
sys.path.insert(0, '/app/vendor/verdock-core')
from verdock_core.receipts import load_seed, verify_log
from verdock_core import ed25519
for log in sorted(pathlib.Path('/app/data/airgap').rglob('*.ndjson')):
    seed = log.parent / ('egress.seed' if log.name == 'egress.ndjson' else 'merchant.seed')
    report = verify_log(str(log), ed25519.public_key(load_seed(str(seed))).hex())
    print(('ok  ' if report['ok'] else 'FAIL'), report['count'], 'lines', log.relative_to('/app/data/airgap'))
"""


def sh(*args, check=True, capture=True):
    result = subprocess.run(list(args), cwd=ROOT, capture_output=capture, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode:
        raise SystemExit(f"failed: {' '.join(args[:4])}...\n{result.stderr[-800:]}")
    return result.stdout.strip() if capture else ""


def inside(code, network=True):
    if network:
        return sh(*COMPOSE, "run", "--rm", "--no-deps", "-T", "clearwake", "python", "-c", code, check=False)
    return sh("docker", "run", "--rm", "--network", "none", "-v", f"{AIRGAP}:/app/data/airgap", "clearwake-airgap:local", "python", "-c", code, check=False)


def wait_for(name, timeout=600):
    started = time.monotonic()
    while not (AIRGAP / name).exists():
        if time.monotonic() - started > timeout:
            raise SystemExit(f"timed out waiting for {name}")
        time.sleep(0.5)


def main():
    os.environ.setdefault("OLLAMA_MODELS", str(Path.home() / ".ollama" / "models"))
    AIRGAP.mkdir(parents=True, exist_ok=True)
    for signal in AIRGAP.glob("m-*"):
        signal.unlink()
    report = {"started": datetime.now().isoformat(timespec="seconds"), "boundary": {}}
    print("building and starting the egress gateway and the local model ...", flush=True)
    sh(*COMPOSE, "up", "-d", "--build", "egress", "ollama")
    time.sleep(3)
    report["gateway"] = sh(*COMPOSE, "logs", "egress").splitlines()[-1:]
    probes = {"direct route out from the agents' container": PROBE_DIRECT, "example.com through the gateway": PROBE_BLOCKED,
              "models inside the boundary": PROBE_MODEL}
    with ThreadPoolExecutor(max_workers=3) as pool:  # three independent read only checks, run together
        results = dict(zip(probes, pool.map(inside, probes.values())))
    report["boundary"].update(results)
    for key, value in report["boundary"].items():
        print(f"  {key}: {value}", flush=True)

    if "--boundary-only" in sys.argv:  # checks the boundary and stops: no sandbox call, no refund
        print("the gateway and the model stay up; stop them with: docker compose -f compose.airgap.yml down", flush=True)
        return 0
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "ollama"
    print(f"case m: sandbox refunds through the gateway, model {model} inside ...", flush=True)
    run = subprocess.Popen([*COMPOSE, "run", "--rm", "--no-deps", "-T", "clearwake", "python", "scripts/cases.py", "--sandbox", "--only", "m",
                            "--model", model], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    wait_for("m-before-cut")
    sh("docker", "network", "disconnect", OUTSIDE, GATEWAY)
    report["cut_at"] = datetime.now().isoformat(timespec="seconds")
    print("  network cut: the gateway has no route out", flush=True)
    (AIRGAP / "m-cut").write_text(report["cut_at"], encoding="utf-8")
    wait_for("m-held")
    sh("docker", "network", "connect", OUTSIDE, GATEWAY)
    report["restored_at"] = datetime.now().isoformat(timespec="seconds")
    print("  network restored", flush=True)
    (AIRGAP / "m-reconnected").write_text(report["restored_at"], encoding="utf-8")
    output, _ = run.communicate(timeout=900)
    report["case_m"] = [line for line in output.splitlines() if line.strip()]
    print("\n".join(report["case_m"]), flush=True)

    report["offline_verify"] = inside(VERIFY_ALL, network=False).splitlines()
    print("receipts verified in a container with networking disabled:", flush=True)
    print("\n".join("  " + line for line in report["offline_verify"]), flush=True)
    sh(*COMPOSE, "down")
    out = AIRGAP / f"airgap-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    passed = run.returncode == 0 and all(line.startswith("ok") for line in report["offline_verify"]) and report["offline_verify"]
    print(f"\n{'PASS' if passed else 'FAIL'}: saved {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
