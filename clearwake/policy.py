"""Autonomy policy loaded from a file outside the model. The code's hard cap always wins."""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json

from .paypal import LIMIT

LEVELS = ("Assist", "Draft", "Execute with Approval", "Execute within Limits")
DEFAULT = Path(__file__).resolve().parent.parent / "policy" / "autonomy.json"
# Levels the current code actually enforces for each operation. A file cannot grant more autonomy than this.
SUPPORTED = {"specialist_review": {"Assist", "Draft"}, "publish_plan": {"Execute with Approval"},
             "refund": {"Execute with Approval"}, "reconcile": {"Execute within Limits", "Execute with Approval"}}


def load(path=DEFAULT):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    operations = data.get("operations") if isinstance(data, dict) else None
    if data.get("version") != 1 or not isinstance(operations, dict) or set(operations) != set(SUPPORTED):
        raise ValueError("The autonomy policy must declare exactly: " + ", ".join(sorted(SUPPORTED)) + ".")
    for name, entry in operations.items():
        level = entry.get("level") if isinstance(entry, dict) else None
        if level not in LEVELS:
            raise ValueError(f"Unknown autonomy level for {name}.")
        if level not in SUPPORTED[name]:
            raise ValueError(f"{name} cannot run at '{level}' in this build.")
    refund = operations["refund"]
    try:
        limit = Decimal(refund["limit"]["max"])
    except (KeyError, TypeError, InvalidOperation):
        raise ValueError("The refund operation needs a numeric limit.") from None
    if refund["limit"].get("currency") != "USD" or not Decimal("0") < limit <= LIMIT or limit != limit.quantize(Decimal("0.01")):
        raise ValueError(f"The refund limit must be a positive USD amount no higher than the built in cap of {LIMIT}.")
    expires = refund.get("approval_expires_seconds")
    if type(expires) is not int or not 30 <= expires <= 900:
        raise ValueError("Approval expiry must be 30 to 900 seconds.")
    if refund.get("retry") != "never":
        raise ValueError("Refunds are never retried automatically.")
    return data
