"""tools/musicgen/build_playbook.py

Phase A step 4: aggregate the per-block Gemini analyses (analyze_blocks.py
output) into a machine-readable playbook JSON + a human-readable
PLAYBOOK.md, following johnny's mod_census.py pattern: census real examples,
count what actually recurs, derive quantitative rules from the counts
rather than vibes.

Usage:
    uv run python tools/musicgen/build_playbook.py \
        --corpus <scratchpad>/block_analysis/_corpus.json \
        --out-json tools/musicgen/playbook.json \
        --out-md tools/musicgen/PLAYBOOK.md
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def _norm_role(role: str) -> str:
    role = role.lower()
    if "drum" in role or "kick" in role or "percussion" in role:
        return "drums"
    if "bass" in role:
        return "bass"
    if "lead" in role or "synth lead" in role:
        return "lead"
    if "guitar" in role:
        return "rhythm guitar"
    if "choir" in role or "vocal" in role or "chant" in role:
        return "choir/vocal"
    if "drone" in role or "pad" in role or "ambient" in role:
        return "drone/pad"
    return role


def build(corpus: list) -> dict:
    ok = [r for r in corpus if "error" not in r.get("analysis", {})]

    tempos = [r["analysis"]["tempo_bpm"] for r in ok
              if isinstance(r["analysis"].get("tempo_bpm"), (int, float))]
    meters = Counter(r["analysis"].get("meter", "?") for r in ok)
    keys = Counter(r["analysis"].get("key_or_mode", "?") for r in ok)
    intensities = Counter(r["analysis"].get("intensity_level", "?") for r in ok)
    structural_roles = Counter(r["analysis"].get("structural_role", "?") for r in ok)

    role_timbres: dict[str, list[str]] = defaultdict(list)
    role_articulations: dict[str, list[str]] = defaultdict(list)
    for r in ok:
        for inst in r["analysis"].get("instrumentation", []):
            role = _norm_role(inst.get("role", "?"))
            if inst.get("timbre"):
                role_timbres[role].append(inst["timbre"])
            if inst.get("articulation"):
                role_articulations[role].append(inst["articulation"])

    # by-track intensity arc (order blocks by track_offset_s)
    by_track: dict[str, list] = defaultdict(list)
    for r in ok:
        by_track[r["title"]].append(r)
    for t in by_track:
        by_track[t].sort(key=lambda r: r["track_offset_s"])
    intensity_arcs = {
        t: [b["analysis"].get("intensity_level") for b in blocks]
        for t, blocks in by_track.items()
    }

    changes = [r["analysis"].get("change_from_previous_block", "")
               for r in ok if r["analysis"].get("change_from_previous_block")]

    return {
        "n_blocks_analyzed": len(ok),
        "n_blocks_errored": len(corpus) - len(ok),
        "tempo_bpm": {
            "median": sorted(tempos)[len(tempos) // 2] if tempos else None,
            "min": min(tempos) if tempos else None,
            "max": max(tempos) if tempos else None,
            "n_samples": len(tempos),
        },
        "meter_histogram": dict(meters.most_common()),
        "key_mode_histogram": dict(keys.most_common(20)),
        "intensity_level_histogram": dict(intensities.most_common()),
        "structural_role_histogram": dict(structural_roles.most_common()),
        "instrument_palette": {
            role: {
                "n_mentions": len(timbres),
                "sample_timbre_descriptions": timbres[:6],
                "sample_articulations": role_articulations.get(role, [])[:6],
            }
            for role, timbres in sorted(role_timbres.items(),
                                         key=lambda kv: -len(kv[1]))
        },
        "intensity_arc_by_track": intensity_arcs,
        "sample_transition_descriptions": changes[:20],
    }


def render_markdown(pb: dict, corpus: list) -> str:
    lines = []
    lines.append("# The Playbook — \"With the Machine, Against the Machine\"\n")
    lines.append(f"Built from Gemini close-listening analysis of "
                 f"{pb['n_blocks_analyzed']} 30s/5s-overlap blocks "
                 f"({pb['n_blocks_errored']} errored) across the full album. "
                 "This is the album's vocabulary: recurring instrument "
                 "palette, rhythmic signatures, harmonic language, "
                 "intensity/layering grammar — meant to be synthesis-ready, "
                 "not just descriptive.\n")

    lines.append("## Tempo & grid\n")
    t = pb["tempo_bpm"]
    if t["median"]:
        lines.append(f"- Median tempo across {t['n_samples']} metrically-clear "
                     f"blocks: **{t['median']} BPM** (range {t['min']}-{t['max']}).")
    lines.append("- Meter distribution: " +
                 ", ".join(f"{k} ({v})" for k, v in pb["meter_histogram"].items()) + "\n")

    lines.append("## Harmonic language\n")
    lines.append("Key/mode distribution across blocks:\n")
    for k, v in list(pb["key_mode_histogram"].items())[:15]:
        lines.append(f"- {k}: {v} block(s)")
    lines.append("")

    lines.append("## Instrument palette (synthesis-ready)\n")
    lines.append("Recurring roles, ranked by how often they were called out, "
                 "with representative timbre descriptions pulled directly "
                 "from the block analyses (precise enough to resynthesize):\n")
    for role, data in pb["instrument_palette"].items():
        lines.append(f"### {role} ({data['n_mentions']} mentions)\n")
        for desc in data["sample_timbre_descriptions"]:
            lines.append(f"- {desc}")
        if data["sample_articulations"]:
            lines.append("\nArticulation patterns:")
            for a in data["sample_articulations"]:
                lines.append(f"- {a}")
        lines.append("")

    lines.append("## Intensity vocabulary\n")
    lines.append("Distribution of the intensity_level tag across all blocks:\n")
    for k, v in pb["intensity_level_histogram"].items():
        lines.append(f"- {k}: {v} block(s)")
    lines.append("")

    lines.append("## Structural roles\n")
    for k, v in pb["structural_role_histogram"].items():
        lines.append(f"- {k}: {v} block(s)")
    lines.append("")

    lines.append("## Intensity arcs per track\n")
    lines.append("Sequence of intensity_level across each track's blocks "
                 "(chronological) — shows how tension is built and released:\n")
    for track, arc in pb["intensity_arc_by_track"].items():
        lines.append(f"- **{track}**: {' -> '.join(arc)}")
    lines.append("")

    lines.append("## Layering grammar — what enters/exits between blocks\n")
    lines.append("Verbatim `change_from_previous_block` samples (what a "
                 "layer's entrance/exit sounds like in this album):\n")
    for c in pb["sample_transition_descriptions"]:
        lines.append(f"- {c}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()

    corpus = json.loads(args.corpus.read_text())
    pb = build(corpus)
    args.out_json.write_text(json.dumps(pb, indent=2))
    args.out_md.write_text(render_markdown(pb, corpus))
    print(f"Wrote {args.out_json} and {args.out_md}")
    print(f"n_blocks_analyzed={pb['n_blocks_analyzed']} "
          f"n_blocks_errored={pb['n_blocks_errored']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
