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

ANCHORED_PROMPT_TEMPLATE = """You are a veteran game sound designer doing a \
calibrated listening review.

Game context: {context}

You will hear TWO clips.

Clip A is a sound that already SHIPPED in this exact game -- by definition it \
is shippable-at-this-game's-aesthetic quality. It calibrates the bar: lo-fi, \
gritty, analog-industrial dread. A and B are DIFFERENT kinds of sounds; A \
calibrates craft and aesthetic fit, not identity.

Clip B is the candidate under review. Its intended spec: {spec}
{repeat_note}
First describe factually what you hear in each clip: events, attack, \
frequency balance, texture, decay. Then, using Clip A as your calibration of \
"shippable for this game", judge Clip B against ITS OWN spec.

p_shippable = P(the designer who shipped A would also ship B for B's spec). \
Use the full range: 0.9+ craft comparable to A; 0.6 usable with minor tweaks; \
0.4 wrong in one important way; below 0.2 severe audible artifacts or reads \
as a different sound entirely.

Report a flaw ONLY if it is present in your own description of Clip B.

Return STRICT JSON only, no markdown code fences, matching exactly this \
schema:
{{"heard_a": "1-2 factual sentences",
  "heard_b": "2-3 factual sentences",
  "matches_spec": true|false,
  "p_shippable": 0.x,
  "better_or_worse": "B clearly worse | comparable craft | B better",
  "amateur_tells": ["only flaws actually audible in clip B"],
  "summary": "2-3 sentences"}}"""

REPEAT_NOTE = """
Note: any clip that is a short one-shot has been repeated FOUR times with \
~350ms gaps so you can hear it clearly ({which}). Judge the single effect, \
not the repetition pattern.
"""

