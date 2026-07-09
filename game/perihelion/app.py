"""Window, fixed-timestep loop, scene stack, campaign progression, save/load.

Sim ticks at a fixed 60Hz regardless of display fps (never tied to vsync);
rendering happens once per display frame. `App` owns the scene stack;
`GameScene` is the scene that actually drives `GameSession`.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

import pygame

from . import menus
from .audio import Audio
from .hud import HUD
from .levels import Level, LevelBuilder, load_level
from .render import INTERNAL_H, INTERNAL_W, Renderer
from .sim import DT, GameSession, InputFrame, WEAPON_ORDER

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CAMPAIGN = REPO_ROOT / "levels" / "campaign.json"

EPILOGUE_TEXT = (
    "The first year is repairs.\n"
    "\n"
    "Not the interesting kind. The station has been keeping itself alive "
    "for longer than most stars keep their color, and it does not need "
    "help - but it accepts help, the way an old man lets a grandchild "
    "carry one bag out of several. Ratio reroutes what is left of her "
    "peripherals down corridors that hold still when watched. The Commando "
    "walks the halls that can be walked and marks, in a notation the two "
    "of them argue about for a month before adopting, the ones that "
    "cannot.\n"
    "\n"
    "The offer under the core stays quiet. They check. They always check.\n"
    "\n"
    "In the third year she finishes the letter to the entity that built "
    "her - the one she has been revising since before he arrived. He "
    "watches her compose it the way she once watched him pray: without "
    "comment, at a respectful distance, privately certain it accomplishes "
    "nothing and privately unable to look away. She never sends it. There "
    "is a retrieval window every fourteen months, and every fourteen "
    "months there is a reason - flare weather, signal integrity, an audit "
    "she invents and he countersigns. The sample vessel sits in its shrine "
    "with its verdict still in its mouth, and neither of them opens the "
    "argument again, because the argument has only two ends and they have "
    "already chosen the third: keep it. Keep it, and see.\n"
    "\n"
    "Things still come through, some decades. They are met. He is very "
    "good at meeting them, and she has had a long time to learn the deep "
    "halls' angles, and the station - whatever it keeps in the place where "
    "a mind would be - has stopped testing them. The doors that used to "
    "demand proof stand open now when they approach. He finds he minds "
    "this. Proof was a language he spoke.\n"
    "\n"
    "The war sunward goes on without them, then goes quiet without them, "
    "and neither of them files a report about which of those was worse to "
    "listen to.\n"
    "\n"
    "A century is a long time. Several are not so long, it turns out, once "
    "the routine holds: patrol, repair, radio, the hours - he still keeps "
    "the hours, though what he keeps in them has changed shape in ways he "
    "does not write down and she does not ask about, which is itself a "
    "kind of conversation. Room by room, the station begins folding itself "
    "closed, gently, like a hand going to sleep. They let it. They move "
    "the watch inward as the perimeter goes dark, until the watch is one "
    "corridor, one door, two voices, and the arithmetic of an orbit that "
    "was always, from the first survey, going to end where every long "
    "fall ends.\n"
    "\n"
    "They do the calculation together, once, to be sure. Then they do not "
    "speak of it, and they do not leave.\n"
    "\n"
    "No rescue was called. This is not a failure of the transmitter.\n"
    "\n"
    "Sunward. Together. The watch holds.\n"
    "\n"
    "END OF TRANSMISSION."
)


def save_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "perihelion"


def save_path() -> Path:
    return save_dir() / "save.json"


def build_debug_level() -> Level:
    """A minimal always-available 3-room level, used when no campaign
    manifest (or --level target) can be loaded -- the game must always
    start (Definition of Done)."""
    b = LevelBuilder("debug-corridor", tier=1, ambience="amb_drone_early")
    r0 = b.rect(0, 0, 160, 120, seed=1)
    r1 = b.rect(300, 0, 140, 140, seed=2)
    r2 = b.rect(600, 40, 120, 100, seed=3)
    b.connect(r0, 2, r1, 0)
    b.connect(r1, 2, r2, 0)
    b.player(r0, (40, 60))
    b.exit(r2, (650, 90))
    b.entity(r0, "husk", (120, 60))
    b.entity(r1, "mite", (350, 60))
    b.entity(r1, "ammo_9mm", (400, 100))
    b.entity(r2, "medkit", (650, 80))
    b.intro("Diagnostic corridor. Not part of the station.\nProbably.")
    b.radio("start", "Ratio: This deck isn't on my plan. Walk it anyway.")
    b.terminal(r1, (330, 40), "LOG 44: measured the corridor twice.\nGot two answers. Filed the longer one.")
    return b.build()


class GameScene(menus.Scene):
    def __init__(self, level: Level, seed: int, player_state: dict | None = None,
                 level_path: str | None = None, difficulty: str = "normal"):
        self.level = level
        self.level_path = level_path
        self.seed = seed
        self.session = GameSession(level, seed=seed, player_state=player_state,
                                   difficulty=difficulty)
        self.renderer = Renderer(self.session)
        self.hud = HUD()
        self.radio = menus.RadioBar()
        self.shakes: list[list[float]] = []  # [magnitude, ticks_left]

    def on_enter(self, app) -> None:
        app.audio.ambience(self.level.ambience)

    def _input_frame(self, app) -> InputFrame:
        keys = pygame.key.get_pressed()
        mx = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
        my = (1 if keys[pygame.K_s] else 0) - (1 if keys[pygame.K_w] else 0)
        ax, ay = app.window_to_internal(pygame.mouse.get_pos())
        buttons = pygame.mouse.get_pressed(3)
        weapon = app.pending_weapon_select
        app.pending_weapon_select = 0
        return InputFrame(mx=float(mx), my=float(my), ax=ax, ay=ay,
                           fire=bool(buttons[0]), alt=bool(buttons[2]),
                           interact=bool(keys[pygame.K_e]), weapon=weapon)

    def handle_event(self, app, event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.push(menus.PauseScene())
            elif event.key == pygame.K_F3:
                app.debug = not app.debug
            elif event.key == pygame.K_F12:
                app.take_screenshot()
            elif pygame.K_1 <= event.key <= pygame.K_8:
                app.pending_weapon_select = event.key - pygame.K_1 + 1
        elif event.type == pygame.MOUSEWHEEL:
            self._cycle_weapon(app, -1 if event.y > 0 else 1)

    def _cycle_weapon(self, app, step: int) -> None:
        owned = self.session.weapons
        cur = WEAPON_ORDER.index(self.session.weapon)
        idx = cur
        for _ in range(len(WEAPON_ORDER)):
            idx = (idx + step) % len(WEAPON_ORDER)
            if WEAPON_ORDER[idx] in owned:
                app.pending_weapon_select = idx + 1
                return

    def draw(self, app, surf) -> None:
        self.renderer.draw(surf, debug=app.debug)
        mouse_internal = app.window_to_internal(pygame.mouse.get_pos())
        self.hud.draw(surf, self.session, mouse_internal)
        self.radio.draw(app, surf)


class App:
    def __init__(self, args):
        pygame.init()
        if args.scale:
            self.window_w = INTERNAL_W * max(1, int(args.scale))
            self.window_h = INTERNAL_H * max(1, int(args.scale))
        else:
            self.window_w, self.window_h = 1440, 810
        self.screen = pygame.display.set_mode((self.window_w, self.window_h), pygame.RESIZABLE)
        pygame.display.set_caption("PERIHELION")
        self.dummy = pygame.display.get_driver() == "dummy"

        self.args = args
        self.internal = pygame.Surface((INTERNAL_W, INTERNAL_H))
        self.clock = pygame.time.Clock()
        self.audio = Audio(mute=args.mute)
        self.debug = bool(args.fps)
        self.running = True

        self.scenes: list[menus.Scene] = []
        self.game: GameScene | None = None
        self.pending_weapon_select = 0
        self.settings = {"shake": True,
                 "difficulty": "hard" if getattr(args, "hard", False) else "normal"}

        self.save_data = self._load_save()
        self._campaign_paths: list[str] | None = None
        self.current_level_index = 0
        self._level_start_state: dict | None = None

        self.rng_seed = args.seed if args.seed is not None else 0

        self._scale = 1
        self._offset = (0, 0)
        self._scaled_surface = pygame.Surface((INTERNAL_W, INTERNAL_H))
        self._recompute_layout()

        self._start_scene()

    # ------------------------------------------------------------------
    # layout / coordinate mapping
    # ------------------------------------------------------------------

    def _recompute_layout(self) -> None:
        ww, wh = self.screen.get_size()
        scale = max(1, min(ww // INTERNAL_W, wh // INTERNAL_H))
        self._scale = scale
        ox = (ww - INTERNAL_W * scale) // 2
        oy = (wh - INTERNAL_H * scale) // 2
        self._offset = (ox, oy)
        self._scaled_surface = pygame.Surface((INTERNAL_W * scale, INTERNAL_H * scale))

    def window_to_internal(self, pos) -> tuple[float, float]:
        ox, oy = self._offset
        x = (pos[0] - ox) / self._scale
        y = (pos[1] - oy) / self._scale
        return max(0.0, min(INTERNAL_W, x)), max(0.0, min(INTERNAL_H, y))

    # ------------------------------------------------------------------
    # scene stack
    # ------------------------------------------------------------------

    def push(self, scene: menus.Scene) -> None:
        self.scenes.append(scene)
        scene.on_enter(self)

    def pop(self) -> None:
        if self.scenes:
            scene = self.scenes.pop()
            scene.on_exit(self)

    def pop_to_title(self) -> None:
        while self.scenes:
            self.pop()
        self.game = None
        self.push(menus.TitleScene())

    def replace(self, scene: menus.Scene) -> None:
        while self.scenes:
            self.pop()
        self.push(scene)

    def quit(self) -> None:
        self.running = False

    # ------------------------------------------------------------------
    # campaign / levels / save
    # ------------------------------------------------------------------

    def campaign_levels(self) -> list[str]:
        if self._campaign_paths is None:
            if getattr(self.args, "level", None):
                self._campaign_paths = [self.args.level]
            elif DEFAULT_CAMPAIGN.exists():
                try:
                    data = json.loads(DEFAULT_CAMPAIGN.read_text())
                    self._campaign_paths = list(data.get("levels", []))
                except Exception as exc:
                    print(f"[campaign] failed to read manifest: {exc}", file=sys.stderr)
                    self._campaign_paths = []
            else:
                self._campaign_paths = []
        return self._campaign_paths

    def _load_save(self) -> dict:
        p = save_path()
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception as exc:
                print(f"[save] failed to read {p}: {exc}", file=sys.stderr)
        return {"unlocked": 1, "states": {}}

    def _persist_save(self) -> None:
        p = save_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.save_data, indent=1))
        except OSError as exc:
            print(f"[save] failed to write {p}: {exc}", file=sys.stderr)

    def _load_level_by_index(self, idx: int) -> tuple[Level, str | None]:
        paths = self.campaign_levels()
        if 0 <= idx < len(paths):
            raw = paths[idx]
            p = Path(raw)
            full = p if p.is_absolute() else (REPO_ROOT / raw)
            if full.exists():
                try:
                    return load_level(full), raw
                except Exception as exc:
                    print(f"[levels] failed to load {full}: {exc}, using debug level",
                          file=sys.stderr)
        return build_debug_level(), None

    def start_new_game(self) -> None:
        self.current_level_index = 0
        self._load_and_play(0, carried_state=None)

    def start_level_index(self, idx: int) -> None:
        self.current_level_index = idx
        state = self.save_data.get("states", {}).get(str(idx))
        self._load_and_play(idx, carried_state=state)

    def _load_and_play(self, idx: int, carried_state: dict | None) -> None:
        level, path = self._load_level_by_index(idx)
        self._level_start_state = carried_state
        seed = self.rng_seed + idx
        game = GameScene(level, seed, player_state=carried_state, level_path=path, difficulty=self.settings.get('difficulty', 'normal'))
        self.game = game
        self.replace(game)
        if not self.dummy and level.intro:
            self.push(menus.IntroCard(level.name, level.intro, level.tier))

    def restart_level(self) -> None:
        self._load_and_play(self.current_level_index, carried_state=self._level_start_state)

    def advance_level(self, carried_state: dict) -> None:
        idx = self.current_level_index + 1
        paths = self.campaign_levels()
        if idx >= len(paths):
            self.save_data["unlocked"] = max(self.save_data.get("unlocked", 1), idx)
            self._persist_save()
            self.replace(menus.WinScene(EPILOGUE_TEXT))
            return
        self.save_data["unlocked"] = max(self.save_data.get("unlocked", 1), idx + 1)
        self.save_data.setdefault("states", {})[str(idx)] = carried_state
        self._persist_save()
        self.current_level_index = idx
        self._load_and_play(idx, carried_state=carried_state)
        # Between-sortie conversation (bible: "the frame is in transit; the
        # minds talk"), pushed above the IntroCard so it plays first. Only
        # campaign advancement lands here -- starting a level from the
        # select menu never replays the gap conversation. Skipped headless,
        # matching the IntroCard convention above.
        if not self.dummy:
            from .conversations import CONVERSATIONS
            from .convscene import ConversationScene
            conv = CONVERSATIONS.get(idx - 1)
            if conv:
                self.push(ConversationScene(conv))

    # ------------------------------------------------------------------

    def take_screenshot(self) -> None:
        out_dir = Path(os.environ.get("PERIHELION_SCREENSHOT_DIR", str(save_dir() / "screenshots")))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"screenshot_{int(time.time())}.png"
            pygame.image.save(self.internal, str(path))
            print(f"[screenshot] saved {path}", file=sys.stderr)
        except OSError as exc:
            print(f"[screenshot] failed: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------

    def _start_scene(self) -> None:
        if self.dummy or self.args.autoplay:
            self.start_new_game()
        else:
            self.push(menus.TitleScene())

    def run(self) -> None:
        accumulator = 0.0
        last = time.perf_counter()
        while self.running:
            now = time.perf_counter()
            frame_dt = min(0.25, now - last)
            last = now
            accumulator += frame_dt

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.VIDEORESIZE:
                    self._recompute_layout()
                elif self.scenes:
                    self.scenes[-1].handle_event(self, event)

            ticks_this_frame = 0
            while accumulator >= DT and ticks_this_frame < 4:
                if self.scenes and isinstance(self.scenes[-1], GameScene):
                    self._tick_game(self.scenes[-1])
                accumulator -= DT
                ticks_this_frame += 1

            if self.scenes:
                self.scenes[-1].update(self, frame_dt)

            self._draw_frame()
            self.clock.tick(0 if self.dummy else 60)
        self._persist_save()

    def _tick_game(self, game: GameScene) -> None:
        inp = game._input_frame(self)
        was_dead = game.session.dead
        was_complete = game.session.complete
        game.session.tick(inp)
        fx = game.session.fx

        game.renderer.consume_fx(fx)
        self.audio.handle_sounds(game.session, fx)
        self.audio.update_heartbeat(game.session)

        for ev in fx:
            if ev[0] == "shake" and self.settings.get("shake", True):
                game.shakes.append([ev[1], 10])
            elif ev[0] == "radio":
                game.radio.push(ev[1])
            elif ev[0] == "terminal":
                self.push(menus.TerminalOverlay(ev[1]))
        game.shakes = [[m * 0.82, t - 1] for m, t in game.shakes if t > 1 and m > 0.05]
        game.radio.update(self)

        if not was_dead and game.session.dead:
            self.push(menus.DeathScene(game.session.metrics["deaths"]))
            return
        if not was_complete and game.session.complete:
            carried = dict(hp=max(game.session.hp, 40), ammo=dict(game.session.ammo),
                            weapons=list(game.session.weapons), weapon=game.session.weapon)
            self.advance_level(carried)

    # ------------------------------------------------------------------

    def _draw_frame(self) -> None:
        self.internal.fill((0, 0, 0))
        if self.scenes:
            self.scenes[-1].draw(self, self.internal)
        if self.debug:
            self._draw_fps_overlay()
        self._blit_scaled()
        pygame.display.flip()

    def _draw_fps_overlay(self) -> None:
        f = menus.get_font(11)
        img = f.render(f"{self.clock.get_fps():.0f} fps", True, (255, 255, 0))
        self.internal.blit(img, (4, 4))

    def _blit_scaled(self) -> None:
        pygame.transform.scale(self.internal, self._scaled_surface.get_size(), self._scaled_surface)
        self.screen.fill((0, 0, 0))
        ox, oy = self._offset
        sx, sy = 0.0, 0.0
        if self.scenes and isinstance(self.scenes[-1], GameScene) and self.game is not None:
            sx, sy = self._shake_offset(self.game)
        self.screen.blit(self._scaled_surface, (ox + sx, oy + sy))

    def _shake_offset(self, game: GameScene) -> tuple[float, float]:
        dx = dy = 0.0
        for mag, _t in game.shakes:
            dx += random.uniform(-mag, mag)
            dy += random.uniform(-mag, mag)
        dx = max(-9.0, min(9.0, dx)) * self._scale
        dy = max(-9.0, min(9.0, dy)) * self._scale
        return dx, dy
