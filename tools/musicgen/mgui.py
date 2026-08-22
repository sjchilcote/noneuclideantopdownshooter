"""mgui — the musicgen tools' local UI kit on the engine stack.

game/perihelion is frozen, so anything its uievent/fb2d/text/audio
surface lacks lives HERE: the extra SDL key constants the DAW binds,
an extended winit-name→key table (uievent.from_platform reads its own
module-level table, so we mirror its logic over the wider one), a Rect
with the pygame geometry helpers these tools kept (collidepoint), a
frame-paced Clock, a Display that owns the necore.Window + the (W,H,3)
numpy frame every tool draws into, and a one-channel OneShot player
for the click-to-audition browsers.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

import necore

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "game") not in sys.path:
    sys.path.insert(0, str(ROOT / "game"))

from perihelion import fb2d, text, uievent          # noqa: E402
from perihelion.audio import (                      # noqa: E402
    Audio, EngineChannel, EngineSound)

# -- key constants uievent lacks (SDL keycode values, uievent's own
#    convention: copied verbatim from pygame-ce 2.5.7) -----------------
K_PLUS = 43
K_COMMA = 44
K_MINUS = 45
K_PERIOD = 46
K_SLASH = 47
K_EQUALS = 61
K_F1 = 1073741882
K_HOME = 1073741898
K_END = 1073741901
K_KP_MINUS = 1073741910
K_KP_PLUS = 1073741911

#: uievent.WINIT_KEYS + the physical keys only these tools bind
WINIT_KEYS = dict(uievent.WINIT_KEYS)
WINIT_KEYS.update({
    "Comma": K_COMMA, "Period": K_PERIOD, "Minus": K_MINUS,
    "Equal": K_EQUALS, "Slash": K_SLASH, "F1": K_F1,
    "Home": K_HOME, "End": K_END,
    "NumpadAdd": K_KP_PLUS, "NumpadSubtract": K_KP_MINUS,
})


def from_platform(ev) -> "uievent.Event | None":
    """uievent.from_platform over the EXTENDED key table (same logic;
    non-key events delegate straight through)."""
    kind, _a, _b, name, txt = ev
    if kind in (1, 2):
        return uievent.Event(
            uievent.KEYDOWN if kind == 1 else uievent.KEYUP,
            key=WINIT_KEYS.get(name, -1), unicode=txt, ch=txt)
    return uievent.from_platform(ev)


class Rect(fb2d.Rect):
    """fb2d.Rect + the pygame geometry calls the tools kept."""

    def collidepoint(self, x, y=None):
        if y is None:
            x, y = x
        return (self.x <= x < self.x + self.w
                and self.y <= y < self.y + self.h)

    def inflate(self, dx, dy) -> "Rect":
        return Rect(self.x - dx // 2, self.y - dy // 2,
                    self.w + dx, self.h + dy)


class Clock:
    """Frame pacing (pygame.time.Clock.tick's replacement)."""

    def __init__(self):
        self._last = time.perf_counter()

    def tick(self, fps: float) -> None:
        target = self._last + 1.0 / max(1e-6, fps)
        now = time.perf_counter()
        if target > now:
            time.sleep(target - now)
            now = time.perf_counter()
        self._last = now


class Display:
    """The OS window + the frame the tool draws.

    `fb` is a (W, H, 3) uint8 view (fb2d/text axis order: fb[x, y] =
    pixel) into an RGBA row-major buffer; `flip()` presents that buffer
    (app.py's exact idiom). headless=True skips the window entirely —
    drawing and events() still work (events() is just empty), which is
    how the fault suite drives the DAW."""

    def __init__(self, w: int, h: int, title: str,
                 headless: bool = False):
        self.w, self.h = int(w), int(h)
        self._raw = bytearray(self.w * self.h * 4)
        self._np = np.frombuffer(self._raw, dtype=np.uint8) \
            .reshape(self.h, self.w, 4)
        self.fb = self._np[:, :, :3].transpose(1, 0, 2)
        self.window = None
        if not headless:
            self.window = necore.Window(self.w, self.h, title)
            # materialize + service the window now (app.py's lesson:
            # the first pump answers compositor pings)
            self.window.pump()
        self.mouse_pos: tuple[int, int] = (0, 0)
        self._mods = 0

    def events(self) -> list:
        """Drain platform events as uievent.Event objects carrying the
        pygame-era fields the tools read: button events get pos (winit
        reports it only on motion), key events get the live SHIFT
        bitmask (winit reports no modifier state on key events)."""
        out = []
        if self.window is None:
            return out
        for raw in self.window.pump():
            ev = from_platform(raw)
            if ev is None:
                continue
            if ev.type == uievent.MOUSEMOTION:
                self.mouse_pos = ev.pos
            elif ev.type in (uievent.MOUSEBUTTONDOWN,
                             uievent.MOUSEBUTTONUP):
                ev.pos = self.mouse_pos
            elif ev.type in (uievent.KEYDOWN, uievent.KEYUP):
                if ev.key in (uievent.K_LSHIFT, uievent.K_RSHIFT):
                    if ev.type == uievent.KEYDOWN:
                        self._mods |= uievent.KMOD_SHIFT
                    else:
                        self._mods &= ~uievent.KMOD_SHIFT
                ev.mod = self._mods
            out.append(ev)
        return out

    def flip(self) -> None:
        if self.window is not None:
            self.window.present(bytes(self._raw), self.w, self.h)


# -- one engine mixer per process (music + audition share it) ----------
_audio: Audio | None = None


def audio() -> Audio:
    global _audio
    if _audio is None:
        _audio = Audio()
    return _audio


def audio_reinit() -> Audio:
    """Fresh mixer backend (the DAW's R-recovery after device death)."""
    global _audio
    _audio = Audio()
    return _audio


class OneShot:
    """Click-to-audition playback: one channel, one file at a time
    (pygame.mixer.stop() + Sound(path).play() as one gesture)."""

    def __init__(self, aud: Audio, ch: int = 0):
        self.audio = aud
        self.ch = EngineChannel(aud, ch)
        self._snd: EngineSound | None = None

    def play(self, path) -> None:
        snd = EngineSound.from_file(self.audio, path)
        if snd is None and self.audio.mixer is not None:
            # from_file already named the reason on stderr
            raise RuntimeError(f"can't play {path}")
        self.ch.stop()
        if self._snd is not None:
            self._snd.free()
        self._snd = snd
        if snd is not None:
            self.ch.play(snd)

    def stop(self) -> None:
        self.ch.stop()