PROMPT_TEMPLATE = """You are a veteran game sound designer doing a listening review.

Game context: {context}

FIRST, listen and describe what you actually hear in this clip, factually: \
number of events, attack character (sharp/soft), frequency balance \
(sub/low/mid/high), texture (noisy/tonal/metallic/organic), how it decays, \
and any artifacts you are certain you heard.

THEN judge it against the intended spec for this sound: {spec}

The game's aesthetic is lo-fi, gritty, analog-industrial dread; sounds should \
feel physical and heavy. A great sound here reads instantly as the physical \
event in the spec, sits dark and weighty, and ends naturally.

Rate p_shippable = P(a professional sound designer would ship this clip for \
that spec in this game). Use the full range: 0.9+ ready as-is; 0.6 usable \
with minor tweaks; 0.4 wrong in one important way; below 0.2 reads as a \
different sound entirely or has severe audible artifacts.

Report a flaw ONLY if it is present in your own description above -- if the \
clip decays cleanly do not report a click; if the low end is strong do not \
report thinness. It is fine to report no flaws.

Return STRICT JSON only, no markdown code fences, matching exactly this \
schema:
{{"heard": "2-3 factual sentences describing the audio",
  "matches_spec": true|false,
  "p_shippable": 0.x,
  "amateur_tells": ["only flaws actually audible in this clip"],
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

def _wav_duration_s(path: Path) -> float:
    import wave
    with wave.open(str(path), "rb") as f:
        return f.getnframes() / f.getframerate()


REPEAT_UNDER_S = 0.6
REPEAT_TIMES = 4
REPEAT_GAP_S = 0.35


def _repeat_wav(src: Path, out: Path, times: int = REPEAT_TIMES,
                gap_s: float = REPEAT_GAP_S) -> None:
    """Write `out` = `src` repeated `times` times with silent gaps (stdlib
    wave only). Used so ultra-short one-shots give the judge enough audio."""
    import wave
    with wave.open(str(src), "rb") as f:
        params = f.getparams()
        frames = f.readframes(f.getnframes())
    gap = b"\x00" * (int(params.framerate * gap_s) * params.sampwidth * params.nchannels)
    data = gap.join([frames] * times) if times > 1 else frames
    with wave.open(str(out), "wb") as g:
        g.setparams(params)
        g.writeframes(data)


def to_mp3(src: Path, out: Path, max_s: float = 50.0) -> None:
    _ensure_ffmpeg()
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn",
           "-t", str(max_s), "-ac", "1"]
    # If we're excerpting (source longer than max_s), fade the excerpt tail so
    # the judge doesn't penalize the measurement's own hard cut as an "abrupt
    # cutoff" in the asset (loopable drones never end in-game).
    try:
        src_dur = _wav_duration_s(src)
    except Exception:
        src_dur = None
    if src_dur is not None and src_dur > max_s:
        cmd += ["-af", f"afade=t=out:st={max_s - 1.0:.2f}:d=1.0"]
    cmd += ["-codec:a", "libmp3lame", "-q:a", "2", str(out)]
    subprocess.run(cmd, check=True)


def _audio_block(mp3_path: Path) -> dict:
    data = base64.b64encode(mp3_path.read_bytes()).decode()
    return {"type": "input_audio", "input_audio": {"data": data, "format": "mp3"}}


def _parse_json_response(txt: str) -> dict:
    txt = txt.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        txt = txt[4:] if txt.startswith("json") else txt
    return json.loads(txt)


def _ask(mp3_path: Path, spec: str, context: str,
         anchor_mp3: Optional[Path] = None,
         repeated_which: Optional[str] = None) -> dict:
    if anchor_mp3 is not None:
        repeat_note = REPEAT_NOTE.format(which=repeated_which) if repeated_which else ""
        prompt = ANCHORED_PROMPT_TEMPLATE.format(context=context, spec=spec,
                                                 repeat_note=repeat_note)
        content = [
            {"type": "text", "text": prompt},
            {"type": "text", "text": "Clip A (the shipped calibration anchor):"},
            _audio_block(anchor_mp3),
            {"type": "text", "text": "Clip B (the candidate under review):"},
            _audio_block(mp3_path),
        ]
    else:
        prompt = PROMPT_TEMPLATE.format(context=context, spec=spec)
        content = [
            {"type": "text", "text": prompt},
            _audio_block(mp3_path),
        ]
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
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


def _ask_with_retry(mp3_path: Path, spec: str, context: str, attempts: int = 3,
                    anchor_mp3: Optional[Path] = None,
                    repeated_which: Optional[str] = None) -> dict:
    """3-attempt retry with linear backoff (8s * attempt_number), matching the
    autoclipping recipe. On final failure, returns an explicit error dict --
    never silently fabricates a passing judgement."""
    last_err: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            return _ask(mp3_path, spec, context, anchor_mp3=anchor_mp3,
                        repeated_which=repeated_which)
        except Exception as e:  # noqa: BLE001 - deliberately broad, see docstring
            last_err = e
            print(f"audio_judge: attempt {attempt + 1}/{attempts} failed: {e}", file=sys.stderr)
            if attempt < attempts - 1:
                time.sleep(8 * (attempt + 1))
    return {"error": f"{type(last_err).__name__}: {last_err}"}


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def _prep_clip(wav_path: Path, tmp_dir: Path, max_s: float,
               tag: str = "judge") -> tuple[Path, bool]:
    """Transcode a wav for judging; short one-shots (<REPEAT_UNDER_S) are
    repeated 4x with gaps first. Returns (mp3_path, was_repeated)."""
    dur = _wav_duration_s(wav_path)
    repeated = dur < REPEAT_UNDER_S
    src = wav_path
    if repeated:
        rep_wav = tmp_dir / f"{wav_path.stem}_{tag}_x{REPEAT_TIMES}.wav"
        _repeat_wav(wav_path, rep_wav)
        src = rep_wav
    mp3_path = tmp_dir / f"{wav_path.stem}_{tag}.mp3"
    to_mp3(src, mp3_path, max_s=max_s)
    return mp3_path, repeated


def judge(wav_path, spec: str, n_passes: int = 2, context: Optional[str] = None,
          max_s: float = 50.0, tmp_dir: Optional[Path] = None,
          anchor_path=None, anchor_max_s: float = 15.0) -> dict:
    """Judge a single wav file against `spec`, averaging over n_passes
    independent Gemini calls to reduce single-call noise.

    If `anchor_path` is given, uses the anchored/comparative prompt: the
    anchor (a shipped-quality sound from this bank) is sent as Clip A to
    calibrate the model's notion of 'shippable', the candidate as Clip B.
    Clips shorter than REPEAT_UNDER_S are repeated 4x with 350ms gaps."""
    wav_path = Path(wav_path)
    context = context or DEFAULT_CONTEXT
    tmp_dir = Path(tmp_dir) if tmp_dir else Path(tempfile.gettempdir())
    tmp_dir.mkdir(parents=True, exist_ok=True)
    mp3_path, cand_repeated = _prep_clip(wav_path, tmp_dir, max_s)

    anchor_mp3 = None
    repeated_which = None
    if anchor_path is not None:
        anchor_path = Path(anchor_path)
        anchor_mp3, anchor_repeated = _prep_clip(anchor_path, tmp_dir,
                                                 anchor_max_s, tag="anchor")
        which = []
        if anchor_repeated:
            which.append("Clip A")
        if cand_repeated:
            which.append("Clip B")
        repeated_which = " and ".join(which) if which else None

    passes = [_ask_with_retry(mp3_path, spec, context, anchor_mp3=anchor_mp3,
                              repeated_which=repeated_which)
              for _ in range(n_passes)]
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

    result = {
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
    if anchor_path is not None:
        result["anchored"] = True
        result["anchor"] = Path(anchor_path).stem
        result["better_or_worse"] = [p.get("better_or_worse") for p in ok_passes]
    return result


def judge_bank(manifest, n_passes: int = 2, context: Optional[str] = None,
               max_s_default: float = 50.0, max_s_drone: float = 15.0,
               only: Optional[set] = None, repo_root: Optional[Path] = None,
               verbose: bool = True, anchor_resolver=None) -> dict:
    """Judge every entry in `manifest` (list of dicts with at least name/spec/
    path[/category]). Drones are judged on a `max_s_drone`-second excerpt to
    control cost. `anchor_resolver(entry) -> wav path | None` enables the
    anchored/comparative mode per candidate."""
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    context = context or DEFAULT_CONTEXT
    results = []
    for entry in manifest:
        if only is not None and entry["name"] not in only:
            continue
        wav_path = repo_root / entry["path"]
        max_s = max_s_drone if entry.get("category") == "drone" else max_s_default
        anchor_path = anchor_resolver(entry) if anchor_resolver else None
        r = judge(wav_path, entry["spec"], n_passes=n_passes, context=context,
                  max_s=max_s, anchor_path=anchor_path)
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
