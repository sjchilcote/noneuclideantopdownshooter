"""build_gauntlet3 — GAUNTLET III: tactical geometry, HP 100.

Director 2026-07-16: buff the player with GEOMETRY, not hit points —
"chokes and environmental hazards (safe-polygon turrets) to lure enemies
to, long open corridors to kite them through mowing them down,
non-euclidean double-backs the player can use to escape". Target 50%
bot pass at HP 100, no armor.

Chain per combat segment (six source arenas keep their polygons):

  ... -> KITE LANE (long+open: backpedal and mow; SENTRY ALCOVE with 2
  friendly sentries + ammo + medkit hangs off mid-lane as a lure/fallback;
  a NON-EUCLIDEAN DOUBLE-BACK portals the lane's far end to its start —
  flee "forward" and come out behind the chase) -> CHOKE (narrow
  antechamber funneling the arena spill) -> ARENA -> next lane ... -> EXIT

Population = the Gauntlet II spread discipline (all 7 kinds, depth
gradient, kind anti-packing, min separation) over ARENAS + LANES only;
chokes/alcoves/spawn stay clear. alert_hops=1. Texture provenance
carried directly from the segment copies.

    uv run python tools/musiccal/build_gauntlet3.py --n 180 --min-sep 90
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))
sys.path.insert(0, str(Path(__file__).parent))

from perihelion.levels import LevelBuilder             # noqa: E402
import build_gauntlet as BG                            # noqa: E402
from build_gauntlet import SEGMENTS, add_segment, LEVEL_SEED  # noqa: E402
from build_gauntlet2 import (DEPTH_MIN, KIND_SEP_MULT,        # noqa: E402
                             POLYGON_CAP, poly_area, point_in_poly,
                             dist_to_edges)
from build_gauntlet2 import MIX as MIX2                        # noqa: E402

# STALWART is boss music (director 2026-07-16): wardens live ONLY in
# boss polygons now, so stalwart>0.9 is geometrically impossible outside
# them (a spread warden pushed 0.916 in an open arena). Their spread
# share moves to brutes -- moved, never thinned.
MIX = dict(MIX2)
MIX["brute"] = MIX["brute"] + MIX.pop("warden")

LANE_LEN = 1050.0
LANE_W = 150.0
CHOKE_LEN = 120.0
CHOKE_W = 64.0
ALCOVE = 170.0
BAND_Y = 60000.0
BAND_SPACING = 3000.0
W_EDGE, E_EDGE = 0, 2      # rect edge indices (see add_corridor)


S_EDGE = 1                 # rect edge order: W, S, E, N (y-down)


def lane_with_alcove(b: LevelBuilder, idx: int) -> dict:
    """Three-piece kite lane A-B-C; alcove north of B; the impossible
    loop folds C's south edge onto A's south edge (flee forward, come
    out behind the chase)."""
    y = BAND_Y + idx * BAND_SPACING
    x0 = idx * 4000.0
    seg_len = LANE_LEN / 3
    A = b.rect(x0, y, seg_len, LANE_W,
               seed=LEVEL_SEED + 7000 + idx, kind="corridor")
    # middle piece = 90 | 170 | 90 so the alcove portal is 170<->170
    # (rigid — no scaled seams anywhere authored)
    m0 = x0 + seg_len
    b1 = b.rect(m0, y, 90, LANE_W,
                seed=LEVEL_SEED + 7010 + idx, kind="corridor")
    b2 = b.rect(m0 + 90, y, ALCOVE, LANE_W,
                seed=LEVEL_SEED + 7011 + idx, kind="corridor")
    b3 = b.rect(m0 + 90 + ALCOVE, y, seg_len - 90 - ALCOVE, LANE_W,
                seed=LEVEL_SEED + 7012 + idx, kind="corridor")
    Cc = b.rect(x0 + 2 * seg_len, y, seg_len, LANE_W,
                seed=LEVEL_SEED + 7020 + idx, kind="corridor")
    b.connect(A, E_EDGE, b1, W_EDGE)
    b.connect(b1, E_EDGE, b2, W_EDGE)
    b.connect(b2, E_EDGE, b3, W_EDGE)
    b.connect(b3, E_EDGE, Cc, W_EDGE)
    Bm = b2
    ax = m0 + 90
    alc = b.rect(ax, y - ALCOVE, ALCOVE, ALCOVE,
                 seed=LEVEL_SEED + 7100 + idx, kind="storage")
    b.connect(b2, 3, alc, 1)      # north edge 170 <-> alcove south 170
    seg = seg_len
    bmx = ax + ALCOVE / 2
    # NO sentries in the lane pieces (director 2026-07-16: "there needs
    # to be, like, 5x as much material between the safe polygons" -- with a
    # gun in every lane polygon, kiting-to-turrets was optimal everywhere.
    # The safe strongpoints per segment are the ALCOVE and the CHOKE
    # pair only; the lane itself is open ground you fight across).
    b.entity(A, "medkit", (x0 + seg * 0.3, y + LANE_W * 0.5))
    b.entity(Bm, "medkit", (bmx, y + LANE_W * 0.5))
    b.entity(Cc, "medkit", (x0 + 2 * seg + seg * 0.7, y + LANE_W * 0.5))
    b.entity(Bm, "ammo_9mm", (bmx - 30, y + LANE_W * 0.3))
    b.entity(Bm, "ammo_shell", (bmx + 30, y + LANE_W * 0.7))
    b.entity(Bm, "ammo_cell", (bmx, y + LANE_W * 0.65))
    # the alcove is the segment's ONE strong lure pocket now that the
    # lane pieces are gunless -- rare but genuinely strong (director:
    # kite-to-turrets stays a valid strat, just not free everywhere)
    b.entity(alc, "sentry", (ax + ALCOVE * 0.3, y - ALCOVE * 0.65))
    b.entity(alc, "sentry", (ax + ALCOVE * 0.7, y - ALCOVE * 0.65))
    b.entity(alc, "sentry", (ax + ALCOVE * 0.5, y - ALCOVE * 0.8))
    b.entity(alc, "medkit", (ax + ALCOVE * 0.5, y - ALCOVE * 0.35))
    b.entity(alc, "ammo_9mm", (ax + ALCOVE * 0.25, y - ALCOVE * 0.4))
    b.entity(alc, "ammo_shell", (ax + ALCOVE * 0.75, y - ALCOVE * 0.4))
    b.entity(alc, "ammo_cell", (ax + ALCOVE * 0.5, y - ALCOVE * 0.5))
    b.connect(Cc, S_EDGE, A, S_EDGE)      # the fold: 350<->350, rigid
    for r, rx in ((A, x0 + seg_len * 0.5), (b2, bmx),
                  (Cc, x0 + 2 * seg_len + seg_len * 0.5)):
        b.light(r, (rx, y + LANE_W / 2),
                color=(170, 185, 210), intensity=0.8, radius=240.0)
    b.light(alc, (ax + ALCOVE / 2, y - ALCOVE / 2),
            color=(120, 220, 150), intensity=1.0, radius=200.0)
    return dict(west_polygon=A, east_polygon=Cc, alc=alc,
                pieces=(A, b1, b2, b3, Cc))


def trapezoid(b: LevelBuilder, x0: float, yc: float, length: float,
              w_in: float, w_out: float, seed: int,
              kind: str = "corridor") -> tuple[int, int, int]:
    """Convex taper: west edge w_in, east edge w_out; the width change
    happens in the WALLS, both portals stay rigid (equal edge lengths).
    Returns (polygon, west_edge_idx, east_edge_idx)."""
    x1 = x0 + length
    verts = [(x0, yc - w_in / 2), (x0, yc + w_in / 2),
             (x1, yc + w_out / 2), (x1, yc - w_out / 2)]
    r = b.polygon(verts, detail_seed=seed, kind=kind)
    return r, 0, 2


def hourglass(b: LevelBuilder, x0: float, yc: float, length: float,
              w_in: float, w_out: float, waist: float, seed: int,
              kind: str = "corridor") -> tuple[int, int, int]:
    """Engine polygons are CONVEX: the pinch is TWO trapezoids whose shared
    portal IS the waist (waist<->waist, rigid). The choke is literally
    the doorway. Returns (west polygon used only for entry bookkeeping is
    not needed) -> (in_polygon, west_edge, out_polygon|east_edge packing):
    returns (in_polygon, in_west_edge, out_polygon, out_east_edge)."""
    half = length / 2
    r1, w1, e1 = trapezoid(b, x0, yc, half, w_in, waist, seed, kind)
    r2, w2, e2 = trapezoid(b, x0 + half, yc, half, waist, w_out,
                           seed + 1, kind)
    b.connect(r1, e1, r2, w2)
    return r1, w1, r2, e2


def choke(b: LevelBuilder, idx: int, w_in: float, w_out: float) -> tuple:
    yc = BAND_Y + idx * BAND_SPACING + LANE_W / 2
    x0 = idx * 4000.0 + LANE_LEN + 250.0
    r1, we, r2, ee = hourglass(b, x0, yc, CHOKE_LEN * 2, w_in, w_out,
                               CHOKE_W, LEVEL_SEED + 7200 + idx * 2)
    b.light(r1, (x0 + CHOKE_LEN * 0.5, yc),
            color=(210, 160, 130), intensity=0.9, radius=150.0)
    b.light(r2, (x0 + CHOKE_LEN * 1.5, yc),
            color=(210, 160, 130), intensity=0.9, radius=150.0)
    b.entity(r1, "sentry", (x0 + CHOKE_LEN * 0.45, yc - 14))
    b.entity(r1, "sentry", (x0 + CHOKE_LEN * 0.45, yc + 14))
    b.entity(r2, "sentry", (x0 + CHOKE_LEN * 1.55, yc))
    b.entity(r1, "medkit", (x0 + CHOKE_LEN * 0.3, yc))
    return r1, we, r2, ee


def populate(level: dict, spawn_free: set, n_total: int, min_sep: float,
             seed: int, margin: float = 22.0, boost: set | None = None,
             polygon_total_cap: int = 6):
    """Gauntlet II spread discipline + anti-clump: hard per-polygon total
    cap pushes the population OUT of the big arenas and into the lane
    stream (director's lever: spread more, never thin); lane polygons get
    a placement weight boost."""
    rng = random.Random(seed)
    polygons = level["polygons"]
    n_polygons = len(polygons)
    areas = [poly_area(r["verts"]) if i not in spawn_free else 0.0
             for i, r in enumerate(polygons)]
    if boost:
        for i in boost:
            areas[i] *= 0.25   # lanes are the PLAYER'S tool: a trickle
            #                    only — packed lanes defeat kiting
    polygon_totals = [0] * n_polygons
    counts = {k: int(n_total * f) for k, f in MIX.items()}
    while sum(counts.values()) < n_total:
        k = max(MIX, key=lambda q: n_total * MIX[q] - counts[q])
        counts[k] += 1
    pool = [k for k, c in counts.items() for _ in range(c)]
    rng.shuffle(pool)
    placed_pts = {i: [] for i in range(n_polygons)}
    kind_pts = {k: [] for k in MIX}
    kind_polygons = {i: {} for i in range(n_polygons)}
    placed = fails = 0
    # (tried pushing wardens to the back third, 2026-07-16: pass rate
    # went 6/20 -> 0/20 -- concentrating the heavies is strictly worse
    # than the Gauntlet-II spread; keep DEPTH_MIN as measured)
    for kind in pool:
        dmin = DEPTH_MIN.get(kind, 0.0)
        allowed = [i for i in range(n_polygons)
                   if areas[i] > 0 and i / max(1, n_polygons - 1) >= dmin]
        if not allowed:
            allowed = [i for i in range(n_polygons) if areas[i] > 0]
        aw = [areas[i] for i in allowed]
        sep_scale = 1.0
        ok = False
        for att in range(600):
            if att and att % 150 == 0:
                sep_scale *= 0.75          # relax, never drop (move,
                #                            don't thin — director)
            ri = rng.choices(allowed, weights=aw)[0]
            if polygon_totals[ri] >= polygon_total_cap:
                continue
            if kind_polygons[ri].get(kind, 0) >= POLYGON_CAP.get(kind, 99):
                continue
            vs = polygons[ri]["verts"]
            xs = [v[0] for v in vs]
            ys = [v[1] for v in vs]
            x = rng.uniform(min(xs), max(xs))
            yy = rng.uniform(min(ys), max(ys))
            if not point_in_poly(x, yy, vs):
                continue
            if dist_to_edges(x, yy, vs) < margin:
                continue
            if any(math.hypot(x - qx, yy - qy) < min_sep * sep_scale
                   for qx, qy in placed_pts[ri]):
                continue
            ksep = min_sep * KIND_SEP_MULT.get(kind, 1.0) * sep_scale
            if any(math.hypot(x - qx, yy - qy) < ksep
                   for qx, qy in kind_pts[kind]):
                continue
            # warden+brute arriving as one wave was the death signature
            # (23/13 of 20 deaths had them together): the heavies are
            # placed apart CROSS-kind too -- each is a fight, the pair
            # is an execution (move, don't thin)
            if kind in ("warden", "brute"):
                other = "brute" if kind == "warden" else "warden"
                if any(math.hypot(x - qx, yy - qy) < 500.0 * sep_scale
                       for qx, qy in kind_pts.get(other, ())):
                    continue
            polygons[ri]["entities"].append(dict(type=kind, pos=[x, yy]))
            placed_pts[ri].append((x, yy))
            kind_pts[kind].append((x, yy))
            kind_polygons[ri][kind] = kind_polygons[ri].get(kind, 0) + 1
            polygon_totals[ri] += 1
            placed += 1
            ok = True
            break
        if not ok:
            fails += 1
    return placed, fails, counts


def _edge_len_of(b: LevelBuilder, polygon: int, edge: int) -> float:
    vs = b.data["polygons"][polygon]["verts"]
    import math as _m
    x1, y1 = vs[edge % len(vs)]
    x2, y2 = vs[(edge + 1) % len(vs)]
    return _m.hypot(x2 - x1, y2 - y1)


def _rigidify(level: dict) -> int:
    """Force EVERY portal rigid (equal edge lengths -> pure isometry m9;
    director: 'get rid of all the scaling transforms'). The lane/choke/
    adapter chain is authored rigid; the residual mismatches live INSIDE
    the copied source arenas. Fix: stretch the shorter edge symmetrically
    about its midpoint to the longer length — only on a side whose
    neighboring edges carry no portal (so no other seam changes), and
    only if the polygon stays convex. Returns seams fixed; raises if any
    seam is left scaled."""
    polygons = level["polygons"]
    conns = level["connects"] + level.get("connects_x", [])

    def edge_vec(r, e):
        vs = polygons[r]["verts"]
        (x1, y1), (x2, y2) = vs[e], vs[(e + 1) % len(vs)]
        return x1, y1, x2, y2, math.hypot(x2 - x1, y2 - y1)

    portal_edges = set()
    for r1, e1, r2, e2 in conns:
        portal_edges.add((r1, e1))
        portal_edges.add((r2, e2))

    def convex(vs):
        n = len(vs)
        sign = 0.0
        for i in range(n):
            ax, ay = vs[i]
            bx, by = vs[(i + 1) % n]
            cx, cy = vs[(i + 2) % n]
            cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
            if abs(cr) < 1e-9:
                continue
            if sign == 0.0:
                sign = cr
            elif sign * cr < 0:
                return False
        return True

    def try_stretch(r, e, target):
        """Re-length edge e of polygon r to `target` by moving only
        endpoints whose OTHER edge is not a portal: symmetric when both
        neighbors are free, else slide the single free endpoint."""
        vs = polygons[r]["verts"]
        n = len(vs)
        start_free = (r, (e - 1) % n) not in portal_edges
        end_free = (r, (e + 1) % n) not in portal_edges
        if not (start_free or end_free):
            return False
        x1, y1, x2, y2, ln = edge_vec(r, e)
        ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
        new = [list(v) for v in vs]
        if start_free and end_free:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            new[e] = [mx - ux * target / 2, my - uy * target / 2]
            new[(e + 1) % n] = [mx + ux * target / 2,
                                my + uy * target / 2]
        elif start_free:      # slide the start vertex away from the end
            new[e] = [x2 - ux * target, y2 - uy * target]
        else:                 # slide the end vertex away from the start
            new[(e + 1) % n] = [x1 + ux * target, y1 + uy * target]
        if not convex(new):
            return False
        polygons[r]["verts"] = new
        return True

    fixed = 0
    for r1, e1, r2, e2 in conns:
        l1 = edge_vec(r1, e1)[4]
        l2 = edge_vec(r2, e2)[4]
        if abs(l2 / l1 - 1.0) <= 0.005:
            continue
        (rs, es), tgt = ((r1, e1), l2) if l1 < l2 else ((r2, e2), l1)
        (rl, el) = (r2, e2) if l1 < l2 else (r1, e1)
        if try_stretch(rs, es, tgt) or \
                try_stretch(rl, el, min(l1, l2)):
            fixed += 1
        else:
            raise ValueError(
                f"cannot rigidify seam {r1}:{e1}<->{r2}:{e2} "
                f"({l1:.1f} vs {l2:.1f}) without touching another portal")
    for r1, e1, r2, e2 in conns:
        l1 = edge_vec(r1, e1)[4]
        l2 = edge_vec(r2, e2)[4]
        if abs(l2 / l1 - 1.0) > 0.005:
            raise ValueError(f"seam still scaled: {r1}:{e1}<->{r2}:{e2}")
    return fixed



# ---------------------------------------------------------------------------
# BOSS ENCOUNTERS (director 2026-07-16: "splice some big boss
# encounters in at arbitrary spots, with big complex arenas with
# corridors leading out... make the corridors LONG, and make each
# arena unique and complex, with lots of geometry and impossible
# geometry in the later ones". STALWART must clear 0.9 ONLY here, so
# every boss fields >=2 wardens; difficulty tunes toward 90% fail.)
# ---------------------------------------------------------------------------

BOSS_CORRIDOR = 1150.0     # legacy constant kept for scale reference
CELL = 220.0               # donut/cross cell module


def _boss_hall(b, x, y, flip, w=150.0):
    """The long walk in/out — now with TURNS (director 2026-07-18): a
    Z of three straight runs and two square-corner bends. The path is
    LONGER than the old straight shot (~1500u vs 1150), the sightline
    into the arena is broken, and the arena sits 5 polygon-hops from the
    last gunfire outside (alert_hops=1), so the wardens are met IN the
    arena instead of strolling up the hall. `flip` mirrors the Z so
    entry and exit halls bend opposite ways.

    Returns (first_polygon, last_polygon, [all polygon ids]). First's open
    edge is W(0), last's open edge is E(2), like the old corridor.
    All seams are square: corner polygons are w x w, so every joined
    edge has length w (rigid-portal law).
    """
    s = LEVEL_SEED + int(x) % 9973
    L1, LV, L2 = 430.0, 340.0, 430.0
    n0 = len(b.data["polygons"])
    h1 = b.rect(x, y, L1, w, seed=s, kind="corridor")
    c1 = b.rect(x + L1, y, w, w, seed=s + 1, kind="corridor")
    vy = y + w if flip else y - LV
    v = b.rect(x + L1, vy, w, LV, seed=s + 2, kind="corridor")
    cy = y + w + LV if flip else y - LV - w
    c2 = b.rect(x + L1, cy, w, w, seed=s + 3, kind="corridor")
    h2 = b.rect(x + L1 + w, cy, L2, w, seed=s + 4, kind="corridor")
    b.connect(h1, 2, c1, 0)
    if flip:
        b.connect(c1, 1, v, 3)      # corner S -> shaft N (going down)
        b.connect(v, 1, c2, 3)
    else:
        b.connect(c1, 3, v, 1)      # corner N -> shaft S (going up)
        b.connect(v, 3, c2, 1)
    b.connect(c2, 2, h2, 0)
    # the arena-mouth PINCH: the hall itself is 150 wide (6 mites
    # abreast — no funnel at all, measured engulfment deaths); the
    # level's choke grammar is a 64 waist. Boss spill single-files
    # through this on its way out to the player.
    pinch_x = x + L1 + w + L2
    p1, _, p2, pe = hourglass(b, pinch_x, cy + w / 2, CHOKE_LEN * 2,
                              w, w, CHOKE_W, s + 5)
    b.connect(h2, 2, p1, 0)
    b.light(h1, (x + L1 / 2, y + w / 2),
            color=(140, 120, 120), intensity=0.55, radius=260.0)
    b.light(v, (x + L1 + w / 2, vy + LV / 2),
            color=(120, 110, 130), intensity=0.5, radius=240.0)
    b.light(h2, (x + L1 + w + L2 / 2, cy + w / 2),
            color=(140, 120, 120), intensity=0.55, radius=260.0)
    b.light(p1, (pinch_x + CHOKE_LEN, cy + w / 2),
            color=(210, 160, 130), intensity=0.9, radius=150.0)
    # the safe-route medkit: behind the second corner, on the walk
    # in and available during a fighting withdrawal (Sol §4.4)
    b.entity(h2, "medkit", (x + L1 + w + 70.0, cy + w / 2))
    return h1, p2, list(range(n0, len(b.data["polygons"])))


def boss_donut(b, ox, oy, protected):
    """B1 PILLAR NAVE: a 3x3 grid of polygons with the center cell OMITTED
    -- one massive pillar the fight rotates around. Positioning: break
    line of sight on the pillar, never get pinched in a corner cell."""
    cells = {}
    for r in range(3):
        for c in range(3):
            if (r, c) == (1, 1):
                continue
            cells[(r, c)] = b.rect(ox + c * CELL, oy + r * CELL,
                                   CELL, CELL,
                                   seed=LEVEL_SEED + 9100 + r * 3 + c,
                                   kind="hall")
    for (r, c), polygon in cells.items():
        if (r, c + 1) in cells and c + 1 <= 2:
            b.connect(polygon, 2, cells[(r, c + 1)], 0)   # E <-> W
        if (r + 1, c) in cells and r + 1 <= 2:
            b.connect(polygon, 1, cells[(r + 1, c)], 3)   # S <-> N
    for (r, c), polygon in cells.items():
        b.light(polygon, (ox + c * CELL + CELL / 2,
                       oy + r * CELL + CELL / 2),
                color=(200, 150, 110), intensity=0.7, radius=200.0)
    wardens = [((0, 0), (0.5, 0.5)), ((2, 2), (0.5, 0.5)),
               ((0, 1), (0.5, 0.35)), ((2, 0), (0.5, 0.6))]
    for (r, c), (fx, fy) in wardens:
        b.entity(cells[(r, c)], "warden",
                 (ox + c * CELL + fx * CELL, oy + r * CELL + fy * CELL))
    for (r, c) in ((0, 2), (2, 0)):
        b.entity(cells[(r, c)], "spitter",
                 (ox + c * CELL + CELL * 0.3, oy + r * CELL + CELL * 0.6))
    for i, (r, c) in enumerate(((1, 0), (1, 2), (0, 1), (2, 1))):
        b.entity(cells[(r, c)], "husk",
                 (ox + c * CELL + CELL * (0.25 + 0.15 * i),
                  oy + r * CELL + CELL * 0.4))
    b.entity(cells[(0, 2)], "flicker",
             (ox + 2 * CELL + CELL * 0.6, oy + CELL * 0.3))
    b.entity(cells[(0, 1)], "brute", (ox + CELL + CELL * 0.7, oy + CELL * 0.6))
    b.entity(cells[(2, 1)], "brute", (ox + CELL + CELL * 0.3,
                                      oy + 2 * CELL + CELL * 0.5))
    b.entity(cells[(1, 2)], "spitter", (ox + 2 * CELL + CELL * 0.7,
                                        oy + CELL + CELL * 0.5))
    b.entity(cells[(1, 0)], "spitter", (ox + CELL * 0.3,
                                        oy + CELL + CELL * 0.3))
    b.entity(cells[(2, 0)], "flicker",
             (ox + CELL * 0.3, oy + 2 * CELL + CELL * 0.7))
    return cells[(1, 0)], 0, cells[(1, 2)], 2   # in W of mid-left, out E


def boss_cross(b, ox, oy, protected):
    """B2 THE CROSS: central vault, four long arms. The wardens hold
    opposite arms; brutes own the vault. Positioning: fight down ONE
    arm or be surrounded at the crossing."""
    cx = b.rect(ox, oy, CELL, CELL, seed=LEVEL_SEED + 9200, kind="hall")
    arm_w = b.rect(ox - 700, oy, 700, CELL, seed=LEVEL_SEED + 9201,
                   kind="corridor")
    arm_e = b.rect(ox + CELL, oy, 700, CELL, seed=LEVEL_SEED + 9202,
                   kind="corridor")
    arm_n = b.rect(ox, oy - 700, CELL, 700, seed=LEVEL_SEED + 9203,
                   kind="corridor")
    arm_s = b.rect(ox, oy + CELL, CELL, 700, seed=LEVEL_SEED + 9204,
                   kind="corridor")
    b.connect(arm_w, 2, cx, 0)
    b.connect(cx, 2, arm_e, 0)
    b.connect(arm_n, 1, cx, 3)
    b.connect(cx, 1, arm_s, 3)
    b.light(cx, (ox + CELL / 2, oy + CELL / 2),
            color=(190, 140, 140), intensity=0.8, radius=240.0)
    b.entity(arm_n, "warden", (ox + CELL / 2, oy - 550))
    b.entity(arm_s, "warden", (ox + CELL / 2, oy + CELL + 550))
    b.entity(cx, "warden", (ox + CELL / 2, oy + CELL / 2))
    b.entity(cx, "brute", (ox + 40, oy + CELL * 0.25))
    for k in range(3):
        b.entity(arm_e, "mite", (ox + CELL + 120 + k * 90,
                                 oy + 40 + (k % 2) * 140))
    b.entity(arm_w, "spitter", (ox - 300, oy + CELL / 2))
    for ax_, ay_ in ((ox - 500, oy + CELL * 0.3),
                     (ox + CELL + 450, oy + CELL * 0.7)):
        b.entity(arm_w if ax_ < ox else arm_e, "medkit", (ax_, ay_))
        b.entity(arm_w if ax_ < ox else arm_e, "ammo_9mm",
                 (ax_ + 30, ay_))
        b.entity(arm_w if ax_ < ox else arm_e, "ammo_shell",
                 (ax_ - 30, ay_))
    return arm_w, 0, arm_e, 2


def boss_ring(b, ox, oy, protected):
    """B3 MOEBIUS GALLERY: five 90-degree turns closed as if four --
    450 degrees of corridor that meets itself IMPOSSIBLY. Wardens
    patrol a loop with no center; kite forever or die cornered."""
    L, W = 430.0, 150.0
    segs = []
    for i in range(5):
        # alternate horizontal/vertical placement; the CONNECTS define
        # the true (impossible) topology, placement is just scaffolding
        if i % 2 == 0:
            segs.append(b.rect(ox + i * 500, oy, L, W,
                               seed=LEVEL_SEED + 9300 + i,
                               kind="corridor"))
        else:
            segs.append(b.rect(ox + i * 500, oy + 300, W, L,
                               seed=LEVEL_SEED + 9300 + i,
                               kind="corridor"))
    for i in range(5):
        j = (i + 1) % 5
        a, bb = segs[i], segs[j]
        ea = 2 if i % 2 == 0 else 1          # E of horiz / S of vert
        eb = 0 if j % 2 == 0 else 3          # W of horiz / N of vert
        b.connect(a, ea, bb, eb)
    for i, s in enumerate(segs):
        x = ox + i * 500 + (L / 2 if i % 2 == 0 else W / 2)
        y = oy + (W / 2 if i % 2 == 0 else 300 + L / 2)
        b.light(s, (x, y), color=(150, 130, 180), intensity=0.6,
                radius=220.0)
    b.entity(segs[1], "warden", (ox + 500 + W / 2, oy + 300 + L * 0.5))
    b.entity(segs[3], "warden", (ox + 1500 + W / 2, oy + 300 + L * 0.5))
    b.entity(segs[4], "warden", (ox + 2000 + W / 2, oy + 300 + L * 0.5))
    b.entity(segs[0], "flicker", (ox + L * 0.7, oy + W * 0.5))
    b.entity(segs[2], "shrieker", (ox + 1000 + L * 0.5, oy + W / 2))
    # encounter-clear caches (Sol 2 §6): recovery between warden
    # pairs raises sequential survival without touching any brawl
    for sg, sx in ((segs[0], ox + L * 0.25), (segs[2], ox + 1000 + L * 0.25)):
        b.entity(sg, "medkit", (sx, oy + W * 0.3))
        b.entity(sg, "ammo_9mm", (sx + 30, oy + W * 0.6))
        b.entity(sg, "ammo_shell", (sx - 30, oy + W * 0.6))
    for k in range(2):
        b.entity(segs[(k * 2) % 5], "husk",
                 (ox + ((k * 2) % 5) * 500 + 80 + k * 60, oy + W * 0.4))
    # entry/exit stubs hang off two ring segments' LONG edges (full-edge
    # portals: stub length matches the segment's long side exactly)
    stub_in = b.rect(ox, oy - 300, L, W, seed=LEVEL_SEED + 9310,
                     kind="corridor")
    b.connect(stub_in, 1, segs[0], 3)
    stub_out = b.rect(ox + 1000, oy - 300, L, W,
                      seed=LEVEL_SEED + 9311, kind="corridor")
    b.connect(stub_out, 1, segs[2], 3)
    protected.add(stub_in)
    protected.add(stub_out)
    return stub_in, 0, stub_out, 2


def boss_dark(b, ox, oy, protected):
    """B4 VESTIBULE OF TEETH: an UNLIT double-hall with side chapels
    and a fold -- fleeing forward returns you to the entrance. The
    dark belongs to the flickers; the wardens own the floor."""
    hall_l = b.rect(ox, oy, 250, 300, seed=LEVEL_SEED + 9400,
                    kind="hall")
    hall_r = b.rect(ox + 250, oy, 250, 300, seed=LEVEL_SEED + 9401,
                    kind="hall")
    chap_l = b.rect(ox, oy - 200, 250, 200, seed=LEVEL_SEED + 9402,
                    kind="chapel")
    chap_r = b.rect(ox + 250, oy - 200, 250, 200,
                    seed=LEVEL_SEED + 9403, kind="chapel")
    vest = b.rect(ox - 300, oy, 300, 300, seed=LEVEL_SEED + 9404,
                  kind="storage")
    out = b.rect(ox + 500, oy, 300, 300, seed=LEVEL_SEED + 9405,
                 kind="storage")
    b.connect(vest, 2, hall_l, 0)
    b.connect(hall_l, 2, hall_r, 0)
    b.connect(hall_r, 2, out, 0)
    b.connect(chap_l, 1, hall_l, 3)
    b.connect(chap_r, 1, hall_r, 3)
    # THE FOLD: the halls' south edges meet each other -- running
    # "away" through the floor brings you back facing the other hall
    b.connect(hall_l, 1, hall_r, 1)
    # no lights. the chapels get a dim candle each; the halls are BLACK
    b.light(chap_l, (ox + 125, oy - 100), color=(120, 90, 60),
            intensity=0.5, radius=120.0)
    b.light(chap_r, (ox + 375, oy - 100), color=(120, 90, 60),
            intensity=0.5, radius=120.0)
    b.entity(hall_l, "warden", (ox + 125, oy + 150))
    b.entity(hall_r, "warden", (ox + 375, oy + 150))
    b.entity(chap_r, "warden", (ox + 375, oy - 100))
    for k in range(4):
        r = (hall_l, hall_r, chap_l)[k % 3]
        xs = (ox + 60 + (k * 67) % 380, oy + 40 + (k * 53) % 220)
        b.entity(r, "flicker", xs)
    b.entity(chap_l, "shrieker", (ox + 60, oy - 60))
    for cr, cx_ in ((chap_l, ox + 190), (chap_r, ox + 310)):
        b.entity(cr, "medkit", (cx_, oy - 150))
        b.entity(cr, "ammo_9mm", (cx_ + 25, oy - 130))
        b.entity(cr, "ammo_shell", (cx_ - 25, oy - 130))
    b.entity(vest, "warden", (ox - 150, oy + 150))
    b.entity(hall_l, "spitter", (ox + 60, oy + 250))
    protected.add(vest)
    protected.add(out)
    return vest, 0, out, 2


BOSSES = {1: boss_donut, 2: boss_cross, 3: boss_ring, 4: boss_dark}


def splice_boss(b, i, prev_polygon, prev_edge, protected, boss_polygons):
    # boss_polygons: {boss_index: [polygon ids]} for per-boss fail attribution
    """LONG corridor -> boss compound -> LONG corridor, spliced into
    the chain after segment i."""
    oy = BAND_Y - 25000.0 - i * 9000.0
    ox = i * 11000.0
    n0 = len(b.data["polygons"])
    cin_a, cin_b, cin_ids = _boss_hall(b, ox - 2400, oy + 60,
                                       flip=(i % 2 == 0))
    protected.update(cin_ids)
    b.connect(prev_polygon, prev_edge, cin_a, 0)
    entry, e_in, exit_, e_out = BOSSES[i](b, ox, oy, protected)
    b.connect(cin_b, 2, entry, e_in)
    cout_a, cout_b, cout_ids = _boss_hall(b, ox + 2600, oy + 60,
                                          flip=(i % 2 == 1))
    protected.update(cout_ids)
    b.connect(exit_, e_out, cout_a, 0)
    boss_polygons[i] = list(range(n0, len(b.data["polygons"])))
    return cout_b, 2


def build(n_total: int, min_sep: float, seed: int):
    b = LevelBuilder("GAUNTLET III — TACTICAL CALIBRATION", tier=3,
                     ambience="amb_drone_late")
    texture_map = {}
    protected = set()          # polygons that stay enemy-free

    spawn = b.rect(-600, BAND_Y, 220, LANE_W,
                   seed=LEVEL_SEED + 7999, kind="storage")
    b.player(spawn, (-490, BAND_Y + LANE_W / 2))
    b.light(spawn, (-490, BAND_Y + LANE_W / 2),
            color=(150, 170, 200), intensity=1.0, radius=220.0)
    protected.add(spawn)

    prev_polygon, prev_edge = spawn, E_EDGE
    lane_polygons = set()
    boss_polygons: dict = {}
    for i, seg in enumerate(SEGMENTS):
        ln = lane_with_alcove(b, i)
        lane_polygons.update(ln.get("pieces", ()))
        protected.add(ln["alc"])
        b.connect(prev_polygon, prev_edge, ln["west_polygon"], W_EDGE)
        # arena first: the choke's east portal must MATCH the arena's
        # entry edge length exactly (rigid m9 — no scaling transforms)
        BG.TEXTURE_MAP.clear()
        info = add_segment(b, seg, (i + 1) * 20000.0, 0.0,
                           keep=set(), seg_idx=i)
        for nr, sv in BG.TEXTURE_MAP.items():
            texture_map[str(nr)] = sv
        entry_len = _edge_len_of(b, info["entry"][0], info["entry"][1])
        ck1, ck_w, ck2, ck_e = choke(b, i, LANE_W, entry_len)
        protected.add(ck1)
        protected.add(ck2)
        b.connect(ln["east_polygon"], E_EDGE, ck1, ck_w)
        b.connect(ck2, ck_e, info["entry"][0], info["entry"][1])
        # adapter after the arena: exit edge length -> LANE_W, rigid
        exit_len = _edge_len_of(b, info["exit"][0], info["exit"][1])
        yc = BAND_Y + i * BAND_SPACING + LANE_W / 2
        ad, ad_w, ad_e = trapezoid(
            b, i * 4000.0 + LANE_LEN + 900.0, yc, 160.0, exit_len,
            LANE_W, LEVEL_SEED + 7300 + i)
        protected.add(ad)
        b.connect(info["exit"][0], info["exit"][1], ad, ad_w)
        prev_polygon, prev_edge = ad, ad_e
        if i in BOSSES:
            prev_polygon, prev_edge = splice_boss(b, i, prev_polygon,
                                               prev_edge, protected,
                                               boss_polygons)

    out = b.rect(30 * 4000.0, BAND_Y, 260, LANE_W,
                 seed=LEVEL_SEED + 8999, kind="storage")
    b.connect(prev_polygon, prev_edge, out, W_EDGE)
    b.exit(out, (30 * 4000.0 + 130, BAND_Y + LANE_W / 2))
    b.light(out, (30 * 4000.0 + 130, BAND_Y + LANE_W / 2),
            color=(150, 200, 160), intensity=1.0, radius=220.0)
    protected.add(out)

    b.build()                   # validates winding/schema/spawn/exit
    level = b.to_dict()
    level["alert_hops"] = 1
    level["texture_map"] = texture_map
    # forward resupply: with the lane guns gone (safe polygons 5x sparser)
    # the mid-run died of attrition -- 0/80 completions, ~350 dmg taken
    # vs ~6 heals found. Medkits INSIDE the arena chains reward pushing
    # through instead of kiting back; a kit every ~3rd combat polygon.
    n_med = 0
    for i, r in enumerate(level["polygons"]):
        if i in protected or i % 3 or i in lane_polygons:
            continue
        vs = r["verts"]
        cx = sum(v[0] for v in vs) / len(vs)
        cy = sum(v[1] for v in vs) / len(vs)
        r.setdefault("entities", []).append(
            dict(type="medkit", pos=[cx, cy]))
        n_med += 1
    print(f"forward resupply: +{n_med} arena medkits")
    n_rigid = _rigidify(level)
    print(f"rigidified {n_rigid} residual scaled seams "
          f"(all portals now pure isometries)")
    all_boss = {r for rs in boss_polygons.values() for r in rs}
    placed, fails, counts = populate(level, protected | all_boss,
                                     n_total, min_sep, seed,
                                     boost=lane_polygons)
    level["boss_polygons"] = {str(k): v for k, v in boss_polygons.items()}
    return level, placed, fails, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=180)
    ap.add_argument("--min-sep", type=float, default=90.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "levels/gauntlet_cal3.json")
    a = ap.parse_args()
    level, placed, fails, counts = build(a.n, a.min_sep, a.seed)
    a.out.write_text(json.dumps(level))
    print(f"placed {placed}/{a.n} (fails {fails}) -> {a.out}")
    print("mix:", counts)


if __name__ == "__main__":
    main()
