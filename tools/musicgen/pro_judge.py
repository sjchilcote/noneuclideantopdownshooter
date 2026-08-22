"""Pro-tier assembled-work judge (director's order: flash is only for solo
instruments; assembled music gets the strongest audio-capable Gemini).

Model: google/gemini-3.1-pro-preview (strongest audio-in tier on
OpenRouter as of 2026-07-13; resolved from the models endpoint).
Fixture discipline before any score counts: a real album block must read
as professional coherent music; the v3-condemned stem (git 3b2035d,
the director's "random GM clips" era) must read as broken/amateur.

    uv run python tools/musicgen/pro_judge.py --fixtures
    uv run python tools/musicgen/pro_judge.py piece.wav -n 5
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "playtest"))
import audio_judge  # noqa: E402

MODEL = "google/gemini-3.1-pro-preview"
S = Path("/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter"
         "/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/musicgen")

RUBRIC = """Audio only, mono mixdown. Ignore stereo width. Your audio
frontend under-reports sub-bass; do not penalize low end. Timestamps you
infer are unreliable.

The clip is a music render from an unknown source: could be a commercial
release, a work-in-progress, or a broken render.

Assess, in this order, keeping the assessments independent:
1. Musicality (brief-independent): intent, phrasing, rhythm that locks,
   sounds that belong together. A finished commercial track is musical
   even if abrasive; disconnected noises are not.
2. Production: source quality, balance, space.
3. Brief execution, scored separately from 1 and 2. The brief: "Church
   music made by posthuman industrial machines that genuinely believe —
   with meaningful musical symbolism." A piece in a different style
   scores low here without affecting its musicality score.

Return STRICT JSON only:
{"works_as_music": true/false,
 "p_first_draft_shippable": 0.x,
 "melody_followable": true/false,
 "brief_execution": 0.x,
 "originality": 0.x,
 "three_strengths": ["..."],
 "three_problems": ["..."],
 "verdict_sentence": "one honest sentence"}"""


def _call(content):
    import urllib.request
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2}
    req = urllib.request.Request(
        audio_judge.OPENROUTER_URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {audio_judge.openrouter_key()}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        payload = json.load(resp)
    usage = payload.get("usage", {})
    audio_judge._log_call({"tool": "musicgen.pro_judge", "model": MODEL,
                           "prompt_tokens": usage.get("prompt_tokens"),
                           "completion_tokens": usage.get("completion_tokens")},
                          float(usage.get("cost", 0.0) or 0.0))
    return audio_judge._parse_json_response(
        payload["choices"][0]["message"]["content"])


def judge(wav: Path, n: int = 3) -> dict:
    import base64
    work = Path(tempfile.mkdtemp(prefix="projudge_", dir=str(S)))
    mp3 = work / (wav.stem + ".mp3")
    audio_judge.to_mp3(wav, mp3, max_s=150.0)
    snd = {"type": "input_audio", "input_audio": {
        "data": base64.b64encode(mp3.read_bytes()).decode(), "format": "mp3"}}
    rs = []
    for _ in range(n):
        try:
            rs.append(_call([{"type": "text", "text": RUBRIC}, snd]))
        except Exception as e:  # noqa: BLE001
            print(f"pro_judge call failed: {e}", file=sys.stderr)
    if not rs:
        return {"error": "all calls failed"}
    return {"n": len(rs),
            "p_median": statistics.median(
                r.get("p_first_draft_shippable", 0.0) for r in rs),
            "works_as_music": [r.get("works_as_music") for r in rs],
            "melody_followable": [r.get("melody_followable") for r in rs],
            "brief_median": statistics.median(
                r.get("brief_execution", 0.0) for r in rs),
            "originality_median": statistics.median(
                r.get("originality", 0.0) for r in rs),
            "problems": [r.get("three_problems") for r in rs],
            "verdicts": [r.get("verdict_sentence") for r in rs],
            "raw": rs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", nargs="?", type=Path)
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--fixtures", action="store_true")
    a = ap.parse_args()
    if a.fixtures:
        good = next(S.glob("blocks/04_not_a_heart__but_an_engine_blk03.wav"))
        bad = S / "fixture_condemned_v3.wav"
        rg = judge(good, 2)
        print("album block:", {k: rg[k] for k in
              ("p_median", "works_as_music", "melody_followable")})
        rb = judge(bad, 2)
        print("condemned v3:", {k: rb[k] for k in
              ("p_median", "works_as_music", "melody_followable")})
        # the discriminating statistic is p_median (0.65 vs 0.1 measured);
        # works_as_music proved noisy on the bad fixture — advisory only
        ok = rg["p_median"] >= 0.6 and rb["p_median"] <= 0.3
        print("PRO-JUDGE FIXTURES", "PASS" if ok else "FAIL")
        out = Path(__file__).parent / "analysis/pro_judge_fixtures.json"
        out.write_text(json.dumps({"good": {k: v for k, v in rg.items() if k != "raw"},
                                   "bad": {k: v for k, v in rb.items() if k != "raw"},
                                   "pass": ok}, indent=1))
        sys.exit(0 if ok else 1)
    if not a.wav:
        ap.error("wav required unless --fixtures")
    fx = Path(__file__).parent / "analysis/pro_judge_fixtures.json"
    if not fx.exists() or not json.loads(fx.read_text()).get("pass"):
        print("Refusing to score: run --fixtures first.")
        sys.exit(2)
    r = judge(a.wav, a.n)
    print(json.dumps({k: v for k, v in r.items() if k != "raw"}, indent=1))


if __name__ == "__main__":
    main()
