"""consult_night — GPT Sol consults: bot improvement + music elevation.

Director 2026-07-17 (overnight): "feed a bunch of data to GPT Sol
Ultra through openrouter - use the existing, working GPT consult
scripts... give it ALL information that could possibly be relevant -
and take everything it says with a grain of salt."

Two consults, each with maximal context, via consult_machinery's
streaming engine (crash-safe to disk):

    uv run python tools/musicgen/consult_night.py bot
    uv run python tools/musicgen/consult_night.py music
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import consult_machinery as cm

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "consults"
MODEL_CANDIDATES = [cm.DEFAULT_MODEL]   # "Sol Ultra" does not exist
#   on OpenRouter (probed /models: gpt-5.6-sol, -sol-pro); sol-pro is
#   the top Sol tier and the existing scripts' default

FINDINGS = (ROOT / "out/consults/night_findings.md")


def _block(title: str, path: Path, max_chars: int = 120_000) -> str:
    txt = path.read_text()[:max_chars]
    return f"\n\n===== {title} ({path.name}) =====\n{txt}"


def build_bot_prompt() -> str:
    p = ["You are consulting on a game-playing bot for PERIHELION, a "
         "non-euclidean top-down shooter (custom engine, portal-connected "
         "polygon polygons, 60Hz lockstep sim). The bot must play like a "
         "COMPETENT HUMAN (marketing videos), not a perfect machine. "
         "It currently clears ~0/850 runs of a 4-boss gauntlet whose "
         "bosses were tuned to ~90% fail each; the designer believes "
         "fixing its 'stupid mistakes' would make it beat the "
         "gauntlet frequently. Give concrete, implementable "
         "improvements ranked by expected survival gain, respecting "
         "the look-human constraint and these hard-won lessons: "
         "closest-enemy-wins fire policy is designer law and beat a "
         "heavy-priority override in farm tests; every change must "
         "win a k>=60 zone-survival farm comparison before adoption."]
    p.append(_block("BOT SOURCE", ROOT / "game/perihelion/testkit/humanbot.py"))
    d = ROOT / "BOT_REALISM_DESIGN.md"
    if d.exists():
        p.append(_block("REALISM DESIGN DOC", d))
    p.append(_block("GAUNTLET + INCIDENT FINDINGS", FINDINGS))
    p.append("\n\nDeliverable: (1) top-8 concrete behavior changes, "
             "each with the specific trigger condition, action, and "
             "which measured incident class it addresses; (2) which "
             "THREE you'd implement first for maximum survival gain "
             "and why; (3) any measurement you'd add to the farm "
             "harness to catch regressions the zone-survival numbers "
             "miss.")
    return "".join(p)


def build_music_prompt() -> str:
    p = ["You are consulting on a dynamic music system for PERIHELION "
         "(industrial metal + Gregorian chant; inspired by 'With the "
         "Machine, Against the Machine'). The DESIGN is considered "
         "excellent by the director ('up there with the best I've "
         "ever heard' structurally); the ask is: how to take it to "
         "the NEXT LEVEL musically and systemically. Constraints: "
         "chunk-queue engine (bar-quantized decisions), causal (no "
         "future knowledge except self-scheduled events), all "
         "material derived from one chant melody per track, laws "
         "below are director-ratified and non-negotiable."]
    p.append(_block("DESIGN DOC (all laws + provenance)", ROOT / "MUSIC_DESIGN.md"))
    # engine source truncated: the full prompt (~25.5k tokens) drew
    # three provider 500s while the bot prompt (~18.8k) succeeded --
    # size-specific; the design doc carries the laws regardless
    p.append(_block("ENGINE SOURCE (truncated)", ROOT / "game/perihelion/music.py",
                    max_chars=40_000))
    p.append(_block("NIGHT FINDINGS (judged results, seam maps, open issues)", FINDINGS))
    p.append("\n\nDeliverable: (1) top-8 concrete ideas to elevate "
             "the musical result (composition, arrangement, mixing, "
             "engine behavior), each implementable in this "
             "architecture, each with how to VERIFY it (we A/B or "
             "rank everything with a blind judge); (2) any structural "
             "risk you see in the current laws; (3) what a rewrite "
             "should keep vs redo, given the design doc's known "
             "tensions section.")
    return "".join(p)


def main():
    import os
    which = sys.argv[1]
    out_dir = OUT / f"sol_{which}"
    out_dir.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        key_file = ROOT / ".openrouter_key"
        if key_file.exists():
            api_key = key_file.read_text().strip()
    if not api_key:
        raise SystemExit("no OpenRouter key available")
    prompt = build_bot_prompt() if which == "bot" else build_music_prompt()
    print(f"[consult] {which}: prompt ~{cm.tokenish_size(prompt)} tokens",
          flush=True)
    last_err = None
    for model in MODEL_CANDIDATES:
        try:
            rc = cm.stream_consult(
                prompt=prompt,
                api_key=api_key,
                model=model,
                effort="high",
                max_tokens=32_000,
                connect_timeout_s=30.0,
                out_dir=out_dir,
            )
            if rc != 0:
                raise RuntimeError(f"stream_consult rc={rc}")
            print(f"[consult] rc={rc} via {model} -> {out_dir}",
                  flush=True)
            return rc
        except Exception as exc:
            last_err = exc
            print(f"[consult] {model} failed: {exc}", flush=True)
    raise SystemExit(f"all models failed: {last_err}")


if __name__ == "__main__":
    main()
