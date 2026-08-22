"""The music-generator audition instrument.

    uv run python tools/musicgen/instrument.py

Drives the REAL game music engine (game/perihelion/music.py MusicSystem,
same engine mixer path the game uses) over generated banks in out/banks/.
Everything you hear is exactly what the game would play.

Controls (mouse + keys):
  melody list (left)     click to load that bank
  stage tier 1-4         keys 1-4 or click
  weapon list            click, or [ / ] to cycle
  enemy rows             click - / + to add or remove aggro'd enemies
  hp slider              drag
  PRAYER/CONTEMPT/       drag sliders in MANUAL; M toggles AUTO/MANUAL
  STALWART               (AUTO = the game's heuristic battery computes
                          them from the enemies/hp you set up)
  T                      flicker tension on/off (riser + pounce sting)
  R                      reload the current bank from disk (hear a
                         replaced stem file without restarting)
  SPACE / click FIRE     fire current weapon (real game SFX);
  A                      auto-fire on the beat; Q = quantize to 8ths
  beat strip (bottom)    flashes on each 8th; bar line marked
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "game"))
sys.path.insert(0, str(ROOT / "tools/musicgen"))

import mgui                                            # noqa: E402
from mgui import Rect                                  # noqa: E402
from perihelion import fb2d, text, uievent             # noqa: E402
from perihelion import music as M                      # noqa: E402
from perihelion.audio import Audio                     # noqa: E402
from perihelion.sim import WEAPONS, WEAPON_ORDER       # noqa: E402

BANKS = ROOT / "out" / "banks"
ENEMY_KINDS = ["mite", "husk", "spitter", "shrieker", "brute", "warden",
               "flicker"]

W, H = 1180, 720
FPS = 60


class FakeSim:
    def get_polygon(self, eid):
        return 0


class FakeSession:
    """The engine's complete input surface, driven by UI state."""

    def __init__(self):
        self.level_name = "instrument"
        self.weapon = "pistol"
        self.hp = 100.0
        self.tick_count = 0
        self.enemies = {}
        self.sim = FakeSim()
        self.music_tier = 1
        self._next_eid = 1
        self._tension_on = False

    def player_polygon(self):
        return 0

    def add_enemy(self, kind):
        state = "lurk" if kind == "flicker" and self._tension_on \
            else "chase"
        self.enemies[self._next_eid] = {"kind": kind, "state": state}
        self._next_eid += 1

    def remove_enemy(self, kind):
        for eid, e in list(self.enemies.items()):
            if e["kind"] == kind:
                del self.enemies[eid]
                return

    def counts(self):
        c = {k: 0 for k in ENEMY_KINDS}
        for e in self.enemies.values():
            c[e["kind"]] += 1
        return c

    def set_tension(self, on):
        self._tension_on = on
        for e in self.enemies.values():
            if e["kind"] == "flicker":
                e["state"] = "lurk" if on else "chase"


class Btn:
    def __init__(self, rect, label, cb, selected=lambda: False):
        self.rect = Rect(*rect)
        self.label = label
        self.cb = cb
        self.selected = selected


