"""Ship the album banks into the game's assets — releasable form.

    uv run python tools/musicgen/ship_banks.py

Encodes every out/banks/album_* stem to OGG (q4 ≈ 10:1) into
game/assets/music/<bank>/, bank.json included. The game discovers and
rotates these automatically — no flags, no dev paths.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "out/banks"
DST = ROOT / "game/assets/music"


def main():
    banks = sorted(p for p in SRC.glob("album_*")
                   if (p / "bank.json").exists())
    if not banks:
        sys.exit("no album banks in out/banks")
    total = 0
    for bank in banks:
        out = DST / bank.name
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy(bank / "bank.json", out / "bank.json")
        for wav in sorted(bank.glob("*.wav")):
            ogg = out / (wav.stem + ".ogg")
            if ogg.exists() and ogg.stat().st_mtime >= wav.stat().st_mtime:
                continue
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(wav),
                 "-codec:a", "libvorbis", "-qscale:a", "4", str(ogg)],
                check=True)
        size = sum(f.stat().st_size for f in out.glob("*.ogg"))
        total += size
        meta = json.loads((bank / "bank.json").read_text())
        print(f"{meta['title']!r}: {size/1e6:.0f} MB -> {out}",
              flush=True)
    print(f"total shipped: {total/1e6:.0f} MB", flush=True)


if __name__ == "__main__":
    main()
