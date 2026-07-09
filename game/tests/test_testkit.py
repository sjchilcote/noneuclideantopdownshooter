"""Tests for `game.perihelion.testkit`: determinism, replay round-trip
identity, bot completion of a smoke level, and engine perf budgets.

Levels are built via `LevelBuilder`. `LevelBuilder.entity/player/exit` take
*absolute canvas coordinates* (matching whatever origin the room's own
`.rect(x, y, w, h)`/`.ngon(...)` call used) — not room-local offsets — so
every placement below re-adds the room's own origin.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from perihelion.levels import Level, LevelBuilder
from perihelion.sim import GameSession
from perihelion.testkit import (
    AggroBot,
    CamperBot,
    ExplorerBot,
    PacifistBot,
    Replay,
    assert_playable,
    play,
    record,
    run_bot,
)
from perihelion.testkit.perf import (
    assert_perf_budgets,
    build_infinite_corridor,
    build_mirror_room,
    build_radial_hub,
    run_perf_suite,
)

SMOKE_MAX_TICKS = 60 * 120


def build_smoke_level() -> tuple[Level, dict]:
    """4-room chain, 2 husks + ammo along the way, exit at the far end."""
    b = LevelBuilder("smoke_4room")
    r0 = b.rect(0, 0, 200, 200)
    r1 = b.rect(300, 0, 200, 200)
    r2 = b.rect(600, 0, 200, 200)
    r3 = b.rect(900, 0, 200, 200)
    b.connect(r0, 2, r1, 0)
    b.connect(r1, 2, r2, 0)
    b.connect(r2, 2, r3, 0)
    b.entity(r1, "husk", (400, 100))
    b.entity(r2, "husk", (700, 100))
    # mites outrun the player and the key forces lingering: combat is
    # genuinely mandatory, not merely present
    b.entity(r2, "mite", (680, 120))
    b.entity(r2, "mite", (720, 80))
    b.entity(r2, "mite", (700, 140))
    b.entity(r2, "key_red", (700, 100))
    b.entity(r1, "ammo_9mm", (450, 150))
    b.entity(r2, "ammo_9mm", (650, 50))
    b.player(r0, (100, 100))
    b.exit(r3, (1000, 100), key="red")
    return b.build(), b.to_dict()


def build_empty_level() -> Level:
    """Two connected rooms, no enemies, exit at the far end."""
    b = LevelBuilder("smoke_empty")
    r0 = b.rect(0, 0, 200, 200)
    r1 = b.rect(300, 0, 200, 200)
    b.connect(r0, 2, r1, 0)
    b.player(r0, (100, 100))
    b.exit(r1, (400, 100))
    return b.build()


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_two_identical_aggro_runs_are_bit_identical():
    level, _ = build_smoke_level()
    res1 = run_bot(level, AggroBot(11), 11, max_ticks=SMOKE_MAX_TICKS)
    res2 = run_bot(level, AggroBot(11), 11, max_ticks=SMOKE_MAX_TICKS)

    assert res1.outcome == res2.outcome
    assert res1.ticks_alive == res2.ticks_alive
    assert res1.events == res2.events
    assert res1.ammo_timeline == res2.ammo_timeline
    assert res1.hp_timeline == res2.hp_timeline
    m1, m2 = dict(res1.metrics), dict(res2.metrics)
    assert m1.pop("rooms_visited") == m2.pop("rooms_visited")
    assert m1 == m2


def test_explorer_bot_run_is_deterministic():
    level, _ = build_smoke_level()
    res1 = run_bot(level, ExplorerBot(5), 5, max_ticks=SMOKE_MAX_TICKS)
    res2 = run_bot(level, ExplorerBot(5), 5, max_ticks=SMOKE_MAX_TICKS)
    assert res1.outcome == res2.outcome
    assert res1.ticks_alive == res2.ticks_alive
    assert res1.metrics["kills"] == res2.metrics["kills"]
    assert res1.metrics["rooms_visited"] == res2.metrics["rooms_visited"]


# ---------------------------------------------------------------------------
# replay round-trip identity
# ---------------------------------------------------------------------------


def test_replay_record_play_roundtrip_identical_final_state():
    level, level_dict = build_smoke_level()
    bot = AggroBot(3)
    session, replay = record(
        lambda: GameSession(level, seed=3),
        lambda s, t: bot.step(s.snapshot(), s),
        SMOKE_MAX_TICKS,
        level_dict=level_dict,
    )
    assert session.complete  # sanity: the recorded run actually finished

    replayed_session, replayed_metrics = play(replay)

    assert replayed_session.tick_count == session.tick_count
    assert replayed_session.hp == session.hp
    assert replayed_metrics["kills"] == session.metrics["kills"]
    assert replayed_session.player_pos() == session.player_pos()
    assert replayed_session.dead == session.dead
    assert replayed_session.complete == session.complete


def test_replay_save_load_gzip_roundtrip():
    level, level_dict = build_smoke_level()
    bot = AggroBot(3)
    session, replay = record(
        lambda: GameSession(level, seed=3),
        lambda s, t: bot.step(s.snapshot(), s),
        SMOKE_MAX_TICKS,
        level_dict=level_dict,
        meta={"note": "unit test"},
    )

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "run.replay.gz")
        replay.save(path)
        loaded = Replay.load(path)

    assert loaded.seed == replay.seed
    assert loaded.frames == replay.frames
    assert loaded.level_dict == replay.level_dict
    assert loaded.meta["note"] == "unit test"

    replayed_session, _ = play(loaded)
    assert replayed_session.tick_count == session.tick_count
    assert replayed_session.hp == session.hp
    assert replayed_session.player_pos() == session.player_pos()


# ---------------------------------------------------------------------------
# bot behavior on smoke levels
# ---------------------------------------------------------------------------


def test_aggro_bot_completes_smoke_level():
    level, _ = build_smoke_level()
    res = run_bot(level, AggroBot(3), 3, max_ticks=SMOKE_MAX_TICKS)
    assert res.outcome == "complete"
    assert res.ticks_alive <= SMOKE_MAX_TICKS
    assert res.metrics["kills"] >= 2


def test_pacifist_bot_survives_empty_level_and_reaches_exit():
    level = build_empty_level()
    res = run_bot(level, PacifistBot(7), 7, max_ticks=SMOKE_MAX_TICKS)
    assert res.outcome == "complete"
    assert res.metrics["dmg_taken"] == 0.0
    assert not res.metrics.get("deaths")


def test_pacifist_bot_does_not_complete_level_with_mandatory_combat():
    level, _ = build_smoke_level()
    res = run_bot(level, PacifistBot(3), 3, max_ticks=SMOKE_MAX_TICKS)
    assert res.outcome != "complete"


def test_camper_and_explorer_bots_run_without_crashing():
    level, _ = build_smoke_level()
    for bot_cls in (CamperBot, ExplorerBot):
        res = run_bot(level, bot_cls(9), 9, max_ticks=60 * 30)
        assert res.outcome in ("complete", "died", "timeout")
        assert res.ticks_alive > 0


def test_assert_playable_smoke_level_has_no_issues():
    level, _ = build_smoke_level()
    issues = assert_playable(level, seed=3, max_ticks=SMOKE_MAX_TICKS)
    assert issues == []


def test_capture_is_best_effort_and_never_fails_the_run():
    """Frame capture must never take down a run: if `perihelion.render`
    is missing, mismatched, or erroring, `capture_skipped` records that and
    the run still completes normally. This intentionally does not assert
    that capture *succeeds* — `render.py` belongs to another slice of this
    codebase and is out of scope here — only that our side of the contract
    (never fail the run) holds, and that a successful capture leaves real
    PNG bytes behind."""
    level, _ = build_smoke_level()
    with tempfile.TemporaryDirectory() as d:
        res = run_bot(level, AggroBot(3), 3, max_ticks=60 * 10,
                       capture_every=6, capture_dir=d)
        assert res.outcome in ("complete", "died", "timeout")
        if not res.capture_skipped:
            frames = sorted(Path(d).glob("frame_*.png"))
            assert frames, "capture reported success but wrote no frames"
            assert frames[0].stat().st_size > 0


# ---------------------------------------------------------------------------
# perf budgets
# ---------------------------------------------------------------------------


def test_perf_budgets_fast_subset():
    """Cheap sanity check on two of the four worst-case worlds at reduced
    tick count — this is the default, always-on perf gate."""
    worlds = {
        "mirror_room": build_mirror_room(),
        "infinite_corridor": build_infinite_corridor(),
    }
    results = run_perf_suite(ticks=120, worlds=worlds, verbose=False)
    issues = assert_perf_budgets(results)
    assert issues == [], issues


@pytest.mark.slow
def test_perf_budgets_full_suite():
    """Full 600-tick perf run across all four worst-case worlds, including
    the radial hub. Measured well under 1s on dev hardware, but kept behind
    the slow marker per spec (`-m "not slow"` for the fast subset)."""
    results = run_perf_suite(ticks=600, verbose=True)
    issues = assert_perf_budgets(results)
    assert issues == [], issues


def test_radial_hub_world_is_well_formed():
    level = build_radial_hub()
    assert len(level.room_verts) == 25  # 1 hub + 8 loops * 3 rooms
    assert len(level.entities) == 24  # 1 husk per loop room
