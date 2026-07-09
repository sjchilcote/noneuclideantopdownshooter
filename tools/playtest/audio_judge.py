"""tools/playtest/audio_judge.py

Gemini-ears verification for procedurally generated SFX, via OpenRouter's
chat-completions endpoint (no google-genai / google-generativeai SDK).
Adapted from the johnny/autoclipping recipe (boot_critic.py + listen_check.py
+ audio_annotate.py key-loading logic).

    judge(wav_path, spec, n_passes=2) -> {p_shippable, matches_spec,
                                           amateur_tells, summary, ...}
    judge_bank(manifest, ...) -> report dict

Never swallows errors: a failed call after retries is recorded as an
explicit error entry (p_shippable=None, "errors": [...]) rather than a
silently-faked judgement.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

MODEL = "google/gemini-3.5-flash"  # OpenRouter model id
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_CONTEXT = "lo-fi industrial cosmic-horror top-down shooter, Teleglitch-adjacent"

PROMPT_TEMPLATE = """You are a veteran sound designer for video games, reviewing a \
procedurally generated sound effect before it ships.

Game context: {context}

Intended spec for this sound (what it is supposed to be/do): {spec}

Listen carefully and describe what you actually hear. Judge whether it \
matches the spec, and whether a professional sound designer would call it \
shippable for THIS specific game -- lo-fi, gritty, industrial, dread-heavy \
horror, NOT arcadey or chiptune. Call out any amateur tells: harsh \
aliasing/digital nastiness that isn't intentional, abrupt or clicky cutoffs, \
muddiness, flat/unconvincing dynamics, or sounding like a generic UI beep \
rather than the described real-world sound.

