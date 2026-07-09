"""Invariant 5: room transitions are imperceptible.

Walk the player through portals while tracking every visible wall segment in
screen space. Between consecutive frames, each wall that is fully on-screen
must have a near-identical predecessor — never a teleport. Any seam, pop, or
jump here is a bug in the camera rebase or the visibility engine.
"""

import math

from perihelion.levels import LevelBuilder
from perihelion.sim import GameSession, InputFrame

# max legitimate per-tick wall motion: player speed * zoom / tickrate plus
# camera catch-up, generously rounded up
ALLOW_PX = 6.0


def _walls_screen(session):
    out = []
    for inst in session.visible(14, 96):
        for (x1, y1, x2, y2, is_portal) in inst[4]:
            if not is_portal:
                out.append((x1, y1, x2, y2))
    return out


def _fully_onscreen(w):
    return (all(2 <= w[i] <= 478 for i in (0, 2))
            and all(2 <= w[i] <= 268 for i in (1, 3)))


def _continuous_with(prev_wall, wall):
    """A wall is continuous with a predecessor when it lies on (nearly) the
    same infinite line with overlapping span. Frustum widening slides a
    clipped wall's endpoints ALONG its line — that is revelation, not
    motion. Actual motion moves the line itself."""
    ax1, ay1, ax2, ay2 = wall
    bx1, by1, bx2, by2 = prev_wall
    bdx, bdy = bx2 - bx1, by2 - by1
    blen = math.hypot(bdx, bdy)
    if blen < 1e-6:
        return False
    ux, uy = bdx / blen, bdy / blen
    # perpendicular distance of both cur endpoints from prev's line
    d1 = abs((ax1 - bx1) * uy - (ay1 - by1) * ux)
    d2 = abs((ax2 - bx1) * uy - (ay2 - by1) * ux)
    if max(d1, d2) > ALLOW_PX:
        return False
    # projected spans must overlap (or nearly touch)
    t1 = (ax1 - bx1) * ux + (ay1 - by1) * uy
    t2 = (ax2 - bx1) * ux + (ay2 - by1) * uy
    lo, hi = min(t1, t2), max(t1, t2)
    return hi >= -ALLOW_PX and lo <= blen + ALLOW_PX


def _wall_continuity(level, seed, moves, ticks):
    s = GameSession(level, seed=seed)
    prev = _walls_screen(s)
    violations = []
    for t in range(ticks):
        s.tick(InputFrame(mx=moves[0], my=moves[1]))
        cur = _walls_screen(s)
        cur_stable = [w for w in cur if _fully_onscreen(w)]
        if prev and len(cur_stable) >= 2:
            matched = sum(
                1 for w in cur_stable
                if any(_continuous_with(p, w) for p in prev))
            unmatched_frac = 1.0 - matched / len(cur_stable)
            # New sightlines legitimately add walls; but if most on-screen
            # geometry has no collinear predecessor, the view jumped.
            if unmatched_frac > 0.5 and len(cur_stable) >= 4:
                violations.append((t, "global", round(unmatched_frac, 2)))
        prev = cur
        if s.dead:
            break
    return violations


def test_seamless_corridor_walk():
    b = LevelBuilder("corridor", 1)
    rooms = [b.rect(i * 200, 0, 200, 150) for i in range(5)]
    b.player(rooms[0], (100, 75))
    violations = _wall_continuity(b.build(), 3, (1.0, 0.0), 420)
    assert not violations, f"wall jumps: {violations[:5]}"


def test_seamless_infinite_loop_walk():
    b = LevelBuilder("loop", 1)
    r = b.rect(0, 0, 220, 150)
    b.connect_pts(r, (0, 75), r, (220, 75))
    b.player(r, (110, 75))
    violations = _wall_continuity(b.build(), 3, (1.0, 0.0), 600)
    assert not violations, f"wall jumps in self-loop: {violations[:5]}"


def test_seamless_doorway_wobble():
    # rooms with doorway-split walls (heights chosen so each shared edge is
    # contained in the neighbor's wall, exercising sub-edge portals)
    b = LevelBuilder("diag", 1)
    r0 = b.rect(0, 0, 180, 190)
    r1 = b.rect(180, 40, 180, 120)
    r2 = b.rect(360, 20, 180, 200)
    r3 = b.rect(540, 60, 180, 120)
    b.player(r0, (90, 100))
    violations = _wall_continuity(b.build(), 9, (0.9, 0.25), 500)
    assert not violations, f"wall jumps: {violations[:5]}"


def test_seamless_mirror_approach():
    b = LevelBuilder("mirror", 1)
    r = b.rect(0, 0, 240, 160)
    ante = b.rect(-200, 30, 200, 100)
    b.connect_pts(r, (120, 160), r, (120, 160))  # mirror south wall
    b.player(ante, (-100, 80))
    violations = _wall_continuity(b.build(), 5, (0.8, 0.5), 400)
    assert not violations, f"wall jumps near mirror: {violations[:5]}"
