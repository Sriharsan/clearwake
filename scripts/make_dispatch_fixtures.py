"""Write the synthetic parcel pictures used by the rehearsal (fixtures/dispatch/). Standard library only.

These are drawn rectangles, not photographs: an open brown box with 3 notebooks and one with 2. The rehearsal counts them with a
scripted table and labels the count "scripted count, not SAM". Real packing photos are counted by SAM (scripts/dispatch.py pack).
"""
from pathlib import Path
import struct
import zlib

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "dispatch"
W, H = 640, 420


def png(pixels):
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def parcel(items):
    canvas = [[c for _ in range(W) for c in (236, 238, 235)] for _ in range(H)]
    def box(x0, y0, x1, y1, colour):
        for y in range(y0, y1):
            row = canvas[y]
            for x in range(x0, x1):
                row[x * 3:x * 3 + 3] = colour
    box(40, 40, 600, 380, (150, 104, 62))       # the open parcel
    box(60, 60, 580, 360, (196, 150, 104))      # its inside
    width = (520 - 20 * (items + 1)) // items
    for i in range(items):
        x = 60 + 20 + i * (width + 20)
        box(x, 100, x + width, 320, (46, 84, 150))      # a notebook cover
        box(x + 12, 100, x + 24, 320, (24, 44, 90))     # its spine
    return canvas


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for items in (3, 2):
        (OUT / f"parcel-{items}-items.png").write_bytes(png(parcel(items)))
        print(f"fixtures/dispatch/parcel-{items}-items.png")


if __name__ == "__main__":
    main()
