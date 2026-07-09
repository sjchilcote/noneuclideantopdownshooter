"""Immediate-mode renderer: necore draw lists -> a 640x360 pygame.Surface.

No pygame.display dependency anywhere in this module (fonts are OK) so it
runs the same under a real window and under SDL_VIDEODRIVER=dummy. All
Surfaces used for post effects/glows are pre-baked once in __init__; draw()
never allocates a Surface.

Effect pools (gibs, sparks, flashes, lightning, screams, hitflash, hurt/die
overlays) are time-decayed in `consume_fx`, which the caller drives once per
*sim tick* (fixed 60Hz) — not once per display frame — so all "N frames"
durations in the spec are exactly N ticks, keeping presentation state
frame-rate independent like everything else in this engine.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pygame

import necore

from .sim import DT

INTERNAL_W, INTERNAL_H = 640, 360

FLOOR_BASE = (26, 26, 33)          # ~0x1a1a21 dark grey-blue — reads clearly against the void
WALL_COLOR = (184, 196, 204)       # 0xb8c4cc
WALL_MIN = (74, 80, 88)            # 0x4a5058 — walls never dim below this (readability skeleton)
DOOR_COLOR = (208, 128, 24)        # 0xd08018
KEY_COLORS = {
    "red": (200, 60, 60),
    "blue": (72, 132, 222),
    "gold": (216, 180, 70),
    "void": (122, 42, 168),
}
BLOOD_COLOR = (64, 12, 15)         # kept below every live-enemy fill: residue never outranks threats
SCORCH_COLOR = (42, 38, 36)
CHIP_COLOR = (150, 150, 140)
EXIT_COLOR = (120, 255, 172)
GIB_COLOR = (94, 16, 16)
SPARK_COLOR = (255, 230, 120)
LIGHTNING_COLOR = (205, 242, 255)
SCREAM_COLOR = (230, 230, 240)

# -- diegetic prop palette -------------------------------------------------
# Desaturated & dark by design: props read below the enemy-color range (the
# brightest enemies run 200+) and above the floor (26,26,33), so furniture
# never competes with a live threat for the eye. Hazard/screen accents are
# the deliberate exceptions -- a lit instrument or caution stripe is meant
# to pop, the way a door key color pops against everything else.
PROP_COLOR = (58, 62, 72)          # structural fill: crates, cots, shelves
PROP_RIM = (90, 96, 108)           # prop edge / rim -- one step brighter
PROP_DARK = (38, 40, 48)           # recessed fill: slabs, lockers, cabinets
HAZARD_COLOR = (150, 112, 40)      # dull amber hazard stripe
HAZARD_COLOR_DIM = (98, 76, 34)
PIPE_COLOR = (70, 80, 92)
PUDDLE_COLOR = (32, 40, 48)
SCREEN_COLOR = (110, 235, 165)     # lit phosphor screen (lab consoles, terminals)
SCREEN_DIM = (46, 96, 78)          # unlit / already-read screen

PLAYER_SHAPE = [(1.3, 0.0), (-0.8, 0.85), (-0.35, 0.0), (-0.8, -0.85)]
PLAYER_COLOR = (205, 248, 255)


def _regular_lumpy(n, radii, phase=0.0):
    pts = []
    for i in range(n):
        a = phase + i * 2.0 * math.pi / n
        r = radii[i % len(radii)]
        pts.append((math.cos(a) * r, math.sin(a) * r))
    return pts


_CIRCLE_SHAPE = _regular_lumpy(8, [1.0] * 8)

ENEMY_SHAPE = {
    "husk": _regular_lumpy(7, [0.75, 1.0, 0.85, 1.05, 0.7, 0.95, 0.8]),
    "spitter": _regular_lumpy(6, [0.8, 0.95, 0.75, 1.0, 0.8, 0.9]),
    "brute": _regular_lumpy(5, [1.0, 0.95, 1.05, 0.95, 1.0]),
    "warden": _regular_lumpy(9, [0.9, 1.0, 0.85, 1.05, 0.9, 0.95, 1.0, 0.85, 1.0]),
    "shrieker": [(1.4, 0.0), (0.0, 0.28), (-1.4, 0.0), (0.0, -0.28)],
}
ENEMY_COLOR = {
    "husk": (126, 142, 116),
    "mite": (208, 220, 198),
    "spitter": (128, 140, 74),
    "brute": (158, 80, 64),
    "shrieker": (236, 228, 205),
    "warden": (52, 32, 60),
}


def _brighten(c, amt: int):
    return (min(255, c[0] + amt), min(255, c[1] + amt), min(255, c[2] + amt))


# Every enemy gets a value-contrast outline (fill +70); these override the
# derived color/width where the archetype's read demands it.
ENEMY_RIM = {"warden": (235, 235, 245)}
ENEMY_RIM_W = {"brute": 2}

BLOOD_BLOB = _regular_lumpy(6, [1.0, 0.7, 0.9, 0.6, 0.85, 0.75])
SPLAT_BLOB = _regular_lumpy(4, [0.8, 0.5, 0.7, 0.5])

GIB_FRICTION = 0.90


def _dim(depth: int) -> float:
    # Depth dimming was a seam: crossing a portal snapped the new room's
    # brightness (invariant 5). Distance-to-player lighting replaces it —
    # applied screen-space after the world draw, smooth across portals.
    return 1.0


def _floor_dim(depth: int) -> tuple[float, float, float]:
    return (1.0, 1.0, 1.0)



def _shade(base, dim, tint=(0, 0, 0)):
    if isinstance(dim, tuple):
        dr, dg, db = dim
    else:
        dr = dg = db = dim
    r = min(255, max(0, int((base[0] + tint[0]) * dr)))
    g = min(255, max(0, int((base[1] + tint[1]) * dg)))
    b = min(255, max(0, int((base[2] + tint[2]) * db)))
    return (r, g, b)


def _room_tint(room: int):
    # Upward-biased (0..+20 per channel): rooms vary noticeably so adjacent
    # spaces read as different through portals, but no room ever falls
    # below the #16161c readability base.
    h = hash(room)
    return ((h) % 21, (h >> 8) % 21, (h >> 16) % 21)


def _point_in_poly(x: float, y: float, poly) -> bool:
    """Winding-independent (ray casting) point-in-convex-polygon test.

    Screen-space clip polygons can come out CW instead of CCW when a portal
    xform has a chirality flip, so this must not assume a winding order.
    """
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_at = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_at:
                inside = not inside
        j = i
    return inside


def _xform_pts(points, cx, cy, scale, ang, squash=1.0):
    ca, sa = math.cos(ang), math.sin(ang)
    out = []
    for lx, ly in points:
        ly2 = ly * squash
        rx = lx * ca - ly2 * sa
        ry = lx * sa + ly2 * ca
        out.append((cx + rx * scale, cy + ry * scale))
    return out


def _xform_scale(xform) -> float:
    dx, dy = necore.mat_apply_dir(xform, 1.0, 0.0)
    return math.hypot(dx, dy)


def _pt(p):
    return (int(round(p[0])), int(round(p[1])))


def _pts(poly):
    return [(int(round(x)), int(round(y))) for x, y in poly]


# ---------------------------------------------------------------------------
# diegetic prop geometry -- room-local coordinate helpers and per-room-kind
# prop-set generators. Everything below is pure geometry (no pygame, no
# necore): it produces the same `_get_detail` primitive tuples the old
# grime generator did ("line"/"dot"/"stain"), plus three new kinds
# ("poly", "polyline", "screenglow") that `Renderer._draw_detail` knows how
# to clip and paint. Room-local coords are always centroid-at-origin (the
# Level contract), which is what makes "toward the room interior" always
# just mean "toward (0, 0)".
# ---------------------------------------------------------------------------


def _rect_local(cx, cy, w, h, ang=0.0):
    hw, hh = w / 2.0, h / 2.0
    ca, sa = math.cos(ang), math.sin(ang)
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in corners]


def _ring_local(cx, cy, r, n=16):
    return [(cx + r * math.cos(2.0 * math.pi * i / n),
             cy + r * math.sin(2.0 * math.pi * i / n)) for i in range(n)]


def _arc_local(cx, cy, r, a0, a1, n=10):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def _basis_arc_local(cx, cy, r, tx, ty, nx, ny, a0=-math.pi / 2, a1=math.pi / 2, n=8):
    """Arc in the (tangent, normal) basis of a wall: a=0 sits `r` along
    (nx,ny) from (cx,cy); a=+-pi/2 sits `r` along +-(tx,ty). Lets callers
    place a bulge "into the room" without caring which way the wall faces
    in world coordinates."""
    pts = []
    for i in range(n + 1):
        a = a0 + (a1 - a0) * i / n
        pts.append((cx + (tx * math.sin(a) + nx * math.cos(a)) * r,
                     cy + (ty * math.sin(a) + ny * math.cos(a)) * r))
    return pts


def _edge_inward_normal(x0, y0, x1, y1):
    """Unit normal of edge (x0,y0)->(x1,y1) pointing toward the room
    interior (room-local origin)."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if (-mx) * nx + (-my) * ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def _wall_edges(verts, portal_edges, min_len=16.0):
    """Non-portal edges of `verts` long enough to hang a prop on: dicts with
    endpoints, length, tangent, and inward normal, longest first. Portal
    (and pending-door) edges are excluded so static furniture never blocks
    a passage that is -- or will become, once a door unlocks -- open."""
    n = len(verts)
    out = []
    for i in range(n):
        if i in portal_edges:
            continue
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < min_len:
            continue
        tx, ty = dx / length, dy / length
        nx, ny = _edge_inward_normal(x0, y0, x1, y1)
        out.append(dict(i=i, p0=(x0, y0), p1=(x1, y1), len=length,
                         tx=tx, ty=ty, nx=nx, ny=ny,
                         mx=(x0 + x1) / 2.0, my=(y0 + y1) / 2.0))
    out.sort(key=lambda e: -e["len"])
    return out


