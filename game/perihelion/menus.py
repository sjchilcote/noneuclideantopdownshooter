"""Scene stack widgets: title/menu screens, intro cards, pause/death/win, and
the two overlay widgets (RadioBar, TerminalOverlay) that GameScene drives.

`Scene` is the interface `App` drives: only the top of the stack receives
input/update/draw, which is also how pausing works for free -- GameScene
stops ticking the moment anything is pushed above it.
"""

from __future__ import annotations

import math
import random
from collections import deque
from pathlib import Path

import pygame

from .render import INTERNAL_W, INTERNAL_H

PHOSPHOR_GREEN = (90, 240, 140)
DIM_GREEN = (40, 110, 70)

_FONT_CACHE: dict[int, "pygame.font.Font"] = {}

# Fixedsys Excelsior 3.01 — the game's typeface. It is a bitmap-grid design
# meant to be rendered at 16px vertical; sizes snap to multiples of 16 so
# every glyph stays on the pixel grid at the 480x270 internal resolution.
_FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "FSEX300.ttf"


def _snap(size: int) -> int:
    if size <= 24:
        return 16
    if size <= 40:
        return 32
    return 48


def get_font(size: int) -> "pygame.font.Font":
    size = _snap(size)
    f = _FONT_CACHE.get(size)
    if f is None:
        if not pygame.font.get_init():
            pygame.font.init()
        try:
            f = pygame.font.Font(str(_FONT_PATH), size)
        except (FileNotFoundError, pygame.error):
            f = pygame.font.Font(None, size)
        _FONT_CACHE[size] = f
    return f


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split(" "):
        candidate = (cur + " " + word).strip()
        if len(candidate) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines or [""]


class Scene:
    def on_enter(self, app) -> None: ...
    def on_exit(self, app) -> None: ...
    def handle_event(self, app, event) -> None: ...
    def update(self, app, dt: float) -> None: ...
    def draw(self, app, surf) -> None: ...


# ---------------------------------------------------------------------------


