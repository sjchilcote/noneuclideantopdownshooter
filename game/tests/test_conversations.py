"""Between-sortie conversations: data integrity, ConversationScene headless
drive-through, and the App-level campaign wiring (conversation pushed above
the IntroCard on advance_level; win path untouched).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from perihelion.conversations import COMMANDO, CONVERSATIONS, RATIO
from perihelion.convscene import ConversationScene

N_GAPS = 9  # ten campaign levels, nine gaps between them
MAX_LINE_CHARS = 260


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


def test_all_gaps_present_and_wellformed():
    assert set(CONVERSATIONS) == set(range(N_GAPS))
    for gap, conv in CONVERSATIONS.items():
        assert 6 <= len(conv) <= 14, f"gap {gap}: {len(conv)} turns"
        speakers = {s for s, _ in conv}
        assert speakers == {RATIO, COMMANDO}, f"gap {gap}: {speakers}"
        for i, (speaker, line) in enumerate(conv):
            assert isinstance(line, str) and line, f"gap {gap} turn {i}: empty"
            assert len(line) <= MAX_LINE_CHARS, (
                f"gap {gap} turn {i}: {len(line)} chars")


def test_ratio_carries_the_words():
    # Bible 5.2: she supplies ~80% of the words in any shared scene.
    for gap, conv in CONVERSATIONS.items():
        ratio_w = sum(len(l.split()) for s, l in conv if s == RATIO)
        cmdo_w = sum(len(l.split()) for s, l in conv if s == COMMANDO)
        assert ratio_w > 2 * cmdo_w, f"gap {gap}: {ratio_w} vs {cmdo_w}"


# ---------------------------------------------------------------------------
# scene, headless
# ---------------------------------------------------------------------------


class _StubAudio:
    def __init__(self):
        self.plays = 0

    def play(self, name, vol=1.0):
        self.plays += 1


class _StubApp:
    def __init__(self):
        self.audio = _StubAudio()
        self.popped = 0

    def pop(self):
        self.popped += 1


@pytest.fixture(scope="module")
def surf():
    pygame.init()
    return pygame.Surface((480, 270))


def test_scene_rejects_empty_conversation():
    with pytest.raises(ValueError):
        ConversationScene([])
    with pytest.raises(ValueError):
        ConversationScene([("NARRATOR", "hi")])


def test_scene_autoplays_to_completion_headless(surf):
    app = _StubApp()
    scene = ConversationScene(CONVERSATIONS[0])
    for i in range(5000):
        scene.update(app, 0.5)
        if i % 7 == 0:
            scene.draw(app, surf)
        if app.popped:
            break
    assert app.popped == 1, "auto-advance never finished the conversation"
    assert app.audio.plays > 0, "typewriter never blipped"
    # panel border painted in the terminal style
    assert surf.get_at((8, 8))[:3] == (40, 110, 70)


def test_scene_space_advances_and_pops(surf):
    app = _StubApp()
    conv = CONVERSATIONS[8]
    scene = ConversationScene(conv)
    press = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    # each press either completes the typing line or advances past it, so
    # 2 * len(conv) presses must end the scene regardless of timing
    for _ in range(2 * len(conv)):
        scene.handle_event(app, press)
        scene.update(app, 0.01)
    assert app.popped == 1
    scene.update(app, 0.01)  # post-pop tick must be a no-op
    scene.draw(app, surf)
    assert app.popped == 1


def test_scene_click_advances(surf):
    app = _StubApp()
    scene = ConversationScene(CONVERSATIONS[3])
    click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(10, 10))
    scene.handle_event(app, click)          # completes the first line
    assert int(scene.shown) == len(scene.lines[0][1])
    scene.handle_event(app, click)          # advances to the second line
    assert scene.idx == 1


def test_scene_esc_skips_immediately():
    app = _StubApp()
    scene = ConversationScene(CONVERSATIONS[5])
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    scene.handle_event(app, esc)
    assert app.popped == 1
    scene.handle_event(app, esc)            # idempotent
    assert app.popped == 1


# ---------------------------------------------------------------------------
# App-level campaign wiring
# ---------------------------------------------------------------------------


def _make_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from perihelion.app import App

    args = SimpleNamespace(level=None, seed=0, scale=None, mute=True,
                            fps=False, autoplay=False)
    return App(args)


def test_advance_level_pushes_conversation_above_intro(tmp_path, monkeypatch):
    from perihelion import menus
    from perihelion.app import GameScene
    from perihelion.sim import WEAPON_ORDER

    app = _make_app(tmp_path, monkeypatch)
    assert len(app.campaign_levels()) == 10
    assert app.current_level_index == 0

    app.dummy = False  # exercise the real (windowed) push path headlessly
    carried = dict(hp=80, ammo={}, weapons=[WEAPON_ORDER[0]],
                   weapon=WEAPON_ORDER[0])
    app.advance_level(carried)

    assert app.current_level_index == 1
    assert isinstance(app.scenes[-1], ConversationScene)
    assert app.scenes[-1].lines == CONVERSATIONS[0]
    assert isinstance(app.scenes[-2], menus.IntroCard)
    assert isinstance(app.scenes[-3], GameScene)

    # skipping the conversation reveals the intro card underneath
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    app.scenes[-1].handle_event(app, esc)
    assert isinstance(app.scenes[-1], menus.IntroCard)


def test_win_path_pushes_no_conversation(tmp_path, monkeypatch):
    from perihelion import menus
    from perihelion.sim import WEAPON_ORDER

    app = _make_app(tmp_path, monkeypatch)
    app.dummy = False
    app.current_level_index = 9  # completing the final level
    carried = dict(hp=80, ammo={}, weapons=[WEAPON_ORDER[0]],
                   weapon=WEAPON_ORDER[0])
    app.advance_level(carried)
    assert isinstance(app.scenes[-1], menus.WinScene)
    assert not any(isinstance(s, ConversationScene) for s in app.scenes)
