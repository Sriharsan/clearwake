"""One OpenAI compatible adapter, three backends. Models only propose; policy decides.

Backends: "ollama" (free open weights model on loopback, default), "meta" (Meta Model API, off unless
CLEARWAKE_META_ACK is set), "scripted" (deterministic rules, always labelled "scripted, not AI").
"""
from dataclasses import dataclass
import hashlib
import json
import os
import re
import time
from urllib.request import ProxyHandler, Request, build_opener

OLLAMA = "http://127.0.0.1:11434/v1/chat/completions"


def ollama_url():
    """Loopback by default. Inside the isolated container network the model runs in the "ollama" container, also inside the boundary."""
    host = os.environ.get("CLEARWAKE_OLLAMA", "127.0.0.1:11434")
    if not re.fullmatch(r"(?:127\.0\.0\.1|ollama):11434", host):
        raise ValueError("CLEARWAKE_OLLAMA must be 127.0.0.1:11434 or ollama:11434: the model stays inside the boundary.")
    return f"http://{host}/v1/chat/completions"
META = "https://api.meta.ai/v1/chat/completions"


@dataclass(frozen=True)
class Proposal:
    backend: str        # "ollama", "meta" or "scripted"
    model: str          # exact model name, or "scripted"
    label: str          # what the screen shows
    value: dict | None  # parsed JSON proposal, or None if the model gave nothing usable
    note: str = ""
    call: dict | None = None  # measured model call: prompt_sha256, latency_ms, tokens; None for scripted


class Adapter:
    def __init__(self, backend=None, model=None, send=None, timeout=90):
        self.backend = backend or os.environ.get("CLEARWAKE_MODEL_BACKEND", "scripted")
        if self.backend not in ("ollama", "meta", "scripted"):
            raise ValueError("Model backend must be ollama, meta or scripted.")
        if self.backend == "meta" and os.environ.get("CLEARWAKE_META_ACK") != "I_CONFIRM_META_CREDIT_TERMS":
            raise ValueError("The Meta backend is off until Sri confirms the credit terms (CLEARWAKE_META_ACK).")
        self.model = model or os.environ.get("CLEARWAKE_MODEL", {"ollama": "qwen3.5:4b", "meta": "muse-spark-1.3", "scripted": "scripted"}[self.backend])
        self.send, self.timeout = send or self._send, timeout
        self.options = {"max_tokens": 300, "reasoning_effort": "none"}  # bound the reply; reasoning off (the native route also sets think false)

    def label(self):
        return "scripted, not AI" if self.backend == "scripted" else f"{self.model} via {'Ollama on this machine' if self.backend == 'ollama' else 'Meta Model API'}"

    def _send(self, url, payload, headers):
        opener = build_opener(ProxyHandler({}))
        native = self.backend == "ollama" and url.endswith("/v1/chat/completions")
        if native:  # Ollama's own chat route accepts the thread count and switches reasoning off; the OpenAI route accepts neither
            url = url.replace("/v1/chat/completions", "/api/chat")
            payload = {"model": payload["model"], "stream": False, "format": payload.get("ollama_format") or "json", "think": False, "keep_alive": "30m", "messages": payload["messages"],
                       "options": {"temperature": 0, "num_predict": payload.get("max_tokens", 400), "num_thread": int(os.environ.get("CLEARWAKE_OLLAMA_THREADS", "6"))}}
        with opener.open(Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST"), timeout=self.timeout) as response:
            reply = json.loads(response.read(1 << 20))
        if native:
            return {"choices": [{"message": {"content": reply["message"]["content"]}}],
                    "usage": {"prompt_tokens": reply.get("prompt_eval_count"), "completion_tokens": reply.get("eval_count")}}
        return reply

    def propose(self, system, user, fields, scripted, required=None, schema=None, max_tokens=None):
        """Ask for a JSON object with `fields` (`required` keys must all be present, default all). `scripted` is the rule used when backend is scripted.

        schema: a JSON schema; on Ollama it is sent as the native `format`, so the reply always matches it. max_tokens bounds the reply for this call."""
        if self.backend == "scripted":
            return Proposal("scripted", "scripted", self.label(), scripted())
        url, headers = (ollama_url(), {}) if self.backend == "ollama" else (META, {"Authorization": "Bearer " + os.environ.get("META_API_KEY", "")})
        payload = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system + " Reply with one JSON object with exactly these keys: " + ", ".join(fields) + "."},
                                {"role": "user", "content": user}]}
        if self.backend == "ollama":
            payload.update(self.options)
            if schema is not None:
                payload["ollama_format"] = schema
            if max_tokens:
                payload["max_tokens"] = max_tokens
        call = {"prompt_sha256": hashlib.sha256(json.dumps(payload["messages"], sort_keys=True).encode()).hexdigest()}
        started = time.perf_counter()
        try:
            reply = self.send(url, payload, headers)
            call["latency_ms"] = round((time.perf_counter() - started) * 1000)
            usage = reply.get("usage") or {}
            call["prompt_tokens"], call["completion_tokens"] = usage.get("prompt_tokens"), usage.get("completion_tokens")
            value = json.loads(reply["choices"][0]["message"]["content"])
        except Exception as error:  # a bad or missing reply is not an instruction
            call["latency_ms"] = call.get("latency_ms", round((time.perf_counter() - started) * 1000))
            call["error"] = type(error).__name__
            return Proposal(self.backend, self.model, self.label(), None, f"no usable proposal ({type(error).__name__})", call)
        need = set(fields if required is None else required)
        if not isinstance(value, dict) or not need <= set(value) <= set(fields):
            call["error"] = "unexpected fields"
            return Proposal(self.backend, self.model, self.label(), None, "proposal had unexpected fields", call)
        return Proposal(self.backend, self.model, self.label(), value, "", call)
