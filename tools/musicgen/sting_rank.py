"""sting_rank — rank boss-release punctuation variants IN CONTEXT.

Director overnight goal: the stinger 'should sound like part of the
song, not a sound effect overlaid... may need to simply be removed.'
Variants, ranked by Gemini at REAL boss-release moments cut from the
night recording (mix rendered without any sting, variant overlaid at
the exact release tap):

  A none        -- no punctuation at all
  B bare        -- current deep bell, dry on top
  C halled      -- the bell through the song's own hall, -4dB
  D amen        -- the track's choir resolving a two-chord cadence

    uv run python tools/musicgen/sting_rank.py REC_DIR
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

import tutti as T                                   # noqa: E402
import mkvideo as MK                                # noqa: E402
from bell_sting import (build_sting, build_sting_halled,
                        build_sting_amen)           # noqa: E402
from judge_track import _ask_multi, _stereo_mp3    # noqa: E402

PRE_S, POST_S = 10.0, 10.0


def main():
    rec = Path(sys.argv[1])
    evs = [json.loads(l) for l in
           (rec / "events.jsonl").read_text().splitlines()]
    rels = [e["t"] for e in evs if e["kind"] == "music_rel"]
    banks = [(e["t"], e["name"]) for e in evs
             if e["kind"] == "music_bank"]
    if not rels:
        sys.exit("no boss releases in recording")
    dur = max(e["t"] for e in evs) + 2
    base = np.zeros((int(dur * MK.RATE) + MK.RATE, 2), dtype=np.float32)
    # mix WITHOUT any sting: drop sting taps before mixing
    evs_nosting = [e for e in evs if e["kind"] != "music_sting"]
    assert MK._mix_music_rich(base, evs_nosting, dur)
    rng = np.random.default_rng(7)
    tmp = Path(tempfile.mkdtemp(prefix="stingrank_"))
    contexts = rels[:2]
    for ci, t_rel in enumerate(contexts):
        bank_name = [n for tt, n in banks if tt <= t_rel][-1]
        mel = bank_name.replace("album_", "")
        rec_t = T.RECIPES[mel]
        variants = {
            "none": None,
            "bare": build_sting(rec_t, rng, "bare") * 0.8,
            "halled": build_sting_halled(rec_t, rng),
            "amen": build_sting_amen(rec_t, rng),
        }
        clips = {}
        for name, sting in variants.items():
            m = base.copy()
            if sting is not None:
                s0 = int(t_rel * MK.RATE)
                seg = sting[: len(m) - s0]
                m[s0:s0 + len(seg), 0] += seg
                m[s0:s0 + len(seg), 1] += seg
            a = int((t_rel - PRE_S) * MK.RATE)
            b = int((t_rel + POST_S) * MK.RATE)
            cut = m[max(0, a):b]
            cut = cut / (np.abs(cut).max() + 1e-9) * 0.9
            w = tmp / f"c{ci}_{name}.wav"
            sf.write(str(w), cut, MK.RATE)
            mp3 = tmp / f"c{ci}_{name}.mp3"
            _stereo_mp3(w, mp3, max_s=PRE_S + POST_S + 1)
            clips[name] = mp3
        order = ["none", "bare", "halled", "amen"]
        prompt = (
            "Four versions of the same game-soundtrack passage: a boss "
            f"fight ends ~{PRE_S:.0f}s in and the music releases back "
            "toward calm chant. They differ in the PUNCTUATION at the "
            "kill: A = none (just the release); B = a deep chapel bell, "
            "dry; C = the same bell inside the track's own reverb, "
            "quieter; D = the track's choir resolving a two-chord "
            "cadence (no bell). Judge: which punctuation (or none) "
            "sounds most like PART OF THE SONG -- intentional writing, "
            "not a sound effect overlaid? Respond ONLY with JSON: "
            "{\"ranking\": [best..worst of A,B,C,D], \"per\": {\"A\": "
            "\"one clause\", ...}, \"verdict\": \"one sentence\"}")
        for rep in range(2):
            res = _ask_multi([clips[k] for k in order], prompt,
                             labels=[f"Clip {c}" for c in "ABCD"])
            print(f"context {ci} ({mel}) rep {rep}:",
                  json.dumps(res, indent=1), flush=True)


if __name__ == "__main__":
    main()
