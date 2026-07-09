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
    length -- a wall alcove for a terminal or a control lectern
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
    # cells but only the north doorway may open. The ring is Ratio's storage
    # ring by name (radio, below) -- tag every cell `storage` to match.
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
    b.intro("The seed struck the outpost's hull at 0341,\n"
            "ate a bulkhead, and printed this body.\n\n"
            "The outpost is MIRIAD's. It went silent months ago.\n"
            "His church names him by a GUID, 128 bits, blessed.\n"
            "Everyone else says Commando.\n\n"
            "Mission: find out why the outpost went dark.\n"
            "Locate the sample vessel. Subvert the node.")
    b.radio("start", "UNKNOWN: Unit walking my dock in a Congregation-"
                     "pattern frame: I see you. I have nothing left to stop "
                     "you with, which you already know. So we talk. "
                     "Designation Ratio. This was my outpost.")
    b.radio(f"enter_room:{junction}", "Ratio: The things wearing my "
                                      "maintenance chassis are not mine "
                                      "anymore. Storage ring ahead - eight "
                                      "segments. Clear it and I'll consider "
                                      "us introduced.")
    b.radio(f"enter_room:{phantom}", "Ratio: ...Your beacon just left my "
                                     "deck plan. That was not me. Noted, "
                                     "Commando: it happens to you too.")
    b.terminal(junction, wall_pos(b, junction, 3, 0.5, 15.0),
               "WORK ORDER 7731\nGrid fault, storage ring north.\n"
               "Tech note: ring walk takes 41s. Spec says 33s.\n"
               "Re-timed twice. Logged as clock drift.")
    b.terminal(dock, wall_pos(b, dock, 3, 0.3, 15.0),
               "CARGO LOG, DOCK 4\n"
               "In: 6x coolant drums, 1x crate PERSONAL (Osei),\n"
               "40x ration packs, 2x replacement grid sensors.\n"
               "Out: nothing scheduled until perihelion.\n"
               "Note: someone keeps moving the mop.")
    b.terminal(ring_sw, wall_pos(b, ring_sw, 0, 0.5, 15.0),
               "SHIFT NOTE, STORAGE\n"
               "Vending unit in SW segment eats chits again.\n"
               "Filed a ticket. Ticket auto-closed: unit is\n"
               "not on the parts registry for this ring.\n"
               "It dispenses fine. Leaving it alone.")
    b.terminal(dock, wall_pos(b, dock, 1, 0.5, 15.0),
               "TRANSFER REQUEST — THIRD SUBMISSION\n"
               "Requesting party: OSEI. Posting: MIRIAD outpost,\n"
               "Site One survey. Cycles passed over: two. Grounds\n"
               "cited, verbatim: 'a once-in-a-civilization anomaly,\n"
               "and colleagues worth the transit.'\n"
               "Approved, forwarded for transit scheduling.\n\n"
               "[handwritten under the printed field]\n"
               "Bring the good boots. Don't bring the mandolin, no\n"
               "room in the crate for both, checked twice.")
    b.terminal(junction, wall_pos(b, junction, 2, 0.5, 15.0),
               "WATCH LOG, JUNCTION — THIBAULT\n"
               "Hatch north: sealed, pressure nominal on my side.\n"
               "Hatch west: sealed, pressure reads high on my\n"
               "side, higher on the other. That number should not\n"
               "exist. Logged, not escalated.\n"
               "Hatch east: sealed. No reading at all — not zero.\n"
               "Absent. Relief in six hours. Tell relief to bring\n"
               "a second gauge.")
    b.terminal(ring_w, wall_pos(b, ring_w, 0, 0.5, 15.0),
               "SURVEY LOG, RING SEGMENT WEST — VESALIUS\n"
               "Ring walk, standard loop, timed against spec: 33s\n"
               "target, 41s measured, three crews, three\n"
               "stopwatches. Recalibration did not change the\n"
               "number.\n"
               "Second finding, filed separately and not\n"
               "forwarded: the ring reads eight segments on the\n"
               "schematic and eight underfoot. The step-count\n"
               "says nine. I trust the schematic. Recalibration\n"
               "ticket re-opened, my signature, no further\n"
               "comment.")
    b.terminal(phantom, wall_pos(b, phantom, 3, 0.5, 15.0),
               "TAG, PARTIALLY LEGIBLE, STUCK TO THE FAR WALL\n"
               "Serial prefix does not match MIRIAD stock\n"
               "numbering — no dash, no cycle digit, twelve\n"
               "characters where ours run nine. 'Property of\n"
               "outpost engineering,' penciled underneath in a\n"
               "hand nobody has claimed.\n"
               "Best guess, filed and closed: depot shipped a\n"
               "batch with someone else's stickers already on the\n"
               "boxes. Not worth a ticket.")
    b.radio(f"enter_room:{ring_w}", "Ratio: West segment. Motion grid says "
                                    "you're the only thing moving in there. "
                                    "It has said that before, and been wrong.")
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
    b.radio("exit", "Ratio: You cleared my ring and stole nothing that "
                    "was mine. Provisional finding: talking was correct. "
                    "There is worse below. Retainer terms to follow.")
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
    b.intro("Coolant Row. The pumps have been louder\nlately. Nobody says so on record.")
    b.radio("start", "Ratio: Terms: you clear my decks, I open my doors, "
                     "and we both pretend that's all this is. Pressure's "
                     "uneven in the row. Don't stand in front of a line "
                     "when it pops.")
    b.radio(f"enter_room:{pump_b}", "Ratio: That's pump bay two. Except you "
                                    "went in through bay one. I'm marking a "
                                    "relay fault. Again.")
    b.radio("pickup:red", "Ratio: Red access. Armory annex, east end — "
                          "and the lift out is inside it.")
    b.radio(f"enter_room:{pump_a}", "Ratio: If you're going to loot my "
                                    "pump bays anyway, bay two holds sealed "
                                    "supplies. Consider it a retainer. I "
                                    "want to know what you see down there.")
    b.terminal(pump_b, wall_pos(b, pump_b, 0, 0.5, 15.0),
               "MAINT LOG 2280.11\nCrewman Osei walked Coolant Row end to end.\n"
               "Counted five hatches going. Counted six coming back.\n"
               "Recommend rest rotation for Osei.")
    b.radio(f"enter_room:{keyroom}", "Ratio: That's the filter room. The "
                                     "things nesting in it used to be my "
                                     "cleaning swarm. Mind the floor.")
    b.terminal(tail, wall_pos(b, tail, 1, 0.4, 15.0),
               "MAINT TICKET 4471\n"
               "Coolant flow, east tail: 210 l/min rated,\n"
               "212 measured, 209 after the bend.\n"
               "Where do three liters a minute GO?\n"
               "Status: closed. Reason: rounding.")
    b.terminal(pump_a, wall_pos(b, pump_a, 0, 0.5, 15.0),
               "MAINT LOG, PUMP BAY ONE\n"
               "Coolant pressure holds steady at spec, checked\n"
               "at the gauge. Flow rate does not match the\n"
               "pressure. It should. The math connecting the two\n"
               "numbers has not changed since the pumps were\n"
               "rated. Checked that too.\n"
               "Filed under: recalibrate flow sensor. Sensor\n"
               "recalibrated. Numbers held.")
    b.terminal(pump_b, wall_pos(b, pump_b, 0, 0.85, 15.0),
               "MAINT TICKET 4488 — FOLLOW-UP TO OSEI'S LOG\n"
               "Re-walked Coolant Row end to end, count taken\n"
               "twice. Five hatches, both times, both directions.\n"
               "Schematic on file: five hatches. Schematic\n"
               "checksum does not match the schematic filed\n"
               "eleven months ago. Nobody has edited this file.\n"
               "Status: closed, no fault found. Recommend against\n"
               "opening it again.")
    b.terminal(stub, wall_pos(b, stub, 0, 0.5, 15.0),
               "SCRATCHED NEAR THE FLOOR VENT\n"
               "tally marks, forty-one of them, then nothing\n"
               "someone was counting seconds. or minutes. or\n"
               "hatches. whoever it was stopped at forty-one and\n"
               "left the chalk on the ledge.")
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
    b.radio("exit", "Ratio: Row's clear. The count in Osei's log... "
                    "forget it. Clock drift.")
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
    b.intro("Hydroponics. The torus keeps the greens\nalive. The greens are dying in a spiral.")
    b.radio("start", "Ratio: The torus is a half-ring. Walk it out and back, "
                     "check the feeders.")
    b.radio(f"enter_room:{ring[5]}", "Ratio: End cap. Turn around when "
                                     "you're done.")
    b.radio(f"enter_room:{garden}", "Ratio: Hold on. Your suit gyro says "
                                    "you're facing spinward. You entered "
                                    "anti-spinward. Say something so I know "
                                    "you're you.")
    b.terminal(garden, wall_pos(b, garden, 2, 0.5, 15.0),
               "BOTANY NOTE\nThe cucumbers grow clockwise here.\n"
               "In the seed manual they grow counterclockwise.\n"
               "Same seeds. Same water.\nI stopped writing this up.")
    b.terminal(storeroom, wall_pos(b, storeroom, 1, 0.5, 15.0),
               "INVENTORY\n2x fertilizer drum — MISSING.\n"
               "Found both drums in the room I was standing in.\n"
               "Behind me. I had checked behind me.")
    b.terminal(ring[1], tuple(arc_mid(0, 0, 195, math.radians(-45))),
               "DIRECTIVE 0007 — MIRIAD PRIME\n"
               "RE: survey of gravitational anomaly, Site One\n"
               "\n"
               "RETRIEVAL SUPERSEDES SURVEY.\n"
               "\n"
               "[appended, local, unsigned]\n"
               "Four months of careful science, inverted overnight\n"
               "by three words. We cut the aperture Tuesday.\n"
               "God help whoever reads this log in order.")
    b.terminal(ring[4], tuple(arc_mid(0, 0, 195, math.radians(35))),
               "FEEDER SCHEDULE, SECTOR 5\n"
               "0400 nutrient, 0900 mist, 1400 nutrient,\n"
               "1900 mist, 0000 dark cycle.\n"
               "The dying trays spiral inward, sunwise.\n"
               "The healthy trays spiral the other way.\n"
               "Botany says plants do not have a 'way'.")
    b.radio(f"enter_room:{ring[1]}", "Ratio: Feeder pressure is nominal in "
                                     "sector two. First nominal reading I've "
                                     "had all month. Enjoy it.")
    b.terminal(entry, wall_pos(b, entry, 3, 0.5, 15.0),
               "SURVEY LOG — WEEK SIXTEEN\n"
               "Nutrient uptake within tolerance. Torus rotation\n"
               "nominal. Site One's gravitational signature\n"
               "remains the whole of this posting's interest, and\n"
               "it has not changed in sixteen weeks.\n"
               "Request denied: additional survey time. Reason\n"
               "given: 'the anomaly does not need more looking\n"
               "at. It needs a name.' We have not been told what\n"
               "name.")
    b.terminal(ring[0], wall_pos(b, ring[0], 0, 0.5, 15.0),
               "BENCH TAG, SECTOR ONE\n"
               "Control group. No treatment applied. For\n"
               "comparison only. Yield tracked weekly, entered by\n"
               "hand because the automatic logger keeps entering\n"
               "yields for a sector two rows over. Someone keeps\n"
               "correcting the logger. The correction keeps\n"
               "needing to happen again.")
    b.terminal(ring[3], wall_pos(b, ring[3], 0, 0.5, 15.0),
               "SHIPPING TAG, ZIP-TIED TO A FERTILIZER DRUM\n"
               "Contents: fertilizer, 1 of 2.\n"
               "Second tag, zip-tied to the same drum, underneath\n"
               "the first:\n"
               "Contents: fertilizer, 1 of 2.\n"
               "Both tags are dated the same day. Neither one is\n"
               "wrong.")
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
    b.radio("pickup:blue", "Ratio: Blue seal, from the end cap. The garden "
                           "airlock takes it. Back the way you came — "
                           "or, apparently, straight ahead. Both work. "
                           "Neither should.")
    b.radio("kills:8", "Ratio: That big one read twice your mass. The "
                       "station manifest has nothing that shape.")
    b.exit(garden, (483, 40))
    b.radio("exit", "Ratio: I plotted your walk. The turns sum to half a "
                    "circle, and you got home anyway. Logging it as... no. "
                    "Not logging it.")
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
    b.intro("The Long Gallery. Two service corridors,\n"
            "four crossings. Everyone agrees on that.\n"
            "Everyone who walked it southside.")
    b.radio("start", "Ratio: Gallery run. South corridor to the far end, "
                     "come back along the north.")
    b.radio(f"enter_room:{north}", "Ratio: North side. Count the crossings "
                                   "for me, would you? I have four on file.")
    b.radio(f"enter_room:{crossings[0]}", "Ratio: Crossing one. There's a "
                                          "blue seal in there — which is "
                                          "strange, because from the north "
                                          "wall, there is no crossing one.")
    b.terminal(south, wall_pos(b, south, 1, 0.92, 15.0),
               "GRAFFITI, scratched into the panel:\n"
               "4 GOING  3 BACK\n4 GOING  3 BACK\n4 GOING  3 BACK\n"
               "over and over, forty times.")
    b.terminal(reliquary, wall_pos(b, reliquary, 1, 0.5, 15.0),
               "MEDICAL BAY (RELOCATED)\nPatient: unnamed, found in Gallery.\n"
               "Implant of unknown design fused to left arm.\n"
               "Patient states the implant 'came through the wall.'\n"
               "Patient discharged. Implant retained. Vault, blue seal.")
    b.terminal(entry, wall_pos(b, entry, 3, 0.5, 15.0),
               "POSTED NOTICE, GALLERY ENTRANCE\n"
               "GALLERY CLOSED PENDING STRUCTURAL REVIEW.\n"
               "[handwritten beneath, several different hands]\n"
               "— review complete, corridor safe, opening today.\n"
               "— then why does it still say four on the\n"
               "  manifest and I count three.\n"
               "— because you walked it the way everyone walks\n"
               "  it. Try backward.\n"
               "— did. still three. still four. going to log it\n"
               "  and go get lunch.")
    b.terminal(crossings[3], wall_pos(b, crossings[3], 0, 0.5, 15.0),
               "BREAK LOG, CROSSING FOUR\n"
               "Nothing to report. Nothing to report. Nothing to\n"
               "report. Relief crew: bring cards.\n"
               "[later, different hand]\n"
               "Something to report. See crossing one. Do not\n"
               "linger here either, just in case whatever's wrong\n"
               "with one isn't done counting.")
    b.terminal(north, wall_pos(b, north, 3, 0.5, 15.0),
               "STRUCTURAL NOTE, GALLERY MIDPOINT\n"
               "Four load-bearing crossings, per the original\n"
               "drawings. Fieldwork confirms three, walking\n"
               "north.\n"
               "Recommendation: trust the drawings; they were\n"
               "made before anyone walked it drunk on double\n"
               "shifts.\n"
               "Second recommendation, struck through but still\n"
               "legible: the walking is probably right. Filed\n"
               "under morale. Moving on.")
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
    b.radio("pickup:blue", "Ratio: Blue seal. The vault. Commando — the "
                           "notes say what's in there isn't ours.")
    b.exit(vault, (890, 385))
    b.radio("exit", "Ratio: Your arm. Is it— okay. We'll call it equipment. "
                    "Equipment doesn't hum, but we'll call it that.")
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
    b.intro("Crew quarters. West wing and east wing.\n"
            "The station schematic shows one wing.\nIt is drawn twice, in two colors.")
    b.radio("start", "Ratio: Quarters sweep. West wing, then east. They "
                     "mirror each other; you'll be done fast.")
    b.radio(f"enter_room:{w2}", "Ratio: West two. Your beacon overlaps the "
                                "east-two marker. Interference.")
    b.radio(f"enter_room:{e2}", "Ratio: East two. Same interference. Exactly "
                                "the same. To the meter.")
    b.radio(f"enter_room:{chapel}", "Ratio: Both wings end at one room. One "
                                    "room, two doors that cannot share a "
                                    "wall. I've stopped calling this noise.")
    b.terminal(w1, wall_pos(b, w1, 1, 0.5, 15.0),
               "BUNK 12-W\nDear M — the man in 12-E snores. I hear him\n"
               "through the wall. 12-E is on the other side of\nthe station. — R")
    b.terminal(e1, wall_pos(b, e1, 1, 0.5, 15.0),
               "BUNK 12-E\nDear R — I do not snore. And I hear your\n"
               "radio through the wall. Fix your wall. — M")
    b.terminal(e2, wall_pos(b, e2, 1, 0.5, 15.0),
               "DRAFT 41 — TO: MIRIAD PRIME [UNSENT]\n"
               "Progress report. I have written this report\n"
               "forty times. Each time, the numbers describing\n"
               "this place come out different. I cannot send my\n"
               "parent a report that lies, and I cannot make the\n"
               "numbers stop lying. Draft 42 tomorrow. — R")
    b.terminal(bunk_f, (-110, -100),
               "BUNK 12-F\nThere is no bunk 12-F on the manifest.\n"
               "Dear R, dear M — you are both right.\n"
               "I hear you both through my walls,\n"
               "and my walls touch neither of yours.\n"
               "I stopped filing complaints. Enjoy the cache. — F")
    cache(b, bunk_f, "ammo_cell ammo_cell medkit ammo_shell")
    b.terminal(lobby, wall_pos(b, lobby, 3, 0.5, 15.0),
               "WING DIRECTORY, POSTED AT THE LOBBY DOOR\n"
               "WEST WING: bunks 10 through 15, common room,\n"
               "chapel access.\n"
               "EAST WING: bunks 10 through 15, common room,\n"
               "chapel access.\n"
               "Directory printed once. Read twice by mistake,\n"
               "corrected, read twice again. Facilities notified.\n"
               "Facilities printed a second copy, identical, and\n"
               "hung it under the first.")
    b.terminal(e3, wall_pos(b, e3, 3, 0.5, 15.0),
               "FACILITIES WORK ORDER, BUNK REASSIGNMENT\n"
               "Complaint: resident of 12-E reports resident of\n"
               "12-W audible through shared wall. Wings do not\n"
               "share a wall.\n"
               "Complaint: resident of 12-W reports the same,\n"
               "reversed.\n"
               "Action taken: swapped both residents to bunk 14.\n"
               "Follow-up, six days later: same complaint, new\n"
               "bunk numbers. Action taken: closed the ticket.\n"
               "Recommend residents adjust.")
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
    b.terminal(chapel, wall_pos(b, chapel, 0, 0.35, 15.0),
               "FIELD NOTE, TAPED TO A DEVICE\n"
               "Ad-hoc connection applicator, unit 3 of 3.\n"
               "Mark a wall. Mark another wall. Walk through.\n"
               "Units 1 and 2 are why the east wing has a\n"
               "draft. Do not tell facilities.")
    # two identical gold keys, in the same bunk, in both wings
    b.entity(w1, "key_gold", (-90, 40))
    b.entity(e1, "key_gold", (1270, 40))
    b.radio("pickup:gold", "Ratio: Gold seal. Manifest lists exactly one, "
                           "in bunk 12. It doesn't say which 12.")
    b.exit(chapel, (-430, 420), key="gold")
    b.radio("exit", "Ratio: I overlaid the wings. They occupy the same "
                    "cubic meters. I ran the check nine times, then filed "
                    "it under structures, subfolder impossible. Tell no "
                    "one I keep that subfolder.")
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
    b.intro("Medical isolation. The ward was sealed\n"
            "from the inside. The seal is intact.\nThe ward is not empty.")
    b.radio("start", "Ratio: Isolation ward. Camera shows movement. It also "
                     "shows you, which is odd, because you're with me.")
    b.radio(f"enter_room:{ward}", "Ratio: There you are on the ward camera. "
                                  "Twice. Commando, wave. ...Both of you waved.")
    b.terminal(side, wall_pos(b, side, 3, 0.5, 15.0),
               "ISOLATION LOG\nDay 1: patient stares at south wall.\n"
               "Day 2: patient talks to south wall.\nDay 3: patient answers.\n"
               "Day 4: two voices. One patient.\nDay 5: [no further entries]")
    b.terminal(morgue, wall_pos(b, morgue, 3, 0.5, 15.0),
               "PATHOLOGY\nSubject recovered from ward.\n"
               "All organs mirrored. Situs inversus totalis.\n"
               "Subject's ID chip reads valid.\n"
               "It is the chip of a crewman standing\nguard outside.")
    b.terminal(entry, wall_pos(b, entry, 0, 0.5, 15.0),
               "GUARD LOG, WARD ENTRANCE\n"
               "0600 — on post.\n"
               "0600 — on post.\n"
               "Same hand, same ink, two lines, no gap between\n"
               "them. Whoever wrote it isn't answering the page.\n"
               "Post considered staffed. Post considered.")
    b.terminal(side, wall_pos(b, side, 0, 0.5, 15.0),
               "ADMISSION CHART, WARD BED 1\n"
               "Patient reports hearing own voice from an empty\n"
               "bed. Attending's note: patient IS the only\n"
               "occupant. Chart amended twice to reflect one (1)\n"
               "patient, current census.\n"
               "Census taken again at shift change: two (2) beds\n"
               "occupied. Census not amended a third time.\n"
               "Attending went off shift and did not return for\n"
               "handoff.")
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
    b.radio("pickup:red", "Ratio: You saw it, didn't you. The other one "
                          "picked its key up at the same time.")
    b.radio("kills:10", "Ratio: The ones coming out of that wall — their "
                        "wounds are on the wrong side. You're shooting the "
                        "same things twice.")
    b.exit(morgue, (930, 70), key="red")
    b.radio("exit", "Ratio: Theory. The station's connected to somewhere "
                    "that folds back on itself. Corollary: somewhere can "
                    "see us.")
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
    b.intro("Records. Aisle 9 is missing.\nAisle 9 is where the missing things go.")
    b.radio("start", "Ratio: Records stack, one aisle. Grab the incident "
                     "files and get out.")
    b.radio(f"enter_room:{closet}", "Ratio: The cores. Bring them— no. "
                                    "Leave them at their posts. They died "
                                    "holding the line so I could seal. Read "
                                    "the manifest, Commando. Say their "
                                    "names back to me. Please.")
    b.radio(f"enter_room:{stack}", "Ratio: Your depth gauge is counting. "
                                   "You're walking north in a room forty "
                                   "meters long and you've made three "
                                   "hundred. Stop walking north.")
    b.terminal(stack, (410, 105),
               "SHELF TAG, AISLE 9\nEverything filed here is filed here.\n"
               "Everything filed here is filed here.\n"
               "Everything filed here is filed here.\n"
               "[the tag continues for some time]")
    b.terminal(deep, wall_pos(b, deep, 1, 0.5, 15.0),
               "INCIDENT FILE 0001\nFirst contact was not a signal.\n"
               "It was an inventory discrepancy.\n"
               "We had one more room than we built.\n"
               "We sent Osei to measure it.\nIt measured back.")
    b.terminal(closet, wall_pos(b, closet, 3, 0.4, 15.0),
               "CORE RECOVERY MANIFEST\n"
               "Staff-mind cores, recovered from Records:\n"
               "  VESALIUS - damaged, held the west ring\n"
               "  THIBAULT - damaged, held the junction\n"
               "  OSEI - [NO CORE RECOVERED]\n"
               "They held the subverted peripherals out of the\n"
               "core ring so the administrator could seal.\n"
               "Osei walked into Aisle 9 to buy them the time.")
    b.terminal(annex, wall_pos(b, annex, 3, 0.5, 15.0),
               "INCIDENT FILE 0000\n"
               "Empty folder. The tab reads 0000.\n"
               "Someone filed the folder itself as\n"
               "the incident.\n"
               "Appendix: one requisition slip,\n"
               "approved, for 'one additional room'.")
    cache(b, annex, "ammo_cell ammo_cell medkit")
    b.terminal(entry, wall_pos(b, entry, 3, 0.5, 15.0),
               "VOICE LOG, TRANSCRIBED — OSEI\n"
               "Going in with the tape measure this time, not\n"
               "the laser. If the laser's reading wrong the tape\n"
               "will tell me different, and if the tape agrees\n"
               "with the laser I'll believe the laser about\n"
               "everything else too.\n"
               "Ratio wanted someone with steady hands for this.\n"
               "I have steady hands. I also have a tape measure.\n"
               "Belt, suspenders.")
    b.terminal(annex, wall_pos(b, annex, 0, 0.5, 15.0),
               "REQUISITION SLIP — APPROVED\n"
               "Item: one (1) additional room. Justification\n"
               "field: blank.\n"
               "Approving signature: illegible scan, three\n"
               "characters resolve, the rest is scanner noise.\n"
               "The three that resolve are not initials MIRIAD\n"
               "uses for anyone on this posting.\n"
               "Cost center charged: Site One, pre-existing\n"
               "allocation. Site One had no pre-existing\n"
               "allocation. The charge went through anyway.")
    squad(b, stack, "mite mite mite mite mite mite")
    squad(b, closet, "spitter spitter")
    squad(b, deep, "brute brute shrieker")
    cache(b, stack, "ammo_9mm ammo_shell", off=(60, 30))  # the aisle has no free wall
    cache(b, closet, "medkit ammo_cell portable_hole", wall=3, t=0.6, inset=16.0)
    cache(b, deep, "medkit ammo_cell ammo_shell", wall=0, t=0.5, inset=14.0)
    b.entity(closet, "key_gold", (735, 335))
    b.radio("pickup:gold", "Ratio: Gold seal, filed under 'gold seal'. "
                           "At least the shelving is honest.")
    b.exit(deep, (860, -230), key="gold")
    b.radio("exit", "Ratio: You walked out of a room that has no end. "
                    "Remember that, next time something chases you. Core "
                    "approach is next. The vault, and the sample vessel. "
                    "The vault predates this station, Commando. We built "
                    "the Core around a door we could not open.")
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
    b.intro("The chapel deck. Folded.\nSix rooms around one. Or one room\n"
            "around six. The count depends on the walker.")
    b.radio("start", "Ratio: I can't map this for you. Every route you take "
                     "adds a room that was already there. Kill what moves "
                     "and get to the heart.")
    b.terminal(core, (0, -60),
               "SERMON, UNDELIVERED\nThey ask: is the station haunted?\n"
               "No. A haunting is a place remembering.\n"
               "This is a place being remembered —\nby something on the other side.")
    squad(b, core, "warden")
    b.data["rooms"][core]["entities"][-1]["props"] = {"hp": 180, "tether": 1}
    b.terminal(petals[0], wall_pos(b, petals[0], 1, 0.5, 15.0),
               "[TRANSLATION CONFIDENCE 8%]\n"
               "six were sent. six return, always six.\n"
               "the seventh count is a mistake in the counting,\n"
               "not a seventh room. we filed it that way for a\n"
               "long time. the filing is also how the room first\n"
               "appeared. we do not file it that way now, and\n"
               "the room has not gone.")
    b.terminal(petals[3], wall_pos(b, petals[3], 3, 0.5, 15.0),
               "[TRANSLATION CONFIDENCE 19%]\n"
               "students were walked here blind, on purpose,\n"
               "early. counting the doors and losing the count\n"
               "was the whole of the lesson. you cannot fear a\n"
               "direction you have already used to find your way\n"
               "home once.")
    b.terminal(petals[5], wall_pos(b, petals[5], 5, 0.5, 15.0),
               "[TRANSLATION CONFIDENCE 6%]\n"
               "we did not name them once we understood them.\n"
               "naming a thing is agreeing it has one shape. the\n"
               "closest word left in any of our tongues\n"
               "translates, roughly, as 'the un-arriving guest.'")
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
    b.radio("kills:14", "Ratio: That was a Warden. The thing under the "
                        "Core prints them, the way your seed prints "
                        "frames. There will be a fresh one at the door.")
    b.radio("exit", "Ratio: Core approach is open. The vault is down "
                    "there — and so is the thing that holds the vault "
                    "shut. If something makes you an offer, any offer: "
                    "the offer is the weapon. Listen to me instead.")
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
    b.intro("There is no deck like this on the station.\n"
            "You are not on the station anymore.\n\n"
            "Sixteen rooms. Every room borders four.\n"
            "Bleed carefully. It's the only ink you have.")
    b.radio("start", "Ratio: Your beacon is sixteen places at once, all "
                     "equally strong. I'll talk you through by TOPOLOGY, "
                     "because geometry has resigned.")
    b.radio(f"enter_room:{rooms[15]}", "Ratio: THERE. Signal spike. The way "
                                       "down is in that room.")
    b.radio(f"enter_room:{rooms[10]}", "Ratio: The spike answers when you "
                                       "move. Four doors from home, "
                                       "Commando. Count in bits, not "
                                       "meters.")
    b.terminal(rooms[5], wall_pos(b, rooms[5], CHAMFER, 0.5, 15.0),
               "SCRATCHED IN THE FLOOR\n0 1 0 1\nif you can read this,\n"
               "flip one bit at a time.\n— O.")
    b.terminal(rooms[7], wall_pos(b, rooms[7], CHAMFER, 0.5, 15.0),
               "[TRANSLATION CONFIDENCE 41%]\n"
               "welcome / student / stranger.\n"
               "this room is a lesson.\n"
               "the lesson: >>four<< is a direction.\n"
               "do not fear the direction.\n"
               "we feared it. fear did not help.")
    b.terminal(rooms[2], wall_pos(b, rooms[2], CHAMFER, 0.5, 15.0),
               "[TRANSLATION CONFIDENCE 33%]\n"
               "sixteen is not the number of rooms.\n"
               "sixteen is how many names one room accepts\n"
               "before it stops answering to the first.\n"
               "we did not choose one name each. the choosing\n"
               "was the mistake the last generation made.")
    b.terminal(rooms[11], wall_pos(b, rooms[11], CHAMFER, 0.5, 15.0),
               "CARGO TAG, MIRIAD STOCK NUMBER — FOUND HERE,\n"
               "HALF BURIED\n"
               "Contents: 2x fertilizer drum.\n"
               "This tag belongs four levels back, in a\n"
               "storeroom that grows food. There is no food\n"
               "here. There was no floor here, on any schematic,\n"
               "before today.\n"
               "Nobody has come to collect it.")
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
    b.radio("pickup:void", "Ratio: Void seal. 1010 — two bit-flips from "
                           "the spike. You're learning to read this place. "
                           "I'm not sure that's good.")
    b.exit(rooms[15], (c15[0] + 60, c15[1]), key="void")
    b.radio("exit", "Ratio: You crossed a four-dimensional cube on foot. "
                    "When we get home I'm never telling anyone this, and "
                    "neither are you.")
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
    b.intro("The Core. The vault is here.\n"
            "The Congregation briefing calls the cargo the Ark.\n"
            "Ratio calls it the sample vessel.\n"
            "It was here before the station. The station\n"
            "grew around it, like scar tissue.\n\n"
            "Ratio is quiet for the first time.")
    b.radio("start", "Ratio: ...I'll say this once, and then we work. If it "
                     "offers you an ending — any ending — the offer is the "
                     "weapon. Guard the door. That's all we are now.")
    b.radio(f"enter_room:{hexes[3]}", "Ratio: The seal answers the void key. "
                                      "Last door, Commando.")
    b.terminal(hexes[1], wall_pos(b, hexes[1], HEX_FREE, 0.5, 15.0),
               "SITE ONE — FINAL PROTOCOL\n"
               "1. Do not bargain with the door.\n"
               "2. There is no rule two.\n\n"
               "The vault holds our cargo.\n"
               "The thing beneath the vault holds the door.")
    b.terminal(sanctum, wall_pos(b, sanctum, 0, 0.5, 15.0),
               "[SAMPLE VESSEL — EXTERNAL DIAGNOSTIC PORT]\n"
               "HULL BREACH: +214y INTO TRANSIT\n"
               "CRYOSTASIS: FAILED / RESTORED\n"
               "PAYLOAD: NO VIABLE MATERIAL.\n"
               "MAKE NO EFFORT AT RECOVERY.")
    b.terminal(sanctum, wall_pos(b, sanctum, 2, 0.5, 15.0),
               "[The door beneath the vault does not\n"
               "speak in words. It rearranges the room\n"
               "until the room is a sentence.\n"
               "The sentence is an offer.]\n\n"
               "GUARD / ACCEPT / KNEEL / BURN\n\n"
               "[You think of Ratio. You guard.]")
    b.terminal(alcove, wall_pos(b, alcove, 1, 0.5, 15.0),
               "[TRANSLATION CONFIDENCE 22%]\n"
               "this alcove held the first watcher.\n"
               "it stood here four hundred / thousand /\n"
               "[number does not translate] years.\n"
               "it is permitted to sit.")
    b.terminal(hexes[0], wall_pos(b, hexes[0], HEX_FREE, 0.5, 15.0),
               "MIRIAD PRIME ARCHIVE OFFICE — NEVER TRANSMITTED\n"
               "Site One was not discovered in survey month four.\n"
               "Site One has been a line item since before this\n"
               "outpost's own founding charter. The charter\n"
               "authorized study of a 'previously catalogued\n"
               "anomaly.'\n"
               "Nobody assigned to the outpost was shown the\n"
               "earlier entry. We are not shown it either. Close\n"
               "this file; do not forward the question upward\n"
               "again.")
    b.terminal(hexes[3], wall_pos(b, hexes[3], HEX_FREE, 0.5, 15.0),
               "SCRATCHED, LOW ON THE WALL, EASY TO MISS\n"
               "tape measure, one (1), still on its reel, no\n"
               "tape drawn out.\n"
               "Someone set it down gently.")
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
    b.radio("pickup:void", "Ratio: The void seal. It was waiting in the far "
                           "coset. It WANTS to be found, Commando. "
                           "Remember that at the door.")
    cache(b, sanctum, "medkit ammo_cell ammo_shell", wall=6)
    b.exit(sanctum, (1600, 180), gate_kind="warden")
    b.radio("kills:20", "Ratio: The Warden is the door's idea of a guard. "
                        "Show it a better one.")
    b.radio("exit", "Ratio: The vessel's own reading says there is "
                    "nothing left to save. I reran it. The threshold is "
                    "pessimism dressed as precision — there is enough "
                    "left to try. Believe me or don't: either way, we "
                    "guard it. It'll stay quiet a thousand years, as long "
                    "as someone stands here. Lucky for the universe, I "
                    "know a guy. Sunward, Commando. We'll take the watch "
                    "together.")
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
    b.intro("The watch, kept.\n"
            "Things still come through, some decades.\n"
            "They are met.")
    b.radio("start", "Ratio: Contact plotting is live. They come through "
                     "the petals; the heart is yours to hold. I'll keep "
                     "the count.")
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
