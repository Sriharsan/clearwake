"""Dispatch proof at the packing bench: count the photos of the open parcel and write one signed receipt.

  python scripts/dispatch.py pack --order ORDER_ID --capture CAPTURE_ID --item notebook-a5=3:notebook --photo parcel.jpg --sealed
  python scripts/dispatch.py show [--order ORDER_ID]

--item is sku=ordered quantity:what to count (a short noun phrase). Use several --photo for several angles: the largest count wins.
--counter sam         SAM 3 on this machine (needs tools/sam/setup.ps1 once; runs offline afterwards)
--counter recorded    the saved result of a real SAM run next to the photo (<photo>.count.json)
--counter scripted    rehearsal only: a fixed table, labelled "scripted count, not SAM"
--data DIR            the merchant's data folder (default data/dispatch). Run this when no server is writing to it.
Photos are copied under DIR/dispatch/ORDER_ID/ and never sent anywhere until a dispute needs them.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearwake import dispatch  # noqa: E402
from clearwake.counter import Counter, CounterError  # noqa: E402
from clearwake.models import Adapter  # noqa: E402
from clearwake.paypal import RehearsalGateway  # noqa: E402
from clearwake.swarm import MerchantSwarm  # noqa: E402


def swarm_for(data):
    data = Path(data)
    return MerchantSwarm(RehearsalGateway(data / "unused-provider.sqlite3"), data, Adapter("scripted"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("--order", required=True); pack.add_argument("--capture", required=True)
    pack.add_argument("--item", action="append", required=True, metavar="SKU=QTY:PROMPT")
    pack.add_argument("--photo", action="append", required=True, type=Path)
    pack.add_argument("--sealed", action="store_true"); pack.add_argument("--counter", default="sam", choices=("sam", "recorded", "scripted"))
    pack.add_argument("--table", default="", help="scripted counter only: file=count,file=count")
    show = commands.add_parser("show"); show.add_argument("--order")
    for sub in (pack, show):
        sub.add_argument("--data", default=str(ROOT / "data" / "dispatch"))
    args = parser.parse_args()
    swarm = swarm_for(args.data)
    if args.command == "show":
        for line in Path(swarm.receipts.path).read_text(encoding="utf-8").splitlines() if Path(swarm.receipts.path).is_file() else []:
            receipt = json.loads(line)
            if receipt["action_id"] == dispatch.ACTION and (not args.order or receipt["params"]["order"] == args.order):
                p = receipt["params"]
                print(f"order {p['order']} capture {p['capture']}: ordered {p['ordered']} counted {p['counted']} sealed {p['sealed']} "
                      f"photos {len(p['images'])} by {p['counter']} ({p['count_ms']} ms)")
        return 0
    items = {}
    for text in args.item:
        sku, _, rest = text.partition("=")
        quantity, _, prompt = rest.partition(":")
        if not sku or not quantity.isdigit() or not prompt:
            sys.exit("--item must look like notebook-a5=3:notebook")
        items[sku] = {"ordered": int(quantity), "prompt": prompt}
    table = dict(pair.split("=") for pair in args.table.split(",") if pair)
    try:
        made = dispatch.pack(swarm, Counter(args.counter, table=table), args.order, args.capture, items, args.photo, args.sealed)
    except (CounterError, ValueError) as error:
        sys.exit(f"Not recorded: {error}")
    print(f"counted {made['counted']} of ordered {made['ordered']} by {made['counter']} in {made['count_ms']} ms")
    print(f"signed dispatch receipt {made['digest'][:16]} written to {swarm.receipts.path}")
    print(f"public key {made['public_key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
