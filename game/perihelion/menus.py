"""Scene stack widgets: title/menu screens, intro cards, pause/death/win.

`Scene` is the interface `App` drives: only the top of the stack receives
input/update/draw, which is also how pausing works for free -- GameScene
stops ticking the moment anything is pushed above it.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pygame

from .render import INTERNAL_W, INTERNAL_H

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


# Generated-art menu backgrounds (tools/artgen). Every scene that draws one
# falls back to its original procedural background if the file is missing
# or fails to load -- the game must run with an empty assets/art/ dir.
_ART_DIR = Path(__file__).resolve().parent.parent / "assets" / "art"
_BG_CACHE: dict[str, "pygame.Surface | None"] = {}


def _load_bg(name: str) -> "pygame.Surface | None":
    if name in _BG_CACHE:
        return _BG_CACHE[name]
    img = None
    try:
        img = pygame.image.load(str(_ART_DIR / name))
        try:
            img = img.convert()
        except pygame.error:
            pass  # no display surface yet (e.g. headless test) -- blit still works
    except (FileNotFoundError, pygame.error, OSError):
        img = None
    _BG_CACHE[name] = img
    return img


def _blit_bg(surf: "pygame.Surface", bg: "pygame.Surface", size: tuple[int, int]) -> None:
    if bg.get_size() != size:
        bg = pygame.transform.scale(bg, size)
    surf.blit(bg, (0, 0))


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        cur = ""
        for word in para.split(" "):
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
        self.items = ["New Game", "The Vigil (endless)", "Level Select",
                      "Settings", "Quit"]
        self.dust = [(random.uniform(0, INTERNAL_W), random.uniform(0, INTERNAL_H),
                      random.uniform(6, 18)) for _ in range(40)]
        self._text_band: "pygame.Surface | None" = None

    def _ensure_text_band(self, width: int, height: int) -> "pygame.Surface":
        if self._text_band is None or self._text_band.get_size() != (width, height):
            self._text_band = pygame.Surface((width, height), pygame.SRCALPHA)
            self._text_band.fill((0, 0, 0, 110))
        return self._text_band

    def on_enter(self, app) -> None:
        self.t = 0.0
        app.audio.ambience("amb_drone_early")  # the station is never silent
        if app.save_data.get("ng_plus") and "New Game+" not in self.items:
            self.items.insert(1, "New Game+")
        best = app.save_data.get("best_wave", 0)
        if best:
            self.items = [
                (f"The Vigil (endless) - best {best}"
                 if it.startswith("The Vigil") else it)
                for it in self.items]

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
            app.push(DifficultyScene())
        elif item == "New Game+":
            app.push(DifficultyScene(plus=True))
        elif item.startswith("The Vigil"):
            app.start_vigil()
        elif item == "Level Select":
            app.push(LevelSelectScene())
        elif item == "Settings":
            app.push(SettingsScene())
        elif item == "Quit":
            app.quit()

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        bg = _load_bg("title_bg.png")
        if bg is not None:
            _blit_bg(surf, bg, (w, h))
            surf.blit(self._ensure_text_band(w, 235), (0, 0))
        else:
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


class DifficultyScene(Scene):
    """One question between 'New Game' and the dark."""

    def __init__(self, plus: bool = False):
        self.plus = plus
        self.sel = 0
        self.items = [("normal", "NORMAL - the station is hostile"),
                      ("hard", "HARD - the station is hungry")]

    def handle_event(self, app, event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_DOWN, pygame.K_s, pygame.K_UP, pygame.K_w):
            self.sel = 1 - self.sel
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            app.settings["difficulty"] = self.items[self.sel][0]
            app.pop()
            app.start_new_game(plus=self.plus)
        elif event.key == pygame.K_ESCAPE:
            app.pop()

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        surf.fill((6, 6, 10))
        img = get_font(18).render("HOW FAR IN ARE YOU?", True, (230, 230, 230))
        surf.blit(img, (w // 2 - img.get_width() // 2, 70))
        mf = get_font(12)
        for i, (_, label) in enumerate(self.items):
            selected = i == self.sel
            color = (255, 255, 255) if selected else (150, 150, 150)
            prefix = "> " if selected else "  "
            t = mf.render(prefix + label, True, color)
            surf.blit(t, (w // 2 - t.get_width() // 2, 130 + i * 22))
        hint = get_font(10).render("ESC: back", True, (110, 110, 110))
        surf.blit(hint, (10, h - 16))


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
            app._persist_save()  # volume/mute/shake/difficulty survive relaunch
            app.pop()
        elif event.key == pygame.K_LEFT:
            app.audio.set_master(app.audio.master_vol - 0.1)
        elif event.key == pygame.K_RIGHT:
            app.audio.set_master(app.audio.master_vol + 0.1)
        elif event.key == pygame.K_t:
            app.settings["shake"] = not app.settings.get("shake", True)
        elif event.key == pygame.K_m:
            app.audio.set_mute(not app.audio.muted)
        elif event.key == pygame.K_d:
            cur = app.settings.get("difficulty", "normal")
            app.settings["difficulty"] = "hard" if cur == "normal" else "normal"

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
            f"Difficulty: {app.settings.get('difficulty', 'normal')}   (d, next new game)",
            "ESC: back",
        ]
        for i, line in enumerate(lines):
            surf.blit(mf.render(line, True, (180, 180, 180)), (40, 60 + i * 18))


class IntroCard(Scene):
    """Level-name title card shown at the start of a sortie."""

    def __init__(self, name: str, tier: int = 1):
        self.name = name
        self.tier = tier
        self._overlay: "pygame.Surface | None" = None

    def _ensure_overlay(self, size):
        if self._overlay is None or self._overlay.get_size() != size:
            self._overlay = pygame.Surface(size, pygame.SRCALPHA)
            self._overlay.fill((0, 0, 0, 100))
        return self._overlay

    def handle_event(self, app, event) -> None:
        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            app.pop()

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        tier = max(1, min(4, self.tier))
        bg = _load_bg(f"intro_t{tier}.png")
        if bg is not None:
            _blit_bg(surf, bg, (w, h))
            surf.blit(self._ensure_overlay((w, h)), (0, 0))
        else:
            surf.fill((4, 4, 6))
        img = get_font(20).render(self.name, True, (220, 220, 225))
        surf.blit(img, (w // 2 - img.get_width() // 2, 50))
        hint = get_font(10).render("press any key", True, (110, 110, 115))
        surf.blit(hint, (w // 2 - hint.get_width() // 2, h - 22))


class PauseScene(Scene):
    def __init__(self):
        self.sel = 0
        self.items = ["Resume", "Restart Level", "Settings", "Quit to Title"]
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
            elif item == "Settings":
                app.push(SettingsScene())
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


class DeathScene(Scene):
    def __init__(self, deaths: int, wave: int = 0, best_wave: int = 0):
        self.deaths = deaths
        self.wave = wave
        self.best_wave = best_wave
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
        if event.key in (pygame.K_r, pygame.K_SPACE, pygame.K_RETURN):
            app.pop()
            app.restart_level()
        elif event.key == pygame.K_ESCAPE:
            app.pop_to_title()

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        bg = _load_bg("death_bg.png")
        if bg is not None:
            _blit_bg(surf, bg, (w, h))
        elif app.game is not None:
            app.game.draw(app, surf)
        surf.blit(self._ensure_overlay(surf.get_size()), (0, 0))
        pulse = 0.6 + 0.4 * math.sin(self.t * 2.0)
        color = (min(255, int(200 * pulse) + 40), 20, 20)
        img = get_font(26).render("YOU DIED", True, color)
        surf.blit(img, (w // 2 - img.get_width() // 2, 100))
        mf = get_font(12)
        deaths_text = f"deaths: {self.deaths}"
        if self.wave:
            deaths_text = f"waves: {self.wave}   (best: {self.best_wave})"
        img2 = mf.render(deaths_text, True, (190, 150, 150))
        surf.blit(img2, (w // 2 - img2.get_width() // 2, 140))
        img3 = mf.render("SPACE: rise again    ESC: title", True, (170, 130, 130))
        surf.blit(img3, (w // 2 - img3.get_width() // 2, 160))


class WinScene(Scene):
    def __init__(self, text: str):
        self.text = text
        self.scroll_y = 0.0
        self._overlay: "pygame.Surface | None" = None

    def _ensure_overlay(self, size):
        if self._overlay is None or self._overlay.get_size() != size:
            self._overlay = pygame.Surface(size, pygame.SRCALPHA)
            self._overlay.fill((0, 0, 0, 100))
        return self._overlay

    def update(self, app, dt: float) -> None:
        self.scroll_y += dt * 10.0

    def handle_event(self, app, event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            app.pop_to_title()

    def draw(self, app, surf) -> None:
        w, h = surf.get_size()
        bg = _load_bg("win_bg.png")
        if bg is not None:
            _blit_bg(surf, bg, (w, h))
            surf.blit(self._ensure_overlay((w, h)), (0, 0))
        else:
            surf.fill((0, 0, 0))
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
