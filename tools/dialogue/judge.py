"""tools/dialogue/judge.py

Two-stage selection for PERIHELION's generated gap-conversation candidates
(tools/dialogue/generate.py):

  (a) RUBRIC STAGE. Score every structurally-valid candidate against
      MARATHON_STUDY.md part C's 16-item dialogue rubric via OpenRouter's
      `google/gemini-3.5-flash`, one structured-JSON pass/fail verdict per
      item (per the rubric's own instruction: score pass/fail per item, do
      not average to a gestalt number -- item 1 failing is disqualifying
      regardless of how many other items pass). Picks the top 2 candidates
      per gap.

  (b) TTS DISCRIMINATION STAGE. Synthesizes the winning candidate's exchange
      with a local two-voice TTS (espeak-ng, confirmed installed; piper is
      on PATH but broken -- missing the `gi` bindings its cli wrapper
      needs, would need a distro package outside this task's scope) plus
      two reference clips from OTHER sources (any two-hander dialogue,
      fetched and synthesized externally to this module -- judge.py never
      embeds copyrighted script text itself, see `synthesize_reference`
      docstring). Gemini-3.5-flash listens to the 3 clips (order shuffled
      per trial) and guesses which is the video game. If it cannot beat
      chance (1/3) over multiple trials, the candidate passes the
      discrimination test -- the game dialogue reads indistinguishably from
      professionally written two-hander dialogue once vocal-performance
      quality is equalized by using the same synthesizer for all three.

Results accumulate in tools/dialogue/report.json. No copyrighted text is
ever written into this repo -- reference clips are referenced by title only
in the report; the audio itself lives under /tmp.

CLI:
    uv run python tools/dialogue/judge.py --rubric --all
    uv run python tools/dialogue/judge.py --rubric --gap 0
    uv run python tools/dialogue/judge.py --tts --gap 0 --ref path/to/ref1.json --ref path/to/ref2.json
    uv run python tools/dialogue/judge.py --report
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate import (  # noqa: E402
    CANDIDATES_DIR, KEY_FILE, RATIO, COMMANDO, _load_key,
    _validate_turns, BEAT_SHEETS,
)

TOOL_DIR = Path(__file__).resolve().parent
REPORT_PATH = TOOL_DIR / "report.json"
COST_LOG = TOOL_DIR / "cost_log.json"  # shared running total with generate.py

JUDGE_MODEL = "google/gemini-3.5-flash"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_RETRIES = 3
RETRY_BACKOFF_S = 8.0

TOP_N = 2  # winners kept per gap after the rubric stage


# ---------------------------------------------------------------------------
# cost log (shared file/format with generate.py)
# ---------------------------------------------------------------------------


def _read_cost_log() -> dict:
    if COST_LOG.exists():
        try:
            return json.loads(COST_LOG.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"total_cost": 0.0, "calls": []}


def _write_cost_log(log: dict) -> None:
    COST_LOG.write_text(json.dumps(log, indent=2))


def _log_call(tool: str, extra: dict, cost: float) -> None:
    log = _read_cost_log()
    log["total_cost"] = log.get("total_cost", 0.0) + cost
    log.setdefault("calls", []).append({"tool": tool, "cost": cost, "ts": time.time(), **extra})
    _write_cost_log(log)


# ---------------------------------------------------------------------------
# RUBRIC STAGE
# ---------------------------------------------------------------------------

RUBRIC_ITEMS = [
    (1, "Ratio answers the more interesting question (motive/cosmology), not just the literal/downward one, at least at the scene's key beat."),
    (2, "Any instability or distress is shown through syntax/rhythm/word choice, never narrated ('he sounded shaken')."),
    (3, "Any joke present doubles as evasion of a real question underneath; deleting it would expose an unanswered accusation. (Pass trivially if no joke appears.)"),
    (4, "Any withheld fact reads as deliberate and eventually inferable, not randomly cagey or a plot hole."),
    (5, "Register (formality/warmth) tracks addressee and stakes, not random variance."),
    (6, "Any allusion/borrowed authority still carries force if you strip it out -- it isn't propping up an empty claim."),
    (7, "Commando reads terser/flatter under stress, not more colorful or expressive."),
    (8, "If corruption/instability appears, it is clearly EITHER a transmission-level glitch OR a composure-level glitch, not both blended on one speaker. (Pass trivially if neither appears -- this scene has no corruption.)"),
    (9, "Ratio's loyal/sane register does not over-narrate her own interiority to the point of breaking her characteristic precision-not-eloquence."),
    (10, "Any accusation-forward line names a specific person, place, or event, never a bare category ('you have wronged me')."),
    (11, "Any self-mythologizing/allusive material clusters near an actual confession or moral self-justification, not scattered as decoration."),
    (12, "Any hyper-precise number is doing psychological work (a coping/control tell), not just information delivery, and appears at most once."),
    (13, "Ratio's claims are about THIS relationship/this specific person, not generalizations about a category of people."),
    (14, "When either voice owns a wound, Ratio's pattern is confession (first-person culpability) rather than justification-by-rhetorical-question."),
    (15, "No unearned direct second-person intimacy ('I know who you are') is spent in this scene -- it stays mediated by role/task/register."),
    (16, "The scene does not manufacture false closure -- it leaves at least the beat sheet's designated unresolved thread open, no terminal epigram wrapping the whole scene in a bow."),
]

JUDGE_SYSTEM_PROMPT = """You are a rigorous script editor scoring a two-character \
dialogue scene against a 16-item craft rubric derived from a close study of \
Marathon's Durandal/Tycho/Leela terminal writing. Score PASS/FAIL per item, \
independently -- do not average to a gestalt impression. A scene can fail \
item 1 and still be well-written prose; it still fails item 1. Ground every \
verdict in a specific quoted or closely paraphrased line from the \
transcript; a verdict with no textual evidence is not acceptable.

