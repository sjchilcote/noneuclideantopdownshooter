#!/usr/bin/env python3
"""Follow-up to consult_soundtrack_gap.py: that consult's diagnosis (H1-H5,
in analysis/soundtrack_gap_consult/answer.md) hit max_tokens before reaching
the actionable-recommendations part of the ask. This is a cheap follow-up
that reuses the diagnosis instead of resending the full ~140k-token prompt,
asking only for the ranked recommendations."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import consult_machinery as cm  # noqa: E402

HERE = Path(__file__).resolve().parent

ASK = """
This is a follow-up to a consult you (or a model like you) already gave on
PERIHELION's procedurally-generated game music pipeline. Your prior
diagnosis (pasted below) found the director's "random child-playing-with-a-
keyboard tunes... MIDI + shitty samples, not a finished soundtrack" verdict
is explained by 5 overlapping causes: H1 melody engine lacks phrase-level
intent (~95-98%), H2 the assembled demo doesn't even use the new Gordon-
chain/real-sample work (~97%), H3 sampler articulation is robotic (~80-90%),
H4 missing mix cohesion (~90% contributes, ~20-30% dominant), H5 sample-rate
mismatch (low prior, minor).

Give ONLY the ranked, concrete, buildable-by-us recommendations now (skip
re-deriving the diagnosis). For each: what to change, expected impact
(high/med/low) given the causes above, and what a human ear would notice if
it worked. We are numpy/fluidsynth/free-samples only, no paid libraries, no
human composer/mixer, offline generation only. Also answer directly: can a
rules-based motif generator alone ever clear "sounds like a finished
soundtrack," or does it need some minimum human-authored seed material
(e.g. a director-written 4-8 bar reference phrase) -- give your honest odds
either way in one paragraph, then stop.
"""


def build_prompt() -> str:
    prior_answer = (HERE / "analysis/soundtrack_gap_consult/answer.md").read_text()
    parts = [
        cm.section("YOUR PRIOR DIAGNOSIS (truncated before recommendations)",
                    prior_answer),
        cm.section("THE FOLLOW-UP ASK", ASK.strip()),
    ]
    return "\n\n".join(parts)


def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("no OPENROUTER_API_KEY set", file=sys.stderr)
        return 1
    prompt = build_prompt()
    print(f"prompt size: ~{cm.tokenish_size(prompt)} tokens", file=sys.stderr)
    out_dir = HERE / "analysis" / "soundtrack_gap_consult_part2"
    out_dir.mkdir(parents=True, exist_ok=True)
    return cm.stream_consult(
        prompt=prompt,
        api_key=api_key,
        model=cm.DEFAULT_MODEL,
        effort="medium",
        max_tokens=4000,
        connect_timeout_s=30.0,
        out_dir=out_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
