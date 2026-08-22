"""Detailed Gemini AV-sync check of a gameplay video with dynamic music.

    uv run python tools/musicgen/judge_video.py out/gauntlet_music_v1.mp4

Sends the actual video (base64) to pro-tier Gemini via OpenRouter and
demands a timeline-cited audit: does the MUSIC track the FIGHT?
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "playtest"))

MODEL = "google/gemini-3.1-pro-preview"

PROMPT = (
    "This is gameplay from a retro-futuristic cosmic-horror top-down "
    "shooter with a DYNAMIC music system: the score is supposed to track "
    "the fight — calm exploration gets sparse sacred ambience (drone, "
    "distant chant); enemies engaging brings in bassline cells (a "
    "different bass pattern per enemy type), a lead voice tied to the "
    "player's weapon, and at high threat a heavy industrial wall with "
    "drums; tension moments get a riser; hard escalations get a sting "
    "accent. Audit the sync IN DETAIL across the whole video. Answer as "
    "strict JSON with keys: "
    "timeline (array of {t: 'mm:ss', scene: what happens in gameplay, "
    "music: what the music does, synced: true/false, note}), "
    "sync_score (integer 1-10: does the music genuinely track the "
    "intensity and events of play?), "
    "music_standalone (integer 1-10: quality of the music itself), "
    "desyncs (array of strings: every moment where music and gameplay "
    "disagree, with timestamps), "
    "verdict (two sentences)."
)


def judge(path: str | Path) -> dict:
    import urllib.request
    import audio_judge
    data = base64.b64encode(Path(path).read_bytes()).decode()
    content = [
        {"type": "text", "text": PROMPT},
        {"type": "video_url",
         "video_url": {"url": f"data:video/mp4;base64,{data}"}},
    ]
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2}
    req = urllib.request.Request(
        audio_judge.OPENROUTER_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {audio_judge.openrouter_key()}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        payload = json.load(resp)
    usage = payload.get("usage", {})
    audio_judge._log_call(
        {"tool": "musicgen.judge_video", "model": MODEL,
         "prompt_tokens": usage.get("prompt_tokens"),
         "completion_tokens": usage.get("completion_tokens")},
        float(usage.get("cost", 0.0) or 0.0))
    txt = payload["choices"][0]["message"]["content"]
    return audio_judge._parse_json_response(txt)


if __name__ == "__main__":
    print(json.dumps(judge(sys.argv[1]), indent=1))