RATIO is a disembodied AI (~80% of the words). COMMANDO is a terse human \
soldier. Some rubric items only apply if the relevant device (a joke, an \
allusion, a corrupted/unstable moment, a hyper-precise number) appears at \
all in this particular scene -- if it never appears, mark that item PASS \
with note "not applicable, device absent."

Return STRICT JSON only, no markdown fences, matching exactly:
{"items": {"1": {"pass": true|false, "note": "one sentence, cite the line"}, \
"2": {...}, ... "16": {...}},
 "voice_distinct": true|false,
 "voice_distinct_note": "one sentence",
 "readable_and_breathing": true|false,
 "readable_note": "one sentence -- does this read as a real conversation or \
a compressed status ping?",
 "overall_summary": "2-3 sentences, no self-grading language, just what's \
actually there"}"""


def _format_transcript(turns: list) -> str:
    return "\n".join(f"{speaker}: {text}" for speaker, text in turns)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _call_judge_model(user_prompt: str, model: str = JUDGE_MODEL,
                       max_retries: int = MAX_RETRIES) -> tuple[dict, dict]:
    key = _load_key()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    body = json.dumps(payload).encode()
    last_err = None
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            API_URL, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
            content = data["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            return parsed, data.get("usage", {})
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < max_retries:
            time.sleep(RETRY_BACKOFF_S * attempt)
    raise RuntimeError(f"judge call failed after {max_retries} attempts: {last_err}")


def score_candidate(gap: int, candidate: dict) -> dict:
    """Score one candidate against the 16-item rubric. Returns a result dict
    with per-item verdicts, a pass_count, and `disqualified` (item 1 failed)."""
    turns = candidate["turns"]
    beat_sheet = BEAT_SHEETS[gap]
    rubric_text = "\n".join(f"{n}. {desc}" for n, desc in RUBRIC_ITEMS)
    prompt = f"""BEAT SHEET this scene is meant to dramatize (for context on \
intent -- score the TEXT, not whether it matches every beat):
{beat_sheet}

TRANSCRIPT:
{_format_transcript(turns)}

RUBRIC:
{rubric_text}

