"""THE VIGIL: the wave director spawns, escalates, and records."""

from perihelion.levels import load_level
from perihelion.sim import GameSession, InputFrame


def test_waves_spawn_and_escalate():
    lvl = load_level("levels/vigil.json")
    assert lvl.vigil
    s = GameSession(lvl, seed=4,
                    player_state=dict(hp=100, ammo={"9mm": 200},
                                      weapons=["knife", "pistol"], weapon="pistol"))
    # burn the opening timer: first wave arrives
    for _ in range(60 * 7):
        s.tick(InputFrame())
        if s.metrics["wave"]:
            break
    assert s.metrics["wave"] == 1
    n1 = len(s.enemies)
    assert n1 > 0
    # cull the wave by decree; the next, bigger wave follows
    for eid in list(s.enemies):
        s.enemies.pop(eid)
        s.sim.remove(eid)
    for _ in range(60 * 10):
        s.tick(InputFrame())
        if s.metrics["wave"] == 2:
            break
    assert s.metrics["wave"] == 2
    assert len(s.enemies) >= n1  # budgets grow


def test_no_exit_and_no_waves_in_campaign_levels():
    lvl = load_level("levels/l01.json")
    assert not lvl.vigil
    s = GameSession(lvl, seed=1)
    for _ in range(120):
        s.tick(InputFrame())
    assert s.metrics["wave"] == 0
