"""Containment is an engine invariant: step_entity ends by clamping every
entity into its polygon (necore physics contain_in_polygon), so an entity
can never persist outside its room. The game-side recovery sweep this file
once tested was damage control for that escape class and is gone."""

from perihelion.levels import LevelBuilder
from perihelion.sim import GameSession, InputFrame


def _level():
    b = LevelBuilder("CONTAIN", 1)
    r0 = b.rect(0, 0, 200, 140)
    b.player(r0, (40, 70))
    b.entity(r0, "husk", (150, 70))
    b.exit(r0, (180, 70))
    return b.build()


def test_escaped_enemy_is_reclaimed_within_one_tick():
    s = GameSession(_level(), seed=1)
    eid = next(iter(s.enemies))
    s.sim.set_pos(eid, s.sim.place(s.sim.get_polygon(eid), 4000.0, -4000.0))
    s.tick(InputFrame())
    x, y = s.sim.get(eid).pos.local()
    assert GameSession._outside_by(x, y, s.level.room_verts[0]) <= 0.0


def test_normal_play_keeps_every_entity_inside():
    s = GameSession(_level(), seed=2)
    for t in range(60 * 5):
        s.tick(InputFrame(mx=1.0))
        if t % 30 == 0:
            for eid in (s.pid, *list(s.enemies)):
                if not s.sim.exists(eid):
                    continue
                st = s.sim.get(eid)
                x, y = st.pos.local()
                assert GameSession._outside_by(
                    x, y, s.level.room_verts[st.polygon]) <= 0.0
