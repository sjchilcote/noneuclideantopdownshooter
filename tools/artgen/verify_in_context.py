"""tools/artgen/verify_in_context.py

In-context verification harness for PERIHELION's generated menu art.

Never trust that a generated background "looks right" in isolation -- draw
the *actual* Scene classes (TitleScene, IntroCard for each tier, DeathScene,
WinScene) from game/perihelion/menus.py onto real 480x270 pygame Surfaces,
under SDL_VIDEODRIVER=dummy, with the *actual* game text rendered on top of
the *actual* accepted background art, then save PNG screenshots for human/
LLM visual review: is the text readable, is the mood right, are there seams?

Run:
    SDL_VIDEODRIVER=dummy uv run python tools/artgen/verify_in_context.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "game"))

import pygame  # noqa: E402

from perihelion import menus  # noqa: E402
from perihelion.app import WIN_TEXT  # noqa: E402
from perihelion.render import INTERNAL_H, INTERNAL_W  # noqa: E402

SCRATCH = Path(
    "/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter/"
    "6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/verify_in_context"
)

# Scenes only touch app.game (DeathScene's no-art fallback path); everything
# else they need comes from their own state, so a bare stub is enough.
DUMMY_APP = SimpleNamespace(game=None, audio=None, settings={}, save_data={})

LEVEL_NAMES = {1: "DECK FOURTEEN", 2: "THE AUDIT", 3: "THE FOLD", 4: "THE CORE"}


def _shot(scene: "menus.Scene", name: str, ticks: int) -> Path:
    surf = pygame.Surface((INTERNAL_W, INTERNAL_H))
    for _ in range(ticks):
        scene.update(DUMMY_APP, 1 / 60)
    scene.draw(DUMMY_APP, surf)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f"{name}.png"
    pygame.image.save(surf, str(out))
    return out


def main() -> None:
    pygame.init()
    pygame.font.init()

    shots = []

    title = menus.TitleScene()
    title.on_enter(DUMMY_APP)
    shots.append(_shot(title, "title_scene", ticks=30))

    death = menus.DeathScene(deaths=3)
    shots.append(_shot(death, "death_scene", ticks=10))

    win_early = menus.WinScene(WIN_TEXT)
    shots.append(_shot(win_early, "win_scene_early", ticks=1))

    win_scrolled = menus.WinScene(WIN_TEXT)
    shots.append(_shot(win_scrolled, "win_scene_scrolled", ticks=180))

    for tier in (1, 2, 3, 4):
        card = menus.IntroCard(LEVEL_NAMES[tier], tier)
        shots.append(_shot(card, f"intro_t{tier}_card", ticks=90))

    pygame.quit()

    print("Wrote screenshots:")
    for s in shots:
        print(" ", s)


if __name__ == "__main__":
    main()
