"""Immediate-mode renderer: necore draw lists -> a 480x270 pygame.Surface.

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

INTERNAL_W, INTERNAL_H = 480, 270

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
    return max(0.42, 0.88 ** depth)


def _floor_dim(depth: int) -> tuple[float, float, float]:
    """Per-channel floor dimming: red decays slowest, blue fastest, so deeper
    instances drift warm — a deliberate, depth-driven sun-red cast (the
    station is falling into the sun)."""
    return (max(0.52, 0.92 ** depth),
            max(0.42, 0.86 ** depth),
            max(0.38, 0.83 ** depth))


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


class Renderer:
    """`Renderer(session).draw(surf, debug=False)` paints one frame.

    `surf` must be a 480x270 pygame.Surface. Immediate-mode: nothing is
    retained across frames except the effect pools and the per-room detail
    cache (both intentionally persistent — grime is stable per room, decals
    live in `session.decals`).
    """

    def __init__(self, session, max_depth: int = 14, max_instances: int = 96):
        self.session = session
        self.max_depth = max_depth
        self.max_instances = max_instances

        self._detail_cache: dict[int, list] = {}

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
        self._draw_post(surf)
        if debug:
            self._draw_debug(surf, instances)

    # -- (1) floor ------------------------------------------------------

    def _draw_floor(self, surf, room, depth, clip_screen):
        dim = _floor_dim(depth)
        tint = _room_tint(room)
        color = _shade(FLOOR_BASE, dim, tint)
        pygame.draw.polygon(surf, color, _pts(clip_screen))

    # -- (2) room detail --------------------------------------------------

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
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        prims = []
        for _ in range(rng.randint(3, 8)):
            if rng.random() < 0.5:
                yy = rng.uniform(y0, y1)
                prims.append(("line", (rng.uniform(x0, x1), yy), (rng.uniform(x0, x1), yy)))
            else:
                xx = rng.uniform(x0, x1)
                prims.append(("line", (xx, rng.uniform(y0, y1)), (xx, rng.uniform(y0, y1))))
        for _ in range(rng.randint(6, 14)):
            prims.append(("dot", (rng.uniform(x0, x1), rng.uniform(y0, y1))))
        for _ in range(rng.randint(1, 2)):
            cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
            rad = rng.uniform(6, 16)
            n = rng.randint(6, 9)
            poly = []
            for i in range(n):
                a = i * 2.0 * math.pi / n + rng.uniform(-0.2, 0.2)
                r = rad * rng.uniform(0.6, 1.0)
                poly.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
            prims.append(("stain", poly))
        self._detail_cache[room] = prims
        return prims

    def _draw_detail(self, surf, room, xform, clip_screen, depth):
        prims = self._get_detail(room)
        if not prims:
            return
        dim = _floor_dim(depth)
        tint = _room_tint(room)
        color = _shade(FLOOR_BASE, dim, (tint[0] + 18, tint[1] + 18, tint[2] + 18))
        for prim in prims:
            kind = prim[0]
            if kind == "line":
                (ax, ay), (bx, by) = prim[1], prim[2]
                sx1, sy1 = necore.mat_apply(xform, ax, ay)
                sx2, sy2 = necore.mat_apply(xform, bx, by)
                for seg in necore.clip_polyline([(sx1, sy1), (sx2, sy2)], clip_screen):
                    if len(seg) >= 2:
                        pygame.draw.line(surf, color, _pt(seg[0]), _pt(seg[-1]), 1)
            elif kind == "dot":
                x, y = prim[1]
                sx, sy = necore.mat_apply(xform, x, y)
                if _point_in_poly(sx, sy, clip_screen):
                    pygame.draw.circle(surf, color, _pt((sx, sy)), 1)
            elif kind == "stain":
                spoly = [necore.mat_apply(xform, x, y) for x, y in prim[1]]
                clipped = necore.clip_polygon(spoly, clip_screen)
                if len(clipped) >= 3:
                    pygame.draw.polygon(surf, color, _pts(clipped))

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
            sx, sy = necore.mat_apply(xform, *t["pos"])
            if not _point_in_poly(sx, sy, clip_screen):
                continue
            ix, iy = _pt((sx, sy))
            bright = not t["read"]
            color = (100, 255, 140) if bright else (55, 110, 75)
            rect = pygame.Rect(0, 0, 6, 8)
            rect.center = (ix, iy)
            pygame.draw.rect(surf, (20, 30, 24), rect)
            pygame.draw.rect(surf, color, rect, 1)

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
            self._blit_glow(surf, sx, sy, fl["radius"] * scale, clip_screen)

        for b in self._bolts:
            if b["room"] != room:
                continue
            sx, sy = necore.mat_apply(xform, b["x"], b["y"])
            if b["life"] % 2 == 0:
                for seg in b["segs"]:
                    spts = []
                    for dx, dy in seg:
                        wdx, wdy = necore.mat_apply_dir(xform, dx, dy)
                        spts.append((sx + wdx, sy + wdy))
                    for piece in necore.clip_polyline(spts, clip_screen):
                        if len(piece) >= 2:
                            pygame.draw.lines(surf, LIGHTNING_COLOR, False, _pts(piece), 1)
            self._blit_glow(surf, sx, sy, b["radius"] * scale * 0.6, clip_screen)

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
        surf.blit(self._vignette, (0, 0))
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
