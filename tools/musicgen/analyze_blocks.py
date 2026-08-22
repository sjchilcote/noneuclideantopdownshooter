"""tools/musicgen/analyze_blocks.py

Phase A step 3: have Gemini listen to every 30s/5s-overlap block of the
inspiration album ("With the Machine, Against the Machine") and produce a
detailed, synthesis-ready breakdown per block. Writes one JSON file per
block plus a combined corpus JSON.

Usage:
    uv run python tools/musicgen/analyze_blocks.py \
        --blocks-manifest <scratchpad>/blocks_manifest.json \
        --out-dir <scratchpad>/block_analysis

The album audio itself is never committed -- only this script and its JSON
output (which contains no audio, just text analysis) belong in the repo.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_listen as gl  # noqa: E402

PROMPT_TEMPLATE = """You are a veteran game-audio composer and mix engineer \
doing close analytical listening on a 30-second block excerpted from a \
metal/orchestral-hybrid album ("With the Machine, Against the Machine") \
that is the primary sonic inspiration for a lo-fi industrial cosmic-horror \
top-down shooter (Teleglitch-adjacent).

Track: "{title}". This block starts at {offset:.1f}s into the track \
({abs_start:.1f}s into the full album).

Listen carefully and report a DETAILED, SYNTHESIS-READY breakdown -- \
precise enough that a sound designer could resynthesize each instrument \
from your description alone, without hearing the original. Avoid vague \
adjectives alone ("heavy", "epic") -- pair them with concrete descriptors: \
waveform character (saw/square/noise/distorted sine), filter movement, \
attack/decay shape, distortion/saturation type, pitch range, articulation.

Return STRICT JSON only, no markdown fences, matching exactly this schema:
{{
  "tempo_bpm": <number or null if not metrically clear>,
  "meter": "e.g. 4/4, 7/8, or 'not metrically pulsed'",
  "key_or_mode": "e.g. E phrygian, or 'atonal/noise-based'",
  "instrumentation": [
    {{"role": "e.g. rhythm guitar / lead synth / choir / bass / drums / drone",
      "timbre": "precise synthesis-ready timbre description",
      "register": "pitch range, e.g. low-mid, sub-bass, high lead",
      "articulation": "how notes are played: staccato chugs, legato swells, tremolo picking, etc."}}
  ],
  "rhythmic_patterns": {{
    "drums": "what the drums/percussion literally do, pattern description",
    "bass": "what the bass does rhythmically and melodically",
    "lead_or_harmony": "what the lead/harmony layer does"
  }},
  "intensity_level": "one of: dormant, low, building, high, peak, release",
  "structural_role": "e.g. intro, verse-equivalent, buildup, drop/climax, breakdown, outro",
  "change_from_previous_block": "what enters, exits, or changes vs. what you'd expect from the immediately preceding ~5s of overlap -- be specific about which instrument/layer",
  "notable_production": "mix/production details: distortion type, reverb space, panning, stereo width, any glitch/industrial texture",
  "summary": "2-3 sentence overview"
}}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks-manifest", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--only", type=str, default=None,
                     help="comma-separated block names to (re-)run")
    args = ap.parse_args()

    if not gl.have_key():
        print("ERROR: no OpenRouter key available.", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.blocks_manifest.read_text())
    only = set(n.strip() for n in args.only.split(",")) if args.only else None

    results = []
    for entry in manifest:
        name = entry["block"]
        if only and name not in only:
            continue
        out_path = args.out_dir / f"{name}.json"
        if out_path.exists() and not only:
            print(f"skip (exists): {name}")
            results.append(json.loads(out_path.read_text()))
            continue
        wav_path = args.blocks_manifest.parent / entry["path"]
        prompt = PROMPT_TEMPLATE.format(
            title=entry["title"], offset=entry["track_offset_s"],
            abs_start=entry["absolute_start_s"])
        print(f"analyzing {name} ...", end=" ", flush=True)
        resp = gl.ask(wav_path, prompt, max_s=32.0)
        record = {**entry, "analysis": resp}
        out_path.write_text(json.dumps(record, indent=2))
        results.append(record)
        if "error" in resp:
            print(f"ERROR: {resp['error']}")
        else:
            print(f"ok (intensity={resp.get('intensity_level')})")

    combined_path = args.out_dir / "_corpus.json"
    combined_path.write_text(json.dumps(results, indent=2))
    n_ok = sum(1 for r in results if "error" not in r.get("analysis", {}))
    n_err = len(results) - n_ok
    print(f"\ndone: {len(results)} blocks, {n_ok} ok, {n_err} errors")
    print(f"cumulative gemini_listen/audio_judge cost: ${gl.total_cost():.4f}")
    print(f"Wrote {combined_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
