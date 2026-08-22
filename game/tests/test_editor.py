"""Tests for `perihelion.editor.model` -- the pure-Python (no pygame) half
of the level editor. Exercises the real model code directly: load a shipped
level, mutate it the way the pygame view would, and check the resulting
dict is exactly what a level author would expect, including round-tripping
through the real `perihelion.levels` loader and a live `GameSession`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from perihelion.editor import model as M
from perihelion.levels import load_level
from perihelion.sim import GameSession, InputFrame

ROOT = Path(__file__).resolve().parents[2]
L01 = ROOT / "levels" / "l01.json"


@pytest.fixture()
def m() -> M.EditorModel:
    model = M.EditorModel()
    errs = model.load(L01)
    assert errs == [], errs
    return model


def test_load_l01(m):
    assert len(m.data["rooms"]) == 12
    assert m.validate() == []
    assert not m.dirty


def test_move_room_moves_verts_and_entities(m):
    before_verts = copy.deepcopy(m.data["rooms"][0]["verts"])
    before_entities = copy.deepcopy(m.data["rooms"][0]["entities"])
    assert before_entities, "room 0 should have at least one entity (medkit) in l01"

    m.move_room(0, 40, 40)

    after_verts = m.data["rooms"][0]["verts"]
    after_entities = m.data["rooms"][0]["entities"]
    for (bx, by), (ax, ay) in zip(before_verts, after_verts):
        assert ax == pytest.approx(bx + 40)
        assert ay == pytest.approx(by + 40)
    for be, ae in zip(before_entities, after_entities):
        assert ae["pos"][0] == pytest.approx(be["pos"][0] + 40)
        assert ae["pos"][1] == pytest.approx(be["pos"][1] + 40)

    # player spawns in room 0 in l01.json -- the marker must travel with it.
    assert m.data["player"]["room"] == 0
    assert m.data["player"]["pos"] == pytest.approx([80 + 40, 90 + 40])

    # other rooms are untouched.
    assert m.data["rooms"][1]["verts"] == [[220, 60], [220, 130], [560, 130], [560, 60]]

    assert m.dirty


def test_move_room_is_a_single_undo_step(m):
    prior = copy.deepcopy(m.data)
    m.move_room(1, 5, -5)
    assert m.data != prior
    assert m.undo() is True
    assert m.data == prior


def test_delete_room_reindexes_everything(m):
    # room 3 participates in connects [3,2,11,0], [0,3,1,0]->untouched,
    # [2,3,8,3]->untouched, [3,1,10,3]; exit sits in room 7 (> 3, must shift).
    n_rooms_before = len(m.data["rooms"])
    assert m.data["exit"]["room"] == 7

    m.delete_room(3)

    assert len(m.data["rooms"]) == n_rooms_before - 1
    # no connect may reference the deleted room, and every remaining index
    # must be in range of the shrunk rooms list.
    n_rooms_after = len(m.data["rooms"])
    for a, ea, b, eb in m.data["connects"]:
        assert 0 <= a < n_rooms_after
        assert 0 <= b < n_rooms_after
    for d in m.data["doors"]:
        assert 0 <= d["a"] < n_rooms_after
        assert 0 <= d["b"] < n_rooms_after
    # player was in room 0 (< 3): untouched.
    assert m.data["player"]["room"] == 0
    # exit was in room 7 (> 3): shifted down by one.
    assert m.data["exit"]["room"] == 6
    # Exact expected remap of every original `connects` entry: the two
    # entries that touched room 3 ([3,2,11,0] and [3,1,10,3]) are dropped;
    # every other room index > 3 shifts down by one (note new index 3 is
    # legitimately reused by what used to be room 4 -- it is NOT "the
    # deleted room" reappearing).
    assert m.data["connects"] == [
        [10, 2, 3, 0],
        [0, 3, 1, 0],
        [1, 2, 2, 1],
        [2, 3, 7, 3],
        [3, 2, 4, 0],
        [4, 1, 5, 3],
        [5, 1, 6, 3],
        [7, 0, 8, 2],
        [8, 3, 9, 1],
    ]
    assert m.validate() == []


def test_delete_room_clears_player_when_its_room_is_deleted():
    model = M.EditorModel()
    model.load(L01)
    player_room = model.data["player"]["room"]
    model.delete_room(player_room)
    assert model.data["player"] is None
    errs = model.validate()
    assert any("no player" in e for e in errs)


def test_add_room_connect_save_loads_and_runs(tmp_path):
    model = M.EditorModel()
    model.load(L01)

    ri = model.add_rect_room(1000, 1000, 120, 90)
    assert model.data["rooms"][ri]["verts"] == [
        [1000, 1000], [1000, 1090], [1120, 1090], [1120, 1000],
    ]

    # room 11 (the "beacon jumped" room) has edges 0 and 2 already used by
    # connects in l01.json; edge 1 is free.
    model.connect_edges(ri, 0, 11, 1)
    assert model.validate() == []

    out = tmp_path / "edited.json"
    errs = model.save(out)
    assert errs == []
    assert model.path == out
    assert not model.dirty

    on_disk = json.loads(out.read_text())
    assert on_disk["version"] == 2
    assert len(on_disk["rooms"]) == 13

    lvl = load_level(out)
    assert len(lvl.room_verts) == 13

    session = GameSession(lvl, seed=1)
    for t in range(60):
        session.tick(InputFrame(mx=(t % 3) - 1, my=((t // 5) % 3) - 1))
    assert not session.dead


def test_undo_restores_exact_prior_dict(m):
    prior = copy.deepcopy(m.data)
    m.add_rect_room(2000, 2000, 50, 50)
    m.move_room(0, 10, 10)
    assert m.data != prior

    assert m.undo() is True  # undoes move_room
    assert m.undo() is True  # undoes add_rect_room
    assert m.data == prior
    assert m.undo() is False  # nothing left to undo


def test_convexity_violation_blocks_save(m, tmp_path):
    # Smash a vertex of room 0 inward so the room becomes reflex there.
    m.data["rooms"][0]["verts"][2] = [50, 50]
    errs_before = m.validate()
    assert any("concave" in e for e in errs_before)

    save_errs = m.save(tmp_path / "should_not_exist.json")
    assert save_errs == errs_before
    assert not (tmp_path / "should_not_exist.json").exists()


def test_wrong_winding_blocks_save(tmp_path):
    model = M.EditorModel()
    model.load(L01)
    model.data["rooms"][0]["verts"] = list(reversed(model.data["rooms"][0]["verts"]))
    errs = model.validate()
    assert any("winding" in e for e in errs)
    assert model.save(tmp_path / "x.json") == errs


def test_missing_player_or_exit_blocks_save(tmp_path):
    model = M.EditorModel()
    model.load(L01)
    model.data["player"] = None
    errs = model.validate()
    assert "no player spawn" in errs
    assert model.save(tmp_path / "x.json") == errs


def test_double_used_edge_blocks_save(m, tmp_path):
    # Room 0 edge 3 is already used by connects[2] == [0,3,1,0]; claim it
    # again from an unrelated room/edge -- must be rejected as a conflict,
    # not silently accepted.
    m.data["connects"].append([0, 3, 2, 0])
    errs = m.validate()
    assert any("used by multiple connections" in e for e in errs)
    assert m.save(tmp_path / "x.json") == errs


def test_self_mirror_connect_is_not_a_double_use_conflict(m):
    # The same edge appearing as BOTH sides of a single record (a==b,
    # ea==eb) is a deliberate mirror connect (see levels/l06.json), not a
    # conflict -- it must not trip the double-used-edge validator.
    ri = m.add_rect_room(5000, 5000, 100, 100)
    m.connect_edges(ri, 0, ri, 0)
    errs = m.validate()
    assert not any("used by multiple connections" in e for e in errs)


def test_add_entity_rejects_unspawnable_type(m):
    with pytest.raises(ValueError):
        m.add_entity(0, "player", 10, 10)  # singleton marker, not a room entity


def test_delete_entity():
    model = M.EditorModel()
    model.load(L01)
    n_before = len(model.data["rooms"][0]["entities"])
    model.delete_entity(0, 0)
    assert len(model.data["rooms"][0]["entities"]) == n_before - 1


def test_delete_vertex_drops_bound_connections_not_others():
    model = M.EditorModel()
    model.load(L01)
    # room 0 has 6 verts; edges 3 and 4 touch vertex 4 (the vertex between
    # them). Delete vertex 4 and confirm any connect bound to those exact
    # edges of room 0 is gone while unrelated connects on room 0 survive.
    room0 = model.data["rooms"][0]
    n_before = len(room0["verts"])
    ok = model.delete_vertex(0, 4)
    assert ok
    assert len(model.data["rooms"][0]["verts"]) == n_before - 1
    # every remaining connect edge index must be valid for room 0 now.
    n_edges = len(model.data["rooms"][0]["verts"])
    for a, ea, b, eb in model.data["connects"]:
        if a == 0:
            assert 0 <= ea < n_edges
        if b == 0:
            assert 0 <= eb < n_edges


def test_delete_vertex_refuses_below_triangle():
    model = M.EditorModel()
    # a bare triangle room
    model.data["rooms"].append({"verts": [[0, 0], [0, -10], [10, 0]], "entities": []})
    assert model.delete_vertex(0, 0) is False
    assert len(model.data["rooms"][0]["verts"]) == 3


def test_load_malformed_file_does_not_crash_or_clobber_state(tmp_path):
    model = M.EditorModel()
    model.load(L01)
    good_data = copy.deepcopy(model.data)

    bad = tmp_path / "broken.json"
    bad.write_text("{not valid json,,,")
    errs = model.load(bad)
    assert errs != []
    assert model.data == good_data  # untouched by the failed load

    missing = tmp_path / "does_not_exist.json"
    errs2 = model.load(missing)
    assert errs2 != []
    assert model.data == good_data
