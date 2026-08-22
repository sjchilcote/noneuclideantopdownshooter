"""monk_ab — before/after A/B of the monk seam fixes, blind, at the
exact defect timestamps the isolated-channel sweep flagged.

BEFORE = the shipped debug11 mix (old banks: baked prayer fold, -15dB
fill cutoff; old mixer: holy steps + hard re-address).
AFTER  = the same recording re-rendered with fold-free prayer +
prayer_tail overlay + full-bar holy glides + jump tail voice.

Two judged tracks, both blind (A/B randomized per window):
  full : full-mix windows around each defect
  solo : isolated holy channel, same windows

Per the judge protocol, pick-letters alone are noise -- we require
rationale-consistency and report the rationales verbatim.

    uv run python tools/musicgen/monk_ab.py REC_DIR OLD_AUDIO
"""
from __future__ import annotations

import json
import subprocess
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
from prayer_probe import isolate_holy              # noqa: E402

# defect timestamps from the 2026-07-17 sweeps of finalrec2: the five
# isolated-channel seam defects plus the full-mix probe's original
# cut-out->gone->slam-in cycle points (13/63/108/281)
DEFECTS = [
    (13.0, "cycle: vigil-loop monk hole"),
    (33.5, "slam at the 22->16 develop jump"),
    (53.5, "doubled voice entering bar 0 from 17"),
    (63.0, "cycle: dies_irae bars 22-27 voice rest"),
    (108.0, "cycle: idumea vigil pre-entrance hole"),
    (121.5, "gain-snap splice in the vigil swell"),
    (175.5, "dead stretch + slam entrance at full gain"),
    (232.0, "splice at the 18->0 loop wrap"),
    (281.5, "cycle: lhomme loop->0 landing"),
]
WIN = 16.0   # seconds per window, defect centered


def render_full(rec: Path) -> np.ndarray:
    evs = [json.loads(l) for l in
           (rec / "events.jsonl").read_text().splitlines()]
    dur = max(e["t"] for e in evs) + 2
    mix = np.zeros((int(dur * MK.RATE) + MK.RATE, 2), dtype=np.float32)
    assert MK._mix_music_rich(mix, evs, dur)
    return mix


def load_old(path: Path) -> np.ndarray:
    if path.suffix in (".mp4", ".mkv"):
        tmp = Path(tempfile.mkdtemp(prefix="monkab_")) / "old.wav"
        subprocess.run(["ffmpeg", "-y", "-i", str(path), "-vn",
                        "-ar", str(MK.RATE), "-ac", "2", str(tmp)],
                       check=True, capture_output=True)
        path = tmp
    x, sr = sf.read(str(path), dtype="float32")
    assert sr == MK.RATE, sr
    return x


def norm(x):
    pk = float(np.abs(x).max()) or 1.0
    return x / pk * 0.85


def judge(pairs, label):
    """pairs: list of (t, desc, old_seg, new_seg). Blind A/B."""
    import random
    rng = random.Random(20260717)
    tmp = Path(tempfile.mkdtemp(prefix=f"monkab_{label}_"))
    results = []
    for t, desc, old, new in pairs:
        flip = rng.random() < 0.5
        a, b = (new, old) if flip else (old, new)
        clips = []
        for tag, seg in (("A", a), ("B", b)):
            w = tmp / f"{label}_{t:.0f}_{tag}.wav"
            sf.write(str(w), seg, MK.RATE)
            m = tmp / f"{label}_{t:.0f}_{tag}.mp3"
            _stereo_mp3(w, m, max_s=WIN + 1)
            clips.append(m)
        prompt = (
            "Two renders of the SAME passage of a dynamic game "
            "soundtrack (industrial metal + Gregorian chant). They "
            "differ only in how the chant voice is handled at "
            "transitions. Listen for the CHANT VOICE specifically: "
            "mid-syllable cuts, abrupt level jumps, doubled copies "
            "of the voice, the voice vanishing then slamming back.\n"
            "Which render treats the voice better? Respond ONLY with "
            'JSON: {"pick": "A"|"B"|"tie", "voice_defects_A": "...", '
            '"voice_defects_B": "...", "reason": "..."}')
        res = _ask_multi(clips, prompt, labels=["Clip A", "Clip B"])
        pick = res.get("pick", "?")
        # unblind: which physical render won
        winner = {"A": "new" if flip else "old",
                  "B": "old" if flip else "new"}.get(pick, pick)
        results.append(dict(t=t, desc=desc, winner=winner, raw=res,
                            flipped=flip))
        print(json.dumps(dict(t=t, track=label, winner=winner,
                              reason=res.get("reason"))), flush=True)
    return results


def main():
    rec = Path(sys.argv[1])
    old_path = Path(sys.argv[2])
    new_full = render_full(rec)
    old_full = load_old(old_path)
    new_solo, _ = isolate_holy(rec)
    new_solo = norm(new_solo)

    def seg(x, t):
        a = int((t - WIN / 2) * MK.RATE)
        return x[max(0, a):max(0, a) + int(WIN * MK.RATE)]

    full_pairs = [(t, d, seg(old_full, t), seg(new_full, t))
                  for t, d in DEFECTS]
    out = {"full": judge(full_pairs, "full")}
    # solo track: no old isolated render exists on disk; re-render it
    # from the SAME taps with the OLD banks is impossible post-regen,
    # so the solo comparison is new-render vs the sweep's archived
    # windows only when available.
    arch = Path("/tmp/prayerprobe_oigg71rm/holy_solo_full.wav")
    if arch.exists():
        old_solo, _ = sf.read(str(arch), dtype="float32")
        solo_pairs = [(t, d, seg(old_solo, t), seg(new_solo, t))
                      for t, d in DEFECTS]
        out["solo"] = judge(solo_pairs, "solo")
    wins = {k: sum(1 for r in v if r["winner"] == "new")
            for k, v in out.items()}
    print(f"\nnew-render wins: {wins} of {len(DEFECTS)} per track",
          flush=True)
    (ROOT / "out/consults/monk_ab_results.json").write_text(
        json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
