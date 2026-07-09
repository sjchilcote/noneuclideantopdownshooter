"""tools/soundgen/verify_bank.py

Runs the full (or a subset of the) SFX bank through the Gemini judge
(tools/playtest/audio_judge.py) and writes tools/soundgen/verify_report.json.

Usage:
    uv run python tools/soundgen/verify_bank.py                # full bank
    uv run python tools/soundgen/verify_bank.py --only pistol_fire,dry_click
    uv run python tools/soundgen/verify_bank.py --n-passes 3

This script does not itself "fix" bad sounds -- that's a synthesis-code
change in bank.py made by whoever is iterating. It just judges and reports,
so the same report file can be re-run/merged across iteration rounds.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "playtest"))
import bank  # noqa: E402
import audio_judge  # noqa: E402

REPORT_PATH = Path(__file__).resolve().parent / "verify_report.json"
CONTEXT = "lo-fi industrial cosmic-horror top-down shooter, Teleglitch-adjacent"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=str, default=None,
                     help="comma-separated sound names to (re-)judge; merges into existing report")
    ap.add_argument("--n-passes", type=int, default=2)
    ap.add_argument("--out", type=Path, default=REPORT_PATH)
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        print("ERROR: ffmpeg not found on PATH. Cannot run Gemini audio verification.",
              file=sys.stderr)
        print("Bank was still generated (see tools/soundgen/bank.py); "
              "no AI verification was performed.", file=sys.stderr)
        return 1

    if not audio_judge.have_key():
        print("ERROR: no OpenRouter API key available (checked OPENROUTER_API_KEY env, "
              "tools/playtest/.openrouter_key, ~/.config/autoclipping/openrouter_key, "
              "/home/login/Documents/youtube/autoclipping/.openrouter_key).", file=sys.stderr)
        print("Bank was still generated; no AI verification was performed.", file=sys.stderr)
        return 1

    only = set(n.strip() for n in args.only.split(",")) if args.only else None

    print(f"Judging {'subset ' + args.only if only else 'full bank'} "
          f"with {MODEL_NAME()} ({args.n_passes} pass(es)/sound)...")
    report = audio_judge.judge_bank(bank.MANIFEST, n_passes=args.n_passes, context=CONTEXT, only=only)

    if only and args.out.exists():
        prev = json.loads(args.out.read_text())
        prev_results = {r["name"]: r for r in prev.get("results", [])}
        for r in report["results"]:
            prev_results[r["name"]] = r
        merged_results = list(prev_results.values())
        ok = [r for r in merged_results if r["p_shippable"] is not None]
        report = {
            "model": report["model"],
            "context": report["context"],
            "n_sounds": len(merged_results),
            "n_ok": len(ok),
            "n_error": len(merged_results) - len(ok),
            "avg_p_shippable": (sum(r["p_shippable"] for r in ok) / len(ok)) if ok else None,
            "min_p_shippable": min((r["p_shippable"] for r in ok), default=None),
            "results": merged_results,
        }

    args.out.write_text(json.dumps(report, indent=2))

    print()
    print(f"n_sounds={report['n_sounds']} n_ok={report['n_ok']} n_error={report['n_error']}")
    avg = report["avg_p_shippable"]
    mn = report["min_p_shippable"]
    print(f"avg_p_shippable={avg:.3f}" if avg is not None else "avg_p_shippable=N/A")
    print(f"min_p_shippable={mn:.3f}" if mn is not None else "min_p_shippable=N/A")

    worst = sorted(
        (r for r in report["results"] if r["p_shippable"] is not None),
        key=lambda r: r["p_shippable"],
    )[:8]
    if worst:
        print("\nworst sounds:")
        for r in worst:
            print(f"  {r['name']:22s} p_shippable={r['p_shippable']:.2f} "
                  f"matches_spec={r['matches_spec']}  tells={r['amateur_tells']}")

    errored = [r for r in report["results"] if r["p_shippable"] is None]
    if errored:
        print("\nsounds with judge ERRORS (never silently treated as passing):")
        for r in errored:
            print(f"  {r['name']:22s} errors={r['errors']}")

    print(f"\nWrote {args.out}")
    return 0


def MODEL_NAME() -> str:
    return audio_judge.MODEL


if __name__ == "__main__":
    raise SystemExit(main())
