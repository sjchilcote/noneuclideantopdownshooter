"""Micro-benchmarks for the four worst-case world shapes called out in
ENGINE_DESIGN.md §5: a radial hub with looping corridors (many simultaneous
portals), a self-connecting mirror room (unbounded visibility recursion,
capped by max_depth), a 40-room grid (broad-phase / router stress), and an
infinite corridor pair (the other unbounded-recursion shape). Each world is
driven by an AggroBot for `ticks` ticks; `session.tick()` and
`session.visible(14, 96)` wall time is sampled independently every tick.

Run directly: `uv run python -m game.perihelion.testkit.perf`
"""

from __future__ import annotations

import math
import time

from ..levels import Level, LevelBuilder
from ..sim import GameSession
from .bots import AggroBot

TICK_BUDGET_P90_MS = 2.5
VISIBLE_BUDGET_P90_MS = 3.0
CI_SLACK = 2.0  # budgets asserted at 2x the nominal number to absorb CI noise

DEFAULT_TICKS = 600
DEFAULT_SEED = 1


def build_radial_hub() -> Level:
    """Octagonal hub; each of its 8 edges feeds a 3-room corridor that
    closes back into a loop (not back through the hub — every hub edge is
    used exactly once as an attachment point)."""
    b = LevelBuilder("perf_radial_hub")
    hub = b.ngon(0.0, 0.0, 220.0, 8)
    for i in range(8):
        origins = [(2000.0 + i * 600.0 + j * 140.0, 0.0) for j in range(3)]
        rooms = [b.rect(ox, oy, 120.0, 120.0) for ox, oy in origins]
        b.connect(hub, i, rooms[0], 0)
        b.connect(rooms[0], 2, rooms[1], 0)
        b.connect(rooms[1], 2, rooms[2], 0)
        b.connect(rooms[2], 2, rooms[0], 1)  # close the loop
        # entity/player/exit take absolute canvas coords, not room-local
        # offsets, so re-add each room's own origin here.
        for r, (ox, oy) in zip(rooms, origins):
            b.entity(r, "husk", (ox + 60.0, oy + 60.0))
    b.player(hub, (0.0, 0.0))
    return b.build()


def build_mirror_room() -> Level:
    """A single room whose opposite edges self-connect: the classic
    infinite-mirror-corridor visibility worst case."""
    b = LevelBuilder("perf_mirror_room")
    r = b.rect(0.0, 0.0, 300.0, 300.0)
    b.connect(r, 0, r, 2)
    for i in range(6):
        b.entity(r, "mite", (20.0 + i * 40.0, 20.0))
    b.player(r, (150.0, 150.0))
    return b.build()


def build_grid40(cols: int = 8, rows: int = 5) -> Level:
    """A cols*rows (default 40) room grid, each cell connected to its right
    and below neighbor — broad-phase/router stress, many active rooms."""
    b = LevelBuilder("perf_grid40")
    size = 140.0
    grid: dict[tuple[int, int], int] = {}
    for j in range(rows):
        for i in range(cols):
            grid[(i, j)] = b.rect(i * size, j * size, size, size)
    for j in range(rows):
        for i in range(cols):
            room = grid[(i, j)]
            if i + 1 < cols:
                b.connect(room, 2, grid[(i + 1, j)], 0)
            if j + 1 < rows:
                b.connect(room, 1, grid[(i, j + 1)], 3)
    # entity/player take absolute canvas coords: re-add each cell's own
    # (i*size, j*size) origin, not just a room-local offset.
    for idx, ((i, j), r) in enumerate(grid.items()):
        if idx % 5 == 0:
            b.entity(r, "husk", (i * size + size / 2.0, j * size + size / 2.0))
    ci, cj = cols // 2, rows // 2
    b.player(grid[(ci, cj)], (ci * size + size / 2.0, cj * size + size / 2.0))
    return b.build()


