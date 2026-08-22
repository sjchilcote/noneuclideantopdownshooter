"""tools/musiccal/aux/build_heavy_probe.py — a small auxiliary level for the
CONTEMPT trash-vs-heavy sanity check ONLY (never used for the main
STALWART/CONTEMPT/PRAYER fit).

The full-density auxiliary batch (gauntlet_full_density.json, all 6
segments) gave the trash-vs-heavy comparison only 34 ticks of heavy-segment
(E/F) data out of 80 runs: at density=1.0 HumanBot dies at ~0% clear rate,
almost always somewhere in the EARLIER segments (B/A/C/D), so most runs
never reach E or F at all. This probe skips straight to E and F (still
chained by a real corridor+loot polygon, still full density) so every run
engages heavy content immediately instead of needing to survive four
segments first.

Run: uv run python tools/musiccal/aux/build_heavy_probe.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from perihelion.levels import LevelBuilder, save_level  # noqa: E402
from build_gauntlet import (SEGMENTS, add_corridor, add_segment,  # noqa: E402
                            HEAVY_KINDS, LEVEL_SEED, ROOT)

OUT = Path(__file__).resolve().parent / "gauntlet_heavy_probe.json"
META_OUT = Path(__file__).resolve().parent / "gauntlet_heavy_probe_meta.json"


def build() -> tuple[LevelBuilder, dict]:
    heavy_segments = [s for s in SEGMENTS if s["tag"] in ("E", "F")]
    assert len(heavy_segments) == 2

    b = LevelBuilder("HEAVY PROBE — CONTEMPT aux", tier=3, ambience="amb_drone_late")
    b.data["alert_hops"] = 2

    seg_results = []
    expected_connects = 0
    for i, seg in enumerate(heavy_segments):
        # build a full "keep everything" set for this segment specifically
        data = json.loads((ROOT / "levels" / f"{seg['src']}.json").read_text())
        polygons = data["polygons"]
        full_keep = set()
        for old_idx in seg["polygons"]:
            ents = [e for e in polygons[old_idx].get("entities", [])
                    if e["type"] in {"husk", "mite", "spitter", "brute",
                                     "shrieker", "warden", "flicker"}]
            for j in range(len(ents)):
                full_keep.add((i, old_idx, j))
        res = add_segment(b, seg, i * 20000.0, 0.0, full_keep, i)
        seg_results.append(res)
        expected_connects += res["n_connects"]

    start = add_corridor(b, 0, None, seg_results[0]["entry"])
    expected_connects += start["n_connects"]
    b.player(start["first_polygon"], start["first_pos"])

    mid = add_corridor(b, 1, seg_results[0]["exit"], seg_results[1]["entry"])
    expected_connects += mid["n_connects"]

    end = add_corridor(b, 2, seg_results[1]["exit"], None)
    expected_connects += end["n_connects"]
    b.exit(end["last_polygon"], end["last_pos"])

    b.intro("HEAVY PROBE — auxiliary CONTEMPT trash-vs-heavy data only.")

    zones: dict[int, dict] = {}
    for s, r in zip(heavy_segments, seg_results):
        is_heavy = bool(set(r["kinds_present"]) & HEAVY_KINDS)
        for polygon in r["polygons"]:
            zones[polygon] = dict(zone="combat", segment=s["tag"],
                               kinds_present=r["kinds_present"], is_heavy=is_heavy)
    for ci, c in enumerate((start, mid, end)):
        for polygon in c["polygons"]:
            zones[polygon] = dict(zone="loot" if polygon == c["loot_polygon"] else "corridor",
                               corridor_idx=ci)

    stats = dict(density=1.0, total_enemies=sum(r["n_enemies"] for r in seg_results),
                per_segment={s["tag"]: r["n_enemies"]
                             for s, r in zip(heavy_segments, seg_results)},
                expected_connects=expected_connects, n_polygons=len(b.data["polygons"]),
                zones=zones, player_polygon=start["first_polygon"], exit_polygon=end["last_polygon"])
    return b, stats


def main() -> int:
    b, stats = build()
    final = b.to_dict()
    actual = len(final["connects"])
    if actual != stats["expected_connects"]:
        raise RuntimeError(f"connects mismatch: expected {stats['expected_connects']} got {actual}")
    lvl = b.build()
    save_level(final, OUT)
    meta = dict(density=stats["density"], total_enemies=stats["total_enemies"],
               per_segment=stats["per_segment"], n_polygons=stats["n_polygons"],
               player_polygon=stats["player_polygon"], exit_polygon=stats["exit_polygon"],
               level_path=str(OUT.relative_to(ROOT)),
               zones={str(k): v for k, v in stats["zones"].items()})
    META_OUT.write_text(json.dumps(meta, indent=1))
    print(f"{OUT}: {lvl.name!r} polygons={len(lvl.polygon_verts)} enemies={stats['total_enemies']}")
    print(f"  per_segment={stats['per_segment']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
