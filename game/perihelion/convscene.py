"""ConversationScene: full-screen tight-beam dialogue played between
campaign levels, above the next level's IntroCard on the scene stack.

Styled after menus.TerminalOverlay (dark panel, thin border, phosphor
green) with the Commando's lines in bone-amber so the two voices read at a
glance. One line types at a time; SPACE or a mouse click completes the
current line or advances to the next; ESC skips the whole scene; a
completed line auto-advances after IDLE_ADVANCE_S of no input. Imports
from menus only -- no dependency on render.py (draw sizes come from the
target surface).
"""

from __future__ import annotations

import pygame

from .menus import DIM_GREEN, PHOSPHOR_GREEN, Scene, _wrap, get_font

COMMANDO_BONE = (231, 214, 178)
HEADER = "TIGHT-BEAM // FRAME IN TRANSIT"

CHARS_PER_SEC = 55.0
IDLE_ADVANCE_S = 2.5
WRAP_WIDTH = 52          # chars; Fixedsys at 16px is ~8px/glyph on a 480 panel
LINE_STEP = 16           # px; keeps the bitmap font on its pixel grid
MARGIN = 26
HEADER_H = 30
FOOTER_H = 34

SPEAKER_COLORS = {"RATIO": PHOSPHOR_GREEN, "COMMANDO": COMMANDO_BONE}


class ConversationScene(Scene):
    def __init__(self, lines: list[tuple[str, str]]):
        if not lines:
            raise ValueError("ConversationScene requires a non-empty conversation")
        for speaker, _ in lines:
            if speaker not in SPEAKER_COLORS:
                raise ValueError(f"unknown speaker {speaker!r}")
        self.lines = list(lines)
        self.idx = 0             # current line being typed / shown
        self.shown = 0.0         # fractional chars revealed of current line
        self.idle = 0.0          # seconds since current line completed
        self.finished = False    # guards double-pop

    # ------------------------------------------------------------------

    def _current_complete(self) -> bool:
        return int(self.shown) >= len(self.lines[self.idx][1])

    def _advance(self, app) -> None:
        if self.idx + 1 < len(self.lines):
            self.idx += 1
            self.shown = 0.0
            self.idle = 0.0
        else:
            self._finish(app)

    def _finish(self, app) -> None:
        if not self.finished:
            self.finished = True
            app.pop()

    # ------------------------------------------------------------------

    def handle_event(self, app, event) -> None:
        if self.finished:
            return
        advance = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._finish(app)
                return
            if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                advance = True
        elif event.type == pygame.MOUSEBUTTONDOWN:
            advance = True
        if advance:
            if self._current_complete():
                self._advance(app)
            else:
                self.shown = float(len(self.lines[self.idx][1]))
                self.idle = 0.0

    def update(self, app, dt: float) -> None:
        if self.finished:
            return
        text = self.lines[self.idx][1]
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
        """Wrapped transcript rows for lines[0..idx], the last one partial."""
        rows: list[tuple[str, tuple[int, int, int]]] = []
        for i in range(self.idx + 1):
            speaker, text = self.lines[i]
            if i == self.idx:
                text = text[: int(self.shown)]
            color = SPEAKER_COLORS[speaker]
            wrapped = _wrap(f"{speaker}: {text}", WRAP_WIDTH)
            for j, row in enumerate(wrapped):
                rows.append((row if j == 0 else "  " + row, color))
            if i < self.idx:
                rows.append(("", color))  # blank spacer between finished turns
        return rows

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        surf.fill((0, 10, 4))
        pygame.draw.rect(surf, DIM_GREEN, (8, 8, w - 16, h - 16), 1)
        f = get_font(12)
        surf.blit(f.render(HEADER, True, DIM_GREEN), (16, 12))
        pygame.draw.line(surf, DIM_GREEN, (16, HEADER_H), (w - 16, HEADER_H), 1)

        rows = self._rows()
        max_rows = max(1, (h - HEADER_H - FOOTER_H - 8) // LINE_STEP)
        y = HEADER_H + 6
        for text, color in rows[-max_rows:]:
            if text:
                surf.blit(f.render(text, True, color), (MARGIN, y))
            y += LINE_STEP

        hint = "SPACE: next    ESC: skip"
        img = get_font(9).render(hint, True, DIM_GREEN)
        surf.blit(img, (w - img.get_width() - 20, h - 28))
