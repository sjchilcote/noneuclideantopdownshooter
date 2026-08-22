"""prayer_probe — the monk's channel ISOLATED, checked chunk by chunk.

Director 2026-07-17 03:xx: "everything but the monk is perfect, but
the monk has SEVERE cut-out and slam-cut issues. Try generating runs
with the prayer channel isolated and having Gemini check them chunk
by chunk."

Renders ONLY the holy lane from a recording's taps (exact offline
reconstruction: bar content, gains, farewell ramps, jump behavior,
halt), slices the result into overlapping windows, and batch-asks
Gemini per window whether the SOLO voice has cut-outs, hard cuts,
splices, or level slams. Output: a seam map with timestamps.

    uv run python tools/musicgen/prayer_probe.py REC_DIR [--windows N]
"""
from __future__ import annotations

import argparse
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

WIN_S = 24.0
HOP_S = 20.0


def isolate_holy(rec: Path):
    """Render the mix with every lane except holy muted, by rewriting
    the bar taps (other lanes -> gain 0). Riser/sting/stab dropped."""
    evs = [json.loads(l) for l in
           (rec / "events.jsonl").read_text().splitlines()]
    dur = max(e["t"] for e in evs) + 2
    solo = []
    for e in evs:
        if e["kind"] in ("music_riser", "music_riser2", "music_sting",
                         "music_stab"):
            continue
        if e["kind"] == "music_bar":
            parts = e["name"].split("|")
            out = [parts[0]]
            for p in parts[1:]:
                ln, key, g = p.rsplit(":", 2)
                if ln != "holy":
                    g = "0.000"
                out.append(f"{ln}:{key}:{g}")
            e = dict(e, name="|".join(out))
        solo.append(e)
    mix = np.zeros((int(dur * MK.RATE) + MK.RATE, 2), dtype=np.float32)
    assert MK._mix_music_rich(mix, solo, dur)
    return mix, dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rec")
    ap.add_argument("--windows", type=int, default=None)
    ap.add_argument("--start", type=float, default=0.0)
    a = ap.parse_args()
    rec = Path(a.rec)
    mix, dur = isolate_holy(rec)
    peak = float(np.abs(mix).max()) or 1.0
    mix = mix / peak * 0.85          # ONE global normalization: level
    #                                  steps must stay comparable
    tmp = Path(tempfile.mkdtemp(prefix="prayerprobe_"))
    sf.write(str(tmp / "holy_solo_full.wav"), mix, MK.RATE)
    print(f"isolated render: {tmp}/holy_solo_full.wav", flush=True)
    t0s = []
    t = a.start
    while t + WIN_S <= dur:
        t0s.append(t)
        t += HOP_S
    if a.windows:
        t0s = t0s[:a.windows]
    findings = []
    for g0 in range(0, len(t0s), 4):
        grp = t0s[g0:g0 + 4]
        clips, descs = [], []
        for i, t0 in enumerate(grp):
            seg = mix[int(t0 * MK.RATE):int((t0 + WIN_S) * MK.RATE)]
            w = tmp / f"w{g0 + i}.wav"
            sf.write(str(w), seg, MK.RATE)
            mp3 = tmp / f"w{g0 + i}.mp3"
            _stereo_mp3(w, mp3, max_s=WIN_S + 1)
            clips.append(mp3)
            descs.append(f"{chr(65 + i)}: covers {t0:.0f}s-"
                         f"{t0 + WIN_S:.0f}s of the piece")
        prompt = (
            "These clips are an ISOLATED vocal/choir channel (a monk "
            "chant with choir and bells) from a dynamic game "
            "soundtrack. The voice legitimately breathes between "
            "phrases and its LEVEL may move gently. You are listening "
            "for DEFECTS ONLY:\n"
            "- a phrase cut off mid-syllable (splice)\n"
            "- an abrupt level slam (sudden loud/quiet step, not a "
            "musical swell)\n"
            "- a dead stretch longer than ~4 seconds\n"
            "- doubled/overlapping copies of the same voice\n" +
            "\n".join(descs) +
            "\nFor EACH clip list defects with their approximate "
            "second WITHIN the clip (or 'clean'). Respond ONLY with "
            "JSON: {\"clips\": {\"A\": [{\"at_s\": 3.5, \"defect\": "
            "\"...\"}] or [], ...}}")
        res = _ask_multi(clips, prompt,
                         labels=[chr(65 + i) for i in range(len(clips))])
        for i, t0 in enumerate(grp):
            items = res.get("clips", {}).get(chr(65 + i), [])
            for it in items if isinstance(items, list) else []:
                at = it.get("at_s")
                gt = t0 + float(at) if isinstance(at, (int, float)) \
                    else None
                findings.append(dict(window_t0=t0, global_t=gt,
                                     defect=it.get("defect")))
                print(json.dumps(findings[-1]), flush=True)
    print(f"\n{len(findings)} defects across {len(t0s)} windows",
          flush=True)
    # cluster by global time for the seam map
    for f in sorted(findings, key=lambda f: f.get("global_t") or -1):
        print(f"  {f['global_t'] if f['global_t'] is not None else '??':>8} "
              f" {f['defect']}", flush=True)


if __name__ == "__main__":
    main()
