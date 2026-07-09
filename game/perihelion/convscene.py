"""ConversationScene: full-screen tight-beam dialogue played between
campaign levels, above the next level's IntroCard on the scene stack.

Styled after menus.TerminalOverlay (dark panel, thin border, phosphor
green) with the Commando's lines in bone-amber so the two voices read at a
glance. One line types at a time; SPACE or a mouse click completes the
current line or advances to the next; ESC skips the whole scene; a
completed line auto-advances after IDLE_ADVANCE_S of no input. Imports
from menus only -- no dependency on render.py (draw sizes come from the
target surface).

CHOICE TURNS (the trust/antagonize mechanic). A conversation's turn list may
contain, alongside ordinary (speaker, text) turns, a CHOICE turn:

    ("CHOICE", [(posture, commando_line, *ratio_reply_lines), ...])

`posture` is "warm" (generous) or "cold" (guarded) per the bible's "hate the
sin, not the sinner" axis (NARRATIVE_DESIGN_DOC.md SS8.2). `commando_line` is
the line the Commando speaks if the player picks that option; every string
after it in the tuple is a follow-up line RATIO speaks in sequence. A CHOICE
turn pauses the scene and renders a 1/2 menu instead of typewriting; picking
an option splices the chosen branch's resolved (speaker, text) turns into
playback and adds +1 (warm) or -1 (cold) to `self.result_trust`.
`ConversationScene(lines, on_trust=callback)` -- if given, `on_trust(delta)`
fires exactly once, with the conversation's total accumulated
`result_trust`, when the scene finishes (naturally or via ESC skip). See
tools/dialogue and the module-level report for the app-side persistence hook
this callback is meant to feed (App does not yet call it; see the director's
integration note).
"""

from __future__ import annotations

from typing import Callable, Optional

import pygame

from .menus import DIM_GREEN, PHOSPHOR_GREEN, Scene, _wrap, get_font

COMMANDO_BONE = (231, 214, 178)
CHOICE_AMBER = (255, 200, 90)
HEADER = "TIGHT-BEAM // FRAME IN TRANSIT"

CHARS_PER_SEC = 55.0
IDLE_ADVANCE_S = 2.5
WRAP_WIDTH = 52          # chars; Fixedsys at 16px is ~8px/glyph on a 480 panel
LINE_STEP = 16           # px; keeps the bitmap font on its pixel grid
MARGIN = 26
HEADER_H = 30
FOOTER_H = 34

SPEAKER_COLORS = {"RATIO": PHOSPHOR_GREEN, "COMMANDO": COMMANDO_BONE}
VALID_POSTURES = {"warm", "cold"}
TRUST_DELTA = {"warm": 1, "cold": -1}

_CHOICE_KEYS = {
    0: (pygame.K_1, pygame.K_KP1),
    1: (pygame.K_2, pygame.K_KP2),
}


def _validate(lines: list) -> None:
    if not lines:
        raise ValueError("ConversationScene requires a non-empty conversation")
    for turn in lines:
        if not isinstance(turn, tuple) or len(turn) != 2:
            raise ValueError(f"malformed turn {turn!r}")
        head, body = turn
        if head == "CHOICE":
            if not isinstance(body, (list, tuple)) or len(body) < 2:
                raise ValueError(f"CHOICE turn needs >=2 options, got {body!r}")
            for opt in body:
                if not isinstance(opt, tuple) or len(opt) < 2:
                    raise ValueError(f"malformed CHOICE option {opt!r}")
                posture = opt[0]
                if posture not in VALID_POSTURES:
                    raise ValueError(f"unknown posture {posture!r} (want warm/cold)")
                if not opt[1]:
                    raise ValueError(f"CHOICE option missing its Commando line: {opt!r}")
        elif head not in SPEAKER_COLORS:
            raise ValueError(f"unknown speaker {head!r}")