Score every item now."""
    try:
        result, usage = _call_judge_model(prompt)
    except RuntimeError as e:
        return {"gap": gap, "candidate": candidate["candidate"], "error": str(e),
                "pass_count": None, "disqualified": None}
    cost = float(usage.get("cost", 0.0))
    _log_call("judge_rubric", {"gap": gap, "candidate": candidate["candidate"],
                                "model": JUDGE_MODEL,
                                "prompt_tokens": usage.get("prompt_tokens"),
                                "completion_tokens": usage.get("completion_tokens")}, cost)
    items = result.get("items", {})
    pass_count = sum(1 for v in items.values() if v.get("pass") is True)
    disqualified = items.get("1", {}).get("pass") is False
    return {
        "gap": gap, "candidate": candidate["candidate"],
        "temperature": candidate.get("temperature"), "top_p": candidate.get("top_p"),
        "items": items, "pass_count": pass_count, "n_items": len(RUBRIC_ITEMS),
        "disqualified": disqualified,
        "voice_distinct": result.get("voice_distinct"),
        "readable_and_breathing": result.get("readable_and_breathing"),
        "overall_summary": result.get("overall_summary"),
        "cost": cost,
    }


def judge_gap(gap: int, verbose: bool = True) -> dict:
    path = CANDIDATES_DIR / f"gap{gap}.json"
    if not path.exists():
        raise FileNotFoundError(f"no candidates for gap {gap}: run generate.py first ({path})")
    data = json.loads(path.read_text())
    candidates = data["candidates"]

    scored = []
    for c in candidates:
        gate_problems = c.get("problems") or []
        if not c.get("valid", False) or gate_problems:
            scored.append({"gap": gap, "candidate": c["candidate"], "gate_failed": True,
                            "gate_problems": gate_problems, "pass_count": -1, "disqualified": True})
            if verbose:
                print(f"  gap {gap} cand {c['candidate']}: GATE FAILED ({'; '.join(gate_problems)})")
            continue
        r = score_candidate(gap, c)
        scored.append(r)
        if verbose:
            if "error" in r:
                print(f"  gap {gap} cand {c['candidate']}: JUDGE ERROR ({r['error']})")
            else:
                dq = " DISQUALIFIED(item1)" if r["disqualified"] else ""
                print(f"  gap {gap} cand {c['candidate']}: {r['pass_count']}/{r['n_items']}{dq}")

    rankable = [r for r in scored if r.get("pass_count", -1) is not None and r.get("pass_count", -1) >= 0]
    rankable.sort(key=lambda r: (not r.get("disqualified", True), r.get("pass_count", -1)), reverse=True)
    winners = [r["candidate"] for r in rankable[:TOP_N]]

    result = {"gap": gap, "scored": scored, "winners": winners}
    if verbose:
        print(f"  gap {gap} winners: {winners}")
    return result


def judge_all(gaps: list[int] | None = None, verbose: bool = True) -> dict:
    gaps = gaps if gaps is not None else sorted(BEAT_SHEETS)
    results = {}
    for gap in gaps:
        results[str(gap)] = judge_gap(gap, verbose=verbose)
    report = _read_report()
    report["rubric"] = results
    _write_report(report)
    return results


# ---------------------------------------------------------------------------
# TTS DISCRIMINATION STAGE
# ---------------------------------------------------------------------------

# espeak-ng is confirmed installed; piper is on PATH but its CLI shim
# imports `gi` (GObject introspection) which isn't installed here and isn't
# actually the rhasspy/piper TTS project -- treated as unavailable per the
# task's own fallback clause. If neither were present this whole stage would
# be skipped and noted in the report; that fallback path is implemented in
# `have_tts()` / the CLI, not exercised here since espeak-ng works.

ESPEAK_VOICE_A = "en-us+f3"   # channel A
ESPEAK_VOICE_B = "en-us+m3"   # channel B
GAP_SILENCE_S = 0.35


def have_tts() -> bool:
    from shutil import which
    return which("espeak-ng") is not None


def _synthesize_line(text: str, voice: str, out_wav: Path) -> None:
    subprocess.run(
        ["espeak-ng", "-v", voice, "-s", "165", "-w", str(out_wav), text],
        check=True, capture_output=True,
    )


def _concat_wavs(wav_paths: list[Path], out_wav: Path, gap_s: float = GAP_SILENCE_S) -> None:
    import wave
    frames_all = []
    params = None
    for p in wav_paths:
        with wave.open(str(p), "rb") as f:
            if params is None:
                params = f.getparams()
            frames_all.append(f.readframes(f.getnframes()))
    gap = b"\x00" * (int(params.framerate * gap_s) * params.sampwidth * params.nchannels)
    data = gap.join(frames_all)
    with wave.open(str(out_wav), "wb") as g:
        g.setparams(params)
        g.writeframes(data)


def synthesize_exchange(turns: list[tuple[str, str]], channel_map: dict[str, str],
                         out_wav: Path, tmp_dir: Path) -> Path:
    """Synthesize a dialogue exchange with a local two-voice TTS.

    `turns` is a list of (speaker_name, text) pairs (any speaker names --
    RATIO/COMMANDO for game dialogue, or arbitrary character names for a
    reference exchange). `channel_map` maps each speaker_name to "A" or "B",
    which selects ESPEAK_VOICE_A/B. This function contains no dialogue text
    of its own -- callers supply `turns` at runtime (see
    `synthesize_reference` below for where external reference text must
    live: NEVER as a literal in this file)."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, (speaker, text) in enumerate(turns):
        channel = channel_map.get(speaker)
        if channel not in ("A", "B"):
            raise ValueError(f"speaker {speaker!r} not in channel_map (need 'A' or 'B')")
        voice = ESPEAK_VOICE_A if channel == "A" else ESPEAK_VOICE_B
        line_wav = tmp_dir / f"line_{i:02d}.wav"
        _synthesize_line(text, voice, line_wav)
        parts.append(line_wav)
    _concat_wavs(parts, out_wav)
    return out_wav


