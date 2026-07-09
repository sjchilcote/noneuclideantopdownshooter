"""Safe room (the Cloister): links, shifting attachment, turret defense."""

import necore

from perihelion.levels import LevelBuilder
from perihelion.sim import GameSession, InputFrame
from perihelion.testkit.bots import nav_to_point


def _session():
    b = LevelBuilder("cloistertest", 1)
    r0 = b.rect(0, 0, 300, 200)
    r1 = b.rect(300, 0, 300, 200)
    b.player(r0, (150, 100))
    b.entity(r0, "safe_room_core", (170, 100))
    b.entity(r0, "portable_hole", (185, 100))
    b.entity(r1, "mite", (450, 100))
    b.exit(r1, (580, 20))
    s = GameSession(b.build(), seed=1)
    for _ in range(40):
        s.tick(InputFrame(mx=0.6))
    for _ in range(50):
        s.tick(InputFrame())
    return s


def _go_to(s, room_target, point, max_ticks=1200):
    for _ in range(max_ticks):
        px, py = s.player_pos()
        if s.player_room() == room_target and \
                abs(px - point[0]) + abs(py - point[1]) < 20:
            return True
        if s.player_room() == room_target:
            mx, my = nav_to_point(s, px, py, point)
        else:
            e = s.sim.next_edge(s.player_room(), room_target)
            if e < 0:
                return False
            mx, my = nav_to_point(s, px, py,
                                  s.sim.edge_midpoint(s.player_room(), e))
        s.tick(InputFrame(mx=mx, my=my))
    return False


def test_core_pickup_builds_pocket_with_guardians():
    s = _session()
    c = s.cloister
    assert c is not None
    assert len(s.turrets) == 2
    assert s.holes >= 3
    # pocket is unreachable until linked
    assert s.sim.hop_distance(0, c["sanctum"]) == -1


def test_link_enter_exit_and_rotation():
    s = _session()
    c = s.cloister
    px, py = s.player_pos()
    ax, ay = necore.mat_apply(s.cam, px, py - 60)
    s.tick(InputFrame(weapon=8, ax=ax, ay=ay, fire=True))
    assert len(c["links"]) == 1 and c["attached"] == 0
    assert _go_to(s, c["sanctum"], (0, 0))
    assert _go_to(s, 0, (0, 0))
    # second link from r1, then entering the sanctum rotates the attachment
    assert _go_to(s, 1, (0, 0))
    for _ in range(40):
        s.tick(InputFrame())
    px, py = s.player_pos()
    ax, ay = necore.mat_apply(s.cam, px, py + 60)
    s.tick(InputFrame(weapon=8, ax=ax, ay=ay, fire=True))
    assert len(c["links"]) == 2 and c["attached"] == 1
    assert _go_to(s, c["sanctum"], (0, 0))
    assert c["attached"] == 0  # rotated on entry


def test_guardians_kill_pursuers():
    s = _session()
    c = s.cloister
    assert _go_to(s, 1, (0, 0))
    for _ in range(40):
        s.tick(InputFrame())  # the mite notices on sight; no gunfire needed
    for _ in range(30):
        s.tick(InputFrame())
    px, py = s.player_pos()
    ax, ay = necore.mat_apply(s.cam, px, py + 60)
    s.tick(InputFrame(weapon=8, ax=ax, ay=ay, fire=True))
    mites0 = sum(1 for e in s.enemies.values() if e["kind"] == "mite")
    assert mites0 == 1
    assert _go_to(s, c["sanctum"], (0, 0))
    for _ in range(60 * 12):
        s.tick(InputFrame())
        if not any(e["kind"] == "mite" for e in s.enemies.values()):
            break
    assert not any(e["kind"] == "mite" for e in s.enemies.values()), \
        "guardians must kill the pursuing mite"


def test_cloister_carries_between_levels():
    b = LevelBuilder("carry", 1)
    r0 = b.rect(0, 0, 200, 200)
    b.player(r0, (100, 100))
    b.exit(r0, (180, 20))
    s = GameSession(b.build(), seed=2,
                    player_state=dict(cloister=True, holes=1,
                                      weapons=["knife", "pistol", "hole"]))
    assert s.cloister is not None
    assert len(s.turrets) == 2