def _place_along_wall(wall, item_w, gap, inset, margin=6.0):
    """Evenly spaced item centers along `wall`, offset `inset` inward from
    the wall line, each `(cx, cy, ang)` with `ang` = the wall's tangent
    angle (so a rect built at that angle sits flush against the wall)."""
    usable = wall["len"] - 2 * margin
    if usable <= item_w:
        return []
    n = max(1, int((usable + gap) // (item_w + gap)))
    span = n * item_w + (n - 1) * gap
    start = (wall["len"] - span) / 2.0
    ang = math.atan2(wall["ty"], wall["tx"])
    out = []
    for k in range(n):
        t = start + item_w / 2.0 + k * (item_w + gap)
        bx = wall["p0"][0] + wall["tx"] * t
        by = wall["p0"][1] + wall["ty"] * t
        out.append((bx + wall["nx"] * inset, by + wall["ny"] * inset, ang))
    return out


def _crate(cx, cy, w, h, ang, rng, fill=PROP_COLOR, rim=PROP_RIM):
    pts = _rect_local(cx, cy, w, h, ang)
    prims = [("poly", pts, fill, rim, 1)]
    strap = tuple(max(0, c - 16) for c in rim)
    if rng.random() < 0.85:
        prims.append(("line", pts[0], pts[2], strap, 1))
    if w > 7 and h > 7 and rng.random() < 0.6:
        prims.append(("line", pts[1], pts[3], strap, 1))
    return prims


def _vent_grate(cx, cy, ang, wall, w=8.0, h=5.0):
    pts = _rect_local(cx, cy, w, h, ang)
    prims = [("poly", pts, PROP_DARK, PROP_RIM, 1)]
    for k in range(1, 4):
        t = -w / 2.0 + k * (w / 4.0)
        lx = cx + wall["tx"] * t
        ly = cy + wall["ty"] * t
        hx = lx + wall["nx"] * (h * 0.4)
        hy = ly + wall["ny"] * (h * 0.4)
        lx2 = lx - wall["nx"] * (h * 0.4)
        ly2 = ly - wall["ny"] * (h * 0.4)
        prims.append(("line", (lx2, ly2), (hx, hy), PROP_RIM, 1))
    return prims


def _props_dock(rng, verts, walls, x0, y0, x1, y1):
    """Cargo crates in corner stacks, a hazard-striped strip near one wall,
    mooring rings along another."""
    prims = []
    corners = list(verts)
    rng.shuffle(corners)
    for cx0, cy0 in corners[:2]:
        length = math.hypot(cx0, cy0) or 1.0
        ux, uy = -cx0 / length, -cy0 / length
        base = 10.0
        for k in range(rng.randint(3, 5)):
            w = rng.uniform(9, 15)
            h = rng.uniform(9, 15)
            off = base + k * rng.uniform(6, 9)
            jitter = rng.uniform(-4, 4)
            cx = cx0 + ux * off + uy * jitter
            cy = cy0 + uy * off - ux * jitter
            prims.extend(_crate(cx, cy, w, h, rng.uniform(-0.15, 0.15), rng))
    if walls:
        wall = rng.choice(walls)
        strip_w = min(wall["len"] * 0.6, 60.0)
        strip_d = 10.0
        steps = max(4, int(strip_w / 7))
        t0 = (wall["len"] - strip_w) / 2.0
        for k in range(steps):
            t = t0 + k * (strip_w / steps)
            bx = wall["p0"][0] + wall["tx"] * t
            by = wall["p0"][1] + wall["ty"] * t
            ex = bx + wall["nx"] * strip_d
            ey = by + wall["ny"] * strip_d
            color = HAZARD_COLOR if k % 2 == 0 else HAZARD_COLOR_DIM
            prims.append(("line", (bx, by), (ex, ey), color, 2))
        ring_wall = rng.choice(walls)
        for cx, cy, ang in _place_along_wall(ring_wall, 6.0, 22.0, 6.0):
            prims.append(("polyline", _ring_local(cx, cy, 2.4, 10), PROP_RIM, 1, True))
            hx = cx - ring_wall["nx"] * 4.0
            hy = cy - ring_wall["ny"] * 4.0
            prims.append(("line", (cx, cy), (hx, hy), PROP_RIM, 1))
    return prims


def _props_corridor(rng, verts, walls, x0, y0, x1, y1):
    """Wall-hugging pipe runs with elbow joints, floor lane chevrons, vent
    grates. Shared by "corridor" and "transit"."""
    prims = []
    for wall in walls[:2]:
        inset = 5.0
        margin = 8.0
        if wall["len"] <= 2 * margin:
            continue
        a = (wall["p0"][0] + wall["nx"] * inset + wall["tx"] * margin,
             wall["p0"][1] + wall["ny"] * inset + wall["ty"] * margin)
        b = (wall["p1"][0] + wall["nx"] * inset - wall["tx"] * margin,
             wall["p1"][1] + wall["ny"] * inset - wall["ty"] * margin)
        prims.append(("line", a, b, PIPE_COLOR, 1))
        run = wall["len"] - 2 * margin
        n_joints = max(1, int(run // 26))
        for k in range(1, n_joints + 1):
            t = margin + k * (run / (n_joints + 1))
            jx = wall["p0"][0] + wall["tx"] * t + wall["nx"] * inset
            jy = wall["p0"][1] + wall["ty"] * t + wall["ny"] * inset
            prims.append(("line", (jx, jy),
                          (jx + wall["nx"] * 3.5, jy + wall["ny"] * 3.5), PIPE_COLOR, 1))
        if rng.random() < 0.7:
            spots = _place_along_wall(wall, 8.0, 20.0, 8.0)
            if spots:
                gx, gy, gang = rng.choice(spots)
                prims.extend(_vent_grate(gx, gy, gang, wall))
    axis_dx, axis_dy = x1 - x0, y1 - y0
    horiz = abs(axis_dx) >= abs(axis_dy)
    for frac in (0.28, 0.72):
        if horiz:
            lx, ly = x0 + axis_dx * frac, (y0 + y1) / 2.0
            tip = (lx + 5, ly)
            prims.append(("line", (lx - 5, ly), tip, PROP_DARK, 1))
            prims.append(("line", tip, (lx, ly - 3), PROP_DARK, 1))
            prims.append(("line", tip, (lx, ly + 3), PROP_DARK, 1))
        else:
            lx, ly = (x0 + x1) / 2.0, y0 + axis_dy * frac
            tip = (lx, ly + 5)
            prims.append(("line", (lx, ly - 5), tip, PROP_DARK, 1))
            prims.append(("line", tip, (lx - 3, ly), PROP_DARK, 1))
            prims.append(("line", tip, (lx + 3, ly), PROP_DARK, 1))
    return prims


def _props_storage(rng, verts, walls, x0, y0, x1, y1):
    """Dense crate rows with a walkable aisle, shelf lines along the walls."""
    prims = []
    w_span, h_span = x1 - x0, y1 - y0
    horiz = w_span >= h_span
    n_rows = rng.randint(2, 3)
    budget = 70
    if horiz:
        rows_y = [y0 + h_span * (0.22 + 0.56 * k / max(1, n_rows - 1)) for k in range(n_rows)]
        aisle_lo, aisle_hi = x0 + w_span * 0.42, x0 + w_span * 0.58
        for ry in rows_y:
            cx_ = x0 + w_span * 0.12
            limit = x1 - w_span * 0.12
            while cx_ < limit and len(prims) < budget:
                w = rng.uniform(10, 16)
                if not (aisle_lo - w < cx_ < aisle_hi + w):
                    prims.extend(_crate(cx_, ry + rng.uniform(-3, 3), w,
                                        rng.uniform(10, 16), rng.uniform(-0.08, 0.08), rng))
                cx_ += w + rng.uniform(3, 6)
    else:
        cols_x = [x0 + w_span * (0.22 + 0.56 * k / max(1, n_rows - 1)) for k in range(n_rows)]
        aisle_lo, aisle_hi = y0 + h_span * 0.42, y0 + h_span * 0.58
        for rx in cols_x:
            cy_ = y0 + h_span * 0.12
            limit = y1 - h_span * 0.12
            while cy_ < limit and len(prims) < budget:
                h = rng.uniform(10, 16)
                if not (aisle_lo - h < cy_ < aisle_hi + h):
                    prims.extend(_crate(rx + rng.uniform(-3, 3), cy_, rng.uniform(10, 16),
                                        h, rng.uniform(-0.08, 0.08), rng))
                cy_ += h + rng.uniform(3, 6)
    for wall in walls[:3]:
        inset = 5.0
        a = (wall["p0"][0] + wall["nx"] * inset, wall["p0"][1] + wall["ny"] * inset)
        b = (wall["p1"][0] + wall["nx"] * inset, wall["p1"][1] + wall["ny"] * inset)
        prims.append(("line", a, b, PROP_RIM, 1))
        a2 = (a[0] + wall["nx"] * 3, a[1] + wall["ny"] * 3)
        b2 = (b[0] + wall["nx"] * 3, b[1] + wall["ny"] * 3)
        prims.append(("line", a2, b2, PROP_COLOR, 1))
    return prims


def _props_pump(rng, verts, walls, x0, y0, x1, y1):
    """A large tank ring (sometimes two) with an inflow pipe from the
    nearest wall, plus floor puddle stains."""
    prims = []
    w_span, h_span = x1 - x0, y1 - y0
    r = min(w_span, h_span) * 0.28
    ox = (x0 + x1) / 2.0 + rng.uniform(-w_span, w_span) * 0.08
    oy = (y0 + y1) / 2.0 + rng.uniform(-h_span, h_span) * 0.08
    prims.append(("polyline", _ring_local(ox, oy, r, 20), PROP_RIM, 2, True))
    prims.append(("polyline", _ring_local(ox, oy, r * 0.78, 18), PROP_COLOR, 1, True))
    if walls:
        wall = min(walls, key=lambda w: (w["mx"] - ox) ** 2 + (w["my"] - oy) ** 2)
        elbow = (wall["mx"] + wall["nx"] * (r * 0.6), wall["my"] + wall["ny"] * (r * 0.6))
        # aim at the rim point facing the wall (+ jitter), not a random
        # point on the ring -- otherwise the pipe can land on the far side
        # and visually skewer straight through the tank
        base_a = math.atan2(wall["my"] - oy, wall["mx"] - ox)
        a = base_a + rng.uniform(-0.3, 0.3)
        target = (ox + math.cos(a) * r, oy + math.sin(a) * r)
        prims.append(("polyline", [(wall["mx"], wall["my"]), elbow, target], PIPE_COLOR, 2, False))
    if rng.random() < 0.5:
        r2 = r * rng.uniform(0.35, 0.5)
        a = rng.uniform(0, 2 * math.pi)
        ox2, oy2 = ox + math.cos(a) * r * 1.6, oy + math.sin(a) * r * 1.6
        if x0 + r2 < ox2 < x1 - r2 and y0 + r2 < oy2 < y1 - r2:
            prims.append(("polyline", _ring_local(ox2, oy2, r2, 14), PROP_RIM, 1, True))
    for _ in range(rng.randint(2, 4)):
        pcx, pcy = rng.uniform(x0 + 6, x1 - 6), rng.uniform(y0 + 6, y1 - 6)
        rad = rng.uniform(5, 11)
        n = rng.randint(6, 8)
        poly = [(pcx + math.cos(2 * math.pi * i / n + rng.uniform(-0.2, 0.2)) * rad * rng.uniform(0.6, 1.0),
                 pcy + math.sin(2 * math.pi * i / n + rng.uniform(-0.2, 0.2)) * rad * rng.uniform(0.6, 1.0))
                for i in range(n)]
        prims.append(("stain", poly, PUDDLE_COLOR))
    return prims


def _props_lab(rng, verts, walls, x0, y0, x1, y1):
    """Console blocks (bright screens on dark slabs) along the walls, a
    specimen table center-adjacent."""
    prims = []
    for wall in walls[:3]:
        for cx, cy, ang in _place_along_wall(wall, 12.0, 6.0, 5.0):
            prims.append(("poly", _rect_local(cx, cy, 12.0, 7.0, ang), PROP_DARK, PROP_RIM, 1))
            scr_cx, scr_cy = cx + wall["nx"], cy + wall["ny"]
            bright = rng.random() < 0.8
            prims.append(("poly", _rect_local(scr_cx, scr_cy, 6.5, 4.0, ang),
                          SCREEN_COLOR if bright else SCREEN_DIM, None, 0))
            if bright:
                prims.append(("screenglow", scr_cx, scr_cy, 7.0))
    off = rng.uniform(10, 18)
    a0 = rng.uniform(0, 2 * math.pi)
    tcx = (x0 + x1) / 2.0 + math.cos(a0) * off
    tcy = (y0 + y1) / 2.0 + math.sin(a0) * off
    prims.append(("poly", _rect_local(tcx, tcy, 16.0, 9.0, rng.uniform(-0.2, 0.2)),
                  PROP_COLOR, PROP_RIM, 1))
    prims.append(("dot", (tcx, tcy), PROP_DARK, 2))
    return prims


def _props_quarters(rng, verts, walls, x0, y0, x1, y1):
    """Cot bays along the walls, each with a pillow and a footlocker."""
    prims = []
    for wall in walls[:3]:
        for cx, cy, ang in _place_along_wall(wall, 16.0, 8.0, 7.0):
            prims.append(("poly", _rect_local(cx, cy, 16.0, 8.0, ang), PROP_COLOR, PROP_RIM, 1))
            pcx, pcy = cx + wall["tx"] * 5.5, cy + wall["ty"] * 5.5
            prims.append(("poly", _rect_local(pcx, pcy, 4.0, 5.5, ang), PROP_RIM, None, 0))
            lcx = cx - wall["tx"] * 9.5 + wall["nx"] * 1.0
            lcy = cy - wall["ty"] * 9.5 + wall["ny"] * 1.0
            prims.append(("poly", _rect_local(lcx, lcy, 5.0, 4.0, ang), PROP_DARK, PROP_RIM, 1))
    return prims


def _props_chapel(rng, verts, walls, x0, y0, x1, y1):
    """Pew rows facing one wall (the "front"), a dais arc against it."""
    prims = []
    if not walls:
        return prims
    front = walls[0]
    pew_half = front["len"] * 0.32
    for k in range(rng.randint(4, 6)):
        d = 14.0 + k * 9.0
        cx = front["mx"] + front["nx"] * d
        cy = front["my"] + front["ny"] * d
        a = (cx - front["tx"] * pew_half, cy - front["ty"] * pew_half)
        b = (cx + front["tx"] * pew_half, cy + front["ty"] * pew_half)
        prims.append(("line", a, b, PROP_COLOR, 1))
    dcx, dcy = front["mx"] + front["nx"] * 6.0, front["my"] + front["ny"] * 6.0
    prims.append(("polyline",
                  _basis_arc_local(dcx, dcy, pew_half * 0.75, front["tx"], front["ty"],
                                   front["nx"], front["ny"], -1.0, 1.0, 10),
                  PROP_RIM, 1, False))
    return prims


def _props_records(rng, verts, walls, x0, y0, x1, y1):
    """Shelf stacks: long parallel double-lines filling the room in rows."""
    prims = []
    w_span, h_span = x1 - x0, y1 - y0
    horiz = w_span >= h_span
    n_rows = rng.randint(3, 5)
    for k in range(n_rows):
        frac = 0.14 + 0.72 * k / max(1, n_rows - 1)
        if horiz:
            ry = y0 + h_span * frac
            a1, b1 = (x0 + w_span * 0.08, ry), (x1 - w_span * 0.08, ry)
            a2, b2 = (a1[0], ry + 2.4), (b1[0], ry + 2.4)
        else:
            rx = x0 + w_span * frac
            a1, b1 = (rx, y0 + h_span * 0.08), (rx, y1 - h_span * 0.08)
            a2, b2 = (rx + 2.4, a1[1]), (rx + 2.4, b1[1])
        prims.append(("line", a1, b1, PROP_RIM, 1))
        prims.append(("line", a2, b2, PROP_COLOR, 1))
    return prims


def _props_medbay(rng, verts, walls, x0, y0, x1, y1):
    """Cots with curtain arcs, a cross-marked cabinet."""
    prims = []
    cabinet_done = False
    for wall in walls[:2]:
        for cx, cy, ang in _place_along_wall(wall, 15.0, 10.0, 7.5)[:2]:
            prims.append(("poly", _rect_local(cx, cy, 15.0, 7.5, ang), PROP_COLOR, PROP_RIM, 1))
            prims.append(("polyline",
                          _basis_arc_local(cx, cy, 11.0, wall["tx"], wall["ty"],
                                           wall["nx"], wall["ny"]),
                          PROP_DARK, 1, False))
        if not cabinet_done and wall["len"] > 30:
            cbx = wall["mx"] + wall["nx"] * 6.0 - wall["tx"] * (wall["len"] * 0.32)
            cby = wall["my"] + wall["ny"] * 6.0 - wall["ty"] * (wall["len"] * 0.32)
            cab_ang = math.atan2(wall["ty"], wall["tx"])
            prims.append(("poly", _rect_local(cbx, cby, 7.0, 6.0, cab_ang), PROP_DARK, PROP_RIM, 1))
            prims.append(("line", (cbx - 2.2, cby), (cbx + 2.2, cby), (200, 90, 90), 1))
            prims.append(("line", (cbx, cby - 2.2), (cbx, cby + 2.2), (200, 90, 90), 1))
            cabinet_done = True
    return prims


def _props_core(rng, verts, walls, x0, y0, x1, y1):
    """Concentric ring inlays, radial conduit spokes, an amber warning ring."""
    prims = []
    r_max = min(x1 - x0, y1 - y0) * 0.42
    n_rings = rng.randint(2, 3)
    for k in range(n_rings):
        r = r_max * (0.35 + 0.6 * k / max(1, n_rings - 1))
        prims.append(("polyline", _ring_local(0.0, 0.0, r, 20), PROP_RIM, 1, True))
    inner = r_max * 0.3
    n_spokes = rng.randint(6, 10)
    for i in range(n_spokes):
        a = 2 * math.pi * i / n_spokes + rng.uniform(-0.05, 0.05)
        p0 = (math.cos(a) * inner, math.sin(a) * inner)
        p1 = (math.cos(a) * r_max * 0.95, math.sin(a) * r_max * 0.95)
        prims.append(("line", p0, p1, PROP_COLOR, 1))
    wr = r_max * 1.05
    prims.append(("polyline", _ring_local(0.0, 0.0, wr, 24), HAZARD_COLOR, 1, True))
    for i in range(0, 24, 2):
        a = 2 * math.pi * i / 24
        ix, iy = math.cos(a) * (wr - 2.5), math.sin(a) * (wr - 2.5)
        ox, oy = math.cos(a) * (wr + 2.5), math.sin(a) * (wr + 2.5)
        prims.append(("line", (ix, iy), (ox, oy), HAZARD_COLOR_DIM, 1))
    return prims


def _props_generic(rng, verts, walls, x0, y0, x1, y1):
    """Untagged room: subtle plates/rivets + grime, toned down from the old
    always-on abstract-lines-and-dots generator."""
    prims = []
    for _ in range(rng.randint(2, 5)):
        if rng.random() < 0.5:
            yy = rng.uniform(y0, y1)
            prims.append(("line", (rng.uniform(x0, x1), yy), (rng.uniform(x0, x1), yy)))
        else:
            xx = rng.uniform(x0, x1)
            prims.append(("line", (xx, rng.uniform(y0, y1)), (xx, rng.uniform(y0, y1))))
    for _ in range(rng.randint(4, 9)):
        prims.append(("dot", (rng.uniform(x0, x1), rng.uniform(y0, y1))))
    for _ in range(rng.randint(1, 2)):
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
        rad = rng.uniform(5, 13)
        n = rng.randint(6, 9)
        poly = [(cx + math.cos(2 * math.pi * i / n + rng.uniform(-0.2, 0.2)) * rad * rng.uniform(0.6, 1.0),
                 cy + math.sin(2 * math.pi * i / n + rng.uniform(-0.2, 0.2)) * rad * rng.uniform(0.6, 1.0))
                for i in range(n)]
        prims.append(("stain", poly))
    for wall in walls[:4]:
        inset, margin = 4.0, 6.0
        if wall["len"] <= 2 * margin + 4:
            continue
        a = (wall["p0"][0] + wall["nx"] * inset + wall["tx"] * margin,
             wall["p0"][1] + wall["ny"] * inset + wall["ty"] * margin)
        b = (wall["p1"][0] + wall["nx"] * inset - wall["tx"] * margin,
             wall["p1"][1] + wall["ny"] * inset - wall["ty"] * margin)
        prims.append(("line", a, b))
        if rng.random() < 0.7:
            prims.append(("dot", a))
            prims.append(("dot", b))
    return prims


_ROOM_PROP_GENERATORS = {
    "dock": _props_dock,
    "corridor": _props_corridor,
    "transit": _props_corridor,
    "storage": _props_storage,
    "pump": _props_pump,
    "lab": _props_lab,
    "quarters": _props_quarters,
    "chapel": _props_chapel,
    "records": _props_records,
    "medbay": _props_medbay,
    "core": _props_core,
    "generic": _props_generic,
}


class Renderer:
    """`Renderer(session).draw(surf, debug=False)` paints one frame.

    `surf` must be a 640x360 pygame.Surface. Immediate-mode: nothing is
    retained across frames except the effect pools and the per-room detail
    cache (both intentionally persistent — grime is stable per room, decals
    live in `session.decals`).
    """

    def __init__(self, session, max_depth: int = 14, max_instances: int = 96):
        self.session = session
        self.max_depth = max_depth
        self.max_instances = max_instances

        self._detail_cache: dict[int, list] = {}
        self._portal_edges: "dict[int, set[int]] | None" = None

        self._gibs: list[dict] = []
        self._sparks: list[dict] = []
        self._flashes: list[dict] = []
        self._bolts: list[dict] = []
        self._screams: list[dict] = []
        self._hitflash: dict[int, int] = {}
        self._hurt_ticks = 0
        self._death_fade = 0
        self._dying = False

        self._font = None

        self._bake_glows()
        self._bake_vignette()
        self._darkness: "pygame.Surface | None" = None
        self._deferred_glows: list = []
        self._deferred_bolts: list = []
        self._deferred_screen_glows: list = []
        self._bake_overlays()

    # ------------------------------------------------------------------
    # one-time surface baking
    # ------------------------------------------------------------------

    def _bake_glows(self):
        # Additive blits add source RGB directly (alpha does NOT attenuate),
        # so the radial falloff must be premultiplied into the RGB itself —
        # otherwise the glow is a hard solid disc, not light on the floor.
        sizes = [8, 16, 26, 40, 60, 90]
        self._glow_sizes = sizes
        self._glow_cache = {}
        for r in sizes:
            d = r * 2 + 4
            s = pygame.Surface((d, d))  # black = adds nothing
            cx = cy = d / 2.0
            for yy in range(d):
                for xx in range(d):
                    dist = math.hypot(xx - cx, yy - cy)
                    if dist <= r:
                        a = max(0.0, 1.0 - dist / r)
                        aa = a * a
                        s.set_at((xx, yy), (int(235 * aa), int(212 * aa), int(164 * aa)))
            self._glow_cache[r] = s

        # A second, smaller, green-phosphor-tinted glow for lit instruments
        # (lab consoles, wall terminals) -- a separate palette from the warm
        # muzzle/lightning glow above so a screen reads as its own light
        # source, not a gunshot afterimage.
        screen_sizes = [6, 10, 16]
        self._screen_glow_sizes = screen_sizes
        self._screen_glow_cache = {}
        for r in screen_sizes:
            d = r * 2 + 4
            s = pygame.Surface((d, d))
            cx = cy = d / 2.0
            for yy in range(d):
                for xx in range(d):
                    dist = math.hypot(xx - cx, yy - cy)
                    if dist <= r:
                        a = max(0.0, 1.0 - dist / r)
                        aa = a * a
                        s.set_at((xx, yy), (int(70 * aa), int(200 * aa), int(150 * aa)))
            self._screen_glow_cache[r] = s

    def _bake_vignette(self):
        w, h = INTERNAL_W, INTERNAL_H
        yy, xx = np.mgrid[0:h, 0:w]
        cx, cy = w / 2.0, h / 2.0
        dist = np.sqrt(((xx - cx) / (w / 2.0)) ** 2 + ((yy - cy) / (h / 2.0)) ** 2)

        a = np.clip((dist - 0.62) / 0.6, 0.0, 1.0)
        alpha = (a * 110).astype(np.uint8)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        arr = pygame.surfarray.pixels_alpha(surf)
        arr[:, :] = alpha.T
        del arr
        self._vignette = surf

        a2 = np.clip((dist - 0.20) / 0.85, 0.0, 1.0)
        alpha2 = (a2 * 190).astype(np.uint8)
        surf2 = pygame.Surface((w, h), pygame.SRCALPHA)
        arr2 = pygame.surfarray.pixels_alpha(surf2)
        arr2[:, :] = alpha2.T
        del arr2
        rgb2 = pygame.surfarray.pixels3d(surf2)
        rgb2[:, :, 0] = 160
        rgb2[:, :, 1] = 8
        rgb2[:, :, 2] = 8
        del rgb2
        self._vignette_lowhp = surf2

    def _bake_overlays(self):
        w, h = INTERNAL_W, INTERNAL_H
        hurt = pygame.Surface((w, h), pygame.SRCALPHA)
        hurt.fill((190, 26, 26, 255))
        self._hurt_overlay = hurt
        death = pygame.Surface((w, h), pygame.SRCALPHA)
        death.fill((0, 0, 0, 255))
        self._death_overlay = death

    # ------------------------------------------------------------------
    # fx ingestion (call once per sim tick, after session.tick())
    # ------------------------------------------------------------------

    def consume_fx(self, fx_list) -> None:
        for g in self._gibs:
            g["x"] += g["vx"] * DT
            g["y"] += g["vy"] * DT
            g["vx"] *= GIB_FRICTION
            g["vy"] *= GIB_FRICTION
            g["life"] -= 1
        self._gibs = [g for g in self._gibs if g["life"] > 0][-400:]

        for sp in self._sparks:
            sp["life"] -= 1
        self._sparks = [sp for sp in self._sparks if sp["life"] > 0][-200:]

        for fl in self._flashes:
            fl["life"] -= 1
        self._flashes = [fl for fl in self._flashes if fl["life"] > 0][-30:]

        for b in self._bolts:
            b["life"] -= 1
        self._bolts = [b for b in self._bolts if b["life"] > 0][-30:]

        for sc in self._screams:
            sc["age"] += 1
        self._screams = [sc for sc in self._screams if sc["age"] < sc["maxage"]][-20:]

        for eid in list(self._hitflash):
            self._hitflash[eid] -= 1
            if self._hitflash[eid] <= 0:
                del self._hitflash[eid]

        if self._hurt_ticks > 0:
            self._hurt_ticks -= 1

        for fx in fx_list:
            tag = fx[0]
            if tag == "gib":
                _, room, x, y, n, (dx, dy) = fx
                base_ang = math.atan2(dy, dx) if (dx or dy) else 0.0
                for _ in range(max(0, int(n))):
                    ang = base_ang + random.uniform(-1.1, 1.1)
                    spd = random.uniform(40.0, 220.0)
                    self._gibs.append(dict(
                        room=room, x=x, y=y,
                        vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                        life=random.randint(18, 34), size=random.uniform(1.5, 3.5),
                    ))
            elif tag == "spark":
                _, room, x, y, nx, ny = fx
                self._sparks.append(dict(room=room, x=x, y=y, nx=nx, ny=ny, life=4))
            elif tag == "flash":
                _, room, x, y, radius = fx
                self._flashes.append(dict(room=room, x=x, y=y, radius=radius, life=3))
            elif tag == "holemark":
                _, room, x, y = fx
                self._flashes.append(dict(room=room, x=x, y=y, radius=12.0, life=6))
            elif tag == "holeopen":
                _, room, x, y = fx
                self._flashes.append(dict(room=room, x=x, y=y, radius=26.0, life=8))
            elif tag == "alerted":
                _, room, x, y = fx
                self._screams.append(dict(room=room, x=x, y=y, age=0, maxage=10))
            elif tag == "lightning":
                _, room, x, y, radius = fx
                segs = []
                for _ in range(random.randint(4, 8)):
                    a = random.uniform(0.0, 2.0 * math.pi)
                    r = radius * random.uniform(0.6, 1.0)
                    mid = (math.cos(a) * r * 0.5 + random.uniform(-6, 6),
                           math.sin(a) * r * 0.5 + random.uniform(-6, 6))
                    end = (math.cos(a) * r, math.sin(a) * r)
                    segs.append([(0.0, 0.0), mid, end])
                self._bolts.append(dict(room=room, x=x, y=y, radius=radius, life=6, segs=segs))
            elif tag == "scream":
                _, room, x, y = fx
                self._screams.append(dict(room=room, x=x, y=y, age=0, maxage=16))
            elif tag == "hitflash":
                _, eid = fx
                self._hitflash[eid] = 3
            elif tag == "playerhurt":
                self._hurt_ticks = 2
            elif tag == "playerdie":
                self._dying = True
            # "sound" / "radio" / "terminal" / "weapon" are consumed by
            # audio.py / menus.py, not the renderer.

        if self._dying:
            self._death_fade = min(40, self._death_fade + 1)

    # ------------------------------------------------------------------
    # per-frame draw
    # ------------------------------------------------------------------

    def draw(self, surf: "pygame.Surface", debug: bool = False) -> None:
        surf.fill((0, 0, 0))
        session = self.session
        self._deferred_glows = []
        self._deferred_bolts = []
        self._deferred_screen_glows = []
        instances = session.visible(self.max_depth, self.max_instances)
        for room, xform, depth, clip_screen, walls, entry_edge, ents in instances:
            if len(clip_screen) < 3:
                continue
            self._draw_floor(surf, room, depth, clip_screen)
            self._draw_detail(surf, room, xform, clip_screen, depth)
            self._draw_decals(surf, room, xform, clip_screen)
            self._draw_exit_and_terminals(surf, room, xform, clip_screen)
            self._draw_walls(surf, walls, depth)
            self._draw_doors(surf, room, xform, clip_screen)
            self._draw_entities(surf, ents, clip_screen)
            self._draw_effects(surf, room, xform, clip_screen)
        self._apply_darkness(surf)
        # light sources punch through the dark: muzzle glows and bolts
        for sx, sy, radius, clip_screen in self._deferred_glows:
            self._blit_glow(surf, sx, sy, radius, clip_screen)
        # lit instruments (lab consoles, wall terminals) punch through too —
        # a screen glowing in the dark is exactly what makes a room read as
        # inhabited/functional rather than merely lit for the player's sake
        for sx, sy, radius, clip_screen in self._deferred_screen_glows:
            self._blit_screen_glow(surf, sx, sy, radius, clip_screen)
        for color, pieces, glow in self._deferred_bolts:
            for piece in pieces:
                pygame.draw.lines(surf, color, False, _pts(piece), 1)
            if glow is not None:
                self._blit_glow(surf, *glow)
        self._draw_post(surf)
        if debug:
            self._draw_debug(surf, instances)

    def _apply_darkness(self, surf) -> None:
        """Player-centered radial falloff, multiply-composited over the whole
        world after it draws at uniform brightness. Smooth across portals by
        construction: the field lives in screen space, not room space."""
        size = surf.get_size()
        if self._darkness is None or self._darkness.get_size() != size:
            import numpy as np
            w, h = size
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            cx, cy = w / 2.0, h / 2.0
            d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
            d = np.clip(d / (0.72 * max(w, h)), 0.0, 1.0)
            k = d * d * (3.0 - 2.0 * d)  # smoothstep
            arr = np.empty((h, w, 3), dtype=np.uint8)
            # warm-dark edges: red survives longest (the sun is always there)
            arr[..., 0] = (255 * (1.0 - 0.42 * k)).astype(np.uint8)
            arr[..., 1] = (255 * (1.0 - 0.55 * k)).astype(np.uint8)
            arr[..., 2] = (255 * (1.0 - 0.60 * k)).astype(np.uint8)
            dark = pygame.Surface(size)
            pygame.surfarray.blit_array(dark, arr.swapaxes(0, 1))
            self._darkness = dark
        surf.blit(self._darkness, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

    # -- (1) floor ------------------------------------------------------

    def _draw_floor(self, surf, room, depth, clip_screen):
        dim = _floor_dim(depth)
        tint = _room_tint(room)
        color = _shade(FLOOR_BASE, dim, tint)
        pygame.draw.polygon(surf, color, _pts(clip_screen))

    # -- (2) room detail --------------------------------------------------

    def _portal_edges_for(self, room: int) -> set:
        """(room, edge) pairs that are an open connection, a connect_x
        mirror, or a pending (locked-or-not) door -- computed once for the
        whole level and cached. Room verts/edge indices come from the same
        post-doorway-split geometry the engine itself connects, so this
        lines up exactly with what `necore` considers a portal."""
        if self._portal_edges is None:
            level = self.session.level
            edges: dict[int, set] = {}
            for a, ea, b, eb in level.connects:
                edges.setdefault(a, set()).add(ea)
                edges.setdefault(b, set()).add(eb)
            for a, ea, b, eb, _m in level.connects_x:
                edges.setdefault(a, set()).add(ea)
                edges.setdefault(b, set()).add(eb)
            for d in level.doors:
                edges.setdefault(d.a, set()).add(d.ea)
                edges.setdefault(d.b, set()).add(d.eb)
            self._portal_edges = edges
        return self._portal_edges.get(room, set())

    def _get_detail(self, room: int):
        cached = self._detail_cache.get(room)
        if cached is not None:
            return cached
        level = self.session.level
        if room >= len(level.room_verts):
            return []
        verts = level.room_verts[room]
        seed = level.room_seeds[room] if room < len(level.room_seeds) else room * 7919 + 13
        rng = random.Random(seed)
        kind = level.room_kinds[room] if room < len(level.room_kinds) else "generic"
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        walls = _wall_edges(verts, self._portal_edges_for(room))
        gen = _ROOM_PROP_GENERATORS.get(kind, _props_generic)
        prims = gen(rng, verts, walls, x0, y0, x1, y1)
        self._detail_cache[room] = prims
        return prims

    def _draw_detail(self, surf, room, xform, clip_screen, depth):
        prims = self._get_detail(room)
        if not prims:
            return
        dim = _floor_dim(depth)
        tint = _room_tint(room)
        default_color = _shade(FLOOR_BASE, dim, (tint[0] + 18, tint[1] + 18, tint[2] + 18))
        scale = None
        for prim in prims:
            kind = prim[0]
            if kind == "line":
                (ax, ay), (bx, by) = prim[1], prim[2]
                color = prim[3] if len(prim) > 3 and prim[3] is not None else default_color
                width = prim[4] if len(prim) > 4 else 1
                sx1, sy1 = necore.mat_apply(xform, ax, ay)
                sx2, sy2 = necore.mat_apply(xform, bx, by)
                for seg in necore.clip_polyline([(sx1, sy1), (sx2, sy2)], clip_screen):
                    if len(seg) >= 2:
                        pygame.draw.line(surf, color, _pt(seg[0]), _pt(seg[-1]), width)
            elif kind == "dot":
                x, y = prim[1]
                color = prim[2] if len(prim) > 2 and prim[2] is not None else default_color
                radius = prim[3] if len(prim) > 3 else 1
                sx, sy = necore.mat_apply(xform, x, y)
                if _point_in_poly(sx, sy, clip_screen):
                    pygame.draw.circle(surf, color, _pt((sx, sy)), radius)
            elif kind == "stain":
                color = prim[2] if len(prim) > 2 and prim[2] is not None else default_color
                spoly = [necore.mat_apply(xform, x, y) for x, y in prim[1]]
                clipped = necore.clip_polygon(spoly, clip_screen)
                if len(clipped) >= 3:
                    pygame.draw.polygon(surf, color, _pts(clipped))
            elif kind == "poly":
                # ("poly", local_pts, fill_or_None, outline_or_None, outline_width)
                _, pts_local, fill, outline, ow = prim
                spoly = [necore.mat_apply(xform, x, y) for x, y in pts_local]
                clipped = necore.clip_polygon(spoly, clip_screen)
                if len(clipped) >= 3:
                    cpts = _pts(clipped)
                    if fill is not None:
                        pygame.draw.polygon(surf, fill, cpts)
                    if outline is not None and ow > 0:
                        pygame.draw.polygon(surf, outline, cpts, ow)
            elif kind == "polyline":
                # ("polyline", local_pts, color, width, closed)
                _, pts_local, color, width, closed = prim
                spts = [necore.mat_apply(xform, x, y) for x, y in pts_local]
                if closed and spts:
                    spts = spts + [spts[0]]
                for seg in necore.clip_polyline(spts, clip_screen):
                    if len(seg) >= 2:
                        pygame.draw.lines(surf, color, False, _pts(seg), width)
            elif kind == "screenglow":
                # ("screenglow", x, y, radius) -- registered for the
                # post-darkness punch-through pass, like flashes/bolts
                _, x, y, radius = prim
                sx, sy = necore.mat_apply(xform, x, y)
                if _point_in_poly(sx, sy, clip_screen):
                    if scale is None:
                        scale = _xform_scale(xform)
                    self._deferred_screen_glows.append((sx, sy, radius * scale, clip_screen))

    # -- (3) decals -------------------------------------------------------

    def _draw_decals(self, surf, room, xform, clip_screen):
        decals = self.session.decals.get(room)
        if not decals:
            return
        scale = _xform_scale(xform)
        for kind, x, y, size, angle in decals:
            sx, sy = necore.mat_apply(xform, x, y)
            if not _point_in_poly(sx, sy, clip_screen):
                continue
            dx, dy = necore.mat_apply_dir(xform, math.cos(angle), math.sin(angle))
            sang = math.atan2(dy, dx) if (dx or dy) else 0.0
            self._draw_decal(surf, kind, sx, sy, size, sang, scale)

    def _draw_decal(self, surf, kind, sx, sy, size, angle, scale):
        s = max(1.0, size * scale)
        if kind == "blood":
            # deliberately undersized vs the sim's `size`: heavy fights must
            # stay readable, not fuse into uniform red mush
            pts = _xform_pts(BLOOD_BLOB, sx, sy, s * 0.72, angle)
            pygame.draw.polygon(surf, BLOOD_COLOR, _pts(pts))
        elif kind == "splat":
            pts = _xform_pts(SPLAT_BLOB, sx, sy, s * 0.6, angle)
            pygame.draw.polygon(surf, BLOOD_COLOR, _pts(pts))
        elif kind == "chip":
            p1, p2 = (sx - s, sy - s), (sx + s, sy + s)
            p3, p4 = (sx - s, sy + s), (sx + s, sy - s)
            pygame.draw.line(surf, CHIP_COLOR, _pt(p1), _pt(p2), 1)
            pygame.draw.line(surf, CHIP_COLOR, _pt(p3), _pt(p4), 1)
        elif kind == "scorch":
            pygame.draw.circle(surf, SCORCH_COLOR, _pt((sx, sy)), max(2, int(s)), 1)
        elif kind.startswith("corpse_"):
            ekind = kind[len("corpse_"):]
            if ekind == "player":
                pts = _xform_pts(PLAYER_SHAPE, sx, sy, s * 0.9, angle, squash=0.55)
                color = tuple(int(c * 0.4) for c in PLAYER_COLOR)
            else:
                shape = ENEMY_SHAPE.get(ekind) or _CIRCLE_SHAPE
                pts = _xform_pts(shape, sx, sy, s * 0.9, angle, squash=0.55)
                base = ENEMY_COLOR.get(ekind, (90, 90, 90))
                color = tuple(int(c * 0.45) for c in base)
            pygame.draw.polygon(surf, color, _pts(pts))
            for off in (0.6, -0.6):
                lx, ly = _xform_pts([(off, 0.2)], sx, sy, s * 0.9, angle, squash=0.55)[0]
                pygame.draw.line(surf, color, _pt((sx, sy)), _pt((lx, ly)), 1)

    # -- (4) exit pad + terminals ------------------------------------------

    def _draw_exit_and_terminals(self, surf, room, xform, clip_screen):
        session = self.session
        if session.exit_room == room:
            sx, sy = necore.mat_apply(xform, *session.exit_pos)
            if _point_in_poly(sx, sy, clip_screen):
                phase = (session.tick_count % 90) / 90.0
                r = 9 + 4 * math.sin(phase * 2 * math.pi)
                pygame.draw.circle(surf, EXIT_COLOR, _pt((sx, sy)), max(2, int(r)), 1)
                cx, cy = _pt((sx, sy))
                pygame.draw.polygon(surf, EXIT_COLOR,
                                     [(cx, cy - 5), (cx - 4, cy + 3), (cx + 4, cy + 3)])
        for t in session.terminals:
            if t["room"] != room:
                continue
            self._draw_terminal(surf, room, xform, clip_screen, t)

    def _nearest_wall_point(self, room: int, pos):
        """Nearest point on a room's wall to `pos` (room-local), for
        flush-mounting a fixture. Strongly prefers non-portal edges (a
        console can't hang in a doorway) but falls back to any edge rather
        than returning nothing, since a level always has *some* wall."""
        level = self.session.level
        if room >= len(level.room_verts):
            return None
        verts = level.room_verts[room]
        portals = self._portal_edges_for(room)
        n = len(verts)
        px, py = pos
        best = None
        best_score = 1e18
        for i in range(n):
            x0, y0 = verts[i]
            x1, y1 = verts[(i + 1) % n]
            dx, dy = x1 - x0, y1 - y0
            length2 = dx * dx + dy * dy
            if length2 < 1e-6:
                continue
            t = max(0.08, min(0.92, ((px - x0) * dx + (py - y0) * dy) / length2))
            cx, cy = x0 + dx * t, y0 + dy * t
            d = (cx - px) ** 2 + (cy - py) ** 2
            score = d * (6.0 if i in portals else 1.0)
            if score < best_score:
                best_score = score
                length = math.sqrt(length2)
                nx, ny = _edge_inward_normal(x0, y0, x1, y1)
                best = dict(cx=cx, cy=cy, nx=nx, ny=ny, tx=dx / length, ty=dy / length)
        return best

    def _draw_terminal(self, surf, room, xform, clip_screen, t):
        """A wall-mounted console slab with an inset phosphor screen
        (Marathon-style wall terminal), flush against the nearest wall
        edge -- not a free-standing glyph."""
        bright = not t["read"]
        screen_color = (100, 255, 140) if bright else (55, 110, 75)
        wall = self._nearest_wall_point(room, t["pos"])
        if wall is None:
            # degenerate room (no usable edge) -- keep the old free-standing
            # glyph rather than dropping the terminal entirely
            sx, sy = necore.mat_apply(xform, *t["pos"])
            if not _point_in_poly(sx, sy, clip_screen):
                return
            rect = pygame.Rect(0, 0, 6, 8)
            rect.center = _pt((sx, sy))
            pygame.draw.rect(surf, (20, 30, 24), rect)
            pygame.draw.rect(surf, screen_color, rect, 1)
            return
        cx, cy, nx, ny = wall["cx"], wall["cy"], wall["nx"], wall["ny"]
        ang = math.atan2(wall["ty"], wall["tx"])
        slab_w, slab_d = 13.0, 6.0
        slab_pts = _rect_local(cx + nx * slab_d * 0.5, cy + ny * slab_d * 0.5,
                                slab_w, slab_d, ang)
        spoly = [necore.mat_apply(xform, x, y) for x, y in slab_pts]
        clipped = necore.clip_polygon(spoly, clip_screen)
        if len(clipped) < 3:
            return
        cpts = _pts(clipped)
        pygame.draw.polygon(surf, PROP_DARK, cpts)
        pygame.draw.polygon(surf, PROP_RIM, cpts, 1)
        scr_cx, scr_cy = cx + nx * slab_d * 0.62, cy + ny * slab_d * 0.62
        scr_pts = _rect_local(scr_cx, scr_cy, slab_w * 0.5, slab_d * 0.55, ang)
        sspoly = [necore.mat_apply(xform, x, y) for x, y in scr_pts]
        sclipped = necore.clip_polygon(sspoly, clip_screen)
        if len(sclipped) >= 3:
            pygame.draw.polygon(surf, screen_color, _pts(sclipped))
        if bright:
            ssx, ssy = necore.mat_apply(xform, scr_cx, scr_cy)
            if _point_in_poly(ssx, ssy, clip_screen):
                self._deferred_screen_glows.append(
                    (ssx, ssy, 6.0 * _xform_scale(xform), clip_screen))

    # -- (5) walls + doors --------------------------------------------------

    def _draw_walls(self, surf, walls, depth):
        # Walls are the level's readability skeleton: dim with depth but
        # never below WALL_MIN (floors may go darker than walls ever do).
        dim = _dim(depth)
        c = _shade(WALL_COLOR, dim)
        color = (max(c[0], WALL_MIN[0]), max(c[1], WALL_MIN[1]), max(c[2], WALL_MIN[2]))
        for x1, y1, x2, y2, is_portal in walls:
            if is_portal:
                continue  # seamlessness is sacred: never draw a portal edge
            pygame.draw.line(surf, color, _pt((x1, y1)), _pt((x2, y2)), 2)

    def _draw_doors(self, surf, room, xform, clip_screen):
        sim = self.session.sim
        for (r, e), key in self.session.door_edges.items():
            if r != room:
                continue
            try:
                x1, y1, x2, y2 = sim.edge_endpoints(r, e)
            except Exception:
                continue
            sx1, sy1 = necore.mat_apply(xform, x1, y1)
            sx2, sy2 = necore.mat_apply(xform, x2, y2)
            if key == "shoot":
                # a secret is a wall that keeps its secret: ordinary wall
                # color, one hairline fissure off-center
                for seg in necore.clip_polyline([(sx1, sy1), (sx2, sy2)],
                                                clip_screen):
                    if len(seg) < 2:
                        continue
                    a, b = seg[0], seg[-1]
                    pygame.draw.line(surf, (184, 196, 204), _pt(a), _pt(b), 2)
                    fx_ = a[0] + (b[0] - a[0]) * 0.62
                    fy_ = a[1] + (b[1] - a[1]) * 0.62
                    nx_, ny_ = (b[1] - a[1]), -(b[0] - a[0])
                    ln = max(1e-6, (nx_ * nx_ + ny_ * ny_) ** 0.5)
                    pygame.draw.line(surf, (90, 96, 104), _pt((fx_, fy_)),
                                     _pt((fx_ + 3 * nx_ / ln,
                                          fy_ + 3 * ny_ / ln)), 1)
                continue
            color = KEY_COLORS.get(key, DOOR_COLOR)
            for seg in necore.clip_polyline([(sx1, sy1), (sx2, sy2)], clip_screen):
                if len(seg) < 2:
                    continue
                a, b = seg[0], seg[-1]
                pygame.draw.line(surf, color, _pt(a), _pt(b), 3)
                mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
                rect = pygame.Rect(0, 0, 4, 4)
                rect.center = _pt((mx, my))
                pygame.draw.rect(surf, color, rect)

    # -- (6) entities -------------------------------------------------------

    def _role_kind(self, eid: int):
        s = self.session
        if eid == s.pid:
            return "player", None
        e = s.enemies.get(eid)
        if e is not None:
            return "enemy", e["kind"]
        b = s.bullets.get(eid)
        if b is not None:
            return "bullet", b["kind"]
        p = s.pickups.get(eid)
        if p is not None:
            return "pickup", p["kind"]
        return None, None

    def _draw_entities(self, surf, ents, clip_screen):
        for eid, sx, sy, dirx, diry, srad, fully_inside in ents:
            role, kind = self._role_kind(eid)
            if role is None:
                continue
            ang = math.atan2(diry, dirx) if (dirx or diry) else 0.0
            if role == "player":
                pts = _xform_pts(PLAYER_SHAPE, sx, sy, max(srad, 2.0), ang)
                if not fully_inside:
                    pts = necore.clip_polygon(pts, clip_screen)
                    if len(pts) < 3:
                        continue
                pygame.draw.polygon(surf, PLAYER_COLOR, _pts(pts))
                pygame.draw.polygon(surf, (255, 255, 255), _pts(pts), 1)
            elif role == "enemy":
                self._draw_enemy(surf, eid, kind, sx, sy, ang, srad, clip_screen, fully_inside)
            elif role == "bullet":
                self._draw_bullet(surf, kind, sx, sy, dirx, diry, clip_screen)
            elif role == "pickup":
                self._draw_pickup(surf, kind, sx, sy, srad, clip_screen)

    def _draw_enemy(self, surf, eid, kind, sx, sy, ang, srad, clip_screen, fully_inside):
        flashed = self._hitflash.get(eid, 0) > 0
        fill = ENEMY_COLOR.get(kind, (150, 150, 150))
        rim = ENEMY_RIM.get(kind) or _brighten(fill, 70)
        if flashed:
            fill = rim = (255, 255, 255)
        if kind == "mite":
            if not _point_in_poly(sx, sy, clip_screen) and not fully_inside:
                return
            r = max(1, int(round(srad * 0.85)))
            pygame.draw.circle(surf, fill, _pt((sx, sy)), r)
            pygame.draw.circle(surf, rim, _pt((sx, sy)), r, 1)
            return
        shape = ENEMY_SHAPE.get(kind, _CIRCLE_SHAPE)
        pts = _xform_pts(shape, sx, sy, max(srad, 2.0), ang)
        if not fully_inside:
            pts = necore.clip_polygon(pts, clip_screen)
            if len(pts) < 3:
                return
        pygame.draw.polygon(surf, fill, _pts(pts))
        pygame.draw.polygon(surf, rim, _pts(pts), ENEMY_RIM_W.get(kind, 1))
        if kind == "husk" and not flashed:
            pygame.draw.circle(surf, (66, 78, 62), _pt((sx, sy)), max(1, int(srad * 0.22)))

    def _draw_bullet(self, surf, kind, sx, sy, dirx, diry, clip_screen):
        if not _point_in_poly(sx, sy, clip_screen):
            return
        if kind == "spit":
            pygame.draw.circle(surf, (140, 205, 60), _pt((sx, sy)), 2)
        elif kind == "dart":
            color = (120, 240, 255)
            base_ang = math.atan2(diry, dirx) if (dirx or diry) else 0.0
            for a in range(4):
                ang = base_ang + a * math.pi / 2.0
                ex, ey = sx + math.cos(ang) * 4, sy + math.sin(ang) * 4
                pygame.draw.line(surf, color, _pt((sx, sy)), _pt((ex, ey)), 1)
            pygame.draw.circle(surf, color, _pt((sx, sy)), 2)
        else:  # "bullet" / "tracer"
            color = (255, 245, 180)
            tx, ty = sx - dirx * 12, sy - diry * 12
            pygame.draw.line(surf, color, _pt((sx, sy)), _pt((tx, ty)), 1)
            pygame.draw.circle(surf, color, _pt((sx, sy)), 2)

    def _draw_pickup(self, surf, kind, sx, sy, srad, clip_screen):
        if not _point_in_poly(sx, sy, clip_screen):
            return
        r = max(2.5, srad)
        ix, iy = _pt((sx, sy))
        if kind == "ammo_9mm":
            rect = pygame.Rect(0, 0, int(r * 1.6), int(r * 1.2))
            rect.center = (ix, iy)
            pygame.draw.rect(surf, (200, 150, 40), rect)
        elif kind == "ammo_shell":
            rect = pygame.Rect(0, 0, int(r * 1.6), int(r * 1.2))
            rect.center = (ix, iy)
            pygame.draw.rect(surf, (180, 60, 50), rect)
        elif kind == "ammo_cell":
            pygame.draw.circle(surf, (60, 200, 220), (ix, iy), max(2, int(r * 0.8)))
            pygame.draw.circle(surf, (200, 250, 255), (ix, iy), max(2, int(r * 0.8)), 1)
        elif kind == "medkit":
            rect = pygame.Rect(0, 0, int(r * 1.8), int(r * 1.8))
            rect.center = (ix, iy)
            pygame.draw.rect(surf, (40, 40, 44), rect)
            pygame.draw.line(surf, (235, 235, 235),
                              (ix - int(r * 0.6), iy), (ix + int(r * 0.6), iy), 2)
            pygame.draw.line(surf, (235, 235, 235),
                              (ix, iy - int(r * 0.6)), (ix, iy + int(r * 0.6)), 2)
        elif kind == "turret":
            # a re-sworn guardian: squat tripod, thin bright rim
            pts = [(ix, iy - int(r)), (ix - int(r * 0.9), iy + int(r * 0.7)),
                   (ix + int(r * 0.9), iy + int(r * 0.7))]
            pygame.draw.polygon(surf, (46, 58, 66), pts)
            pygame.draw.polygon(surf, (150, 220, 235), pts, 1)
            pygame.draw.circle(surf, (150, 220, 235), (ix, iy), 2)
        elif kind == "safe_room_core":
            pygame.draw.circle(surf, (30, 26, 44), (ix, iy), max(3, int(r)))
            pygame.draw.circle(surf, (170, 140, 255), (ix, iy), max(3, int(r)), 1)
            pygame.draw.circle(surf, (220, 205, 255), (ix, iy), 1)
        elif kind.startswith("weapon_"):
            pygame.draw.rect(surf, (190, 195, 200),
                              pygame.Rect(ix - int(r), iy - 1, int(r * 2), 2))
            pygame.draw.rect(surf, (190, 195, 200),
                              pygame.Rect(ix - int(r * 0.3), iy - int(r * 0.7),
                                          max(1, int(r * 0.4)), int(r * 0.7)))
        elif kind == "implant_lightning":
            pts = [(ix, iy - r), (ix + r, iy), (ix, iy + r), (ix - r, iy)]
            pygame.draw.polygon(surf, (90, 220, 255), [(int(x), int(y)) for x, y in pts])
        elif kind.startswith("key_"):
            col = KEY_COLORS.get(kind[4:], DOOR_COLOR)
            pygame.draw.circle(surf, col, (ix - int(r * 0.3), iy), max(1, int(r * 0.5)), 1)
            pygame.draw.line(surf, col, (ix, iy), (ix + int(r), iy), 1)
            pygame.draw.line(surf, col, (ix + int(r * 0.6), iy),
                              (ix + int(r * 0.6), iy + int(r * 0.4)), 1)

    # -- (7) particles / effects pools --------------------------------------

    def _blit_glow(self, surf, sx, sy, radius, clip_screen):
        if radius <= 1:
            return
        best = min(self._glow_sizes, key=lambda r: abs(r - radius))
        img = self._glow_cache[best]
        iw, ih = img.get_size()
        dest = (int(sx - iw / 2), int(sy - ih / 2))
        xs = [p[0] for p in clip_screen]
        ys = [p[1] for p in clip_screen]
        clip_rect = pygame.Rect(int(min(xs)), int(min(ys)),
                                 int(max(xs) - min(xs)) + 1, int(max(ys) - min(ys)) + 1)
        prev_clip = surf.get_clip()
        surf.set_clip(clip_rect)
        surf.blit(img, dest, special_flags=pygame.BLEND_RGB_ADD)
        surf.set_clip(prev_clip)

    def _blit_screen_glow(self, surf, sx, sy, radius, clip_screen):
        if radius <= 1:
            return
        best = min(self._screen_glow_sizes, key=lambda r: abs(r - radius))
        img = self._screen_glow_cache[best]
        iw, ih = img.get_size()
        dest = (int(sx - iw / 2), int(sy - ih / 2))
        xs = [p[0] for p in clip_screen]
        ys = [p[1] for p in clip_screen]
        clip_rect = pygame.Rect(int(min(xs)), int(min(ys)),
                                 int(max(xs) - min(xs)) + 1, int(max(ys) - min(ys)) + 1)
        prev_clip = surf.get_clip()
        surf.set_clip(clip_rect)
        surf.blit(img, dest, special_flags=pygame.BLEND_RGB_ADD)
        surf.set_clip(prev_clip)

    def _draw_effects(self, surf, room, xform, clip_screen):
        scale = _xform_scale(xform)

        for g in self._gibs:
            if g["room"] != room:
                continue
            sx, sy = necore.mat_apply(xform, g["x"], g["y"])
            if not _point_in_poly(sx, sy, clip_screen):
                continue
            r = max(1, int(g["size"] * scale * 0.5))
            pygame.draw.circle(surf, GIB_COLOR, _pt((sx, sy)), r)

        for sp in self._sparks:
            if sp["room"] != room:
                continue
            sx, sy = necore.mat_apply(xform, sp["x"], sp["y"])
            if not _point_in_poly(sx, sy, clip_screen):
                continue
            ndx, ndy = necore.mat_apply_dir(xform, sp["nx"], sp["ny"])
            nl = math.hypot(ndx, ndy) or 1.0
            ex, ey = sx + ndx / nl * 5, sy + ndy / nl * 5
            pygame.draw.line(surf, SPARK_COLOR, _pt((sx, sy)), _pt((ex, ey)), 1)

        for fl in self._flashes:
            if fl["room"] != room:
                continue
            sx, sy = necore.mat_apply(xform, fl["x"], fl["y"])
            self._deferred_glows.append((sx, sy, fl["radius"] * scale, clip_screen))

        for b in self._bolts:
            if b["room"] != room:
                continue
            sx, sy = necore.mat_apply(xform, b["x"], b["y"])
            pieces = []
            if b["life"] % 2 == 0:
                for seg in b["segs"]:
                    spts = []
                    for dx, dy in seg:
                        wdx, wdy = necore.mat_apply_dir(xform, dx, dy)
                        spts.append((sx + wdx, sy + wdy))
                    for piece in necore.clip_polyline(spts, clip_screen):
                        if len(piece) >= 2:
                            pieces.append(piece)
            self._deferred_bolts.append(
                (LIGHTNING_COLOR, pieces,
                 (sx, sy, b["radius"] * scale * 0.6, clip_screen)))

        for sc in self._screams:
            if sc["room"] != room:
                continue
            sx, sy = necore.mat_apply(xform, sc["x"], sc["y"])
            if not _point_in_poly(sx, sy, clip_screen):
                continue
            t = sc["age"] / sc["maxage"]
            for ring_off in (0, 6):
                rad = int((6 + ring_off) + t * 20)
                pygame.draw.circle(surf, SCREAM_COLOR, _pt((sx, sy)), rad, 1)

    # -- (8) post -------------------------------------------------------

    def _draw_post(self, surf):
        session = self.session
        if session.hp < 35 and not session.dead:
            pulse = 0.55 + 0.45 * math.sin(session.tick_count * 0.25)
            a = max(0, min(255, int(150 * pulse)))
            self._vignette_lowhp.set_alpha(a)
            surf.blit(self._vignette_lowhp, (0, 0))
        if self._hurt_ticks > 0:
            # pain reads at the screen edges (red vignette) + a faint cast;
            # the center of the world must stay readable through the flash
            k = self._hurt_ticks / 2.0
            self._vignette_lowhp.set_alpha(int(230 * k))
            surf.blit(self._vignette_lowhp, (0, 0))
            self._hurt_overlay.set_alpha(int(36 * k))
            surf.blit(self._hurt_overlay, (0, 0))
        if session.dead and self._death_fade > 0:
            a = min(255, int(255 * self._death_fade / 40))
            self._death_overlay.set_alpha(a)
            surf.blit(self._death_overlay, (0, 0))

    # -- debug ------------------------------------------------------------

    def _draw_debug(self, surf, instances):
        if self._font is None:
            if not pygame.font.get_init():
                pygame.font.init()
            self._font = pygame.font.Font(None, 12)
        for room, xform, depth, clip_screen, walls, entry_edge, ents in instances:
            if not clip_screen:
                continue
            cx = sum(p[0] for p in clip_screen) / len(clip_screen)
            cy = sum(p[1] for p in clip_screen) / len(clip_screen)
            img = self._font.render(f"r{room} d{depth}", True, (255, 0, 255))
            surf.blit(img, (cx - 12, cy - 6))
