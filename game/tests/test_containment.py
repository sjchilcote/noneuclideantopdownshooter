"""Containment sweep: entities that escape their room's polygon are
recovered to the room's (verts-frame) centroid, loudly."""

from perihelion.levels import LevelBuilder
from perihelion.sim import GameSession, InputFrame


def _level():
    b = LevelBuilder("CONTAIN", 1)
    r0 = b.rect(0, 0, 200, 140)
    b.player(r0, (40, 70))
    b.entity(r0, "husk", (150, 70))
    b.exit(r0, (180, 70))
    return b.build()


def test_escaped_enemy_is_recovered():
    s = GameSession(_level(), seed=1)
    eid = next(iter(s.enemies))
    s.sim.set_pos(eid, 4000.0, -4000.0)  # far outside the room polygon
    # recovery requires 6 consecutive outside sweeps (3s) so door-crush
    # excursions never trigger it
    for _ in range(200):
        s.tick(InputFrame())
    assert s.metrics.get("containment_recoveries", 0) >= 1
    _, x, y, *_ = s.sim.get(eid)
    assert GameSession._outside_by(x, y, s.level.room_verts[0]) <= 0.0


def test_normal_play_never_triggers_recovery():
    s = GameSession(_level(), seed=2)
    for _ in range(60 * 5):
        s.tick(InputFrame(mx=1.0))
    assert s.metrics.get("containment_recoveries", 0) == 0