class ConversationScene(Scene):
    def __init__(self, lines: list[tuple], on_trust: Optional[Callable[[int], None]] = None):
        _validate(lines)
        self.lines = list(lines)          # authored script, verbatim (CHOICE turns included)
        self.on_trust = on_trust
        self.result_trust = 0
        self.idx = 0                      # index into self._turns (the resolved playback list)
        self.shown = 0.0                  # fractional chars revealed of current line
        self.idle = 0.0                   # seconds since current line completed
        self.finished = False             # guards double-pop / double on_trust
        self._turns: list[tuple[str, str]] = []
        self._script_pos = 0              # next index in self.lines to pull
        self._awaiting_choice = False
        self._pending_options: list[tuple] = []
        self._pull_until_choice()

    # ------------------------------------------------------------------
    # script -> playback resolution
    # ------------------------------------------------------------------

    def _pull_until_choice(self) -> None:
        while self._script_pos < len(self.lines):
            turn = self.lines[self._script_pos]
            self._script_pos += 1
            if turn[0] == "CHOICE":
                self._pending_options = turn[1]
                self._awaiting_choice = True
                return
            self._turns.append(turn)
        self._awaiting_choice = False

    def _in_choice(self) -> bool:
        return self._awaiting_choice and self.idx >= len(self._turns)

    def choose(self, app, option_index: int) -> None:
        if not self._in_choice():
            return
        if not (0 <= option_index < len(self._pending_options)):
            return
        posture, commando_line, *replies = self._pending_options[option_index]
        self.result_trust += TRUST_DELTA[posture]
        self._turns.append(("COMMANDO", commando_line))
        for line in replies:
            self._turns.append(("RATIO", line))
        self._awaiting_choice = False
        self._pending_options = []
        self._pull_until_choice()
        self.shown = 0.0
        self.idle = 0.0

    # ------------------------------------------------------------------

    def _current_complete(self) -> bool:
        if self._in_choice():
            return False
        return int(self.shown) >= len(self._turns[self.idx][1])

    def _advance(self, app) -> None:
        if self.idx + 1 < len(self._turns):
            self.idx += 1
            self.shown = 0.0
            self.idle = 0.0
        elif self._awaiting_choice:
            self.idx = len(self._turns)   # sit at the choice gate
        else:
            self._finish(app)

    def _finish(self, app) -> None:
        if not self.finished:
            self.finished = True
            if self.on_trust is not None:
                self.on_trust(self.result_trust)
            app.pop()

    # ------------------------------------------------------------------

    def handle_event(self, app, event) -> None:
        if self.finished:
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._finish(app)
            return
        if self._in_choice():
            if event.type == pygame.KEYDOWN:
                for option_index, keys in _CHOICE_KEYS.items():
                    if event.key in keys:
                        self.choose(app, option_index)
                        return
            return
        advance = False
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                advance = True
        elif event.type == pygame.MOUSEBUTTONDOWN:
            advance = True
        if advance:
            if self._current_complete():
                self._advance(app)
            else:
                self.shown = float(len(self._turns[self.idx][1]))
                self.idle = 0.0

    def update(self, app, dt: float) -> None:
        if self.finished or self._in_choice():
            return
        text = self._turns[self.idx][1]
        if int(self.shown) < len(text):
            before = int(self.shown)
            self.shown = min(float(len(text)), self.shown + CHARS_PER_SEC * dt)
            if (int(self.shown) // 3) != (before // 3):
                app.audio.play("radio_blip", 0.35)
        else:
            self.idle += dt
            if self.idle >= IDLE_ADVANCE_S:
                self._advance(app)

    # ------------------------------------------------------------------

    def _rows(self) -> list[tuple[str, tuple[int, int, int]]]:
        """Wrapped transcript rows for the resolved turns so far, the last
        one partial unless we're sitting at a choice gate (all complete)."""
        rows: list[tuple[str, tuple[int, int, int]]] = []
        n = self.idx if self._in_choice() else min(self.idx + 1, len(self._turns))
        for i in range(n):
            speaker, text = self._turns[i]
            if not self._in_choice() and i == self.idx:
                text = text[: int(self.shown)]
            color = SPEAKER_COLORS[speaker]
            wrapped = _wrap(f"{speaker}: {text}", WRAP_WIDTH)
            for j, row in enumerate(wrapped):
                rows.append((row if j == 0 else "  " + row, color))
            if i < n - 1 or self._in_choice():
                rows.append(("", color))  # blank spacer between finished turns
        return rows

    def _choice_rows(self) -> list[tuple[str, tuple[int, int, int]]]:
        rows: list[tuple[str, tuple[int, int, int]]] = [("", CHOICE_AMBER)]
        for i, opt in enumerate(self._pending_options[:2]):
            _, commando_line = opt[0], opt[1]
            wrapped = _wrap(f"{i + 1}) {commando_line}", WRAP_WIDTH)
            for j, row in enumerate(wrapped):
                rows.append((row if j == 0 else "   " + row, CHOICE_AMBER))
        return rows

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        surf.fill((0, 10, 4))
        pygame.draw.rect(surf, DIM_GREEN, (8, 8, w - 16, h - 16), 1)
        f = get_font(12)
        surf.blit(f.render(HEADER, True, DIM_GREEN), (16, 12))
        pygame.draw.line(surf, DIM_GREEN, (16, HEADER_H), (w - 16, HEADER_H), 1)

        rows = self._rows()
        if self._in_choice():
            rows = rows + self._choice_rows()
        max_rows = max(1, (h - HEADER_H - FOOTER_H - 8) // LINE_STEP)
        y = HEADER_H + 6
        for text, color in rows[-max_rows:]:
            if text:
                surf.blit(f.render(text, True, color), (MARGIN, y))
            y += LINE_STEP

        hint = "1/2: choose    ESC: skip" if self._in_choice() else "SPACE: next    ESC: skip"
        img = get_font(9).render(hint, True, DIM_GREEN)
        surf.blit(img, (w - img.get_width() - 20, h - 28))
