"""One OpenAI compatible adapter, three backends. Models only propose; policy decides.

Backends: "ollama" (free open weights model on loopback, default), "meta" (Meta Model API, off unless
CLEARWAKE_META_ACK is set), "scripted" (deterministic rules, always labelled "scripted, not AI").
"""
from dataclasses import dataclass
import json
import os
import re
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


class Adapter:
    def __init__(self, backend=None, model=None, send=None, timeout=90):
        self.backend = backend or os.environ.get("CLEARWAKE_MODEL_BACKEND", "scripted")
        if self.backend not in ("ollama", "meta", "scripted"):
            raise ValueError("Model backend must be ollama, meta or scripted.")
        if self.backend == "meta" and os.environ.get("CLEARWAKE_META_ACK") != "I_CONFIRM_META_CREDIT_TERMS":
            raise ValueError("The Meta backend is off until Sri confirms the credit terms (CLEARWAKE_META_ACK).")
        self.model = model or os.environ.get("CLEARWAKE_MODEL", {"ollama": "qwen2.5-coder:3b", "meta": "muse-spark-1.3", "scripted": "scripted"}[self.backend])
        self.send, self.timeout = send or self._send, timeout

    def label(self):
        return "scripted, not AI" if self.backend == "scripted" else f"{self.model} via {'Ollama on this machine' if self.backend == 'ollama' else 'Meta Model API'}"

    def _send(self, url, payload, headers):
        opener = build_opener(ProxyHandler({}))
        with opener.open(Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST"), timeout=self.timeout) as response:
            return json.loads(response.read(1 << 20))

    def propose(self, system, user, fields, scripted):
        """Ask for a JSON object with exactly `fields`. `scripted` is the rule used when backend is scripted."""
        if self.backend == "scripted":
            return Proposal("scripted", "scripted", self.label(), scripted())
        url, headers = (ollama_url(), {}) if self.backend == "ollama" else (META, {"Authorization": "Bearer " + os.environ.get("META_API_KEY", "")})
        payload = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system + " Reply with one JSON object with exactly these keys: " + ", ".join(fields) + "."},
                                {"role": "user", "content": user}]}
        try:
            content = self.send(url, payload, headers)["choices"][0]["message"]["content"]
            value = json.loads(content)
        except Exception as error:  # a bad or missing reply is not an instruction
            return Proposal(self.backend, self.model, self.label(), None, f"no usable proposal ({type(error).__name__})")
        if not isinstance(value, dict) or set(value) != set(fields):
            return Proposal(self.backend, self.model, self.label(), None, "proposal had unexpected fields")
        return Proposal(self.backend, self.model, self.label(), value)
