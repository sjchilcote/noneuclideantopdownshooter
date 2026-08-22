"""GROUNDED complete-track judge — anchored, contrastive, validated.

    uv run python tools/musicgen/judge_track.py out/tutti_x.wav [n]

Ungrounded 1-10 scoring floats on an uncalibrated scale (director,
2026-07-15: "It needs grounding"). Every pass therefore scores THREE
clips on ONE scale in ONE request:

  A = positive anchor: the real album (the target, by definition ~9-10)
  B = negative anchor: the condemned old generation (known ~1-2)
  C = the candidate

A pass is VALID only if score(A) - score(B) >= 3 (the judge separated
the anchors); invalid passes are discarded, never averaged. The
reported grounded score is the median valid C, plus C normalized into
the A-B interval. Gaps are CONTRASTIVE: what does C lack that A has.

Anchors (scratchpad): album track 01 (chant intro -> band entry —
structurally parallel to the tutti form) and fixture_condemned_v3.wav.
Stereo mp3s throughout (mono is blind to double-tracking).
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "playtest"))

S = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
         "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b"
         "/scratchpad/musicgen")
ANCHOR_GOOD = S / ("tracks/01_rejoice__for_we_were_once_blessed__"
                   "chant_of_remembrance.wav")
ANCHOR_BAD = S / "fixture_condemned_v3.wav"

BRIEF = ("church music made by posthuman industrial machines that "
         "genuinely believe — an original sound with meaningful musical "
         "symbolism, for combat in a retro-futuristic cosmic-horror game")

PROMPT = (
    "Three complete music tracks follow, in order: Track A, Track B, "
    "Track C. Score ALL THREE on the same 1-10 scale: does this sound "
    f"like a finished, professional piece of music that evokes: {BRIEF}? "
    "Use the full scale; the tracks may differ widely. "
    "Answer as strict JSON with keys: "
    "score_a, score_b, score_c (integers 1-10), "
    "gaps (array of strings: the concrete, actionable things Track C "
    "LACKS THAT TRACK A HAS — composition, arrangement, performance, "
    "sound design, mix; cite times in C), "
    "c_works (one sentence: what C already does that must be kept)."
)

MODEL = "google/gemini-3.1-pro-preview"


def _stereo_mp3(src: Path, out: Path, max_s: float = 100.0):
    import audio_judge
    audio_judge._ensure_ffmpeg()
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn",
           "-t", str(max_s), "-ac", "2"]
    try:
        dur = audio_judge._wav_duration_s(src)
    except Exception:
        dur = None
    if dur is not None and dur > max_s:
        cmd += ["-af", f"afade=t=out:st={max_s - 1.0:.2f}:d=1.0"]
    cmd += ["-codec:a", "libmp3lame", "-q:a", "3", str(out)]
    subprocess.run(cmd, check=True)


def _ask_multi(clips, prompt: str, model: str = MODEL,
               attempts: int = 3, labels=None) -> dict:
    """labels: optional per-clip text markers ("Clip A", ...) inserted
    IMMEDIATELY BEFORE each audio block. Without them the model must
    guess which attachment is which -- for same-passage A/B pairs the
    letter mapping degenerates to a coin flip (2026-07-17: two A/B
    rounds unblinded backwards at one probe point before this was
    caught). Any letter-referencing prompt should pass labels."""
    import urllib.request
    import audio_judge
    last = None
    for _ in range(attempts):
        try:
            content = [{"type": "text", "text": prompt}]
            for i, c in enumerate(clips):
                if labels is not None:
                    content.append({"type": "text",
                                    "text": f"{labels[i]}:"})
                content.append(audio_judge._audio_block(c))
            body = {"model": model,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.2}
            req = urllib.request.Request(
                audio_judge.OPENROUTER_URL,
                data=json.dumps(body).encode(),
                headers={"Authorization":
                         f"Bearer {audio_judge.openrouter_key()}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=420) as resp:
                payload = json.load(resp)
            usage = payload.get("usage", {})
            audio_judge._log_call(
                {"tool": "musicgen.judge_track_grounded", "model": model,
                 "prompt_tokens": usage.get("prompt_tokens"),
                 "completion_tokens": usage.get("completion_tokens")},
                float(usage.get("cost", 0.0) or 0.0))
            txt = payload["choices"][0]["message"]["content"]
            return audio_judge._parse_json_response(txt)
        except Exception as exc:
            last = exc
    return {"error": str(last)}


def judge(wav: str | Path, n: int = 3) -> dict:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        clips = []
        for name, src in [("a", ANCHOR_GOOD), ("b", ANCHOR_BAD),
                          ("c", Path(wav))]:
            mp3 = tmp / f"{name}.mp3"
            _stereo_mp3(src, mp3)
            clips.append(mp3)
        valid, discarded = [], 0
        for _ in range(n):
            r = _ask_multi(clips, PROMPT)
            if "error" in r or "score_c" not in r:
                discarded += 1
                continue
            a, b, c = int(r["score_a"]), int(r["score_b"]), int(r["score_c"])
            if a - b < 3:
                discarded += 1              # judge failed the anchors
                continue
            norm = (c - b) / max(1, a - b)  # 0 = as bad as B, 1 = at A
            valid.append(dict(a=a, b=b, c=c, norm=round(norm, 2),
                              gaps=r.get("gaps", []),
                              works=r.get("c_works", "")))
    if not valid:
        return {"error": f"no valid passes ({discarded} discarded)"}
    return dict(
        c_median=statistics.median(v["c"] for v in valid),
        norm_median=statistics.median(v["norm"] for v in valid),
        anchors=[(v["a"], v["b"], v["c"]) for v in valid],
        discarded=discarded,
        gaps=[g for v in valid for g in v["gaps"]],
        works=[v["works"] for v in valid])


if __name__ == "__main__":
    wav = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(json.dumps(judge(wav, n), indent=1))
