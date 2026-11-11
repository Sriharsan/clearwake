"""Measure where the time goes in a local model call, and sweep the options that change it.

  python scripts/ai_speed.py profile --model qwen2.5-coder:3b            merchant decision, buyer draft and rules call, one table
  python scripts/ai_speed.py sweep --model qwen2.5-coder:3b [--grammar] --threads 6,8,10,14 --ctx 512,1024 --batch 128,512
  python scripts/ai_speed.py load                                         CPU load now (run the sweep on a quiet machine)

Every row is a real call to Ollama's native /api/chat on loopback ("local run on the local provider"). It reads prompt_eval_count,
eval_count and the durations Ollama returns, so prompt time, generation time and weight load time are shown apart.
Results go to data/runs/ai-speed-<time>.json. Nothing is sent anywhere else.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

URL = "http://127.0.0.1:11434/api/chat"

# One representative input per call type. The merchant one is the exact prompt shape swarm.inquiry builds.
MERCHANT_FIELDS = None  # taken from swarm.INQUIRY_FIELDS
MERCHANT_DATA = "reason: MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED\nbuyer_amount: 2.50 USD\nowner_offer_limit: 5.00 USD\nrecords: 0\ndeadline: ok\n<buyer>I ordered 3 notebooks and the box had 2. Please fix this.</buyer>"
BUYER_DATA = "reason: item not received\nitem: notebook-a5 x3\nwhat_happened: 2 of 3 arrived\n"
RULES_DATA = "<rules>Refund up to 30 dollars without asking me, ask me above 50 dollars, fight item not received disputes.</rules>"


def systems():
    from clearwake import swarm, rules_nl
    from clearwake.models import fields_instruction
    merchant = swarm.INQUIRY_SYSTEM
    buyer = "You are a buyer's agent writing the first message of a PayPal dispute. One or two short polite sentences, at most 25 words in all. Say what went wrong and ask for a refund of the affected part. No number except the order id and the amount paid."
    return {"merchant decision": (merchant, MERCHANT_DATA, swarm.INQUIRY_FIELDS, swarm.INQUIRY_SCHEMA, swarm.INQUIRY_MAX_TOKENS),
            "buyer draft": (buyer, BUYER_DATA, ["message"], {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"], "additionalProperties": False}, 60),
            "rules": (rules_nl.SYSTEM["merchant"], RULES_DATA, rules_nl.MERCHANT_FIELDS, rules_nl.SCHEMAS["merchant"], rules_nl.MAX_TOKENS)}


def chat(model, system, user, fields, schema, max_tokens, threads=6, ctx=1024, batch=512, keep_alive="30m", timeout=300, grammar=False):
    from clearwake.models import fields_instruction
    body = {"model": model, "stream": False, "think": False, "keep_alive": keep_alive,
            "messages": [{"role": "system", "content": system + fields_instruction(fields)}, {"role": "user", "content": user}],
            "options": {"temperature": 0, "num_predict": max_tokens, "num_thread": threads, "num_ctx": ctx, "num_batch": batch}}
    if grammar:
        body["format"] = schema
    started = time.perf_counter()
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"), timeout=timeout) as r:
        reply = json.loads(r.read())
    wall = (time.perf_counter() - started) * 1000
    ms = lambda key: round(reply.get(key, 0) / 1e6)
    gen = reply.get("eval_count") or 0
    return {"wall_ms": round(wall), "total_ms": ms("total_duration"), "load_ms": ms("load_duration"), "prompt_tokens": reply.get("prompt_eval_count"), "prompt_ms": ms("prompt_eval_duration"),
            "gen_tokens": gen, "gen_ms": ms("eval_duration"), "tokens_per_s": round(gen / (reply["eval_duration"] / 1e9), 1) if gen and reply.get("eval_duration") else None,
            "reply": reply["message"]["content"][:200], "grammar": grammar}


def repeat(model, call, n=3, **options):
    chat(model, *call, **options)                       # warm, not counted
    rows = [chat(model, *call, **options) for _ in range(n)]
    pick = lambda key: statistics.median(r[key] for r in rows if r[key] is not None)
    return {"median_wall_ms": round(pick("wall_ms")), "prompt_tokens": rows[0]["prompt_tokens"], "prompt_ms": round(pick("prompt_ms")),
            "gen_tokens": round(pick("gen_tokens")), "gen_ms": round(pick("gen_ms")), "tokens_per_s": round(pick("tokens_per_s"), 1), "load_ms": rows[0]["load_ms"], "reply": rows[0]["reply"]}


def cpu_load():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return float(out)
    except Exception:
        return None


def arg(name, default):
    a = sys.argv
    return a[a.index(name) + 1] if name in a else default


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "profile"
    model = arg("--model", "qwen2.5-coder:3b")
    if mode == "load":
        print("cpu load percent:", cpu_load())
        return
    calls = systems()
    load = cpu_load()
    out = {"label": "local run on the local provider", "model": model, "started": datetime.now(timezone.utc).isoformat(), "cpu_load_percent_before": load, "rows": []}
    print(f"{model}  cpu load before: {load}%")
    if mode == "profile":
        for name, call in calls.items():
            row = {"call": name, **repeat(model, call, threads=int(arg("--threads", "6")), grammar="--grammar" in sys.argv, ctx=int(arg("--ctx", "1024")), batch=int(arg("--batch", "512")))}
            out["rows"].append(row)
            print(f"{name:18} wall {row['median_wall_ms']:>6} ms  prompt {row['prompt_tokens']} tok {row['prompt_ms']} ms  gen {row['gen_tokens']} tok {row['gen_ms']} ms  {row['tokens_per_s']} tok/s  load {row['load_ms']} ms")
    elif mode == "sweep":
        name = arg("--call", "merchant decision")
        for t in [int(x) for x in arg("--threads", "6").split(",")]:
            for c in [int(x) for x in arg("--ctx", "1024").split(",")]:
                for b in [int(x) for x in arg("--batch", "512").split(",")]:
                    row = {"call": name, "threads": t, "ctx": c, "batch": b, **repeat(model, calls[name], threads=t, ctx=c, batch=b, grammar="--grammar" in sys.argv)}
                    out["rows"].append(row)
                    print(f"threads {t:>2} ctx {c:>4} batch {b:>4}  wall {row['median_wall_ms']:>6} ms  prompt {row['prompt_ms']} ms  gen {row['gen_ms']} ms  {row['tokens_per_s']} tok/s", flush=True)
    out["cpu_load_percent_after"] = cpu_load()
    path = ROOT / "data" / "runs" / f"ai-speed-{mode}-{model.replace(':', '-')}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("saved", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
