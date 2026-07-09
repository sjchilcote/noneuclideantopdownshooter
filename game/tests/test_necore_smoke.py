"""Smoke tests for the necore PyO3 bindings: build a tiny two-room world and
exercise simulation, visibility, raycasting, and the matrix helpers."""

from __future__ import annotations

import math

import necore

SQUARE = [(0.0, 0.0), (0.0, 100.0), (100.0, 100.0), (100.0, 0.0)]


def two_room_sim():
    sim = necore.Sim()
    a = sim.add_room(SQUARE)
    b = sim.add_room(SQUARE)
    # Canonical square edge order: 0 left, 1 bottom, 2 right, 3 top.
    sim.connect(a, 2, b, 0)
    return sim, a, b


def test_transfer_preserves_speed_and_changes_room():
    sim, a, b = two_room_sim()
    eid = sim.spawn(a, 0.0, 0.0, 5.0, 1.0, 0)
    sim.set_vel(eid, 200.0, 0.0)

    transfer = None
    for _ in range(600):
        for ev in sim.step(1.0 / 60.0):
            if ev[0] == "transfer":
                transfer = ev
        if transfer is not None:
            break

    assert transfer is not None, "entity never crossed the portal"
    _, ent, from_room, to_room, edge, _m9 = transfer
    assert ent == eid
    assert from_room == a
    assert to_room == b

    room, px, py, vx, vy, dx, dy = sim.get(eid)
    assert room == b
    speed = math.hypot(vx, vy)
    assert abs(speed - 200.0) < 1e-6


def test_visible_set_returns_sane_instances():
    sim, a, b = two_room_sim()
    cam = necore.mat_translate(400.0, 300.0)
    instances = sim.visible_set(a, cam, 0.0, 0.0, 800.0, 600.0, 8, 64)

    assert len(instances) >= 2
    rooms_seen = {inst[0] for inst in instances}
    assert a in rooms_seen
    assert b in rooms_seen

    for room, xform, depth, clip_screen, walls, entry_edge, ents in instances:
        assert len(clip_screen) >= 3
        assert isinstance(depth, int)
        assert len(xform) == 9
        for x, y in clip_screen:
            assert math.isfinite(x) and math.isfinite(y)


def test_raycast_crosses_portal_and_hits_far_wall():
    sim, a, b = two_room_sim()
    # From the centroid of room a, straight through the shared edge (edge 2,
    # the +x side) into room b, which should report a wall hit in room b.
    kind, room, edge, px, py, dist, hops, m9 = sim.raycast(
        a, 0.0, 0.0, 1.0, 0.0, 4, 1000.0, 0xFFFF, -1
    )
    assert kind == "wall"
    assert room == b
    assert hops >= 1
    assert dist > 50.0  # travelled past the shared edge into b


def test_mat_helpers_roundtrip():
    m = necore.mat_mul(necore.mat_translate(3.0, -2.0), necore.mat_rotate(0.7))
    m = necore.mat_mul(m, necore.mat_scale(2.0, 0.5))
    inv = necore.mat_inv(m)
    prod = necore.mat_mul(m, inv)
    ident = necore.mat_identity()
    for got, want in zip(prod, ident):
        assert abs(got - want) < 1e-9

    # apply / apply_dir sanity.
    x, y = necore.mat_apply(necore.mat_translate(5.0, 7.0), 1.0, 2.0)
    assert abs(x - 6.0) < 1e-9 and abs(y - 9.0) < 1e-9
    dx, dy = necore.mat_apply_dir(necore.mat_translate(5.0, 7.0), 1.0, 2.0)
    assert abs(dx - 1.0) < 1e-9 and abs(dy - 2.0) < 1e-9

    angle = necore.mat_rotation_angle(necore.mat_rotate(0.3))
    assert abs(angle - 0.3) < 1e-9


def test_errors_are_value_errors():
    sim = necore.Sim()
    try:
        sim.add_room([(0.0, 0.0), (1.0, 0.0)])
        assert False, "expected ValueError for too-few verts"
    except ValueError:
        pass

    try:
        sim.get(99999)
        assert False, "expected ValueError for unknown entity"
    except ValueError:
        pass
