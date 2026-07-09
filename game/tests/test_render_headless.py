"""Headless smoke test for the renderer: SDL_VIDEODRIVER=dummy, no window.

Builds the built-in 3-room debug level, drives 240 ticks of scripted input
(move + fire) through GameSession, feeds fx into Renderer.consume_fx every
tick, and draws onto a plain Surface every 30 ticks. Verifies the renderer
never raises, actually paints something (not a black frame), the player
silhouette is visible near screen center (camera always follows the
player), and draw() stays comfortably within budget. Saves the final frame
as a PNG for human/LLM inspection.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame
import pytest

from perihelion.app import build_debug_level
from perihelion.render import INTERNAL_H, INTERNAL_W, Renderer
from perihelion.sim import GameSession, InputFrame

SCRATCH_PNG = Path(
    "/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter/"
    "6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/render_smoke.png"
)

TOTAL_TICKS = 240
DRAW_EVERY = 30
DRAW_TIME_BUDGET_S = 0.012


def _scripted_input(tick: int) -> InputFrame:
    # Drift right and slightly down across the corridor, aiming ahead, firing
    # in bursts -- exercises movement, room transfer, weapon fx (flash,
    # tracers), and enemy contact (blood/hitflash/gib fx) all at once.
    fire = (tick % 20) < 8
    return InputFrame(
        mx=1.0, my=0.15 * ((tick // 40) % 2 * 2 - 1),
        ax=INTERNAL_W * 0.62, ay=INTERNAL_H * 0.5,
        fire=fire, alt=False, interact=(tick % 97 == 0), weapon=0,
    )


@pytest.fixture(scope="module")
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


def test_render_headless_smoke(pygame_ready):
    level = build_debug_level()
    # screen must match render.INTERNAL_W/H: GameSession bakes the camera
    # matrix and visible-set frustum from `screen` at construction time, so
    # a mismatched default here would off-center the world and clip it to
    # the old resolution regardless of the surface size draw() targets.
    session = GameSession(level, seed=1234, screen=(INTERNAL_W, INTERNAL_H))
    renderer = Renderer(session)

    frames: list[tuple[int, "pygame.Surface"]] = []
    draw_times: list[float] = []

    for tick in range(1, TOTAL_TICKS + 1):
        session.tick(_scripted_input(tick))
        renderer.consume_fx(session.fx)

        if tick % DRAW_EVERY == 0:
            surf = pygame.Surface((INTERNAL_W, INTERNAL_H))
            t0 = time.perf_counter()
            renderer.draw(surf, debug=False)
            draw_times.append(time.perf_counter() - t0)
            frames.append((tick, surf))

    assert len(frames) == TOTAL_TICKS // DRAW_EVERY

    for tick, surf in frames:
        arr = pygame.surfarray.array3d(surf).astype(np.float64)
        variance = float(arr.std())
        assert variance > 5.0, f"tick {tick}: frame looks all-black (std={variance:.2f})"

        # Player silhouette near screen center: camera re-centers on the
        # player every tick (with critically-damped lag while moving), so a
        # bright (non-floor) pixel should always be present in a box around
        # (W/2, H/2) generous enough to cover that lag.
        cx, cy = INTERNAL_W // 2, INTERNAL_H // 2
        box = arr[cx - 40:cx + 40, cy - 40:cy + 40, :]
        brightest = float(box.sum(axis=2).max())
        assert brightest > 260.0, (
            f"tick {tick}: no bright (player) pixel found near screen center "
            f"(max channel-sum={brightest:.1f})"
        )

    mean_draw = sum(draw_times) / len(draw_times)
    assert mean_draw < DRAW_TIME_BUDGET_S, (
        f"draw() mean time {mean_draw * 1000:.2f}ms exceeds {DRAW_TIME_BUDGET_S * 1000:.0f}ms budget"
    )

    SCRATCH_PNG.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(frames[-1][1], str(SCRATCH_PNG))
    assert SCRATCH_PNG.exists()
