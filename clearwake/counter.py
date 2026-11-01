"""Counting the items in a packing photo, inside the merchant's own machine. Nothing goes to an outside AI.

Three backends, and every result carries a label that says which one ran:

* "sam": SAM 3 from Meta (open weights, SAM License) through tools/sam/count.py in its own environment. It runs offline
  (HF_HUB_OFFLINE=1) once the weights are in the local cache. Label: the model name and the device, for example "facebook/sam3 sam3.pt, local, cpu".
* "recorded": the result of a real SAM run saved next to the photo as <photo>.count.json. It is used only when the file's
  SHA-256 and the prompt match. Label: "recorded <model> run of <date>".
* "scripted": a fixed table for rehearsal and tests. Label: "scripted count, not SAM".
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
SAM_PYTHON = ROOT / "tools" / "sam" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SAM_SCRIPT = ROOT / "tools" / "sam" / "count.py"
PROMPT = re.compile(r"[A-Za-z][A-Za-z -]{0,39}\Z")


class CounterError(Exception):
    """The count could not be made. Nothing is recorded as counted."""


@dataclass(frozen=True)
class Counted:
    count: int
    prompt: str
    image_sha256: str
    model: str           # what ran, for the receipt
    device: str
    milliseconds: int
    label: str           # what the screens and receipts say about how it was counted
    scores_milli: tuple = ()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Counter:
    def __init__(self, backend="scripted", table=None, runner=None, python=None, offline=True):
        if backend not in ("sam", "recorded", "scripted"):
            raise ValueError("Counter backend must be sam, recorded or scripted.")
        self.backend, self.table, self.offline = backend, dict(table or {}), offline
        self.runner, self.python = runner or subprocess.run, Path(python) if python else SAM_PYTHON

    def count(self, image_path, prompt):
        if not isinstance(prompt, str) or not PROMPT.fullmatch(prompt):
            raise CounterError("The prompt must be a short noun phrase of letters.")
        path = Path(image_path)
        if not path.is_file():
            raise CounterError(f"No photo at {path.name}.")
        digest = sha256_file(path)
        if self.backend == "scripted":
            if path.name not in self.table:
                raise CounterError(f"The scripted counter has no count for {path.name}.")
            return Counted(int(self.table[path.name]), prompt, digest, "scripted", "none", 0, "scripted count, not SAM")
        if self.backend == "recorded":
            saved = Path(str(path) + ".count.json")
            if not saved.is_file():
                raise CounterError(f"No recorded SAM run for {path.name}.")
            data = json.loads(saved.read_text(encoding="utf-8"))
            if data.get("image_sha256") != digest or data.get("prompt") != prompt:
                raise CounterError("The recorded run is for a different photo or prompt.")
            return self._from(data, f"recorded {data['model']} run of {data.get('recorded', 'unknown date')}")
        return self._run_sam(path, prompt)

    def _run_sam(self, path, prompt):
        if not self.python.is_file():
            raise CounterError("SAM is not set up. Run tools/sam/setup.ps1 (see tools/sam/README.md).")
        env = {**os.environ, "HF_HUB_OFFLINE": "1" if self.offline else "0", "PYTHONIOENCODING": "utf-8",
               "HF_HOME": os.environ.get("CLEARWAKE_HF_HOME") or os.environ.get("HF_HOME") or str(ROOT.parent / "_hf")}
        env.pop("HF_TOKEN", None)   # counting never needs the token, so it never reaches the counter
        done = self.runner([str(self.python), str(SAM_SCRIPT), str(path), "--prompt", prompt], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800, env=env)
        if done.returncode != 0:
            raise CounterError("SAM did not finish: " + (done.stderr or "no message").strip().splitlines()[-1][:200])
        try:
            data = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise CounterError("SAM printed no result.") from None
        if data.get("image_sha256") != sha256_file(path):
            raise CounterError("SAM counted a different file than the one asked for.")
        return self._from(data, f"{data['model']}, local, {data['device']}")

    @staticmethod
    def _from(data, label):
        try:
            return Counted(int(data["count"]), data["prompt"], data["image_sha256"], data["model"], data["device"],
                           int(data["milliseconds"]), label, tuple(int(s) for s in data.get("scores_milli", ())))
        except (KeyError, TypeError, ValueError):
            raise CounterError("The count result was malformed.") from None
