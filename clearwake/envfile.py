"""Load known names from the ignored local .env. Values are never printed or returned."""
from pathlib import Path
import os
import re

NAMES = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_BASE_URL", "CLEARWAKE_SANDBOX_ACK", "CLEARWAKE_REFUND_AMOUNT", "PAYPAL_SANDBOX_CAPTURE_ID",
         "CLEARWAKE_LOCAL_AI_ACK", "CLEARWAKE_LOCAL_MODEL_DIGEST", "CLEARWAKE_LOCAL_LEDGER")
LINE = re.compile(r"([A-Z_][A-Z0-9_]*)=(.*)")


def load(path):
    """Set only known names from the file; existing environment values win. Returns name -> filled."""
    path = Path(path)
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            match = LINE.fullmatch(raw.strip())
            if match and match[1] in NAMES and match[2].strip() and not os.environ.get(match[1]):
                os.environ[match[1]] = match[2].strip()
    return {name: bool(os.environ.get(name)) for name in NAMES}


def set_value(path, name, value):
    """Write one non-secret value (the sandbox capture ID) without touching other lines."""
    if name != "PAYPAL_SANDBOX_CAPTURE_ID" or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("Only a valid sandbox capture ID may be written by setup.")
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out, done = [], False
    for raw in lines:
        if raw.strip().startswith(name + "="):
            out.append(f"{name}={value}"); done = True
        else:
            out.append(raw)
    if not done:
        out.append(f"{name}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
