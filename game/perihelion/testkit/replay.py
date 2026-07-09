"""Deterministic replay recording and playback for `GameSession` runs.

A `Replay` is the minimal data needed to reproduce a run bit-for-bit: the
level (embedded as `level_dict`, or referenced by `level_path`), the seed,
and the packed `InputFrame` row for every tick. Nothing about wall-clock
time, randomness outside `session.rng`/bot RNGs, or engine internals is
recorded — determinism comes entirely from `GameSession.tick` being a pure
function of (level, seed, input sequence).

`record()` drives a fresh session tick-by-tick via an `input_source`
callable (typically a bot's `.step`), capturing every `InputFrame`.
`play()` rebuilds a session from a `Replay` and re-runs it. Because both
paths go through `GameSession(level, seed=...)` -> `session.tick(inp)` with
identical inputs, `play(record(...)[1])` must land on the same final state
as the original run (see `game/tests/test_testkit.py`).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..levels import Level, level_from_dict, load_level
from ..sim import GameSession, InputFrame


@dataclass
class Replay:
    seed: int = 0
    frames: list = field(default_factory=list)  # InputFrame.pack() rows
    level_path: Optional[str] = None
    level_dict: Optional[dict] = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level_path is None and self.level_dict is None:
            raise ValueError("Replay requires level_path or level_dict")

    def level(self) -> Level:
        if self.level_dict is not None:
            return level_from_dict(self.level_dict)
        return load_level(self.level_path)

    def save(self, path: str | Path) -> None:
        payload = dict(seed=self.seed, frames=self.frames,
                        level_path=self.level_path, level_dict=self.level_dict,
                        meta=self.meta)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(payload, f)

    @staticmethod
    def load(path: str | Path) -> "Replay":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        return Replay(seed=payload["seed"], frames=payload["frames"],
                      level_path=payload.get("level_path"),
                      level_dict=payload.get("level_dict"),
                      meta=payload.get("meta", {}))


def record(session_factory: Callable[[], GameSession],
           input_source: Callable[[GameSession, int], InputFrame],
           max_ticks: int, *, level_path: str | Path | None = None,
           level_dict: dict | None = None,
           meta: dict | None = None) -> tuple[GameSession, Replay]:
    """Run `session_factory()` to `max_ticks` (or death/completion),
    recording every `InputFrame` produced by `input_source(session, tick)`.

    The caller must identify the level via `level_path` or `level_dict` (a
    `GameSession` only carries the already-localized `Level`, not the raw
    JSON it was built from, so the source of truth for playback has to be
    supplied explicitly rather than reverse-engineered).
    """
    if level_path is None and level_dict is None:
        raise ValueError("record() needs level_path= or level_dict= to build a Replay")
    session = session_factory()
    replay = Replay(seed=session.seed,
                    level_path=str(level_path) if level_path is not None else None,
                    level_dict=level_dict, meta=dict(meta or {}))
    tick = 0
    while tick < max_ticks and not session.dead and not session.complete:
        inp = input_source(session, tick)
        row = inp.pack()
        replay.frames.append(row)
        # Tick with the *quantized* frame, not the bot's raw floats:
        # InputFrame.pack() rounds mx/my/ax/ay for compact storage, so
        # ticking with the unrounded `inp` here would make this live run
        # diverge from `play()` replaying the rounded row a few hundred
        # ticks later (chaotic sensitivity in the physics amplifies even
        # 1e-4-scale rounding). Recording must drive the session with
        # exactly what gets replayed for record/play to agree bit-for-bit.
        session.tick(InputFrame.unpack(row))
        tick += 1
    replay.meta.setdefault("ticks", session.tick_count)
    replay.meta.setdefault(
        "outcome",
        "complete" if session.complete else ("died" if session.dead else "timeout"),
    )
    return session, replay


def play(replay: Replay, screen: tuple[int, int] = (480, 270),
          zoom: float = 1.35) -> tuple[GameSession, dict]:
    """Rebuild a session from `replay` and re-run every recorded frame."""
    level = replay.level()
    session = GameSession(level, seed=replay.seed, screen=screen, zoom=zoom)
    for row in replay.frames:
        if session.dead or session.complete:
            break
        session.tick(InputFrame.unpack(row))
    return session, session.metrics