def main():
    disp = mgui.Display(W, H, "PERIHELION music instrument")
    screen = disp.fb
    font, big = 14, 18            # text.blit_text sizes (FSEX300)

    audio = Audio()
    audio.master_vol = 1.0
    # ONLY current-pipeline banks (album_*), labeled by track title —
    # stale generate_bank-era banks retired (director: "certainly isn't
    # the same pipeline that produced these tracks")
    banks = sorted(p for p in BANKS.iterdir()
                   if p.name.startswith("album_")
                   and (p / "bank.json").exists()) \
        if BANKS.exists() else []
    if not banks:
        print("No banks in out/banks/ — run tools/musicgen/generate_bank.py "
              "<melody> first.", file=sys.stderr)
        return
    sess = FakeSession()
    state = dict(bank_i=0, auto=True, manual=[0.8, 0.1, 0.1],
                 autofire=False, quantize=True, tension=False,
                 last_shot_beat=-1, fire_flash=0.0, pending_shot=False)
    ms = None

    def load_bank(i):
        nonlocal ms
        state["bank_i"] = i % len(banks)
        if ms is not None:
            ms.stop()
        ms = M.MusicSystem(audio, enabled=True,
                           bank_dir=banks[state["bank_i"]])
        sess.tick_count = 0

    load_bank(0)

    buttons: list[Btn] = []

    def layout():
        buttons.clear()
        y = 46
        for i, b in enumerate(banks):
            import json as _j
            label = _j.loads((b / "bank.json").read_text()) \
                .get("title", b.name)[:24]
            buttons.append(Btn((12, y, 190, 22), label,
                               lambda i=i: load_bank(i),
                               lambda i=i: state["bank_i"] == i))
            y += 25
        for t in range(1, 5):
            buttons.append(Btn((230 + (t - 1) * 52, 46, 46, 24),
                               f"T{t}",
                               lambda t=t: setattr(sess, "music_tier", t),
                               lambda t=t: sess.music_tier == t))
        y = 108
        for i, w in enumerate(WEAPON_ORDER):
            buttons.append(Btn((230, y, 120, 20), w,
                               lambda w=w: setattr(sess, "weapon", w),
                               lambda w=w: sess.weapon == w))
            y += 23
        y = 108
        for k in ENEMY_KINDS:
            kk = k
            buttons.append(Btn((385, y, 20, 20), "-",
                               lambda kk=kk: sess.remove_enemy(kk)))
            buttons.append(Btn((475, y, 20, 20), "+",
                               lambda kk=kk: sess.add_enemy(kk)))
            y += 26
        buttons.append(Btn((385, y + 6, 110, 22), "clear all",
                           lambda: sess.enemies.clear()))

    layout()

    sliders = {  # name -> rect; manual P/C/S + hp
        "PRAYER": Rect(560, 80, 26, 220),
        "CONTEMPT": Rect(640, 80, 26, 220),
        "STALWART": Rect(720, 80, 26, 220),
        "hp": Rect(385, 320, 130, 14),
    }
    drag = None

    def fire():
        w = WEAPONS.get(sess.weapon, {})
        snd = w.get("sound")
        if snd:
            audio.play(snd, 0.9, 0.5)
        state["fire_flash"] = 1.0

    clock = mgui.Clock()
    running = True
    while running:
        for ev in disp.events():
            if ev.type == uievent.QUIT:
                running = False
            elif ev.type == uievent.KEYDOWN:
                if ev.key == uievent.K_ESCAPE:
                    running = False
                elif ev.key == uievent.K_m:
                    state["auto"] = not state["auto"]
                elif ev.key == uievent.K_r:
                    # hot-reload: re-slice the current bank from disk
                    # (drop a replacement stem in the folder, press R)
                    load_bank(state["bank_i"])
                elif ev.key == uievent.K_a:
                    state["autofire"] = not state["autofire"]
                elif ev.key == uievent.K_q:
                    state["quantize"] = not state["quantize"]
                elif ev.key == uievent.K_t:
                    state["tension"] = not state["tension"]
                    sess.set_tension(state["tension"])
                    if state["tension"] and not any(
                            e["kind"] == "flicker"
                            for e in sess.enemies.values()):
                        sess.add_enemy("flicker")
                elif ev.key == uievent.K_SPACE:
                    state["pending_shot"] = True
                elif ev.key in (uievent.K_1, uievent.K_2, uievent.K_3,
                                uievent.K_4):
                    sess.music_tier = ev.key - uievent.K_0
                elif ev.key == uievent.K_LEFTBRACKET:
                    i = WEAPON_ORDER.index(sess.weapon)
                    sess.weapon = WEAPON_ORDER[(i - 1) % len(WEAPON_ORDER)]
                elif ev.key == uievent.K_RIGHTBRACKET:
                    i = WEAPON_ORDER.index(sess.weapon)
                    sess.weapon = WEAPON_ORDER[(i + 1) % len(WEAPON_ORDER)]
            elif ev.type == uievent.MOUSEBUTTONDOWN:
                for b in buttons:
                    if b.rect.collidepoint(ev.pos):
                        b.cb()
                for name, r in sliders.items():
                    if r.inflate(16, 16).collidepoint(ev.pos):
                        drag = name
                if Rect(560, 560, 200, 70).collidepoint(ev.pos):
                    state["pending_shot"] = True
            elif ev.type == uievent.MOUSEBUTTONUP:
                drag = None
            elif ev.type == uievent.MOUSEMOTION and drag:
                r = sliders[drag]
                if drag == "hp":
                    v = (ev.pos[0] - r.x) / r.w
                    sess.hp = max(0.0, min(1.0, v)) * 100.0
                else:
                    v = 1.0 - (ev.pos[1] - r.y) / r.h
                    idx = ["PRAYER", "CONTEMPT", "STALWART"].index(drag)
                    state["manual"][idx] = max(0.0, min(1.0, v))

        # ---- engine tick (the real thing) -------------------------------
        ms.override_vals = None if state["auto"] \
            else tuple(round(v, 3) for v in state["manual"])
        ms.update(sess)
        sess.tick_count += 1

        # ---- beat clock + shooting (the audio's clock, not tick 0) ------
        t_s = ms.music_time(sess.tick_count)
        eighth = ms.bar_s / 8.0
        beat_i = int(t_s / eighth)
        on_beat = (t_s % eighth) < 0.05
        if state["pending_shot"]:
            if not state["quantize"] or on_beat:
                fire()
                state["pending_shot"] = False
                state["last_shot_beat"] = beat_i
        if state["autofire"] and beat_i != state["last_shot_beat"] \
                and beat_i % 2 == 0 and on_beat:
            fire()
            state["last_shot_beat"] = beat_i
        state["fire_flash"] *= 0.9

        # ---- draw ---------------------------------------------------------
        fb2d.fill(screen, (16, 16, 20))

        def txt(s, x, y, c=(200, 200, 200), f=font):
            text.blit_text(screen, s, x, y, c, f)

        txt("MELODY", 12, 24, (240, 220, 160), big)
        txt("STAGE", 230, 24, (240, 220, 160), big)
        txt("WEAPON", 230, 88, (240, 220, 160), big)
        txt("ENEMIES (aggro)", 385, 88, (240, 220, 160), big)
        cnt = sess.counts()
        yy = 108
        for k in ENEMY_KINDS:
            txt(f"{cnt[k]}", 412, yy + 2, (255, 255, 255))
            txt(k, 500, yy + 2)
            yy += 26
        txt(f"hp {sess.hp:5.0f}", 385, 300)
        for b in buttons:
            sel = b.selected()
            fb2d.rect(screen, (90, 70, 40) if sel else (40, 40, 48),
                      b.rect)
            fb2d.rect(screen, (140, 120, 80) if sel else (70, 70, 80),
                      b.rect, 1)
            txt(b.label, b.rect.x + 5, b.rect.y + 3,
                (255, 240, 200) if sel else (190, 190, 190))
        # sliders + live vals
        vals = ms.vals
        live = [ms._live.get(n, 0.0) for n in ("holy", "groove", "wall")]
        txt(f"{'AUTO' if state['auto'] else 'MANUAL'} (M to toggle)",
            560, 40, (240, 220, 160), big)
        for i, name in enumerate(["PRAYER", "CONTEMPT", "STALWART"]):
            r = sliders[name]
            fb2d.rect(screen, (36, 36, 42), r)
            v = vals[i] if state["auto"] else state["manual"][i]
            fh = int(r.h * v)
            col = [(120, 170, 220), (220, 160, 90), (200, 80, 80)][i]
            fb2d.rect(screen, col,
                      (r.x, r.y + r.h - fh, r.w, fh))
            lh = int(r.h * min(1.0, live[i]))
            fb2d.rect(screen, (255, 255, 255),
                      (r.x + r.w + 4, r.y + r.h - lh, 3, lh))
            txt(name, r.x - 14, r.y + r.h + 8)
            txt(f"{v:.2f}", r.x, r.y - 18)
        r = sliders["hp"]
        fb2d.rect(screen, (36, 36, 42), r)
        fb2d.rect(screen, (120, 200, 120),
                  (r.x, r.y, int(r.w * sess.hp / 100), r.h))
        # engine state readout
        txt(f"bank: {banks[state['bank_i']].name}   "
            f"bar {ms._bar_idx}   bpm {240/ms.bar_s:.0f}   "
            f"riser {ms._riser_gain:.2f}", 12, 640)
        act = [f"{n}:{lane.key}={lane.gain:.2f}"
               for n, lane in sorted(ms._lanes.items())
               if lane.gain > 0.02 and lane.key != "silence"]
        txt("  ".join(act[:5]), 12, 660, (150, 150, 160))
        txt("  ".join(act[5:10]), 12, 678, (150, 150, 160))
        # player sim box
        fb2d.rect(screen, (50, 30, 30), (560, 560, 200, 70))
        flash = int(120 + 120 * state["fire_flash"])
        fb2d.rect(screen, (flash, 60, 60), (560, 560, 200, 70), 3)
        txt("FIRE (SPACE)", 600, 580, (255, 200, 200), big)
        txt(f"autofire[A]:{'ON' if state['autofire'] else 'off'}  "
            f"quantize[Q]:{'ON' if state['quantize'] else 'off'}  "
            f"tension[T]:{'ON' if state['tension'] else 'off'}",
            560, 636)
        # beat strip
        strip = Rect(12, 700, W - 24, 10)
        fb2d.rect(screen, (30, 30, 36), strip)
        pos = (t_s % ms.bar_s) / ms.bar_s
        for k in range(8):
            x = strip.x + int(strip.w * k / 8)
            fb2d.line(screen, (70, 70, 90), (x, strip.y),
                      (x, strip.y + strip.h))
        px = strip.x + int(strip.w * pos)
        fb2d.rect(screen, (240, 220, 160), (px - 2, strip.y, 4,
                                            strip.h))
        disp.flip()
        clock.tick(FPS)

    ms.stop()


if __name__ == "__main__":
    main()
