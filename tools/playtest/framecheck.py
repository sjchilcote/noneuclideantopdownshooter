#!/usr/bin/env python
"""tools/playtest/framecheck.py — sample a capture for frame-by-frame review.

Copies every 10th sim tick's frame (given the capture's --record-every
cadence) from a `--record` directory into `<rec>/review/` and writes
`manifest.json` mapping each sampled frame to its capture-clock timestamp.
Reviewers then follow tools/playtest/FRAME_REVIEW_RUBRIC.md.

    uv run python tools/playtest/framecheck.py --rec DIR [--every-ticks 10]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rec", required=True)
    p.add_argument("--record-every", type=int, default=2,
                   help="the --record-every the capture was made with")
    p.add_argument("--every-ticks", type=int, default=10,
                   help="sim ticks between sampled frames")
    args = p.parse_args(argv)

    rec = Path(args.rec)
    frames = sorted(rec.glob("frame_*.png"))
    if not frames:
        print(f"[framecheck] no frames in {rec}", file=sys.stderr)
        return 1
    step = max(1, args.every_ticks // args.record_every)
    out = rec / "review"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    manifest = []
    for i, f in enumerate(frames[::step]):
        dst = out / f"sample_{i:05d}.png"
        shutil.copy(f, dst)
        t = int(f.stem.split("_")[1]) * args.record_every / 60.0
        manifest.append(dict(frame=dst.name, source=f.name, t=round(t, 2)))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"[framecheck] {len(manifest)} samples "
          f"({args.every_ticks} ticks apart) in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
