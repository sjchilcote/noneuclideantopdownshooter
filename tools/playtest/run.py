#!/usr/bin/env python
"""tools/playtest/run.py — headless AI-playtest CLI.

Runs a deterministic bot policy over a level with no window, no human, and
prints the run's `Result` summary as JSON to stdout — the entry point an
LLM (or CI) uses to judge whether a level is playable.

    uv run python tools/playtest/run.py --level levels/smoke_4room.json --bot aggro --seed 3
    uv run python tools/playtest/run.py --level levels/smoke_4room.json --bot aggro --seed 3 --gif

`--gif` captures frames every `--capture-every` ticks (default 6) into a
scratch directory via `perihelion.render` (lazily imported; if that module
doesn't exist yet or errors, capture is skipped and reported, the run still
completes) and assembles them into an animated GIF with Pillow *if it's
installed*. Pillow is deliberately not a project dependency — if it's
missing, the PNG frames are left on disk and their directory is printed;
nothing is added to pyproject.toml to work around that.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from perihelion.levels import load_level
from perihelion.testkit import AggroBot, CamperBot, ExplorerBot, PacifistBot, run_bot
from perihelion.testkit.harness import summarize

BOTS = {
    "aggro": AggroBot,
    "pacifist": PacifistBot,
    "camper": CamperBot,
    "explorer": ExplorerBot,
}


def _finish_gif(capture_dir: str | None, capture_skipped: bool) -> dict:
    if capture_dir is None:
        return dict(status="no_capture_dir")
    if capture_skipped:
        return dict(status="skipped", capture_dir=capture_dir,
                    reason="renderer unavailable (perihelion.render not importable, "
                            "or render_to_surface() errored) — PNGs (if any) left in capture_dir")
    frames = sorted(Path(capture_dir).glob("frame_*.png"))
    if not frames:
        return dict(status="no_frames", capture_dir=capture_dir)
    try:
        from PIL import Image
    except ImportError:
        return dict(status="pil_missing", capture_dir=capture_dir, frame_count=len(frames),
                    note="Pillow is not a project dependency; PNG frames left in capture_dir")
    gif_path = str(Path(capture_dir) / "playtest.gif")
    images = [Image.open(f) for f in frames]
    images[0].save(gif_path, save_all=True, append_images=images[1:], duration=100, loop=0)
    return dict(status="ok", gif_path=gif_path, frame_count=len(frames), capture_dir=capture_dir)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Headless PERIHELION bot playtest")
    p.add_argument("--level", required=True, help="path to a level v2 JSON file")
    p.add_argument("--bot", choices=sorted(BOTS), default="aggro")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-ticks", type=int, default=60 * 300)
    p.add_argument("--gif", action="store_true",
                    help="capture frames and assemble a GIF (needs Pillow; else leaves PNGs)")
    p.add_argument("--capture-every", type=int, default=6,
                    help="ticks between captured frames when --gif is set")
    p.add_argument("--capture-dir", default=None,
                    help="defaults to a fresh tempdir when --gif is set")
    args = p.parse_args(argv)

    level = load_level(args.level)
    bot = BOTS[args.bot](args.seed)

    capture_every = args.capture_every if args.gif else 0
    capture_dir = args.capture_dir
    if args.gif and capture_dir is None:
        capture_dir = tempfile.mkdtemp(prefix=f"perihelion_playtest_{args.bot}_{args.seed}_")

    res = run_bot(level, bot, args.seed, max_ticks=args.max_ticks,
                  capture_every=capture_every, capture_dir=capture_dir)

    summary = summarize(res)
    if args.gif:
        summary["gif"] = _finish_gif(capture_dir, res.capture_skipped)
        if summary["gif"]["status"] in ("skipped", "pil_missing", "no_frames"):
            print(f"[playtest] {summary['gif']['status']}: frames (if any) in {capture_dir}",
                  file=sys.stderr)

    print(json.dumps(summary, indent=2))
    return 0 if res.outcome == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
