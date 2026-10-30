"""Show which names in clearwake/.env are filled. Never prints a value."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clearwake import envfile  # noqa: E402

for name, filled in envfile.load(ROOT / ".env").items():
    if name.startswith(("PAYPAL", "CLEARWAKE_SANDBOX")):
        print(f"{name}: {'filled' if filled else 'EMPTY'}")
