"""Headless bot-playtest harness: drive a `GameSession` with a `Bot` for up
to `max_ticks`, collecting the metrics/derived stats/event log an AI (or a
human skimming a report) needs to judge whether a level is playable and
fun-shaped, without ever opening a window.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..levels import Level
from ..sim import ENEMIES, GameSession, InputFrame
from .bots import AggroBot, Bot, CamperBot, ExplorerBot, PacifistBot

DEFAULT_MAX_TICKS = 60 * 300
CONTAINMENT_MARGIN = 8.0
TICK_BUDGET_MS = 2.5


@dataclass
class Result:
    outcome: str  # 'complete' | 'died' | 'timeout'
    metrics: dict
    ticks_alive: int
    rooms_visited: int
    ammo_timeline: list = field(default_factory=list)   # [(tick, total_ammo), ...]
    hp_timeline: list = field(default_factory=list)      # [(tick, hp), ...]
    ammo_starved_ticks: int = 0
    time_in_combat_ticks: int = 0
    portal_crossings: int = 0
    events: list = field(default_factory=list)
    capture_skipped: bool = False
    capture_dir: str | None = None
    seed: int = 0
    bot: str = ""


def _capture_frame(renderer_mod, session: GameSession, capture_dir: str | Path,
                    frame_idx: int) -> bool:
    """Best-effort single-frame PNG capture via an SDL dummy-safe Surface.
    Returns False (never raises) on any failure — `render.py` doesn't exist
    yet in this tree, so this path is exercised once it lands; until then
    every capture attempt safely no-ops via the except below."""
    try:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame

        pygame.init()
        surf = pygame.Surface((session.screen_w, session.screen_h))
        # Assumed contract for perihelion.render: a function that draws the
        # current session state onto a given Surface. See report gap notes.
        renderer_mod.render_to_surface(session, surf)
        Path(capture_dir).mkdir(parents=True, exist_ok=True)
        pygame.image.save(surf, str(Path(capture_dir) / f"frame_{frame_idx:06d}.png"))
        return True
    except Exception:
        return False


def run_bot(level: Level, bot: Bot, seed: int, max_ticks: int = DEFAULT_MAX_TICKS,
            capture_every: int = 0, capture_dir: str | Path | None = None,
            renderer=None) -> Result:
    session = GameSession(level, seed=seed)

    events: list[dict] = []
    ammo_timeline: list[tuple[int, int]] = []
    hp_timeline: list[tuple[int, float]] = []
    ammo_starved_ticks = 0
    time_in_combat_ticks = 0
    prev_kills = prev_pickups = 0
    prev_dmg_taken = 0.0

    capture_skipped = False
    renderer_mod = renderer
    if capture_every > 0 and renderer_mod is None:
        try:
            import perihelion.render as renderer_mod  # lazy; module may not exist yet
        except Exception:
            capture_skipped = True
    frame_idx = 0

    i = 0
    while i < max_ticks and not session.dead and not session.complete:
        snap = session.snapshot()
        proom = snap["room"]
        if any(e["room"] == proom for e in snap["enemies"]):
            time_in_combat_ticks += 1

        inp = bot.step(snap, session)
        session.tick(inp)
        i += 1

        m = session.metrics
        if m["kills"] > prev_kills:
            events.append(dict(tick=session.tick_count, type="kill",
                                count=m["kills"] - prev_kills))
            prev_kills = m["kills"]
        if m["dmg_taken"] > prev_dmg_taken:
            events.append(dict(tick=session.tick_count, type="damage_taken",
                                amount=m["dmg_taken"] - prev_dmg_taken))
            prev_dmg_taken = m["dmg_taken"]
        if m["pickups"] > prev_pickups:
            events.append(dict(tick=session.tick_count, type="pickup",
                                count=m["pickups"] - prev_pickups))
            prev_pickups = m["pickups"]

        total_ammo = sum(session.ammo.values())
        if total_ammo <= 0:
            ammo_starved_ticks += 1
        if session.tick_count % 60 == 0:
            ammo_timeline.append((session.tick_count, total_ammo))
            hp_timeline.append((session.tick_count, session.hp))

        if (capture_every > 0 and not capture_skipped and capture_dir is not None
                and session.tick_count % capture_every == 0):
            ok = _capture_frame(renderer_mod, session, capture_dir, frame_idx)
            frame_idx += 1
            if not ok:
                capture_skipped = True

    outcome = "complete" if session.complete else ("died" if session.dead else "timeout")
    return Result(
        outcome=outcome,
        metrics=dict(session.metrics),
        ticks_alive=session.tick_count,
        rooms_visited=len(session.metrics["rooms_visited"]),
        ammo_timeline=ammo_timeline,
        hp_timeline=hp_timeline,
        ammo_starved_ticks=ammo_starved_ticks,
        time_in_combat_ticks=time_in_combat_ticks,
        portal_crossings=session.metrics["transfers"],
        events=events,
        capture_skipped=capture_skipped,
        capture_dir=str(capture_dir) if capture_dir is not None else None,
        seed=seed,
        bot=type(bot).__name__,
    )


def summarize(res: Result) -> dict:
    """JSON-safe summary of a `Result` (metrics['rooms_visited'] is a set;
    everything else is already JSON-native)."""
    m = dict(res.metrics)
    if isinstance(m.get("rooms_visited"), set):
        m["rooms_visited"] = sorted(m["rooms_visited"])
    return dict(
        outcome=res.outcome, bot=res.bot, seed=res.seed,
        ticks_alive=res.ticks_alive, rooms_visited=res.rooms_visited,
        ammo_starved_ticks=res.ammo_starved_ticks,
        time_in_combat_ticks=res.time_in_combat_ticks,
        portal_crossings=res.portal_crossings,
        capture_skipped=res.capture_skipped, capture_dir=res.capture_dir,
        metrics=m, ammo_timeline=res.ammo_timeline, hp_timeline=res.hp_timeline,
        events=res.events,
    )


def _instantiate(bot_like, seed: int) -> Bot:
    if isinstance(bot_like, Bot):
        return type(bot_like)(seed)
    return bot_like(seed)  # a Bot subclass or a seed->Bot factory


def run_matrix(level: Level, bots: list, seeds: list[int],
                max_ticks: int = DEFAULT_MAX_TICKS) -> list[dict]:
    """Run every (bot, seed) pair, return a flat table of summary rows.
    `bots` elements may be `Bot` subclasses, `seed -> Bot` factories, or
    already-constructed instances (a fresh instance of the same class is
    made per seed either way, so state never leaks across runs)."""
    table = []
    for bot_like in bots:
        for seed in seeds:
            bot = _instantiate(bot_like, seed)
            res = run_bot(level, bot, seed, max_ticks=max_ticks)
            table.append(dict(
                bot=res.bot, seed=seed, outcome=res.outcome,
                ticks_alive=res.ticks_alive, kills=res.metrics["kills"],
                dmg_dealt=res.metrics["dmg_dealt"], dmg_taken=res.metrics["dmg_taken"],
                rooms_visited=res.rooms_visited, portal_crossings=res.portal_crossings,
                ammo_starved_ticks=res.ammo_starved_ticks,
                time_in_combat_ticks=res.time_in_combat_ticks,
            ))
    return table


def assert_playable(level: Level, seed: int = 0, max_ticks: int = DEFAULT_MAX_TICKS,
                     containment_ticks: int = 3600) -> list[str]:
    """Cheap, deterministic playability gate for a level. Returns a list of
    human-readable issues (empty == passes)."""
    issues: list[str] = []

    aggro = AggroBot(seed)
    aggro_res = run_bot(level, aggro, seed, max_ticks=max_ticks)
    if aggro_res.outcome != "complete":
        issues.append(
            f"AggroBot did not complete (outcome={aggro_res.outcome}, "
            f"ticks_alive={aggro_res.ticks_alive}/{max_ticks})"
        )

    has_enemies = any(spec.type in ENEMIES for _, spec in level.entities)
    if has_enemies:
        pac_res = run_bot(level, PacifistBot(seed), seed, max_ticks=max_ticks)
        if pac_res.outcome == "complete":
            issues.append(
                "PacifistBot completed a level with enemies present "
                "(expected death or timeout under mandatory combat)"
            )

    for bot_cls in (AggroBot, PacifistBot, CamperBot, ExplorerBot):
        bot = bot_cls(seed)
        session = GameSession(level, seed=seed)
        t = 0
        while t < min(max_ticks, containment_ticks) and not session.dead and not session.complete:
            snap = session.snapshot()
            room = snap["room"]
            radius = session.sim.room_radius(room)
            px, py = snap["pos"]
            r = math.hypot(px, py)
            if r > radius + CONTAINMENT_MARGIN:
                issues.append(
                    f"{bot_cls.__name__} escaped room {room} bounds at tick "
                    f"{snap['tick']} (|pos|={r:.1f} > room_radius+margin={radius + CONTAINMENT_MARGIN:.1f})"
                )
                break
            inp = bot.step(snap, session)
            session.tick(inp)
            t += 1

    fps_session = GameSession(level, seed=seed)
    fps_bot = AggroBot(seed)
    n = min(600, max_ticks)
    elapsed = 0.0
    count = 0
    for _ in range(n):
        if fps_session.dead or fps_session.complete:
            break
        snap = fps_session.snapshot()
        inp = fps_bot.step(snap, fps_session)
        t0 = time.perf_counter()
        fps_session.tick(inp)
        elapsed += time.perf_counter() - t0
        count += 1
    if count > 0:
        mean_ms = (elapsed / count) * 1000.0
        if mean_ms >= TICK_BUDGET_MS:
            issues.append(f"mean session.tick() wall time {mean_ms:.3f}ms >= {TICK_BUDGET_MS}ms budget")

    return issues
