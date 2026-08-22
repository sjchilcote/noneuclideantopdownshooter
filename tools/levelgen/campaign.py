"""PERIHELION campaign generator.

Ten levels along the escalation curve of design_document_2.md §8.1:
deniable wrongness -> confirmable paradox -> overt impossibility -> pure graph.

Authoring style: rooms are drawn adjacent on the canvas; the level builder's
doorway-splitter turns any short wall segment shared with a longer wall into
an opening automatically. Impossible connections are added with connect_pts
(edge chosen by midpoint, resolved after splitting). no_connect keeps a
shared wall solid.

Run: uv run python tools/levelgen/campaign.py   (writes levels/*.json)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "game"))

from perihelion.levels import LevelBuilder, save_level  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "levels"


def center(b: LevelBuilder, room: int) -> tuple[float, float]:
    vs = b.data["rooms"][room]["verts"]
    return (sum(v[0] for v in vs) / len(vs), sum(v[1] for v in vs) / len(vs))


def squad(b: LevelBuilder, room: int, spec: str, spread: float = 32.0):
    kinds = spec.split()
    cx, cy = center(b, room)
    n = len(kinds)
    for i, k in enumerate(kinds):
        a = 2 * math.pi * i / max(1, n) + 0.7
        r = spread if n > 1 else 0.0
        b.entity(room, k, (cx + r * math.cos(a), cy + r * math.sin(a)))


def wall_basis(b: LevelBuilder, room: int, wall: int, t: float = 0.5):
    """(mx, my, tx, ty, nx, ny) for edge `wall` of `room` in absolute-canvas
    (authoring) coordinates: a point `t` along the wall, its tangent, and its
    inward normal (toward the room's own centroid). For any room authored
    with `LevelBuilder.rect(x, y, w, h)`, edge indices are stable and known:
    0=west, 1=south, 2=east, 3=north (verified against rect()'s vertex
    order) -- pass that index explicitly rather than guessing. For irregular
    rooms (ngons, polys), the caller is responsible for picking a `wall`
    index that is not a portal edge (see LEVEL_DESIGN_PLAYBOOK.md §5)."""
    verts = b.data["rooms"][room]["verts"]
    n = len(verts)
    cx = sum(v[0] for v in verts) / n
    cy = sum(v[1] for v in verts) / n
    x0, y0 = verts[wall % n]
    x1, y1 = verts[(wall + 1) % n]
    mx, my = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    tx, ty = dx / length, dy / length
    nx, ny = -dy / length, dx / length
    if (cx - mx) * nx + (cy - my) * ny < 0:
        nx, ny = -nx, -ny
    return mx, my, tx, ty, nx, ny


def wall_pos(b: LevelBuilder, room: int, wall: int, t: float = 0.5,
             inset: float = 15.0) -> tuple[float, float]:
    """A point `inset` units in from wall `wall` of `room`, `t` along its
    length -- a wall alcove for a fixture placement
    (LEVEL_DESIGN_PLAYBOOK.md §4), never a room's floor-center."""
    mx, my, tx, ty, nx, ny = wall_basis(b, room, wall, t)
    return (mx + nx * inset, my + ny * inset)


def cache(b: LevelBuilder, room: int, spec: str, off=(0.0, 0.0),
          wall: int | None = None, t: float = 0.5, inset: float = 16.0):
    """Place a supply cache. Default (`wall=None`): a literal offset from
    room-center, `off` -- kept for paradox-critical spots and irregular
    rooms where a wall index must be hand-verified against portal edges
    first. Pass `wall=<edge index>` to rack the cache in a single row along
    that wall's tangent instead (locker/shelf framing, LEVEL_DESIGN_
    PLAYBOOK.md §5) -- safe for any `LevelBuilder.rect` room using the
    stable 0=west/1=south/2=east/3=north edge order."""
    if wall is not None:
        mx, my, tx, ty, nx, ny = wall_basis(b, room, wall, t)
        bx, by = mx + nx * inset, my + ny * inset
        items = spec.split()
        span = (len(items) - 1) * 13.0
        for i, k in enumerate(items):
            tt = -span / 2.0 + i * 13.0
            b.entity(room, k, (bx + tx * tt, by + ty * tt))
        return
    cx, cy = center(b, room)
    for i, k in enumerate(spec.split()):
        b.entity(room, k, (cx + off[0] + (i % 3) * 15 - 15,
                           cy + off[1] + (i // 3) * 15))


def sector_ring(b, cx, cy, r_in, r_out, n, a0, a1) -> list[int]:
    rooms = []
    for i in range(n):
        t0 = a0 + (a1 - a0) * i / n
        t1 = a0 + (a1 - a0) * (i + 1) / n
        rooms.append(b.poly([
            (cx + r_in * math.cos(t0), cy + r_in * math.sin(t0)),
            (cx + r_in * math.cos(t1), cy + r_in * math.sin(t1)),
            (cx + r_out * math.cos(t1), cy + r_out * math.sin(t1)),
            (cx + r_out * math.cos(t0), cy + r_out * math.sin(t0)),
        ]))
    return rooms


def arc_mid(cx, cy, r, t):
    return (cx + r * math.cos(t), cy + r * math.sin(t))


# ---------------------------------------------------------------------------
# L1 — DOCK SWEEP. Deniable: the storage ring holds nine segments in an
# eight-segment footprint.
# ---------------------------------------------------------------------------

def l01():
    b = LevelBuilder("DOCK 4 — SWEEP", 1, "amb_drone_early")
    # NOTE: an editor golden-fixture test (game/tests/test_editor.py) loads
    # levels/l01.json and hardcodes its exact room count/order/indices
    # (room 0 = dock, room 3, room 7 = exit, room 11 = phantom...) -- this
    # level's room list is load-bearing for a test outside this file's
    # scope, so no new rooms are added here even though an entry airlock
    # would otherwise be the obvious circulation fix (see
    # LEVEL_DESIGN_PLAYBOOK.md §2). dock itself already plays that role:
    # it's where the seed prints the player's body, sized like a threshold.
    dock = b.rect(0, 0, 220, 180, kind="dock")
    hall = b.rect(220, 60, 340, 70, kind="corridor")   # auto-split into dock
    junction = b.rect(560, 20, 140, 140, kind="transit")

    # 3x3 ring around the junction, pitch 140; junction touches N/W/S/E ring
    # cells but only the north doorway may open. Tag every cell `storage`.
    ring_nw = b.rect(420, -120, 140, 140, kind="storage")
    ring_n = b.rect(560, -120, 140, 140, kind="storage")
    ring_ne = b.rect(700, -120, 140, 140, kind="storage")
    ring_e = b.rect(700, 20, 140, 140, kind="storage")
    ring_se = b.rect(700, 160, 140, 140, kind="storage")
    ring_s = b.rect(560, 160, 140, 140, kind="storage")
    ring_sw = b.rect(420, 160, 140, 140, kind="storage")
    ring_w = b.rect(420, 20, 140, 140, kind="storage")
    phantom = b.rect(960, -420, 140, 140, kind="storage")  # the ninth segment

    # only the south hatch of the ring answers; and the ring is broken just
    # short of the exit, so the sweep goes the long way round -- through the
    # segment that is not on any deck plan.
    for r in (ring_n, ring_w, ring_e):
        b.no_connect(junction, r)
    b.no_connect(ring_s, ring_se)
    b.no_connect(ring_nw, ring_n)
    b.connect_pts(ring_nw, (560, -50), phantom, (960, -350))
    b.connect_pts(phantom, (1100, -350), ring_n, (560, -50))

    b.player(dock, (80, 90))
    squad(b, ring_sw, "husk")
    squad(b, ring_w, "husk husk")
    squad(b, phantom, "husk husk")
    squad(b, ring_ne, "husk")
    squad(b, ring_e, "husk")
    cache(b, ring_nw, "ammo_9mm", wall=0)
    cache(b, phantom, "ammo_9mm medkit", wall=1)
    cache(b, ring_sw, "ammo_9mm", wall=1)
    b.entity(dock, "medkit", wall_pos(b, dock, 3, 0.75, 15.0))
    b.exit(ring_se, (770, 230))
    return b


# ---------------------------------------------------------------------------
# L2 — COOLANT ROW. Deniable-going-on-odd: a pump room whose north hatch
# drops you back into a different pump room facing the other way. Mites.
# Red key, SMG.
# ---------------------------------------------------------------------------

def l02():
    b = LevelBuilder("COOLANT ROW", 1, "amb_drone_early")
    entry = b.rect(0, 0, 160, 140, kind="corridor")
    row = b.rect(160, 30, 560, 80, kind="corridor")
    pump_a = b.rect(240, -200, 160, 230, kind="pump")   # bay opens into the row
    pump_b = b.rect(760, -170, 160, 200, kind="pump")   # sits over the tail
    tail = b.rect(720, 30, 220, 80, kind="corridor")
    stub = b.rect(300, 110, 70, 80, kind="corridor")
    keyroom = b.rect(240, 190, 190, 160, kind="pump")   # the filter room
    armory = b.rect(940, 30, 140, 80, kind="storage")

    # the impossible hatch: out pump A's north wall, in through pump B's
    # north wall — you emerge walking the way you came.
    b.connect_pts(pump_a, (320, -200), pump_b, (840, -170))
    b.door_pts(tail, (940, 70), armory, (940, 70), "red")
    b.no_connect(tail, armory)  # the door IS the only opening

    b.player(entry, (70, 70))
    squad(b, row, "mite mite mite mite")
    squad(b, pump_a, "husk mite mite")
    squad(b, pump_b, "husk husk")
    squad(b, keyroom, "mite mite mite mite mite spitter")
    squad(b, tail, "spitter husk")
    b.entity(keyroom, "key_red", (335, 270))
    cache(b, pump_a, "ammo_9mm", wall=2)
    cache(b, pump_b, "medkit ammo_9mm", wall=2)
    cache(b, row, "medkit", off=(180, 0))
    # racked just inside the only door into the armory (the red door from
    # the tail) -- the exit pad sits mid-room and the streamer carves its
    # spine doorway wherever the nearest wall happens to be, so a cache
    # placed "at the exit" is not reliably on the walk; the doorway itself
    # is the one point every route through this room shares.
    cache(b, armory, "weapon_smg ammo_9mm ammo_9mm", wall=0, t=0.5, inset=12.0)
    b.exit(armory, (1010, 70))
    return b


# ---------------------------------------------------------------------------
# L3 — HYDROPONICS TORUS. Confirmable: walking half an arc is a full loop;
# you come back rotated. Shotgun. Brute.
# ---------------------------------------------------------------------------

def l03():
    b = LevelBuilder("HYDROPONICS TORUS", 2, "amb_drone_mid")
    ring = sector_ring(b, 0, 0, 180, 320, 6,
                       math.radians(-90), math.radians(90))
    for r in ring:
        b.set_kind(r, "lab")   # hydroponics benches, the ring's own function
    # entry room sized to the outer chord (165.6) to keep portals rigid
    entry = b.poly([(-83, -440), (-83, -320), (83, -320), (83, -440)])
    b.set_kind(entry, "corridor")
    garden = b.rect(400, -80, 166, 160, kind="lab")
    storeroom = b.rect(-420, 40, 166, 140, kind="storage")

    b.connect_pts(entry, (0, -320), ring[0],
                  arc_mid(0, 0, 320, math.radians(-75)))
    # the mobius glue: end face to start face
    b.connect_pts(ring[5], arc_mid(0, 0, 250, math.radians(90)),
                  ring[0], arc_mid(0, 0, 250, math.radians(-90)))
    b.door_pts(ring[2], arc_mid(0, 0, 320, math.radians(-15)),
               garden, (400, 0), "blue")
    b.connect_pts(ring[3], arc_mid(0, 0, 320, math.radians(15)),
                  storeroom, (-254, 110))

    b.player(entry, (0, -380))
    squad(b, ring[1], "husk husk")
    squad(b, ring[2], "mite mite mite husk")
    squad(b, ring[4], "spitter husk")
    squad(b, ring[5], "brute")
    squad(b, garden, "mite mite mite")
    b.entity(ring[5], "key_blue",
             tuple(arc_mid(0, 0, 250, math.radians(75))))
    # ring[0] is the ring's sole doorway from the entry -- unlike every
    # later cell, the mobius glue offers no shortcut around it, so the
    # level's namesake shotgun goes here rather than in the storeroom
    # detour (which a shortest-path walk of the ring can skip entirely).
    # placed at the entry threshold (just inside ring[0]'s outer arc, where
    # the player necessarily first stands) rather than the wedge's middle
    # or its far inner wall -- both routing choices out of ring[0] (the
    # chain or the mobius glue) start from this exact point, so the pickup
    # doesn't depend on which way the walk goes.
    cache(b, ring[0], "weapon_shotgun ammo_shell", off=(16.4, -61.3))
    cache(b, ring[1], "ammo_9mm", off=(-32.9, 32.9))
    cache(b, ring[3], "medkit", off=(-44.9, -12.0))
    cache(b, ring[4], "medkit ammo_9mm", off=(-32.9, -32.9))
    cache(b, storeroom, "ammo_shell ammo_shell", wall=1, t=0.2, inset=16.0)
    b.exit(garden, (483, 40))
    return b


# ---------------------------------------------------------------------------
# L4 — THE LONG GALLERY. Confirmable: four crossings southside, three
# northside. Shrieker. The implant.
# ---------------------------------------------------------------------------

def l04():
    b = LevelBuilder("THE LONG GALLERY", 2, "amb_drone_mid")
    entry = b.rect(-160, 200, 160, 110, kind="corridor")
    south = b.rect(0, 200, 760, 110, kind="corridor")
    north = b.rect(0, -110, 760, 110, kind="corridor")
    crossings = [b.rect(80 + i * 180, 0, 70, 200, kind="corridor")
                 for i in range(4)]
    # crossing 0 opens south only: its north mouth is a blank wall
    b.no_connect(north, crossings[0])
    reliquary = b.rect(280, 310, 200, 150, kind="medbay")
    vault = b.rect(760, 310, 170, 150, kind="storage")
    b.door_pts(south, (760, 255), vault, (760, 385), "blue")
    b.no_connect(south, vault)

    b.player(entry, (-80, 255))
    squad(b, south, "husk husk mite mite")
    squad(b, crossings[1], "shrieker")
    squad(b, crossings[2], "husk husk husk")
    squad(b, north, "spitter spitter brute")
    squad(b, reliquary, "husk husk spitter")
    # the key lives in the crossing that doesn't exist from the north side
    b.entity(crossings[0], "key_blue", (115, 60))
    cache(b, crossings[0], "ammo_shell medkit", wall=3)  # the blank north wall
    cache(b, north, "ammo_9mm ammo_9mm medkit", off=(300, 0))
    cache(b, south, "ammo_shell", off=(-260, 0))
    # the west-entry/east-exit line runs straight through vault center at
    # y=385 -- every route from the blue door to the exit pad crosses it.
    cache(b, vault, "implant_lightning medkit ammo_9mm")
    b.exit(vault, (890, 385))
    return b


# ---------------------------------------------------------------------------
# L5 — TWO WINGS. Two wings, one volume. Rail gun.
# ---------------------------------------------------------------------------

def l05():
    b = LevelBuilder("TWO WINGS", 3, "amb_drone_mid")
    lobby = b.rect(0, 0, 220, 180, kind="corridor")
    w1 = b.rect(-180, 10, 180, 160, kind="quarters")
    w2 = b.rect(-360, 10, 180, 160, kind="quarters")
    w3 = b.rect(-540, 10, 180, 160, kind="quarters")
    e1 = b.rect(1180, 10, 180, 160, kind="quarters")
    e2 = b.rect(1000, 10, 180, 160, kind="quarters")
    e3 = b.rect(820, 10, 180, 160, kind="quarters")
    chapel = b.rect(-540, 300, 220, 160, kind="chapel")

    bunk_f = b.rect(-160, -110, 140, 120, kind="quarters")  # the third twelve, flush above w1
    b.door_pts(w1, (-90, 10), bunk_f, (-90, 10), "shoot")
    b.no_connect(w1, bunk_f)
    b.connect_pts(lobby, (220, 90), e1, (1360, 90))   # east door, impossible
    b.connect_pts(w3, (-450, 170), chapel, (-430, 300))
    b.connect_pts(e3, (820, 90), chapel, (-320, 380))  # east wall of chapel

    b.player(lobby, (110, 90))
    cache(b, bunk_f, "ammo_cell ammo_cell medkit ammo_shell")
    squad(b, w1, "husk husk")
    squad(b, w2, "husk mite mite mite")
    squad(b, w3, "brute")
    cache(b, w1, "medkit")
    squad(b, e1, "spitter husk")
    squad(b, e2, "husk husk")
    squad(b, e3, "spitter husk")
    squad(b, chapel, "spitter husk")
    cache(b, w2, "ammo_9mm ammo_shell")
    cache(b, e2, "medkit ammo_9mm")
    cache(b, w3, "ammo_shell")
    # chapel has two independent entries (north from w3, east from e3) and
    # the run only ever walks ONE wing before the gold key it needs -- a
    # single cache can sit unreached on the wing not taken, so the rail and
    # the hole are each racked at both doorways rather than once at center.
    cache(b, chapel, "weapon_rail ammo_cell medkit portable_hole", off=(0, -70))
    cache(b, chapel, "weapon_rail ammo_cell portable_hole", off=(105, 0))
    # two identical gold keys, in the same bunk, in both wings
    b.entity(w1, "key_gold", (-90, 40))
    b.entity(e1, "key_gold", (1270, 40))
    b.exit(chapel, (-430, 420), key="gold")
    return b


# ---------------------------------------------------------------------------
# L6 — MIRROR WARD. The mirror room. Things come out of it.
# ---------------------------------------------------------------------------

def l06():
    b = LevelBuilder("MIRROR WARD", 3, "amb_drone_late")
    entry = b.rect(0, 0, 140, 140, kind="corridor")
    hall = b.rect(140, 20, 420, 100, kind="corridor")
    ward = b.rect(560, 20, 240, 100, kind="medbay")
    side = b.rect(560, -120, 240, 140, kind="medbay")
    morgue = b.rect(800, 20, 180, 100, kind="medbay")

    # THE MIRROR: the ward's south wall connects to itself.
    b.connect_pts(ward, (680, 120), ward, (680, 120))

    b.player(entry, (70, 70))
    squad(b, hall, "husk husk mite mite")
    squad(b, ward, "husk husk husk husk")
    squad(b, side, "spitter")
    squad(b, morgue, "brute shrieker")
    cache(b, hall, "ammo_9mm", off=(-120, 0))
    cache(b, side, "weapon_tau ammo_cell medkit", wall=3, t=0.4, inset=16.0)
    # morgue is the level's only exit room, entered from the west (ward)
    # wall at the same height (y=70) as the exit pad -- the tau rack sits
    # right at that threshold so the walk to the exit can't miss it, the
    # way the smg rack in COOLANT ROW's armory does.
    cache(b, morgue, "weapon_tau ammo_cell", wall=0, t=0.5, inset=12.0)
    cache(b, morgue, "ammo_shell ammo_shell medkit", off=(30, 0))
    # the seal sits against the mirror wall: to leave, you must walk up to
    # your own reflection
    b.entity(ward, "key_red", (680, 108))
    b.exit(morgue, (930, 70), key="red")
    return b


# ---------------------------------------------------------------------------
# L7 — RECURSION STACK. The infinite corridor.
# ---------------------------------------------------------------------------

def l07():
    b = LevelBuilder("RECURSION STACK", 3, "amb_drone_late")
    entry = b.rect(0, 0, 160, 140, kind="corridor")
    stack = b.rect(300, 0, 220, 140, kind="records")
    closet = b.rect(700, 300, 120, 140, kind="core")     # the staff-mind cores
    deep = b.rect(700, -300, 200, 140, kind="records")

    annex = b.rect(740, -390, 120, 90, kind="records")   # the aisle before aisle one
    b.door_pts(deep, (800, -300), annex, (800, -300), "shoot")
    b.no_connect(deep, annex)
    b.connect_pts(entry, (160, 70), stack, (300, 70))
    # the endless aisle: top of the stack feeds its own bottom
    b.connect_pts(stack, (410, 0), stack, (410, 140))
    b.connect_pts(stack, (520, 70), closet, (700, 370))
    b.connect_pts(closet, (820, 370), deep, (700, -230))

    b.player(entry, (80, 70))
    cache(b, annex, "ammo_cell ammo_cell medkit")
    squad(b, stack, "mite mite mite mite mite mite")
    squad(b, closet, "spitter spitter")
    squad(b, deep, "brute brute shrieker")
    cache(b, stack, "ammo_9mm ammo_shell", off=(60, 30))  # the aisle has no free wall
    cache(b, closet, "medkit ammo_cell portable_hole", wall=3, t=0.6, inset=16.0)
    cache(b, deep, "medkit ammo_cell ammo_shell", wall=0, t=0.5, inset=14.0)
    b.entity(closet, "key_gold", (735, 335))
    b.exit(deep, (860, -230), key="gold")
    return b


# ---------------------------------------------------------------------------
# L8 — THE FOLD. Six petals around a heart; every route adds a room that
# was already there. Warden's first stand.
# ---------------------------------------------------------------------------

def l08():
    b = LevelBuilder("THE FOLD", 4, "amb_drone_late")
    b.data["alert_hops"] = 1  # the fold eats sound
    # `core` is the chapel's own heart -- SERMON text below -- kept a real
    # kind despite the pure-graph tier; `petals` stay `generic` on purpose
    # (see LEVEL_DESIGN_PLAYBOOK.md §8): six visually-identical cells is the
    # paradox ("the count depends on the walker"), not a tagging gap.
    core = b.ngon(0, 0, 100, 6, phase=math.radians(90), kind="chapel")
    petals = []
    angs = []
    for i in range(6):
        a = math.radians(90) - (i + 0.5) * math.pi / 3
        angs.append(a)
        petals.append(b.ngon(260 * math.cos(a), 260 * math.sin(a), 100, 6,
                             phase=a + math.radians(90), kind="generic"))
    for i, a in enumerate(angs):
        b.connect_pts(core, (86.6 * math.cos(a), 86.6 * math.sin(a)),
                      petals[i],
                      (260 * math.cos(a) - 86.6 * math.cos(a),
                       260 * math.sin(a) - 86.6 * math.sin(a)))
    # fold: each petal's far-right edge to the far-left edge of petal i+2
    for i in range(6):
        j = (i + 2) % 6
        ai, aj = angs[i], angs[j]
        pi_c = (260 * math.cos(ai), 260 * math.sin(ai))
        pj_c = (260 * math.cos(aj), 260 * math.sin(aj))
        b.connect_pts(
            petals[i], (pi_c[0] + 86.6 * math.cos(ai - math.pi / 3),
                        pi_c[1] + 86.6 * math.sin(ai - math.pi / 3)),
            petals[j], (pj_c[0] + 86.6 * math.cos(aj + math.pi / 3),
                        pj_c[1] + 86.6 * math.sin(aj + math.pi / 3)))

    b.player(petals[0], center(b, petals[0]))
    squad(b, core, "warden")
    b.data["rooms"][core]["entities"][-1]["props"] = {"hp": 180, "tether": 1}
    petal_squads = ["husk", "spitter", "mite mite mite",
                    "brute", "shrieker", "spitter"]
    petal_caches = ["ammo_9mm ammo_shell medkit", "medkit", "medkit ammo_cell",
                    "ammo_shell medkit", "ammo_shell ammo_9mm", "medkit"]
    for i, p in enumerate(petals):
        squad(b, p, petal_squads[i])
        if petal_caches[i]:
            cache(b, p, petal_caches[i])
    cache(b, core, "medkit medkit ammo_cell ammo_shell ammo_9mm safe_room_core portable_hole")
    b.exit(core, (0, 40), gate_kind="warden")
    return b


# ---------------------------------------------------------------------------
# L9 — TESSERACT DECK. Sixteen identical rooms on a 4-cube. Pure graph.
# ---------------------------------------------------------------------------

def l09():
    b = LevelBuilder("TESSERACT DECK", 4, "amb_drone_finale")
    rooms = []
    for i in range(16):
        x, y = (i % 4) * 400, (i // 4) * 400
        # cut-corner square: one sealed diagonal face per room — the only
        # solid wall on the deck, an anchor for the eye and the seam the
        # world can be entered through
        rooms.append(b.poly([(x, y), (x, y + 200), (x + 100, y + 200),
                             (x + 200, y + 100), (x + 200, y)],
                            seed=1000 + i))
        # pure-graph tier: sixteen address-bearing cells, deliberately
        # uniform (LEVEL_DESIGN_PLAYBOOK.md §8) -- not a tagging gap.
        b.set_kind(rooms[-1], "generic")
    # dims 0..3 live on edges [0,1,3,4]; edge 2 is the chamfer wall -- the
    # only wall every one of the sixteen rooms has in common, so it is
    # where every fixture in this level goes.
    DIM_EDGE = [0, 1, 3, 4]
    CHAMFER = 2
    for i in range(16):
        for d in range(4):
            j = i ^ (1 << d)
            if i < j:
                b.connect(rooms[i], DIM_EDGE[d], rooms[j], DIM_EDGE[d])

    c15 = center(b, rooms[15])
    b.player(rooms[0], center(b, rooms[0]))
    squad(b, rooms[3], "husk husk")
    squad(b, rooms[5], "spitter spitter")
    squad(b, rooms[6], "brute")
    squad(b, rooms[9], "shrieker mite mite")
    squad(b, rooms[10], "husk spitter")
    squad(b, rooms[12], "brute shrieker")
    squad(b, rooms[15], "brute brute")
    cache(b, rooms[4], "ammo_9mm ammo_shell", wall=CHAMFER)
    cache(b, rooms[8], "medkit ammo_cell portable_hole", wall=CHAMFER)
    cache(b, rooms[7], "ammo_shell ammo_9mm medkit", wall=CHAMFER)
    cache(b, rooms[13], "ammo_cell ammo_shell", wall=CHAMFER)
    cache(b, rooms[6], "medkit", wall=CHAMFER)
    cache(b, rooms[12], "medkit", wall=CHAMFER)
    c10 = center(b, rooms[10])
    b.entity(rooms[10], "key_void", (c10[0] - 60, c10[1]))
    b.exit(rooms[15], (c15[0] + 60, c15[1]), key="void")
    return b


# ---------------------------------------------------------------------------
# L10 — PERIHELION CORE. Cayley graph of Z6 with generators {+1,+2}; the
# Container; the Warden. Guard ending.
# ---------------------------------------------------------------------------

def l10():
    b = LevelBuilder("PERIHELION CORE", 4, "amb_drone_finale")
    b.data["alert_hops"] = 1  # sound folds strangely between identical rooms
    airlock = b.rect(0, 10, 160, 120, kind="corridor")
    hexes = []
    for i in range(6):
        x, y = 400 + (i % 3) * 360, (i // 3) * 360
        hexes.append(b.ngon(x, y, 120, 6, phase=math.radians(30),
                            seed=2000 + i, kind="core"))
    # edge 0 faces east, edge 3 west (phase 30): r-generator chains 0->3;
    # s-generator uses edges 1 and 4. Edge 2 is claimed by the alcove/
    # sanctum doors below on hexes[1]/[3] specifically -- edge 5 is the one
    # wall every hex has in common and free, so fixtures rack there.
    HEX_FREE = 5
    for i in range(6):
        b.connect(hexes[i], 0, hexes[(i + 1) % 6], 3)
    for i in range(6):
        b.connect(hexes[i], 1, hexes[(i + 2) % 6], 4)
    sanctum = b.ngon(1600, 180, 157, 8, phase=math.radians(22.5), seed=3000,
                     kind="core")

    # hex edges 0/1/3/4 belong to the Cayley wiring; edge 2 (up-left) is free
    alcove = b.rect(1240, 560, 120, 100, kind="quarters")  # the first watcher's post
    b.door_pts(hexes[1], (812, 90), alcove, (1300, 560), "shoot")
    b.connect_pts(airlock, (160, 70), hexes[0], (348, -90))
    # sanctum behind the void seal, off hex 3's remaining edge (2)
    b.door(a=hexes[3], ea=2, b=sanctum, eb=4, key="void")

    b.player(airlock, (80, 70))
    cache(b, alcove, "medkit ammo_cell", wall=0, t=0.5, inset=14.0)
    # the streamer respawns a chunk-9 death right back at this airlock at
    # floor-40 hp (stream.py's entry-snapshot restore) -- a small emergency
    # kit at the threshold keeps a hard respawn from spiraling immediately.
    cache(b, airlock, "medkit ammo_9mm", wall=1, t=0.5, inset=14.0)
    squad(b, hexes[1], "husk husk husk")
    squad(b, hexes[2], "spitter brute")
    squad(b, hexes[4], "brute mite")
    squad(b, hexes[5], "husk husk spitter")
    squad(b, hexes[3], "brute")
    squad(b, sanctum, "warden")
    for _e in b.data["rooms"][sanctum]["entities"]:
        if _e["type"] == "warden":
            _e["props"] = {"tether": 1}
    cache(b, hexes[2], "ammo_cell ammo_shell medkit medkit", wall=HEX_FREE)
    cache(b, hexes[4], "ammo_9mm ammo_9mm ammo_shell", wall=HEX_FREE)
    cache(b, hexes[5], "medkit medkit ammo_cell medkit", wall=HEX_FREE)
    b.entity(hexes[5], "key_void",
             (center(b, hexes[5])[0], center(b, hexes[5])[1] - 60))
    cache(b, sanctum, "medkit ammo_cell ammo_shell", wall=6)
    b.exit(sanctum, (1600, 180), gate_kind="warden")
    return b



# ---------------------------------------------------------------------------
# THE VIGIL — endless holdout on a fold arena. "Things still come through,
# some decades. They are met."
# ---------------------------------------------------------------------------

def vigil():
    b = LevelBuilder("THE VIGIL", 4, "amb_drone_finale")
    b.data["vigil"] = True
    b.data["alert_hops"] = 1
    # same fold shape as THE FOLD (L8): the heart is a real place (the
    # watch is kept here), the petals stay uniform on purpose (see
    # LEVEL_DESIGN_PLAYBOOK.md §8) since every wave arrives identically.
    core = b.ngon(0, 0, 110, 6, phase=math.radians(90), kind="chapel")
    petals = []
    angs = []
    for i in range(6):
        a = math.radians(90) - (i + 0.5) * math.pi / 3
        angs.append(a)
        petals.append(b.ngon(280 * math.cos(a), 280 * math.sin(a), 110, 6,
                             phase=a + math.radians(90), seed=4000 + i,
                             kind="generic"))
    for i, a in enumerate(angs):
        b.connect_pts(core, (95.3 * math.cos(a), 95.3 * math.sin(a)),
                      petals[i],
                      (280 * math.cos(a) - 95.3 * math.cos(a),
                       280 * math.sin(a) - 95.3 * math.sin(a)))
    for i in range(6):
        j = (i + 2) % 6
        ai, aj = angs[i], angs[j]
        pi_c = (280 * math.cos(ai), 280 * math.sin(ai))
        pj_c = (280 * math.cos(aj), 280 * math.sin(aj))
        b.connect_pts(
            petals[i], (pi_c[0] + 95.3 * math.cos(ai - math.pi / 3),
                        pi_c[1] + 95.3 * math.sin(ai - math.pi / 3)),
            petals[j], (pj_c[0] + 95.3 * math.cos(aj + math.pi / 3),
                        pj_c[1] + 95.3 * math.sin(aj + math.pi / 3)))
    b.player(core, (0, 0))
    cache(b, core, "medkit ammo_9mm ammo_shell")
    return b



LEVELS = [l01, l02, l03, l04, l05, l06, l07, l08, l09, l10]


def main():
    OUT.mkdir(exist_ok=True)
    manifest = []
    kinds = ("husk", "mite", "spitter", "brute", "shrieker", "warden")
    for i, fn in enumerate(LEVELS, 1):
        b = fn()
        final = b.to_dict()
        lvl = b.build()  # validates winding/schema/spawn
        name = f"l{i:02d}.json"
        save_level(final, OUT / name)
        manifest.append(f"levels/{name}")
        n_enemies = sum(1 for _, e in lvl.entities if e.type in kinds)
        print(f"{name}: {lvl.name!r} rooms={len(lvl.room_verts)} "
              f"connects={len(lvl.connects)} doors={len(lvl.doors)} "
              f"enemies={n_enemies}")
    vb = vigil()
    vb.build()
    save_level(vb.to_dict(), OUT / "vigil.json")
    print("vigil.json: THE VIGIL arena")
    (OUT / "campaign.json").write_text(json.dumps({"levels": manifest}, indent=1))
    print(f"campaign.json: {len(manifest)} levels")


if __name__ == "__main__":
    main()
