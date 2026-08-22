"""monk_fullmix_probe — the director's bugs, hunted in the SHIPPED mix.

Director 2026-07-17 ~03:30: listened to debug12 -- "NONE of the bugs I
told you about have been fixed. Confirm them with Gemini, then fix
them." The bugs as originally stated: the monk has SEVERE cut-out and
slam-cut issues.

This probe listens to the FULL MIX of an actual deliverable mp4 (not
an isolated channel, not a re-render) in overlapping windows and asks
ONLY about the chant voice's presence dynamics: does he vanish
mid-line, is he gone for long stretches while the music plays on, does
he slam back in at full force. Timestamps come back per window for tap
correlation.

    uv run python tools/musicgen/monk_fullmix_probe.py VIDEO.mp4
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from judge_track import _ask_multi, _stereo_mp3    # noqa: E402

WIN_S = 30.0
HOP_S = 25.0


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="mp4/wav, or a REC DIR (audio-only "
                    "mix straight from taps -- no video encode)")
    ap.add_argument("--windows", type=int, default=None)
    ap.add_argument("--skip", type=int, default=0)
    a = ap.parse_args()
    src = Path(a.src)
    tmp = Path(tempfile.mkdtemp(prefix="monkfull_"))
    import numpy as np
    import soundfile as sf
    if src.is_dir():
        sys.path.insert(0, str(Path(__file__).parents[1] / "playtest"))
        import mkvideo as MK
        import json as _json
        evf = src / "events.jsonl"
        evs = [_json.loads(l) for l in evf.read_text().splitlines()]
        dur = max(e["t"] for e in evs) + 2
        x = np.zeros((int(dur * MK.RATE) + MK.RATE, 2),
                     dtype=np.float32)
        assert MK._mix_music_rich(x, evs, dur)
        pk = float(np.abs(x).max()) or 1.0
        x = x / pk * 0.85
        sr = MK.RATE
    else:
        wav = tmp / "full.wav"
        if src.suffix == ".wav":
            wav = src
        else:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i",
                            str(src), "-vn", "-ar", "44100", "-ac",
                            "2", str(wav)], check=True)
        x, sr = sf.read(str(wav))
    dur = len(x) / sr
    t0s = []
    t = 0.0
    while t + WIN_S <= dur:
        t0s.append(t)
        t += HOP_S
    t0s = t0s[a.skip:]
    if a.windows:
        t0s = t0s[:a.windows]
    findings = []
    import soundfile as sf
    for g0 in range(0, len(t0s), 4):
        grp = t0s[g0:g0 + 4]
        clips, descs, labels = [], [], []
        for i, t0 in enumerate(grp):
            seg = x[int(t0 * sr):int((t0 + WIN_S) * sr)]
            w = tmp / f"w{g0 + i}.wav"
            sf.write(str(w), seg, sr)
            m = tmp / f"w{g0 + i}.mp3"
            _stereo_mp3(w, m, max_s=WIN_S + 1)
            clips.append(m)
            lab = chr(65 + i)
            labels.append(f"Clip {lab}")
            descs.append(f"{lab}: covers {t0:.0f}s-{t0 + WIN_S:.0f}s")
        prompt = (
            "This is a dynamic game soundtrack: industrial metal with "
            "a Gregorian chant voice (a monk, sometimes with choir) "
            "woven through it as a continuous through-line. The DESIGN "
            "INTENT is that the chant NEVER stops -- it may get "
            "quieter under heavy combat but should stay present and "
            "should never vanish abruptly or lurch back in.\n"
            "Listen ONLY for the chant voice and report:\n"
            "- CUT-OUT: the voice disappears abruptly (mid-phrase or "
            "between phrases) while other music continues\n"
            "- GONE: stretches longer than ~5 seconds where you "
            "cannot hear the chant at all while other music plays\n"
            "- SLAM-IN: the voice re-enters as a sudden jolt (a level "
            "lurch, not a musical entrance or swell)\n" +
            "\n".join(descs) +
            "\nFor EACH clip list events with approximate seconds "
            "WITHIN that clip, or 'clean'. Respond ONLY with JSON: "
            '{"clips": {"A": [{"at_s": 3.5, "kind": "CUT-OUT|GONE|'
            'SLAM-IN", "note": "..."}] or [], ...}}')
        res = _ask_multi(clips, prompt, labels=labels)
        for i, t0 in enumerate(grp):
            items = res.get("clips", {}).get(chr(65 + i), [])
            for it in items if isinstance(items, list) else []:
                at = it.get("at_s")
                gt = t0 + float(at) if isinstance(at, (int, float)) \
                    else None
                findings.append(dict(window_t0=t0, global_t=gt,
                                     kind=it.get("kind"),
                                     note=it.get("note")))
                print(json.dumps(findings[-1]), flush=True)
    print(f"\n{len(findings)} events across {len(t0s)} windows",
          flush=True)
    for f in sorted(findings, key=lambda f: f.get("global_t") or -1):
        print(f"  {f['global_t'] if f['global_t'] is not None else '??':>8}"
              f"  {f['kind']:8s} {f.get('note', '')[:70]}", flush=True)


if __name__ == "__main__":
    main()
