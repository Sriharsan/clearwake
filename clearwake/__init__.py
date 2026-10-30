"""Clearwake extends the pinned public Relayloom core; no private imports."""
from pathlib import Path
import sys

CORE = Path(__file__).resolve().parent.parent / "vendor" / "relayloom"
if not (CORE / "relayloom" / "controller.py").is_file():
    raise RuntimeError("Initialize the pinned submodule: git submodule update --init --recursive")
sys.path.insert(0, str(CORE))

__version__ = "0.1.0"
