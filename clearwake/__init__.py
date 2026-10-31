"""Clearwake extends the pinned public Relayloom core and the shared verdock-core engine; no private imports."""
from pathlib import Path
import sys

VENDOR = Path(__file__).resolve().parent.parent / "vendor"
CORE = VENDOR / "relayloom"
ENGINE = VENDOR / "verdock-core"
for path, marker in ((CORE, "relayloom/controller.py"), (ENGINE, "verdock_core/receipts.py")):
    if not (path / marker).is_file():
        raise RuntimeError("Initialize the pinned submodules: git submodule update --init --recursive")
    sys.path.insert(0, str(path))

__version__ = "0.1.0"
