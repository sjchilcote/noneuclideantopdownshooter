"""One seamless world: chunk streaming, spines, arrival, respawn."""

import os
import tempfile

from perihelion.levels import LevelBuilder, save_level, load_level
from perihelion.sim import GameSession, InputFrame
from perihelion.stream import WorldStreamer
from perihelion.testkit.bots import nav_to_point


def _chunks(n=3):
    tmp = tempfile.mkdtemp()
    paths = []
    for i in range(n):
        b = LevelBuilder(f"CHUNK {i}", 1)
        r0 = b.rect(0, 0, 260, 180, kind="dock")
        r1 = b.rect(260, 30, 200, 120, kind="corridor")
        b.player(r0, (60, 90))
        b.entity(r1, "husk", (360, 90))
        b.exit(r1, (420, 90))
        p = os.path.join(tmp, f"c{i}.json")
        save_level(b.to_dict(), p)
        paths.append(p)
    return paths


def _go(s, ws, room_target, point, max_ticks=2500, fire=False):
    for _ in range(max_ticks):
        px, py = s.player_pos()
        if s.player_room() == room_target and \
                abs(px - point[0]) + abs(py - point[1]) < 26:
            return True
        if s.player_room() == room_target:
            mx, my = nav_to_point(s, px, py, point)
        else:
            e = s.sim.next_edge(s.player_room(), room_target)
            if e < 0:
                return False
            mx, my = nav_to_point(s, px, py,
                                  s.sim.edge_midpoint(s.player_room(), e))
        s.tick(InputFrame(mx=mx, my=my, fire=fire))
        ws.tick()
    return False


def test_stream_lazy_load_arrival_and_completion():
    paths = _chunks()
    s = GameSession(load_level(paths[0]), seed=3)
    ws = WorldStreamer(s, paths)
    assert s.exit_enabled is False
    assert s.sim.num_rooms() == 4  # chunk 0 + its spine
    spine_a = ws.chunks[0]["spine_rooms"][0]
    assert _go(s, ws, spine_a, (0, 0), fire=True)
    assert ws.chunks[0]["loaded_next"]
    s.keys.add("red")
    c1 = ws.chunks[1]
    assert _go(s, ws, c1["entry_room"] + c1["offset"], c1["entry_pos"],
               fire=True)
    assert ws.current == 1
    assert not s.keys  # new security zone
    # final chunk enables the true exit and completes there
    spine1a = ws.chunks[1]["spine_rooms"][0]
    assert _go(s, ws, spine1a, (0, 0), fire=True)
    c2 = ws.chunks[2]
    assert _go(s, ws, c2["entry_room"] + c2["offset"], c2["entry_pos"],
               fire=True)
    assert s.exit_enabled
    lvl2 = c2["level"]
    assert _go(s, ws, lvl2.exit_room + c2["offset"], lvl2.exit_pos, fire=True)
    for _ in range(120):
        px, py = s.player_pos()
        mx, my = nav_to_point(s, px, py, lvl2.exit_pos)
        s.tick(InputFrame(mx=mx, my=my))
        ws.tick()
        if s.complete:
            break
    assert s.complete


def test_stream_respawn_at_chunk_entry():
    paths = _chunks()
    s = GameSession(load_level(paths[0]), seed=3)
    ws = WorldStreamer(s, paths)
    spine_a = ws.chunks[0]["spine_rooms"][0]
    assert _go(s, ws, spine_a, (0, 0), fire=True)
    c1 = ws.chunks[1]
    assert _go(s, ws, c1["entry_room"] + c1["offset"], c1["entry_pos"],
               fire=True)
    hp_entry = ws.entry_states[1]["hp"]
    s.hurt_cd = 0
    s.hp = 1
    s._damage_player(50, s.player_room())
    assert s.dead
    n_enemies_before = len(s.enemies)
    ws.respawn()
    assert not s.dead
    assert s.hp == hp_entry
    assert ws.room_chunk(s.player_room()) == 1
    assert len(s.enemies) >= n_enemies_before  # the chunk's dead rose again