class TitleScene(Scene):
    def __init__(self):
        self.t = 0.0
        self.sel = 0
        self.items = ["New Game", "Level Select", "Settings", "Quit"]
        self.dust = [(random.uniform(0, INTERNAL_W), random.uniform(0, INTERNAL_H),
                      random.uniform(6, 18)) for _ in range(40)]

    def on_enter(self, app) -> None:
        self.t = 0.0

    def update(self, app, dt: float) -> None:
        self.t += dt

    def handle_event(self, app, event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_DOWN, pygame.K_s):
            self.sel = (self.sel + 1) % len(self.items)
        elif event.key in (pygame.K_UP, pygame.K_w):
            self.sel = (self.sel - 1) % len(self.items)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self._activate(app)

    def _activate(self, app) -> None:
        item = self.items[self.sel]
        if item == "New Game":
            app.start_new_game()
        elif item == "Level Select":
            app.push(LevelSelectScene())
        elif item == "Settings":
            app.push(SettingsScene())
        elif item == "Quit":
            app.quit()

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        pulse = 0.5 + 0.5 * math.sin(self.t * 0.6)
        top = (int(14 + 16 * pulse), 4, 6)
        for y in range(h):
            k = y / h
            r = int(top[0] * (1 - k))
            g = int(top[1] * (1 - k))
            b = int(top[2] * (1 - k))
            pygame.draw.line(surf, (r, g, b), (0, y), (w, y))
        for x, y, spd in self.dust:
            y2 = (y + self.t * spd) % h
            surf.set_at((int(x), int(y2)), (95, 75, 62))
        title = get_font(40).render("PERIHELION", True, (235, 225, 210))
        surf.blit(title, (w // 2 - title.get_width() // 2, 55))
        sub = get_font(12).render("a descent into non-Euclidean dark", True, (150, 120, 110))
        surf.blit(sub, (w // 2 - sub.get_width() // 2, 98))
        mf = get_font(16)
        for i, item in enumerate(self.items):
            selected = i == self.sel
            color = (255, 255, 255) if selected else (150, 150, 150)
            prefix = "> " if selected else "  "
            img = mf.render(prefix + item, True, color)
            surf.blit(img, (w // 2 - 60, 150 + i * 20))


class LevelSelectScene(Scene):
    def __init__(self):
        self.sel = 0
        self.levels: list[str] = []
        self.unlocked = 1

    def on_enter(self, app) -> None:
        self.levels = app.campaign_levels()
        self.unlocked = app.save_data.get("unlocked", 1)
        self.sel = 0

    def handle_event(self, app, event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        n = max(1, len(self.levels))
        if event.key in (pygame.K_DOWN, pygame.K_s):
            self.sel = (self.sel + 1) % n
        elif event.key in (pygame.K_UP, pygame.K_w):
            self.sel = (self.sel - 1) % n
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.levels and self.sel < self.unlocked:
                app.start_level_index(self.sel)
        elif event.key == pygame.K_ESCAPE:
            app.pop()

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        surf.fill((6, 6, 10))
        img = get_font(18).render("LEVEL SELECT", True, (230, 230, 230))
        surf.blit(img, (w // 2 - img.get_width() // 2, 20))
        mf = get_font(12)
        if not self.levels:
            hint = mf.render("(no campaign manifest -- debug level only)", True, (140, 140, 140))
            surf.blit(hint, (30, 50))
        for i, path in enumerate(self.levels):
            locked = i >= self.unlocked
            selected = i == self.sel
            color = (90, 90, 90) if locked else ((255, 255, 255) if selected else (170, 170, 170))
            name = f"{i + 1}. {Path(path).stem}" + ("  [locked]" if locked else "")
            surf.blit(mf.render(name, True, color), (40, 50 + i * 16))
        hint = get_font(10).render("ESC: back", True, (110, 110, 110))
        surf.blit(hint, (10, h - 16))


class SettingsScene(Scene):
    def handle_event(self, app, event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_ESCAPE:
            app.pop()
        elif event.key == pygame.K_LEFT:
            app.audio.set_master(app.audio.master_vol - 0.1)
        elif event.key == pygame.K_RIGHT:
            app.audio.set_master(app.audio.master_vol + 0.1)
        elif event.key == pygame.K_t:
            app.settings["shake"] = not app.settings.get("shake", True)
        elif event.key == pygame.K_m:
            app.audio.set_mute(not app.audio.muted)

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        surf.fill((6, 6, 10))
        img = get_font(18).render("SETTINGS", True, (230, 230, 230))
        surf.blit(img, (w // 2 - img.get_width() // 2, 20))
        mf = get_font(12)
        lines = [
            f"Master volume: {app.audio.master_vol:.1f}   (left/right)",
            f"Muted: {'yes' if app.audio.muted else 'no'}   (m)",
            f"Screenshake: {'on' if app.settings.get('shake', True) else 'off'}   (t)",
            "ESC: back",
        ]
        for i, line in enumerate(lines):
            surf.blit(mf.render(line, True, (180, 180, 180)), (40, 60 + i * 18))


class IntroCard(Scene):
    CHARS_PER_SEC = 28.0

    def __init__(self, name: str, text: str):
        self.name = name
        self.text = text
        self.t = 0.0
        self.shown_chars = 0

    def update(self, app, dt: float) -> None:
        self.t += dt
        self.shown_chars = min(len(self.text), int(self.t * self.CHARS_PER_SEC))

    def handle_event(self, app, event) -> None:
        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            if self.shown_chars < len(self.text):
                self.shown_chars = len(self.text)
                # keep in sync so the next update() doesn't rewind the reveal
                self.t = len(self.text) / self.CHARS_PER_SEC
            else:
                app.pop()

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        surf.fill((4, 4, 6))
        img = get_font(20).render(self.name, True, (220, 220, 225))
        surf.blit(img, (w // 2 - img.get_width() // 2, 50))
        bf = get_font(11)
        y = 90
        for line in _wrap(self.text[: self.shown_chars], 58):
            surf.blit(bf.render(line, True, (172, 172, 178)), (30, y))
            y += 14
        if self.shown_chars >= len(self.text):
            hint = get_font(10).render("press any key", True, (110, 110, 115))
            surf.blit(hint, (w // 2 - hint.get_width() // 2, h - 22))


class PauseScene(Scene):
    def __init__(self):
        self.sel = 0
        self.items = ["Resume", "Restart Level", "Quit to Title"]
        self._overlay: "pygame.Surface | None" = None

    def _ensure_overlay(self, size):
        if self._overlay is None or self._overlay.get_size() != size:
            self._overlay = pygame.Surface(size, pygame.SRCALPHA)
            self._overlay.fill((0, 0, 0, 165))
        return self._overlay

    def handle_event(self, app, event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_ESCAPE:
            app.pop()
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.sel = (self.sel + 1) % len(self.items)
        elif event.key in (pygame.K_UP, pygame.K_w):
            self.sel = (self.sel - 1) % len(self.items)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            item = self.items[self.sel]
            if item == "Resume":
                app.pop()
            elif item == "Restart Level":
                app.pop()
                app.restart_level()
            elif item == "Quit to Title":
                app.pop_to_title()

    def draw(self, app, surf) -> None:
        if app.game is not None:
            app.game.draw(app, surf)
        surf.blit(self._ensure_overlay(surf.get_size()), (0, 0))
        w, h = surf.get_size()
        img = get_font(22).render("PAUSED", True, (230, 230, 230))
        surf.blit(img, (w // 2 - img.get_width() // 2, 80))
        mf = get_font(14)
        for i, item in enumerate(self.items):
            selected = i == self.sel
            color = (255, 255, 255) if selected else (150, 150, 150)
            prefix = "> " if selected else "  "
            img = mf.render(prefix + item, True, color)
            surf.blit(img, (w // 2 - 60, 120 + i * 20))


# The cheapest characterization channel in the game: one line of the
# Commando's log per death, in his own register.
PALMER_LOGS = [
    "PALMER LOG: Stripped the old frame for parts. Prayed the De Profundis "
    "over it first. It is not a body, whatever it feels like. It is not a body.",
    "PALMER LOG: Death count rising. The rite does not say how often a man "
    "may be buried. I have started abbreviating.",
    "PALMER LOG: I no longer look at the old frames' faces. This is either "
    "mercy or discipline. The hours continue on schedule.",
    "PALMER LOG: Lauds, on the internal clock. The clock does not know what "
    "deck I died on. Neither, anymore, do I.",
    "PALMER LOG: The seed prints the frames faster now. It has learned my "
    "sizes. I try not to think about what else it is learning.",
    "PALMER LOG: Ratio asked if dying hurts. I said the rules require me "
    "not to check. She did not laugh. Neither did I.",
]


class DeathScene(Scene):
    def __init__(self, deaths: int):
        self.deaths = deaths
        self.t = 0.0
        self._overlay: "pygame.Surface | None" = None

    def _ensure_overlay(self, size):
        if self._overlay is None or self._overlay.get_size() != size:
            self._overlay = pygame.Surface(size, pygame.SRCALPHA)
            self._overlay.fill((40, 0, 0, 190))
        return self._overlay

    def update(self, app, dt: float) -> None:
        self.t += dt

    def handle_event(self, app, event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_r:
            app.pop()
            app.restart_level()
        elif event.key == pygame.K_ESCAPE:
            app.pop_to_title()

    def draw(self, app, surf) -> None:
        if app.game is not None:
            app.game.draw(app, surf)
        surf.blit(self._ensure_overlay(surf.get_size()), (0, 0))
        w, h = surf.get_size()
        pulse = 0.6 + 0.4 * math.sin(self.t * 2.0)
        color = (min(255, int(200 * pulse) + 40), 20, 20)
        img = get_font(26).render("YOU DIED", True, color)
        surf.blit(img, (w // 2 - img.get_width() // 2, 100))
        mf = get_font(12)
        img2 = mf.render(f"deaths: {self.deaths}", True, (190, 150, 150))
        surf.blit(img2, (w // 2 - img2.get_width() // 2, 140))
        img3 = mf.render("R: retry level    ESC: title", True, (170, 130, 130))
        surf.blit(img3, (w // 2 - img3.get_width() // 2, 160))
        log = PALMER_LOGS[min(self.deaths - 1, len(PALMER_LOGS) - 1)] \
            if self.deaths >= 1 else PALMER_LOGS[0]
        y = 196
        words = log.split()
        line = ""
        for word in words + [""]:
            trial = (line + " " + word).strip()
            if word and mf.size(trial)[0] < w - 80:
                line = trial
                continue
            if line:
                img4 = mf.render(line, True, (150, 140, 120))
                surf.blit(img4, (w // 2 - img4.get_width() // 2, y))
                y += 16
            line = word


class WinScene(Scene):
    def __init__(self, text: str):
        self.text = text
        self.scroll_y = 0.0

    def update(self, app, dt: float) -> None:
        self.scroll_y += dt * 10.0

    def handle_event(self, app, event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            app.pop_to_title()

    def draw(self, app, surf) -> None:
        surf.fill((0, 0, 0))
        w, h = surf.get_size()
        f = get_font(13)
        lines = _wrap(self.text, 56)
        y0 = h - self.scroll_y
        for i, line in enumerate(lines):
            y = y0 + i * 16
            if -16 <= y <= h:
                img = f.render(line, True, (225, 225, 225))
                surf.blit(img, (w // 2 - img.get_width() // 2, y))
        if self.scroll_y > len(lines) * 16 + h:
            hint = get_font(10).render("ESC: title", True, (120, 120, 120))
            surf.blit(hint, (w // 2 - hint.get_width() // 2, h - 16))


class TerminalOverlay(Scene):
    def __init__(self, text: str):
        self.text = text
        self.scroll = 0
        self._overlay: "pygame.Surface | None" = None

    def _ensure_overlay(self, size):
        if self._overlay is None or self._overlay.get_size() != size:
            self._overlay = pygame.Surface(size, pygame.SRCALPHA)
            self._overlay.fill((0, 10, 4, 225))
        return self._overlay

    def handle_event(self, app, event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_e, pygame.K_ESCAPE, pygame.K_RETURN):
            app.pop()
        elif event.key == pygame.K_DOWN:
            self.scroll += 1
        elif event.key == pygame.K_UP:
            self.scroll = max(0, self.scroll - 1)

    def draw(self, app, surf) -> None:
        if app.game is not None:
            app.game.draw(app, surf)
        w, h = surf.get_size()
        surf.blit(self._ensure_overlay(surf.get_size()), (0, 0))
        pygame.draw.rect(surf, DIM_GREEN, (16, 16, w - 32, h - 32), 1)
        f = get_font(11)
        y = 26
        for line in _wrap(self.text, 62)[self.scroll:]:
            surf.blit(f.render(line, True, PHOSPHOR_GREEN), (26, y))
            y += 14
            if y > h - 30:
                break
        hint = get_font(9).render("E/ESC: close", True, DIM_GREEN)
        surf.blit(hint, (w - hint.get_width() - 20, h - 26))


# ---------------------------------------------------------------------------


class RadioBar:
    """Bottom-strip typewriter for ("radio", text) fx. A widget, not a Scene
    -- GameScene owns and drives it every sim tick so it decays in ticks
    like everything else, and draws it itself after the world."""

    HOLD_TICKS = 90
    CHARS_PER_TICK = 0.9

    def __init__(self):
        self.queue: deque[str] = deque()
        self.current = ""
        self.shown = 0
        self.hold = 0
        self._accum = 0.0
        self._strip = pygame.Surface((INTERNAL_W, 22), pygame.SRCALPHA)
        self._strip.fill((0, 15, 6, 200))

    def push(self, text: str) -> None:
        self.queue.append(text)

    def update(self, app) -> None:
        if not self.current:
            if not self.queue:
                return
            self.current = self.queue.popleft()
            self.shown = 0
            self._accum = 0.0
        if self.shown < len(self.current):
            self._accum += self.CHARS_PER_TICK
            new_shown = min(len(self.current), int(self._accum))
            if new_shown > self.shown and (new_shown // 3) != (self.shown // 3):
                app.audio.play("radio_blip", 0.5)
            self.shown = new_shown
        else:
            self.hold += 1
            if self.hold > self.HOLD_TICKS:
                self.current = ""
                self.hold = 0

    def draw(self, app, surf) -> None:
        if not self.current:
            return
        w, h = surf.get_size()
        surf.blit(self._strip, (0, h - 22))
        pygame.draw.line(surf, PHOSPHOR_GREEN, (0, h - 22), (w, h - 22), 1)
        img = get_font(12).render(self.current[: self.shown], True, PHOSPHOR_GREEN)
        surf.blit(img, (8, h - 17))
