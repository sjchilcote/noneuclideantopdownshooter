"""tools/musicgen/gemini_listen.py

Thin, generic "have Gemini listen to an audio clip and answer a structured
question" helper. Reuses tools/playtest/audio_judge.py's key-loading,
wav->mp3 transcode, and cost-logging machinery (same OpenRouter model,
same cost_log.json) rather than reimplementing auth or billing tracking.

This module is deliberately NOT a copy of audio_judge's comparative judge
prompt -- it exposes a generic describe()/ask() call with a caller-supplied
prompt template, for musicgen's block-analysis and instrument/melody
judging use cases (Phase A/C of the musicgen mission).

Never swallows errors: a failed call after retries returns an explicit
{"error": ...} dict, never a silently-fabricated "pass".
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "playtest"))
import audio_judge  # noqa: E402  (reused: key loading, mp3 transcode, cost log)


def have_key() -> bool:
    return audio_judge.have_key()


def total_cost() -> float:
    return audio_judge.total_cost()


def ask(wav_path: Path, prompt: str, max_s: float = 32.0,
        attempts: int = 3, model: Optional[str] = None) -> dict:
    """Send one audio clip + a freeform text prompt to Gemini (via
    OpenRouter), expecting a strict-JSON response. Returns the parsed dict,
    or {"error": ...} on failure after retries -- never fabricates a
    passing/neutral result."""
    import tempfile
    model = model or audio_judge.MODEL
    last_err = None
    for attempt in range(attempts):
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                mp3_path = tmp / (wav_path.stem + ".mp3")
                audio_judge.to_mp3(wav_path, mp3_path, max_s=max_s)
                content = [
                    {"type": "text", "text": prompt},
                    audio_judge._audio_block(mp3_path),
                ]
                body = {
                    "model": model,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.2,
                }
                import urllib.request
                req = urllib.request.Request(
                    audio_judge.OPENROUTER_URL,
                    data=json.dumps(body).encode(),
                    headers={
                        "Authorization": f"Bearer {audio_judge.openrouter_key()}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=300) as resp:
                    payload = json.load(resp)
            usage = payload.get("usage", {})
            cost = float(usage.get("cost", 0.0) or 0.0)
            audio_judge._log_call(
                {"tool": "musicgen.gemini_listen", "model": model,
                 "prompt_tokens": usage.get("prompt_tokens"),
                 "completion_tokens": usage.get("completion_tokens")}, cost)
            txt = payload["choices"][0]["message"]["content"]
            return audio_judge._parse_json_response(txt)
        except Exception as e:  # noqa: BLE001 - retried below, surfaced if all fail
            last_err = e
            print(f"gemini_listen: attempt {attempt + 1}/{attempts} failed: {e}",
                  file=sys.stderr)
            if attempt < attempts - 1:
                time.sleep(8 * (attempt + 1))
    return {"error": f"{type(last_err).__name__}: {last_err}"}
