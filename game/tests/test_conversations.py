"""Between-sortie conversations: data integrity (including CHOICE turns and
the gap-8 trust-gated variant), ConversationScene headless drive-through
(typewriter path and scripted choice path), the App-level campaign wiring
(conversation pushed above the IntroCard on advance_level; win path
untouched), and the dialogue-pipeline rubric report.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from perihelion.conversations import (
    COMMANDO, CONVERSATIONS, CONVERSATIONS_HIGH_TRUST_GAP8,
    HIGH_TRUST_THRESHOLD, RATIO, conversation_for,
)
from perihelion.convscene import ConversationScene

N_GAPS = 9  # ten campaign levels, nine gaps between them
MAX_LINE_CHARS = 240
MIN_TURNS = 14
MAX_TURNS = 24
CHOICE_GAPS = {0, 4, 6, 8}  # first terms, data-share, Osei, disclosure answer
REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# data -- authored structure
# ---------------------------------------------------------------------------


def _flatten(conv: list[tuple], branch: str) -> list[tuple[str, str]]:
    """Resolve every CHOICE turn in `conv` along `branch` ("warm"/"cold")
    into plain (speaker, text) turns -- i.e. one concrete playthrough."""
    out: list[tuple[str, str]] = []
    for turn in conv:
        if turn[0] == "CHOICE":
            options = {opt[0]: opt for opt in turn[1]}
            posture, commando_line, *replies = options[branch]
            out.append((COMMANDO, commando_line))
            for line in replies:
                out.append((RATIO, line))
        else:
            out.append(turn)
    return out


def _all_conversations() -> dict[str, list[tuple]]:
    convs = {f"gap{g}": CONVERSATIONS[g] for g in CONVERSATIONS}
    convs["gap8-high-trust"] = CONVERSATIONS_HIGH_TRUST_GAP8
    return convs


def test_all_gaps_present_and_wellformed():
    assert set(CONVERSATIONS) == set(range(N_GAPS))
    for gap, conv in CONVERSATIONS.items():
        assert MIN_TURNS <= len(conv) <= MAX_TURNS, f"gap {gap}: {len(conv)} turns"


@pytest.mark.parametrize("name,conv", list(_all_conversations().items()))
def test_conversation_structure_and_line_length(name, conv):
    for i, turn in enumerate(conv):
        head, body = turn[0], turn[1]
        if head == "CHOICE":
            options = turn[1]
            assert len(options) >= 2, f"{name} turn {i}: CHOICE needs >=2 options"
            postures = {opt[0] for opt in options}
            assert postures <= {"warm", "cold"}, f"{name} turn {i}: bad postures {postures}"
            for opt in options:
                posture, commando_line, *replies = opt
                assert commando_line and len(commando_line) <= MAX_LINE_CHARS
                for reply in replies:
                    assert reply and len(reply) <= MAX_LINE_CHARS
        else:
            assert head in (RATIO, COMMANDO), f"{name} turn {i}: unknown speaker {head!r}"
            assert isinstance(body, str) and body, f"{name} turn {i}: empty line"
            assert len(body) <= MAX_LINE_CHARS, f"{name} turn {i}: {len(body)} chars"


@pytest.mark.parametrize("name,conv", list(_all_conversations().items()))
@pytest.mark.parametrize("branch", ["warm", "cold"])
def test_flattened_playthrough_wellformed(name, conv, branch):
    flat = _flatten(conv, branch)
    assert MIN_TURNS <= len(flat) <= MAX_TURNS + 3, (
        f"{name}/{branch}: {len(flat)} resolved turns")
    speakers = {s for s, _ in flat}
    assert speakers <= {RATIO, COMMANDO}, f"{name}/{branch}: {speakers}"
    assert flat[0][0] == RATIO, f"{name}/{branch}: does not open on RATIO"


def test_ratio_carries_the_words():
    # Bible SS5.2: she supplies ~80% of the words in any shared scene. Check
    # every possible resolved playthrough (both CHOICE branches), not just
    # the raw authored text, since only one branch plays per playthrough.
    for name, conv in _all_conversations().items():
        for branch in ("warm", "cold"):
            flat = _flatten(conv, branch)
            ratio_w = sum(len(l.split()) for s, l in flat if s == RATIO)
            cmdo_w = sum(len(l.split()) for s, l in flat if s == COMMANDO)
            assert ratio_w > 2 * cmdo_w, f"{name}/{branch}: {ratio_w} vs {cmdo_w}"


def test_choice_gaps_match_the_load_bearing_beats():
    # first terms, data-share reaction, Osei, disclosure answer (task spec).
    have_choice = {g for g, conv in CONVERSATIONS.items()
                   if any(t[0] == "CHOICE" for t in conv)}
    assert have_choice == CHOICE_GAPS
    assert any(t[0] == "CHOICE" for t in CONVERSATIONS_HIGH_TRUST_GAP8)


def test_gap8_trust_gate():
    assert conversation_for(8, 0) is CONVERSATIONS[8]
    assert conversation_for(8, HIGH_TRUST_THRESHOLD - 1) is CONVERSATIONS[8]
    assert conversation_for(8, HIGH_TRUST_THRESHOLD) is CONVERSATIONS_HIGH_TRUST_GAP8
    assert conversation_for(8, HIGH_TRUST_THRESHOLD + 5) is CONVERSATIONS_HIGH_TRUST_GAP8
    # every other gap ignores total_trust
    for gap in range(N_GAPS):
        if gap == 8:
            continue
        assert conversation_for(gap, 99) is CONVERSATIONS[gap]


def test_gap8_variants_stay_undecided_on_the_page():
    # bible rule: neither branch of the disclosure answer may resolve to an
    # explicit yes/no, in either trust variant.
    refusals_or_yeses = ("yes.", "no.", "i will.", "i won't.")
    for conv in (CONVERSATIONS[8], CONVERSATIONS_HIGH_TRUST_GAP8):
        choice_turn = next(t for t in conv if t[0] == "CHOICE")
        for opt in choice_turn[1]:
            _, commando_line, *_replies = opt
            assert commando_line.strip().lower() not in refusals_or_yeses


# ---------------------------------------------------------------------------
# scene, headless -- typewriter path
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


def test_scene_rejects_malformed_choice():
    with pytest.raises(ValueError):
        ConversationScene([(RATIO, "hi"), ("CHOICE", [("neutral", "ok")])])
    with pytest.raises(ValueError):
        ConversationScene([(RATIO, "hi"), ("CHOICE", [("warm", "ok")])])  # only 1 option


def test_scene_autoplays_to_completion_headless(surf):
    # A gap with no CHOICE turn (gap 2 -- "the hours") so pure update()-only
    # idle-advance can drive it to completion without any input, matching
    # the original typewriter-only autoplay contract. Choice-bearing gaps
    # cannot auto-resolve -- see test_scene_scripted_choice_path_headless.
    app = _StubApp()
    scene = ConversationScene(CONVERSATIONS[2])
    for i in range(8000):
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
    conv = CONVERSATIONS[7]  # no CHOICE turn -- pure SPACE-driven advance
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
    assert int(scene.shown) == len(scene._turns[0][1])
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
# scene, headless -- CHOICE path
# ---------------------------------------------------------------------------


def _drive_to_choice_gate(app, scene, space):
    for _ in range(500):
        if scene._in_choice() or scene.finished:
            return
        scene.handle_event(app, space)
        scene.update(app, 0.01)
    raise AssertionError("never reached a choice gate")


def test_scene_scripted_choice_path_headless(surf):
    """Drives an entire choice-bearing gap (gap 0: first terms) headlessly
    via a scripted key sequence: SPACE through ordinary lines, '1' at the
    choice gate (the warm option), to completion -- exercising the CHOICE
    turn end-to-end the way the task calls for."""
    app = _StubApp()
    scene = ConversationScene(CONVERSATIONS[0])
    space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    one = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1)

    _drive_to_choice_gate(app, scene, space)
    assert scene._in_choice()
    scene.draw(app, surf)  # choice menu must render without error

    scene.handle_event(app, one)
    assert not scene._in_choice()
    assert scene.result_trust == 1  # option 0 is "warm" in every CHOICE turn authored here

    for _ in range(500):
        scene.handle_event(app, space)
        scene.update(app, 0.01)
        if app.popped:
            break
    assert app.popped == 1


def test_scene_choice_cold_option_and_on_trust_callback():
    app = _StubApp()
    trust_reports = []
    scene = ConversationScene(CONVERSATIONS[4], on_trust=lambda d: trust_reports.append(d))
    space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    two = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_2)

    _drive_to_choice_gate(app, scene, space)
    scene.handle_event(app, two)
    assert scene.result_trust == -1  # option 1 is "cold" in every CHOICE turn authored here

    for _ in range(500):
        scene.handle_event(app, space)
        scene.update(app, 0.01)
        if app.popped:
            break
    assert app.popped == 1
    assert trust_reports == [-1], "on_trust must fire exactly once, with the final total"


def test_scene_esc_mid_choice_still_reports_trust():
    app = _StubApp()
    trust_reports = []
    scene = ConversationScene(CONVERSATIONS[6], on_trust=lambda d: trust_reports.append(d))
    space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    one = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1)
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)

    _drive_to_choice_gate(app, scene, space)
    scene.handle_event(app, one)
    assert scene.result_trust == 1
    scene.handle_event(app, esc)
    assert app.popped == 1
    assert trust_reports == [1]


def test_scene_ignores_choice_keys_outside_choice_mode():
    app = _StubApp()
    scene = ConversationScene(CONVERSATIONS[1])  # no CHOICE turns at all
    one = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1)
    scene.handle_event(app, one)
    assert scene.idx == 0 and scene.shown == 0.0  # '1' is not a typewriter-advance key


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


# ---------------------------------------------------------------------------
# dialogue pipeline artifacts (tools/dialogue)
# ---------------------------------------------------------------------------


def test_rubric_report_exists_and_has_all_gaps():
    report_path = REPO_ROOT / "tools" / "dialogue" / "report.json"
    assert report_path.exists(), (
        "tools/dialogue/report.json missing -- run "
        "`uv run python tools/dialogue/judge.py --rubric --all` first")
    report = json.loads(report_path.read_text())
    assert "rubric" in report
    assert set(report["rubric"]) == {str(g) for g in range(N_GAPS)}
    for gap_key, gap_result in report["rubric"].items():
        assert "winners" in gap_result
        assert "scored" in gap_result
