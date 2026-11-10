"""Serve site/ on 127.0.0.1 with the same headers and clean URLs as site/vercel.json, to check the public site before deploying.

  python scripts/serve_site.py [port]

vercel.json is read on every request, so a changed header takes effect without a restart.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

SITE = Path(__file__).resolve().parent.parent / "site"


def headers_for(path):
    """Headers of every vercel.json rule whose source matches this path; later rules win, like Vercel's."""
    found = {}
    for rule in json.loads((SITE / "vercel.json").read_text(encoding="utf-8")).get("headers", []):
        if re.fullmatch(rule["source"], path):
            found.update({h["key"]: h["value"] for h in rule["headers"]})
    return found


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".ndjson": "application/x-ndjson"}

    def translate_path(self, path):
        # cleanUrls: /control-room serves control-room.html
        clean = urlsplit(path).path
        if clean != "/" and "." not in clean.rsplit("/", 1)[-1] and (SITE / (clean.lstrip("/") + ".html")).is_file():
            path = clean + ".html"
        return super().translate_path(path)

    def end_headers(self):
        path = urlsplit(self.path).path
        clean = path[:-5] if path.endswith(".html") else path  # Vercel matches the clean URL
        for key, value in headers_for(clean).items():
            self.send_header(key, value)
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8820
    print(f"site on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(SITE))).serve_forever()