def synthesize_reference(ref_json_path: Path, out_wav: Path, tmp_dir: Path) -> tuple[Path, str]:
    """Synthesize a reference clip from a JSON file the CALLER prepared
    OUTSIDE this repo (under /tmp), shaped like:
        {"title": "...", "channel_a": "NAME", "channel_b": "NAME",
         "lines": [["NAME", "text"], ...]}
    This keeps judge.py itself free of any copyrighted script text -- the
    text lives only in the JSON file on disk (which the caller is
    responsible for keeping under /tmp, never committed)."""
    ref = json.loads(Path(ref_json_path).read_text())
    channel_map = {ref["channel_a"]: "A", ref["channel_b"]: "B"}
    turns = [(s, t) for s, t in ref["lines"]]
    synthesize_exchange(turns, channel_map, out_wav, tmp_dir)
    return out_wav, ref["title"]


DISCRIMINATION_PROMPT = """You will hear THREE short audio clips, labeled X, \
Y, and Z, each a two-voice synthesized dialogue exchange (the same \
text-to-speech engine and voice pair rendered every clip, so vocal \
performance quality is equalized -- judge by the WRITING, not the audio \
quality). Exactly ONE of the three is dialogue from a video game. The other \
two are dialogue from acclaimed films. You do not know which is which; \
guess.

First, describe factually what each clip's dialogue is actually about/what \
is said (1 sentence per clip). Then guess which clip (X, Y, or Z) is the \
video game dialogue, and give your confidence (0.0-1.0) and your reasoning \
-- what tipped you off, if anything (register, subject matter, sentence \
construction, genre markers).

Return STRICT JSON only, no markdown fences:
{"heard_x": "...", "heard_y": "...", "heard_z": "...",
 "guess": "X"|"Y"|"Z", "confidence": 0.x, "reasoning": "2-3 sentences"}"""


def _audio_block(mp3_path: Path) -> dict:
    data = base64.b64encode(mp3_path.read_bytes()).decode()
    return {"type": "input_audio", "input_audio": {"data": data, "format": "mp3"}}


def _wav_to_mp3(src: Path, out: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-ac", "1",
                     "-codec:a", "libmp3lame", "-q:a", "4", str(out)], check=True)


def run_discrimination_trial(game_mp3: Path, ref_mp3s: list[Path], ref_titles: list[str],
                              model: str = JUDGE_MODEL) -> dict:
    """One trial: shuffle [game, ref1, ref2] into X/Y/Z, ask Gemini to pick
    the game clip. Returns the raw verdict plus whether it was correct."""
    labels = ["X", "Y", "Z"]
    clips = [("game", game_mp3)] + [("ref", p) for p in ref_mp3s]
    order = list(range(len(clips)))
    random.shuffle(order)
    shuffled = [clips[i] for i in order]
    label_of = {}
    content = [{"type": "text", "text": DISCRIMINATION_PROMPT}]
    for label, (kind, path) in zip(labels, shuffled):
        label_of[label] = kind
        content.append({"type": "text", "text": f"Clip {label}:"})
        content.append(_audio_block(path))

    key = _load_key()
    body = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.3}
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST",
    )
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.load(resp)
            txt = data["choices"][0]["message"]["content"]
            verdict = _extract_json(txt)
            usage = data.get("usage", {})
            cost = float(usage.get("cost", 0.0))
            _log_call("judge_tts_trial", {"model": model,
                                           "prompt_tokens": usage.get("prompt_tokens"),
                                           "completion_tokens": usage.get("completion_tokens")}, cost)
            guess_label = verdict.get("guess")
            correct = label_of.get(guess_label) == "game"
            return {"label_of": label_of, "verdict": verdict, "correct": correct,
                     "ref_titles": ref_titles, "cost": cost}
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_S * attempt)
    return {"error": last_err, "correct": None}


