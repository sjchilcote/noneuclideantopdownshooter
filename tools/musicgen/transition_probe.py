"""transition_probe — extract EVERY state transition from a recording
and batch-judge them with Gemini (director 2026-07-16 overnight goal:
'Focus on any state transition - probe thoroughly').

Reads a recording's events.jsonl + its rendered mix.wav, cuts a short
clip around every transition event (form jumps, seamless loops, boss
releases, rotations, riser events, spike walls, death), and asks
Gemini per clip whether the transition reads as intentional music or
as an edit artifact. Also supports blind A/B between two mixes of the
SAME recording (before/after a fix) at the same transition points.

    uv run python tools/musicgen/transition_probe.py list REC
    uv run python tools/musicgen/transition_probe.py probe REC [--limit N]
    uv run python tools/musicgen/transition_probe.py ab REC MIX_A MIX_B --kinds pop,rotation
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
from judge_track import _ask_multi, _stereo_mp3   # noqa: E402

PRE_S, POST_S = 6.0, 8.0


def load_events(rec: Path) -> list:
    return [json.loads(l) for l in
            (rec / "events.jsonl").read_text().splitlines() if l.strip()]


def transitions(evs: list) -> list[tuple[float, str, str]]:
    """(t, kind, label) for every musical state transition."""
    out = []
    prev_riser = 0.0
    for e in evs:
        k, nm, t = e["kind"], str(e["name"]), e["t"]
        if k == "music_jump":
            out.append((t, "loop" if nm.endswith("~s") else "jump",
                        f"form {'loop' if nm.endswith('~s') else 'jump'} "
                        f"-> {nm.rstrip('~s')}"))
        elif k == "music_rel":
            out.append((t, "release", "boss release + toll"))
        elif k == "music_bank" and t > 1.0:
            out.append((t, "rotation", f"bank handoff -> {nm}"))
        elif k == "music_halt":
            out.append((t, "death", "death halt"))
        elif k == "music_riser":
            v = float(nm)
            if v > 0.01 and prev_riser <= 0.01:
                out.append((t, "riser", "riser one-shot"))
            prev_riser = v
        elif k == "music_valslp":
            pass
    # spike walls: stalwart lp jumping >= 0.25 between consecutive
    # 10Hz samples = the nonlinear filter snapping (slam-cut feature)
    lp = [(e["t"], float(e["name"].split(",")[2])) for e in evs
          if e["kind"] == "music_valslp"]
    for (t0, a), (t1, b) in zip(lp, lp[1:]):
        if b - a >= 0.25:
            out.append((t1, "slam", f"spike wall {a:.2f}->{b:.2f}"))
    out.sort()
    # de-dup transitions closer than 1.5s (keep the first)
    dedup = []
    for tr in out:
        if not dedup or tr[0] - dedup[-1][0] > 1.5 or tr[1] != dedup[-1][1]:
            dedup.append(tr)
    return dedup


def _clip(mix, sr, t, out_mp3):
    a = max(0, int((t - PRE_S) * sr))
    b = min(len(mix), int((t + POST_S) * sr))
    seg = mix[a:b]
    seg = seg / (np.abs(seg).max() + 1e-9) * 0.9
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        sf.write(f.name, seg, sr)
        _stereo_mp3(Path(f.name), out_mp3, max_s=PRE_S + POST_S + 1)


def probe(rec: Path, limit: int | None):
    evs = load_events(rec)
    trs = transitions(evs)
    if limit:
        trs = trs[:limit]
    mix, sr = sf.read(str(rec / "mix.wav"), dtype="float32")
    tmp = Path(tempfile.mkdtemp(prefix="probe_"))
    results = []
    # batch in groups of 4 per request
    for g0 in range(0, len(trs), 4):
        grp = trs[g0:g0 + 4]
        clips, descs = [], []
        for i, (t, kind, label) in enumerate(grp):
            mp3 = tmp / f"c{g0 + i}.mp3"
            _clip(mix, sr, t, mp3)
            clips.append(mp3)
            descs.append(f"{chr(65 + i)}: at ~{PRE_S:.0f}s in, a "
                         f"'{label}' occurs")
        prompt = (
            "Clips from a dynamic game soundtrack (industrial metal + "
            "chant). Each contains ONE deliberate musical state "
            "transition:\n" + "\n".join(descs) +
            "\nFor EACH clip judge ONLY that transition moment: does "
            "it sound like intentional musical development, or like "
            "an edit artifact (pop, click, hard cut, dropout, "
            "misaligned entry)? Respond ONLY with JSON: {\"clips\": "
            "{\"A\": {\"intentional\": 1-10, \"artifact\": \"none\" "
            "or a specific description}, ...}}")
        res = _ask_multi(clips, prompt)
        for i, (t, kind, label) in enumerate(grp):
            r = res.get("clips", {}).get(chr(65 + i), {})
            results.append(dict(t=round(t, 2), kind=kind, label=label,
                                score=r.get("intentional"),
                                artifact=r.get("artifact")))
            print(json.dumps(results[-1]), flush=True)
    lows = [r for r in results
            if isinstance(r.get("score"), (int, float)) and r["score"] <= 6]
    print(f"\n{len(results)} transitions probed, "
          f"{len(lows)} scored <=6:", flush=True)
    for r in lows:
        print(f"  {r['t']:7.2f}s {r['kind']:9s} {r['score']} "
              f"{r['artifact']}", flush=True)
    return results


def ab(rec: Path, mix_a: Path, mix_b: Path, kinds: set, limit: int):
    """Blind A/B at the same transition points between two mixes of
    the same recording (before/after a fix)."""
    evs = load_events(rec)
    trs = [tr for tr in transitions(evs) if tr[1] in kinds][:limit]
    xa, sr = sf.read(str(mix_a), dtype="float32")
    xb, _ = sf.read(str(mix_b), dtype="float32")
    tmp = Path(tempfile.mkdtemp(prefix="probeab_"))
    wins = {"a": 0, "b": 0}
    for i, (t, kind, label) in enumerate(trs):
        order = ["a", "b"]
        random.Random(i * 31).shuffle(order)
        clips = []
        for j, tag in enumerate(order):
            mp3 = tmp / f"t{i}_{j}.mp3"
            _clip(xa if tag == "a" else xb, sr, t, mp3)
            clips.append(mp3)
        prompt = (
            f"Two versions (A then B) of the same game-soundtrack "
            f"passage containing a '{label}' transition about "
            f"{PRE_S:.0f}s in. They differ only in how that "
            "transition is produced. Which version handles it more "
            "cleanly and musically (no pops, clicks, hard cuts, "
            "dropouts)? Respond ONLY with JSON: "
            "{\"better\": \"A\"|\"B\", \"margin\": "
            "\"slight\"|\"clear\", \"why\": \"one sentence\"}")
        res = _ask_multi(clips, prompt)
        pick = order[0] if res.get("better") == "A" else order[1]
        wins[pick] += 1
        print(f"{t:7.2f}s {kind:9s} -> {pick.upper()} | "
              f"{res.get('margin')} {res.get('why')}", flush=True)
    print(f"\nB (after) wins {wins['b']}/{wins['a'] + wins['b']}",
          flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["list", "probe", "ab"])
    ap.add_argument("rec")
    ap.add_argument("mix_a", nargs="?")
    ap.add_argument("mix_b", nargs="?")
    ap.add_argument("--kinds", default="jump,loop,release,rotation,"
                    "riser,slam,death")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    rec = Path(a.rec)
    if a.mode == "list":
        for t, kind, label in transitions(load_events(rec)):
            print(f"{t:8.2f}s {kind:9s} {label}")
    elif a.mode == "probe":
        probe(rec, a.limit)
    else:
        ab(rec, Path(a.mix_a), Path(a.mix_b),
           set(a.kinds.split(",")), a.limit or 8)


if __name__ == "__main__":
    main()
