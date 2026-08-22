"""Gate-2 judge: does the dynamic music match gameplay at beta quality?

Operationalization (honest limits stated): a professional technical
artist judging gameplay<->music matching would watch the video. Our model
ears take AUDIO + a text gameplay timeline (derived from the recording's
OWN sfx events — combat = gunfire/impact density; the music events are
withheld from the judge). The judge hears the MUSIC-ONLY channel so sfx
can't leak the answer, and scores whether the music tracks the fights.

Control validation (johnny law — the judge is void until it
discriminates): the same timeline judged against a STATIC loop of the
same material must score materially lower than the dynamic mix. Position
bias handled by running both orders.

    uv run python tools/musicgen/dynamic_judge.py <rec_dir> [-n 3]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "playtest"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "musicgen"))
import audio_judge  # noqa: E402
import mkvideo      # noqa: E402  (build_mix for the music-only render)


def _call(content: list, tag: str) -> dict:
    import urllib.request
    body = {"model": audio_judge.MODEL,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2}
    req = urllib.request.Request(
        audio_judge.OPENROUTER_URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {audio_judge.openrouter_key()}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.load(resp)
    usage = payload.get("usage", {})
    audio_judge._log_call({"tool": tag, "model": audio_judge.MODEL,
                           "prompt_tokens": usage.get("prompt_tokens"),
                           "completion_tokens": usage.get("completion_tokens")},
                          float(usage.get("cost", 0.0) or 0.0))
    return audio_judge._parse_json_response(
        payload["choices"][0]["message"]["content"])


def _mp3(src: Path, work: Path, max_s: float = 95.0) -> Path:
    out = work / (src.stem + ".mp3")
    if not out.exists():
        audio_judge.to_mp3(src, out, max_s=max_s)
    return out


def _snd(mp3: Path) -> dict:
    import base64
    return {"type": "input_audio", "input_audio": {
        "data": base64.b64encode(mp3.read_bytes()).decode(),
        "format": "mp3"}}

BANK = Path(__file__).resolve().parents[2] / "game/perihelion/assets/music/hymn01"

RUBRIC = """Audio only: the music track from a top-down action game
session, sound effects removed. Assess the dynamic music SYSTEM only —
whether the music tracks the gameplay — not composition quality or mix
polish.

The session's gameplay timeline (from the game's own event log):
{timeline}

Score against these observables:
- Does musical intensity rise when fights start (within ~2 seconds of the
  listed fight windows) and fall after they end?
- Do transitions land musically (on rhythmic boundaries, with intentional
  hits/stings) rather than as arbitrary mid-phrase jumps or abrupt volume
  pops?
- Do calm stretches get genuinely calmer material (not just quieter)?
- Any state changes with NO gameplay cause, or fights the music ignores?

Return STRICT JSON only:
{{"fight_windows_tracked": "N of M windows where music visibly responds",
 "false_transitions": 0,
 "musical_transitions": true/false,
 "calm_is_calm": true/false,
 "p_beta_shippable": 0.x,  // P(a professional technical artist calls this
                           // gameplay<->music matching beta-test shippable)
 "biggest_gap": "...",
 "summary": "2 sentences"}}"""


def gameplay_timeline(events_path: Path, dur: float) -> str:
    evs = [json.loads(l) for l in events_path.read_text().splitlines()
           if l.strip()]
    # combat proxy: player weapon fire + enemy hit/death sfx per 5s bucket
    combat_names = ("pistol", "shotgun", "smg", "rifle", "tau", "gun",
                    "hit", "die", "death", "pounce", "scream")
    buckets = {}
    for e in evs:
        if e["kind"] != "sfx":
            continue
        if any(k in e["name"] for k in combat_names):
            buckets[int(e["t"] // 5) * 5] = buckets.get(
                int(e["t"] // 5) * 5, 0) + 1
    lines = []
    fighting = False
    start = 0
    for t in range(0, int(dur) + 5, 5):
        hot = buckets.get(t, 0) >= 3
        if hot and not fighting:
            fighting, start = True, t
        elif not hot and fighting:
            fighting = False
            lines.append(f"- FIGHT from ~{start}s to ~{t}s")
    if fighting:
        lines.append(f"- FIGHT from ~{start}s to end")
    if not lines:
        lines.append("- no sustained fights detected (calm session)")
    return "\n".join(lines)


def render_music_only(rec: Path, dur: float, out: Path):
    evs = [json.loads(l) for l in (rec / "events.jsonl").read_text()
           .splitlines() if l.strip()]
    tmp = out.parent / (out.stem + "_events.jsonl")
    tmp.write_text("\n".join(json.dumps(e) for e in evs
                             if e["kind"].startswith("music")))
    mkvideo.build_mix(tmp, dur, out)


def render_static_control(dur: float, out: Path):
    with wave.open(str(BANK / "stalwart.wav")) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1).astype(np.int16)
        rate = w.getframerate()
    n = int(dur * rate)
    reps = int(np.ceil(n / len(data)))
    loop = np.tile(data, reps)[:n]
    stereo = np.stack([loop, loop], axis=1)
    with wave.open(str(out), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(stereo.astype(np.int16).tobytes())


def judge(wav: Path, timeline: str, work: Path, n: int) -> dict:
    rs = []
    for _ in range(n):
        content = [{"type": "text",
                    "text": RUBRIC.format(timeline=timeline)},
                   _snd(_mp3(wav, work, max_s=95.0))]
        try:
            rs.append(_call(content, "musicgen.dynamic_judge"))
        except Exception as e:  # noqa: BLE001
            print(f"judge call failed: {e}", file=sys.stderr)
    if not rs:
        return {"error": "all calls failed"}
    return {"p_median": statistics.median(
                r.get("p_beta_shippable", 0.0) for r in rs),
            "raw": rs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rec", type=Path)
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--dur", type=float, default=90.0)
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="djudge_",
                                 dir=str(a.rec.parent)))
    timeline = gameplay_timeline(a.rec / "events.jsonl", a.dur)
    print("gameplay timeline given to the judge:")
    print(timeline)
    dyn = work / "dynamic.wav"
    stat = work / "static.wav"
    render_music_only(a.rec, a.dur, dyn)
    render_static_control(a.dur, stat)
    print("\njudging DYNAMIC mix:")
    rd = judge(dyn, timeline, work, a.n)
    print(f"  p_median = {rd.get('p_median')}")
    print("judging STATIC control (same timeline):")
    rst = judge(stat, timeline, work, a.n)
    print(f"  p_median = {rst.get('p_median')}")
    ok = rd.get("p_median", 0) >= rst.get("p_median", 1) + 0.15
    print(f"\ncontrol discrimination: {'PASS' if ok else 'FAIL'} "
          f"(dynamic must beat static by >=0.15)")
    outp = Path(__file__).parent / "analysis/dynamic_judge_result.json"
    outp.write_text(json.dumps(
        {"timeline": timeline, "dynamic": rd, "static": rst,
         "discriminates": ok}, indent=1))
    print(f"wrote {outp}")
    for r in rd.get("raw", [])[:2]:
        print("dyn:", r.get("fight_windows_tracked"),
              "| gap:", r.get("biggest_gap"))


if __name__ == "__main__":
    main()
