"""Print refund IDs held by the local provider, as a merchant would read its own records.

Usage: python scripts/show_provider_record.py data/<local run folder>
Local only. This never sends or changes a refund.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1]) / "local-provider.sqlite3"
    if not path.is_file():
        sys.exit(f"No local provider records at {path}")
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT refund_id, body FROM records").fetchall()
    print("LOCAL provider records (local gateway):")
    for refund_id, body in rows:
        record = json.loads(body)
        print(f"  refund ID {refund_id}  status {record['status']}  USD {record['amount']['value']}")
    if not rows:
        print("  none")


if __name__ == "__main__":
    main()
