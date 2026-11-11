"""Write site/img/qr-console.svg, the QR code on the Home page that opens the hosted console on a phone.

  python scripts/build_qr.py

Needs segno (pip install segno). The code is black on white with a quiet zone, so it scans in both themes.
"""
from pathlib import Path
import sys

URL = "https://clearwake-console.onrender.com/console"
OUT = Path(__file__).resolve().parent.parent / "site" / "img" / "qr-console.svg"


def main():
    try:
        import segno
    except ImportError:
        print("segno is not installed: run  pip install segno  and run this script again")
        return 1
    qr = segno.make(URL, error="m", micro=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    qr.save(str(OUT), kind="svg", scale=8, border=2, dark="#0b1620", light="#ffffff", xmldecl=False, svgns=True, title="QR code for " + URL, nl=True)
    text = OUT.read_text(encoding="utf-8")
    if "viewBox" not in text:  # segno writes only width and height; a viewBox lets the page size it
        side = qr.symbol_size(scale=8, border=2)[0]
        text = text.replace("<svg ", f'<svg viewBox="0 0 {side} {side}" shape-rendering="crispEdges" ', 1)
        OUT.write_text(text, encoding="utf-8")
    print("wrote", OUT, f"({qr.version} version, {qr.symbol_size(border=2)[0]} modules wide with the quiet zone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
