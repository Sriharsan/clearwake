"""Serve site/ on 127.0.0.1 with the same headers as site/vercel.json, to check the public site before deploying.

  python scripts/serve_site.py [port]
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys

SITE = Path(__file__).resolve().parent.parent / "site"
HEADERS = {h["key"]: h["value"] for h in json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))["headers"][0]["headers"]}


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".ndjson": "application/x-ndjson"}

    def end_headers(self):
        for key, value in HEADERS.items():
            self.send_header(key, value)
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8820
    print(f"site on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(SITE))).serve_forever()
