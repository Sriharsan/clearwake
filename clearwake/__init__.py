"""Clearwake extends the pinned public Relayloom core and the shared verdock-core engine; no private imports.

One line drop in for PayPal's Agent Toolkit:

    from clearwake import guard
    tools = guard(paypal_toolkit_tools, policy="policy.yaml")
"""
from pathlib import Path
import importlib.util
import sys
import types

__version__ = "0.1.0"

# In a source checkout the two engines live in vendor/ (git submodules). In an installed wheel they are bundled as the top level
# packages verdock_core and relayloom, so the vendor folders are not needed at runtime.
VENDOR = Path(__file__).resolve().parent.parent / "vendor"
for _path, _marker, _module in ((VENDOR / "relayloom", "relayloom/controller.py", "relayloom"), (VENDOR / "verdock-core", "verdock_core/receipts.py", "verdock_core")):
    if (_path / _marker).is_file():
        sys.path.insert(0, str(_path))
    elif importlib.util.find_spec(_module) is None:
        raise RuntimeError("Initialize the pinned submodules: git submodule update --init --recursive")

from . import guard as _checks  # noqa: E402  the order giving text checks; the module itself is callable, see below


class _CallableGuard(types.ModuleType):
    """`from clearwake import guard` gives the text check module of clearwake/guard.py. Calling it wraps PayPal's toolkit tools:
    guard(tools, policy="policy.yaml") is clearwake.guard_api.guard(tools, policy="policy.yaml")."""

    def __call__(self, *args, **kwargs):
        from .guard_api import guard
        return guard(*args, **kwargs)


_checks.__class__ = _CallableGuard