def build_infinite_corridor() -> Level:
    """Two long rooms connected end-to-end both ways: walking either
    direction never terminates. Unbounded recursion depth, the other shape,
    capped by max_depth."""
    b = LevelBuilder("perf_infinite_corridor")
    a = b.rect(0.0, 0.0, 60.0, 500.0)
    c = b.rect(1000.0, 0.0, 60.0, 500.0)
    b.connect(a, 2, c, 0)
    b.connect(c, 2, a, 0)
    for i in range(4):
        b.entity(a, "mite", (30.0, 50.0 + i * 100.0))
    b.player(a, (30.0, 250.0))
    return b.build()


WORLDS = {
    "radial_hub": build_radial_hub,
    "mirror_room": build_mirror_room,
    "grid40": build_grid40,
    "infinite_corridor": build_infinite_corridor,
}


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def _bench_world(level: Level, ticks: int = DEFAULT_TICKS, seed: int = DEFAULT_SEED) -> dict:
    session = GameSession(level, seed=seed)
    bot = AggroBot(seed)
    tick_ms: list[float] = []
    visible_ms: list[float] = []
    for _ in range(ticks):
        if session.dead or session.complete:
            session = GameSession(level, seed=seed)
            bot = AggroBot(seed)
        snap = session.snapshot()
        inp = bot.step(snap, session)

        t0 = time.perf_counter()
        session.tick(inp)
        tick_ms.append((time.perf_counter() - t0) * 1000.0)

        t0 = time.perf_counter()
        session.visible(14, 96)
        visible_ms.append((time.perf_counter() - t0) * 1000.0)

    tick_ms.sort()
    visible_ms.sort()
    return dict(
        tick_p50=_percentile(tick_ms, 0.5), tick_p90=_percentile(tick_ms, 0.9),
        tick_max=max(tick_ms),
        visible_p50=_percentile(visible_ms, 0.5), visible_p90=_percentile(visible_ms, 0.9),
        visible_max=max(visible_ms),
    )


def run_perf_suite(ticks: int = DEFAULT_TICKS, seed: int = DEFAULT_SEED,
                    worlds: dict | None = None, verbose: bool = True) -> dict:
    worlds = worlds if worlds is not None else {name: build() for name, build in WORLDS.items()}
    results = {name: _bench_world(level, ticks=ticks, seed=seed) for name, level in worlds.items()}
    if verbose:
        print_table(results)
    return results


def print_table(results: dict) -> None:
    cols = ["world", "tick p50", "tick p90", "tick max", "vis p50", "vis p90", "vis max"]
    hdr = f"{cols[0]:<20}" + "".join(f"{c:>10}" for c in cols[1:])
    print(hdr)
    print("-" * len(hdr))
    for name, r in results.items():
        print(f"{name:<20}"
              f"{r['tick_p50']:>10.3f}{r['tick_p90']:>10.3f}{r['tick_max']:>10.3f}"
              f"{r['visible_p50']:>10.3f}{r['visible_p90']:>10.3f}{r['visible_max']:>10.3f}")


def assert_perf_budgets(results: dict, slack: float = CI_SLACK) -> list[str]:
    issues = []
    for name, r in results.items():
        tick_budget = TICK_BUDGET_P90_MS * slack
        vis_budget = VISIBLE_BUDGET_P90_MS * slack
        if r["tick_p90"] >= tick_budget:
            issues.append(f"{name}: tick p90 {r['tick_p90']:.3f}ms >= {tick_budget:.3f}ms budget")
        if r["visible_p90"] >= vis_budget:
            issues.append(f"{name}: visible p90 {r['visible_p90']:.3f}ms >= {vis_budget:.3f}ms budget")
    return issues


if __name__ == "__main__":
    results = run_perf_suite()
    issues = assert_perf_budgets(results)
    if issues:
        for issue in issues:
            print("BUDGET FAIL:", issue)
        raise SystemExit(1)
    print("all perf budgets OK")
