"""transition_iter — Gemini iteration on the transition grammar.

Director 2026-07-16 (bedtime order): "iterate on it with Gemini - ask
it if the transition sounds natural or sounds like a sudden cut-off.
Focus on transition sections."

Scripted value trajectories drive the REAL engine (tick_clock mode)
and the REAL offline mixer, so the clips contain exactly the
transition grammar and nothing else. Scenarios:
  S1 battle->calm   (the 02:24 case: sudden fight end)
  S2 calm->battle   (rising: walls are the law, must stay punchy)
  S3 boss->calm     (peak, overlay, then nothing)
  S4 skirmish blips (1-bar threat pulses; must NOT wake the mix)

    uv run python tools/musicgen/transition_iter.py [judge|render]
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


def fake_session(tick):
    s = SimpleNamespace()
    s.enemies = {}
    s.sim = FakeSim()
    s.hp = 100.0
    s.tick_count = tick
    s.player_polygon = lambda: 0
    s.player_pos = lambda: (0.0, 0.0)
    s.metrics = {"kills": 0}
    s.music_tier = 3
    return s


SCENARIOS = {
    "S1_battle_to_calm": lambda bar: (0.12, 0.65, 0.55) if bar < 14
    else (1.0, 0.0, 0.0),
    "S2_calm_to_battle": lambda bar: (1.0, 0.0, 0.0) if bar < 6
    else (0.15, 0.7, 0.6),
    "S3_boss_to_calm": lambda bar: (0.12, 0.55, 0.95) if bar < 14
    else (1.0, 0.0, 0.0),
    "S4_skirmish_blips": lambda bar: (0.2, 0.5, 0.35)
    if bar in (6, 12, 18) else (1.0, 0.0, 0.0),
}
TOTAL_BARS = 24


def run_scenario(name, traj) -> list:
    import perihelion.music as pm
    events = []
    now = [0]

    def tap(kind, detail, vol, pan):
        events.append(dict(t=now[0] / 60.0, kind=kind,
                           name=detail, vol=vol, pan=pan))
    bank = SimpleNamespace(_ready=True, tap=tap, master_vol=1.0)
    ms = MusicSystem(bank, enabled=True, bank_dirs=[BANK],
                     tick_clock=True)
    bar_ticks = int(ms.bar_s * TICKS_PER_S)
    real_values = pm.values
    cur = [0]
    pm.values = lambda inputs: traj(cur[0])
    try:
        for tick in range(TOTAL_BARS * bar_ticks):
            now[0] = tick
            cur[0] = tick // bar_ticks
            ms.update(fake_session(tick + 1))
    finally:
        pm.values = real_values
    return events


def harden(events):
    """Simulate the OLD hard-switch grammar from the same tap stream:
    strip farewell markers and snap falling gains instantly."""
    import copy
    out = copy.deepcopy(events)
    last = {}
    for e in out:
        if e["kind"] != "music_bar":
            continue
        parts = e["name"].split("|")
        new = [parts[0]]
        for pt in parts[1:]:
            ln, key, g = pt.rsplit(":", 2)
            g = float(g)
            if key.endswith("~f"):
                key, g = "silence", 0.0
            prev = last.get(ln, 0.0)
            if g < prev and g > 0.02:
                g = 0.0 if g < prev * 0.7 else g   # snap the glide away
            last[ln] = g
            new.append(f"{ln}:{key}:{g:.3f}")
        e["name"] = "|".join(new)
    return out


def render_pair(name, traj, outdir: Path):
    events = run_scenario(name, traj)
    dur = TOTAL_BARS * 240.0 / 110.0
    n = int(dur * MK.RATE)
    outs = {}
    for tag, evs in (("new", events), ("old", harden(events))):
        mix = np.zeros((n, 2), dtype=np.float32)
        assert MK._mix_music_rich(mix, evs, dur), name
        mix = mix / (np.abs(mix).max() + 1e-9) * 0.85
        w = outdir / f"{name}_{tag}.wav"
        sf.write(str(w), mix, MK.RATE)
        mp3 = outdir / f"{name}_{tag}.mp3"
        _stereo_mp3(w, mp3, max_s=60.0)
        outs[tag] = mp3
    return outs


def render(outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, traj in SCENARIOS.items():
        events = run_scenario(name, traj)
        dur = TOTAL_BARS * 240.0 / 110.0
        n = int(dur * MK.RATE)
        mix = np.zeros((n, 2), dtype=np.float32)
        ok = MK._mix_music_rich(mix, events, dur)
        assert ok, name
        peak = np.abs(mix).max() + 1e-9
        mix = mix / peak * 0.85
        w = outdir / f"{name}.wav"
        sf.write(str(w), mix, MK.RATE)
        mp3 = outdir / f"{name}.mp3"
        _stereo_mp3(w, mp3, max_s=60.0)
        paths[name] = mp3
    return paths


def judge(paths: dict) -> dict:
    clips = list(paths.values())
    names = list(paths.keys())
    prompt = (
        "Four clips from a dynamic game-music engine, each containing "
        "an intensity TRANSITION. "
        f"A={names[0]}: heavy combat music ending, return to calm "
        "chant. B={1}: calm chant, then combat begins. "
        f"C={names[2]}: full boss intensity ending, return to calm. "
        f"D={names[3]}: calm with three 1-bar threat blips that should "
        "barely ripple the music. For EACH clip judge the TRANSITION "
        "MOMENTS ONLY: does the change sound like natural musical "
        "development (a release, a build) or like a sudden cut-off / "
        "glitch / broken audio? Respond ONLY with JSON: {\"per_clip\": "
        "{\"A\": {\"natural\": 1-10, \"cutoff_artifacts\": \"...\", "
        "\"what_would_a_composer_do\": \"...\"}, ...}, \"worst\": "
        "\"A-D\", \"verdict\": \"one sentence\"}")
    return _ask_multi(clips, prompt)


def ab_judge(reps=2):
    import random
    tmp = Path(tempfile.mkdtemp(prefix="transab_"))
    wins = {"S1_battle_to_calm": 0, "S3_boss_to_calm": 0}
    for rep in range(reps):
        for name in list(wins):
            pair = render_pair(name, SCENARIOS[name], tmp)
            order = ["new", "old"]
            random.Random(rep * 7 + len(name)).shuffle(order)
            clips = [pair[order[0]], pair[order[1]]]
            prompt = (
                "Two versions (A then B) of the same dynamic game-music "
                "passage: heavy combat music that ends, returning to a "
                "calm chant. They differ ONLY in how the de-escalation "
                "transition is handled. Which version handles the "
                "transition more naturally and musically? Respond ONLY "
                "with JSON: {\"more_natural\": \"A\"|\"B\", "
                "\"margin\": \"slight\"|\"clear\", \"why\": "
                "\"one sentence\"}")
            res = _ask_multi(clips, prompt)
            pick = res.get("more_natural")
            picked = order[0] if pick == "A" else order[1]
            if picked == "new":
                wins[name] += 1
            print(name, "rep", rep, "->", picked, "|",
                  res.get("margin"), res.get("why"))
    print("new-grammar wins:", wins, f"of {reps} reps each")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "ab"
    if mode == "ab":
        ab_judge()
    else:
        tmp = Path(tempfile.mkdtemp(prefix="trans_"))
        paths = render(tmp)
        print("rendered to", tmp)
        print(json.dumps(judge(paths), indent=1))
