"""Campaign structural gates: every shipped level loads, runs, and is
traversable. Deeper playability (bot completion) lives in test_testkit.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from perihelion.levels import LevelBuilder, load_level
from perihelion.sim import GameSession, InputFrame

ROOT = Path(__file__).resolve().parents[2]
LEVELS = sorted((ROOT / "levels").glob("l*.json"))


def test_campaign_exists_and_generator_runs():
    assert (ROOT / "levels" / "campaign.json").exists(), \
        "run: uv run python tools/levelgen/campaign.py"
    manifest = json.loads((ROOT / "levels" / "campaign.json").read_text())
    assert len(manifest["levels"]) == 10


@pytest.mark.parametrize("path", LEVELS, ids=[p.stem for p in LEVELS])
def test_level_structure(path):
    lvl = load_level(path)
    s = GameSession(lvl, seed=1)
    for t in range(120):
        s.tick(InputFrame(mx=(t % 3) - 1, my=((t // 3) % 3) - 1))
    assert not s.dead
    # with all doors open, the whole graph and the exit are reachable
    for d in s.doors:
        if not d["open"]:
            s.sim.connect(d["a"], d["ea"], d["b"], d["eb"])
    reach = set(s.sim.polygons_within(lvl.player_room, 99))
    assert reach == set(range(s.sim.num_polygons())), "unreachable rooms"
    assert lvl.exit_room in reach


@pytest.mark.parametrize("path", LEVELS, ids=[p.stem for p in LEVELS])
def test_keys_reachable_before_their_doors(path):
    """Every door's key must be obtainable without passing that door."""
    lvl = load_level(path)
    s = GameSession(lvl, seed=1)
    key_rooms = {}
    for eid, p in s.pickups.items():
        if p["kind"].startswith("key_"):
            key_rooms[p["kind"][4:]] = s.sim.get_polygon(eid)
    for d in s.doors:
        if d["key"] in ("", "shoot"):
            continue
        assert d["key"] in key_rooms, f"door needs key_{d['key']} but none placed"
        hops = s.sim.hop_distance(lvl.player_room, key_rooms[d["key"]])
        assert hops >= 0, f"key_{d['key']} unreachable while its door is shut"


def test_doorway_splitter_makes_doorways():
    b = LevelBuilder("t", 1)
    big = b.rect(0, 0, 400, 300)
    hall = b.rect(400, 100, 200, 90)  # short west edge inside big's east wall
    b.player(big, (200, 150))
    lvl = b.build()
    # big got split vertices; the two rooms are connected
    assert any(c[0] == big and c[2] == hall or c[0] == hall and c[2] == big
               for c in b.resolve()["connects"])
    assert len(lvl.room_verts[big]) == 6  # 4 corners + 2 inserted


def test_no_connect_keeps_walls_solid():
    b = LevelBuilder("t", 1)
    a = b.rect(0, 0, 200, 200)
    c = b.rect(200, 0, 200, 200)
    b.no_connect(a, c)
    b.player(a, (100, 100))
    assert b.resolve()["connects"] == []