Return STRICT JSON only, no markdown code fences, matching exactly this \
schema:
{{"matches_spec": true|false,
  "p_shippable": 0.x,
  "amateur_tells": ["..."],
  "summary": "2-3 sentences"}}"""


# --------------------------------------------------------------------------
# key loading -- copied logic from autoclipping/audio_annotate.py:
# env var first, then a small list of fallback plaintext key files.
# NEVER print/log the key value itself.
# --------------------------------------------------------------------------

def openrouter_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k.strip()
    for p in (
        Path(__file__).parent / ".openrouter_key",
        Path.home() / ".config/autoclipping/openrouter_key",
        Path("/home/login/Documents/youtube/autoclipping/.openrouter_key"),
    ):
        if p.exists():
            return p.read_text().strip()
    raise RuntimeError(
        "no OpenRouter key found (checked OPENROUTER_API_KEY env var, "
        f"{Path(__file__).parent / '.openrouter_key'}, "
        "~/.config/autoclipping/openrouter_key, and "
        "/home/login/Documents/youtube/autoclipping/.openrouter_key)"
    )


def have_key() -> bool:
    try:
        openrouter_key()
        return True
    except RuntimeError:
        return False


def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH (checked via shutil.which) -- "
                            "required to transcode wav -> mono mp3 for the judge")


# --------------------------------------------------------------------------
# audio transcode + request plumbing
# --------------------------------------------------------------------------

def to_mp3(src: Path, out: Path, max_s: float = 50.0) -> None:
    _ensure_ffmpeg()
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn",
         "-t", str(max_s), "-ac", "1", "-codec:a", "libmp3lame", "-q:a", "2", str(out)],
        check=True,
    )


def _audio_block(mp3_path: Path) -> dict:
    data = base64.b64encode(mp3_path.read_bytes()).decode()
    return {"type": "input_audio", "input_audio": {"data": data, "format": "mp3"}}


def _parse_json_response(txt: str) -> dict:
    txt = txt.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        txt = txt[4:] if txt.startswith("json") else txt
    return json.loads(txt)


def _ask(mp3_path: Path, spec: str, context: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(context=context, spec=spec)
    body = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                _audio_block(mp3_path),
            ],
        }],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {openrouter_key()}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.load(resp)
    txt = payload["choices"][0]["message"]["content"]
    return _parse_json_response(txt)


def _ask_with_retry(mp3_path: Path, spec: str, context: str, attempts: int = 3) -> dict:
    """3-attempt retry with linear backoff (8s * attempt_number), matching the
    autoclipping recipe. On final failure, returns an explicit error dict --
    never silently fabricates a passing judgement."""
    last_err: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            return _ask(mp3_path, spec, context)
        except Exception as e:  # noqa: BLE001 - deliberately broad, see docstring
            last_err = e
            print(f"audio_judge: attempt {attempt + 1}/{attempts} failed: {e}", file=sys.stderr)
            if attempt < attempts - 1:
                time.sleep(8 * (attempt + 1))
    return {"error": f"{type(last_err).__name__}: {last_err}"}


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def judge(wav_path, spec: str, n_passes: int = 2, context: Optional[str] = None,
          max_s: float = 50.0, tmp_dir: Optional[Path] = None) -> dict:
    """Judge a single wav file against `spec`, averaging over n_passes
    independent Gemini calls to reduce single-call noise."""
    wav_path = Path(wav_path)
    context = context or DEFAULT_CONTEXT
    tmp_dir = Path(tmp_dir) if tmp_dir else Path(tempfile.gettempdir())
    tmp_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = tmp_dir / f"{wav_path.stem}_judge.mp3"
    to_mp3(wav_path, mp3_path, max_s=max_s)

    passes = [_ask_with_retry(mp3_path, spec, context) for _ in range(n_passes)]
    ok_passes = [p for p in passes if "error" not in p]
    err_passes = [p for p in passes if "error" in p]

    if ok_passes:
        p_shippable = sum(float(p.get("p_shippable", 0.0)) for p in ok_passes) / len(ok_passes)
        matches_spec = all(bool(p.get("matches_spec", False)) for p in ok_passes)
        tells: list[str] = []
        seen = set()
        for p in ok_passes:
            for t in p.get("amateur_tells", []) or []:
                if t not in seen:
                    seen.add(t)
                    tells.append(t)
        summary = " | ".join(p.get("summary", "") for p in ok_passes if p.get("summary"))
    else:
        p_shippable = None
        matches_spec = None
        tells = []
        summary = ""

    return {
        "name": wav_path.stem,
        "spec": spec,
        "p_shippable": p_shippable,
        "matches_spec": matches_spec,
        "amateur_tells": tells,
        "summary": summary,
        "n_passes": n_passes,
        "n_ok": len(ok_passes),
        "n_error": len(err_passes),
        "errors": [p["error"] for p in err_passes],
        "raw_passes": passes,
    }


def judge_bank(manifest, n_passes: int = 2, context: Optional[str] = None,
               max_s_default: float = 50.0, max_s_drone: float = 15.0,
               only: Optional[set] = None, repo_root: Optional[Path] = None,
               verbose: bool = True) -> dict:
    """Judge every entry in `manifest` (list of dicts with at least name/spec/
    path[/category]). Drones are judged on a `max_s_drone`-second excerpt to
    control cost."""
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    context = context or DEFAULT_CONTEXT
    results = []
    for entry in manifest:
        if only is not None and entry["name"] not in only:
            continue
        wav_path = repo_root / entry["path"]
        max_s = max_s_drone if entry.get("category") == "drone" else max_s_default
        r = judge(wav_path, entry["spec"], n_passes=n_passes, context=context, max_s=max_s)
        r["category"] = entry.get("category")
        results.append(r)
        if verbose:
            ps = r["p_shippable"]
            ps_str = f"{ps:.2f}" if ps is not None else "ERROR"
            ms = r["matches_spec"]
            print(f"  {entry['name']:22s} p_shippable={ps_str:6s} matches_spec={ms}")

    ok = [r for r in results if r["p_shippable"] is not None]
    avg = sum(r["p_shippable"] for r in ok) / len(ok) if ok else None
    return {
        "model": MODEL,
        "context": context,
        "n_sounds": len(results),
        "n_ok": len(ok),
        "n_error": len(results) - len(ok),
        "avg_p_shippable": avg,
        "min_p_shippable": min((r["p_shippable"] for r in ok), default=None),
        "results": results,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: audio_judge.py <wav_path> <spec text...>", file=sys.stderr)
        raise SystemExit(2)
    out = judge(Path(sys.argv[1]), " ".join(sys.argv[2:]), n_passes=1)
    print(json.dumps(out, indent=2))
