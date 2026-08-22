"""loop_seam_rank — rank seamless-loop landing treatments, blind.

The numeric sweep flagged loop-steer landings at +8..12dB in 50ms
(lhomme loop->0, media_vita loop->16). Whether a big landing is a
composed downbeat or a splice is a musical judgment: render the SAME
recording under each treatment (clean / micro-crossfade / half-bar
come-in), cut the same seam windows, and have Gemini rank per seam.

    uv run python tools/musicgen/loop_seam_rank.py REC t1 t2 t3 ...
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/playtest"))

import mkvideo as MK                                # noqa: E402
from judge_track import _ask_multi, _stereo_mp3    # noqa: E402

PRE_S, POST_S = 7.0, 7.0
VARIANTS = ["clean", "micro", "comein"]


def render(rec: Path, variant: str) -> np.ndarray:
    MK.LOOP_SEAM = variant
    evs = [json.loads(l) for l in
           (rec / "events.jsonl").read_text().splitlines()]
    dur = max(e["t"] for e in evs) + 2
    mix = np.zeros((int(dur * MK.RATE) + MK.RATE, 2), dtype=np.float32)
    assert MK._mix_music_rich(mix, evs, dur)
    return mix


def main():
    rec = Path(sys.argv[1])
    ts = [float(a) for a in sys.argv[2:]]
    mixes = {v: render(rec, v) for v in VARIANTS}
    tmp = Path(tempfile.mkdtemp(prefix="loopseam_"))
    import random
    rng = random.Random(20260717)
    tallies = {v: 0 for v in VARIANTS}
    for t in ts:
        order = VARIANTS[:]
        rng.shuffle(order)
        clips, labels = [], []
        for i, v in enumerate(order):
            seg = mixes[v][int((t - PRE_S) * MK.RATE):
                           int((t + POST_S) * MK.RATE)]
            w = tmp / f"{t:.0f}_{i}.wav"
            sf.write(str(w), seg, MK.RATE)
            m = tmp / f"{t:.0f}_{i}.mp3"
            _stereo_mp3(w, m, max_s=PRE_S + POST_S + 1)
            clips.append(m)
            labels.append(f"Clip {chr(65 + i)}")
        prompt = (
            "Three renders of the SAME passage of an industrial-metal "
            "game soundtrack. Each contains a musical section "
            "boundary (a loop point) in the middle. They differ only "
            "in how that boundary is treated. Rank them from best to "
            "worst on: does the boundary sound like an intentional "
            "musical downbeat/arrival, vs an abrupt splice or an "
            "over-smoothed smear? Respond ONLY with JSON: "
            '{"ranking": ["A","B","C"], "reason": "..."}')
        res = _ask_multi(clips, prompt, labels=labels)
        rk = res.get("ranking", [])
        out = {}
        for pos, letter in enumerate(rk):
            idx = ord(letter) - 65
            if 0 <= idx < len(order):
                out[order[idx]] = pos
                tallies[order[idx]] += len(VARIANTS) - 1 - pos
        print(json.dumps(dict(t=t, order=order, ranking=rk,
                              scores=out,
                              reason=res.get("reason", ""))),
              flush=True)
    print("\ntotals (higher=better):",
          sorted(tallies.items(), key=lambda kv: -kv[1]), flush=True)


if __name__ == "__main__":
    main()
