"""Portable hole and tau cannon behavior gates."""

import math

import necore

from perihelion.levels import LevelBuilder
from perihelion.sim import GameSession, InputFrame, HOLE_WIDTH


def _hole_session():
    b = LevelBuilder("holetest", 1)
    r0 = b.rect(0, 0, 300, 200)
    b.player(r0, (60, 100))
    b.entity(r0, "portable_hole", (80, 100))
    b.entity(r0, "portable_hole", (90, 100))
    b.exit(r0, (280, 20))
    return GameSession(b.build(), seed=1)


def test_portable_hole_links_two_walls():
    s = _hole_session()
    for _ in range(40):
        s.tick(InputFrame(mx=1.0))
    assert s.holes == 2 and "hole" in s.weapons
    px, py = s.player_pos()
    ax, ay = necore.mat_apply(s.cam, px, py - 50)
    s.tick(InputFrame(weapon=8, ax=ax, ay=ay, fire=True))
    assert s.hole_mark is not None
    for _ in range(20):
        s.tick(InputFrame())
    px, py = s.player_pos()
    ax2, ay2 = necore.mat_apply(s.cam, px, py + 50)
    s.tick(InputFrame(ax=ax2, ay=ay2, fire=True))
    assert s.hole_mark is None and s.holes == 1
    assert s.sim.num_polygons() == 2  # corridor added
    crossed = [s.player_room()]
    for _ in range(500):
        s.tick(InputFrame(my=1.0))
        r = s.player_room()
        if crossed[-1] != r:
            crossed.append(r)
    assert 1 in crossed and crossed.count(0) >= 2, crossed


def test_hole_corridor_excludes_brutes_admits_mites():
    # the fit rule: 2*radius must be <= opening * 1.05
    from perihelion.sim import ENEMIES
    assert 2 * ENEMIES["brute"]["radius"] > HOLE_WIDTH * 1.05
    assert 2 * ENEMIES["mite"]["radius"] <= HOLE_WIDTH * 1.05
    assert 2 * 6.5 <= HOLE_WIDTH * 1.05  # the player fits


def test_tau_primary_ricochets_and_charged_shot_fires():
    b = LevelBuilder("tautest", 1)
    r0 = b.rect(0, 0, 400, 200)
    b.player(r0, (60, 100))
    b.entity(r0, "weapon_tau", (80, 100))
    b.entity(r0, "husk", (340, 100))
    b.exit(r0, (380, 20))
    s = GameSession(b.build(), seed=2)
    for _ in range(30):
        s.tick(InputFrame(mx=1.0))
    assert "tau" in s.weapons and s.ammo["cell"] >= 8
    # primary at a wall: bullet should ricochet (still alive after wall hit)
    px, py = s.player_pos()
    ax, ay = necore.mat_apply(s.cam, px + 40, py - 60)
    s.tick(InputFrame(weapon=7, ax=ax, ay=ay, fire=True))
    assert any(bl["kind"] == "tau" for bl in s.bullets.values())
    ricocheted = False
    for _ in range(30):
        s.tick(InputFrame())
        for f in s.fx:
            if f[0] == "sound" and f[1] == "ricochet":
                ricocheted = True
    assert ricocheted, "tau round should bounce at least once"
    # charged shot: hold alt, release
    cells_before = s.ammo["cell"]
    for _ in range(45):
        s.tick(InputFrame(alt=True))
    assert s.tau_charge > 0
    s.tick(InputFrame(alt=False))
    assert s.tau_charge == 0
    assert s.ammo["cell"] < cells_before
    assert any(bl["kind"] == "taucharged" for bl in s.bullets.values())


def test_tau_overcharge_bites():
    b = LevelBuilder("tautest2", 1)
    r0 = b.rect(0, 0, 300, 200)
    b.player(r0, (150, 100))
    b.entity(r0, "weapon_tau", (160, 100))
    b.exit(r0, (280, 20))
    s = GameSession(b.build(), seed=3)
    for _ in range(20):
        s.tick(InputFrame(mx=0.5))
    s.tick(InputFrame(weapon=7))
    hp0 = s.hp
    for _ in range(200):
        s.tick(InputFrame(alt=True))
    assert s.hp < hp0, "overcharge should hurt"
