"""Serve the voice page to a phone on the same Wi-Fi over https. Same as: python -m clearwake --voice-lan
Needs CLEARWAKE_VOICE_LAN=1. See docs/VOICE.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clearwake.voice_lan import main

if __name__ == "__main__":
    main()
