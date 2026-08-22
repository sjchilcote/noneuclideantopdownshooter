"""slam_rank — rank ambush-slam lead-up variants with Gemini.

Director overnight goal: the slam is for a boss hurtling out of the
dark; 'even then it should have SOME lead-up, maybe half a bar of
come up and/or a half-bar riser.' Four variants of the SAME scripted
ambush (real engine, real mixer), one ranking request, two reps:

  V1 zero-width slam (the old behavior)
  V2 half-bar come-up on the rising lanes
  V3 half-bar micro-riser (reversed bell tail), instant wall
  V4 micro-riser + come-up

    uv run python tools/musicgen/slam_rank.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))
sys.path.insert(0, str(ROOT / "tools/playtest"))

from perihelion.music import MusicSystem, TICKS_PER_S   # noqa: E402
import mkvideo as MK                                    # noqa: E402
from judge_track import _ask_multi, _stereo_mp3         # noqa: E402

BANK = ROOT / "out/banks/album_dies_irae"


class FakeSim:
    def get_polygon(self, eid):
        return 0

    def hop_distance(self, a, b):
        return abs(a - b)


def session(tick, enemies):
    s = SimpleNamespace()
    s.enemies = enemies
    s.sim = FakeSim()
    s.hp = 100.0
    s.tick_count = tick
    s.player_polygon = lambda: 0
    s.player_pos = lambda: (0.0, 0.0)
    s.metrics = {"kills": 0}
    s.music_tier = 3
    return s


AMBUSH = {1: dict(kind="warden", state="hunt"),
          2: dict(kind="brute", state="hunt")}


def run_variant(variant: str) -> list:
    events = []
    now = [0]

    def tap(kind, detail, vol, pan):
        events.append(dict(t=now[0] / 60.0, kind=kind,
                           name=detail, vol=vol, pan=pan))
    bank = SimpleNamespace(_ready=True, tap=tap, master_vol=1.0)
    ms = MusicSystem(bank, enabled=True, bank_dirs=[BANK],
                     tick_clock=True)
    ms.slam_riser = variant in ("v3", "v4")
    if variant == "v1":
        # the OLD zero-width slam: window always open, come-up off
        ms._ambush_window = 10 ** 9

        def _no_window_decay():
            pass
    bar_ticks = int(ms.bar_s * TICKS_PER_S)
    total = 14 * bar_ticks
    ambush_at = 7 * bar_ticks + bar_ticks // 3   # mid-bar contact
    for tick in range(1, total):
        now[0] = tick
        if variant == "v1":
            ms._ambush_window = 10 ** 9
        enemies = AMBUSH if tick >= ambush_at else {}
        ms.update(session(tick, enemies))
    return events


def render(variant: str, outdir: Path) -> Path:
    evs = run_variant(variant)
    dur = 14 * 240.0 / 110.0
    n = int(dur * MK.RATE)
    mix = np.zeros((n, 2), dtype=np.float32)
    # V1/V3 are the zero-width-wall variants: come-up ramp off
    MK.COMEUP_DELTA = 9.9 if variant in ("v1", "v3") else 0.4
    assert MK._mix_music_rich(mix, evs, dur), variant
    MK.COMEUP_DELTA = 0.4
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.9
    w = outdir / f"{variant}.wav"
    sf.write(str(w), mix, MK.RATE)
    mp3 = outdir / f"{variant}.mp3"
    _stereo_mp3(w, mp3, max_s=35.0)
    return mp3


def main():
    tmp = Path(tempfile.mkdtemp(prefix="slam_"))
    clips = {}
    for v in ("v1", "v2", "v3", "v4"):
        clips[v] = render(v, tmp)
    labels = dict(zip("ABCD", ("v1", "v2", "v3", "v4")))
    prompt = (
        "Four versions of the same game-soundtrack passage: calm "
        "chant, then at ~15s a monster AMBUSHES the player and the "
        "music must panic instantly. They differ in how the panic "
        "hits: A = instant full wall (zero-width cut-in); B = the "
        "wall rises over half a bar; C = a half-bar reversed-bell "
        "swell then instant wall; D = the swell AND the half-bar "
        "rise. Judge: which best conveys sudden panic while still "
        "sounding like MUSIC (no edit-artifact feel)? Respond ONLY "
        "with JSON: {\"ranking\": [best..worst of A,B,C,D], "
        "\"per\": {\"A\": \"one clause\", ...}, \"verdict\": "
        "\"one sentence\"}")
    for rep in range(2):
        res = _ask_multi([clips[labels[k]] for k in "ABCD"], prompt,
                         labels=[f"Clip {c}" for c in "ABCD"])
        print(json.dumps(res, indent=1), flush=True)


if __name__ == "__main__":
    main()