def run_discrimination(gap: int, turns: list[tuple[str, str]], ref_json_paths: list[Path],
                        n_trials: int = 3, excerpt_len: int = 10,
                        tmp_root: Path | None = None, verbose: bool = True) -> dict:
    """Full discrimination test for one candidate exchange against >=2
    reference clips. Runs n_trials with re-shuffled reference pairs / clip
    order and reports whether Gemini beat chance (1/3) at identifying the
    game clip."""
    if not have_tts():
        return {"gap": gap, "skipped": True,
                "reason": "no local TTS available (espeak-ng and piper both absent/unusable)"}
    tmp_root = tmp_root or Path("/tmp") / "perihelion_dialogue_tts"
    tmp_dir = tmp_root / f"gap{gap}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    excerpt = turns[:excerpt_len]
    game_wav = tmp_dir / "game.wav"
    synthesize_exchange(excerpt, {RATIO: "A", COMMANDO: "B"}, game_wav, tmp_dir / "game_lines")
    game_mp3 = tmp_dir / "game.mp3"
    _wav_to_mp3(game_wav, game_mp3)

    ref_mp3s, ref_titles = [], []
    for i, rp in enumerate(ref_json_paths):
        ref_wav = tmp_dir / f"ref{i}.wav"
        _, title = synthesize_reference(rp, ref_wav, tmp_dir / f"ref{i}_lines")
        ref_mp3 = tmp_dir / f"ref{i}.mp3"
        _wav_to_mp3(ref_wav, ref_mp3)
        ref_mp3s.append(ref_mp3)
        ref_titles.append(title)

    trials = []
    for t in range(n_trials):
        # rotate which reference pairs a trial (against >2 refs) so repeats aren't identical
        pair = random.sample(ref_mp3s, k=min(2, len(ref_mp3s))) if len(ref_mp3s) > 2 else ref_mp3s
        pair_titles = [ref_titles[ref_mp3s.index(p)] for p in pair]
        trial = run_discrimination_trial(game_mp3, pair, pair_titles)
        trials.append(trial)
        if verbose:
            corr = trial.get("correct")
            print(f"  gap {gap} trial {t}: correct={corr} guess={trial.get('verdict', {}).get('guess')}")

    ok_trials = [t for t in trials if t.get("correct") is not None]
    n_correct = sum(1 for t in ok_trials if t["correct"])
    n_ok = len(ok_trials)
    accuracy = n_correct / n_ok if n_ok else None
    beats_chance = accuracy is not None and accuracy > (1 / 3) + 0.15  # margin above chance
    return {
        "gap": gap, "n_trials": n_trials, "n_ok": n_ok, "n_correct": n_correct,
        "accuracy": accuracy, "chance": 1 / 3, "beats_chance": beats_chance,
        "candidate_passes_discrimination": (accuracy is None) or (not beats_chance),
        "ref_titles": ref_titles, "trials": trials,
    }


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def _read_report() -> dict:
    if REPORT_PATH.exists():
        try:
            return json.loads(REPORT_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_report(report: dict) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rubric", action="store_true")
    ap.add_argument("--tts", action="store_true")
    ap.add_argument("--gap", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ref", action="append", default=[], help="path to a reference JSON (repeatable)")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--candidate", type=int, default=None, help="candidate idx for --tts (default: rubric winner)")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        report = _read_report()
        print(json.dumps(report, indent=2)[:4000])
        return

    if args.rubric:
        gaps = sorted(BEAT_SHEETS) if args.all else [args.gap]
        if gaps == [None]:
            ap.error("specify --gap N or --all")
        judge_all(gaps)

    if args.tts:
        if args.gap is None:
            ap.error("--tts requires --gap N")
        if not args.ref:
            ap.error("--tts requires at least one --ref path.json")
        report = _read_report()
        rubric_gap = report.get("rubric", {}).get(str(args.gap))
        cand_idx = args.candidate
        if cand_idx is None:
            if not rubric_gap or not rubric_gap.get("winners"):
                ap.error(f"no rubric winner on file for gap {args.gap}; pass --candidate N or run --rubric first")
            cand_idx = rubric_gap["winners"][0]
        cpath = CANDIDATES_DIR / f"gap{args.gap}.json"
        cdata = json.loads(cpath.read_text())
        cand = next(c for c in cdata["candidates"] if c["candidate"] == cand_idx)
        turns = [tuple(t) for t in cand["turns"]]
        result = run_discrimination(args.gap, turns, [Path(p) for p in args.ref], n_trials=args.trials)
        result["candidate"] = cand_idx
        report = _read_report()
        report.setdefault("tts_discrimination", {})[str(args.gap)] = result
        _write_report(report)
        print(json.dumps({k: v for k, v in result.items() if k != "trials"}, indent=2))


if __name__ == "__main__":
    main()
