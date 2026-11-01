"""Print a saved network cut run (data/airgap/airgap-*.json) the way it happened. Reads a file; no network.

Usage: python scripts/show_airgap_run.py data/airgap/airgap-20261031-223749.json
"""
import json
import re
import sys
import textwrap


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as handle:
        run = json.load(handle)
    print(f"Recorded run, real PayPal sandbox, network isolated containers (started {run['started']})")
    for key, value in run["boundary"].items():
        print(f"  {key}: {value}")
    print(f"  network cut at {run['cut_at']}, restored at {run['restored_at']}")
    for line in run["case_m"]:
        if line.startswith(("PASS", "FAIL")):
            status, title, how, detail = re.split(r"\s{2,}", line, maxsplit=3)
            print(f"  {status}  {title}")
            print(textwrap.fill(how, 150, initial_indent="      ", subsequent_indent="        "))
            for piece in detail.split("; "):
                print(textwrap.fill(piece, 150, initial_indent="      ", subsequent_indent="        "))
    print("receipts verified in a container with networking disabled:")
    for line in run["offline_verify"]:
        print(f"  {line}")


if __name__ == "__main__":
    main()
