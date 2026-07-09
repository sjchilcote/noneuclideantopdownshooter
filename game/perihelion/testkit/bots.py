"""Deterministic bot policies driving `GameSession` via `InputFrame`.

Every bot owns its own `Random(seed)` — never `session.rng` — so swapping
bots or reseeding one bot never perturbs another bot's decisions or the
sim's own RNG stream. Bots read `session` (cam, sim queries, exit info) but
must never mutate it; `session.sim.next_edge` / `hop_distance` do lazily
cache routing internally, which is a read-shaped query, not game-state
mutation.

Coordinate conversions follow `sim.py`'s own convention exactly:
  screen -> room delta:  `mat_apply_dir(mat_inv(cam), sx, sy)`   (used by sim for moves)
  room -> screen delta:  `mat_apply_dir(cam, rx, ry)`            (the inverse operation; bots use this)
  room point -> screen point: `mat_apply(cam, rx, ry)`           (used by bots for aim targets)
"""

from __future__ import annotations

import math
from collections import deque
from random import Random

import necore

from ..sim import GameSession, InputFrame, WEAPON_ORDER

AIM_ERR_FIRE = math.radians(8.0)
STRAFE_RANGE_MIN = 60.0
STRAFE_RANGE_MAX = 140.0
UNSTICK_WINDOW = 30
UNSTICK_TICKS = 20
UNSTICK_DIST = 4.0


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _norm(vec) -> tuple[float, float]:
    l = math.hypot(vec[0], vec[1])
    if l < 1e-9:
        return (0.0, 0.0)
    return (vec[0] / l, vec[1] / l)


def _weapon_field(name: str) -> int:
    return WEAPON_ORDER.index(name) + 1


def choose_weapon(snapshot: dict, dist: float, n_enemies: int) -> int:
    """Sensible weapon pick for a fight at `dist` against `n_enemies` in-room
    enemies: knife when truly out of ammo and close, shotgun up close,
    smg/pistol otherwise, falling back to whatever still has ammo."""
    weapons = snapshot["weapons"]
    ammo = snapshot["ammo"]

    def has(t: str) -> bool:
        return ammo.get(t, 0) > 0

    out_of_ammo = not (has("9mm") or has("shell") or has("cell"))
    if out_of_ammo and dist < 40.0 and "knife" in weapons:
        return _weapon_field("knife")
    if dist < 70.0 and "shotgun" in weapons and has("shell"):
        return _weapon_field("shotgun")
    if "smg" in weapons and has("9mm"):
        return _weapon_field("smg")
    if "pistol" in weapons and has("9mm"):
        return _weapon_field("pistol")
    if "rail" in weapons and has("cell"):
        return _weapon_field("rail")
    if "shotgun" in weapons and has("shell"):
        return _weapon_field("shotgun")
    if "knife" in weapons:
        return _weapon_field("knife")
    return 0


def nav_to_point(session: GameSession, px: float, py: float,
                  target: tuple[float, float]) -> tuple[float, float]:
    """Room-local direction toward `target`, expressed as a normalized
    screen-space move vector (what `InputFrame.mx/my` expects)."""
    dx, dy = target[0] - px, target[1] - py
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return (0.0, 0.0)
    ndx, ndy = dx / d, dy / d
    sx, sy = necore.mat_apply_dir(session.cam, ndx, ndy)
    return _norm((sx, sy))


def nav_to_room(session: GameSession, snapshot: dict, target_room: int,
                 target_point: tuple[float, float] | None = None) -> tuple[float, float]:
    """Screen-space move vector toward `target_room` (or `target_point`
    within it, once arrived), via the router's next portal edge."""
    proom = snapshot["room"]
    px, py = snapshot["pos"]
    if target_room == proom:
        if target_point is not None:
            return nav_to_point(session, px, py, target_point)
        return (0.0, 0.0)
    edge = session.sim.next_edge(proom, target_room)
    if edge < 0:
        return (0.0, 0.0)
    tx, ty = session.sim.edge_midpoint(proom, edge)
    return nav_to_point(session, px, py, (tx, ty))


def nav_to_exit(session: GameSession, snapshot: dict) -> tuple[float, float]:
    proom = snapshot["room"]
    px, py = snapshot["pos"]
    exit_room = session.exit_room
    if exit_room < 0:
        return (0.0, 0.0)
    if proom == exit_room:
        return nav_to_point(session, px, py, session.exit_pos)
    edge = snapshot.get("exit_next_edge", -1)
    if edge < 0:
        return (0.0, 0.0)
    tx, ty = session.sim.edge_midpoint(proom, edge)
    return nav_to_point(session, px, py, (tx, ty))


class Bot:
    """Base policy. Subclasses implement `step`; they may read `session`
    freely (cam, sim queries, exit_room/exit_pos, screen_w/h) but must never
    write to it — that's the harness's and sim's job."""

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.rng = Random(seed)

    def step(self, snapshot: dict, session: GameSession) -> InputFrame:
        raise NotImplementedError


class _UnstickMixin:
    """Shared wall-unstick jitter: if net displacement over the last
    UNSTICK_WINDOW ticks is under UNSTICK_DIST units, push a random screen
    direction for UNSTICK_TICKS ticks, overriding whatever movement the
    policy chose."""

    def _init_unstick(self) -> None:
        self._pos_hist: deque = deque(maxlen=UNSTICK_WINDOW)
        self._unstick_ticks = 0
        self._unstick_dir = (0.0, 0.0)

    def _apply_unstick(self, px: float, py: float, inp: InputFrame) -> InputFrame:
        self._pos_hist.append((px, py))
        if self._unstick_ticks <= 0 and len(self._pos_hist) == UNSTICK_WINDOW:
            ox, oy = self._pos_hist[0]
            if math.hypot(px - ox, py - oy) < UNSTICK_DIST:
                ang = self.rng.uniform(0.0, 2.0 * math.pi)
                self._unstick_dir = (math.cos(ang), math.sin(ang))
                self._unstick_ticks = UNSTICK_TICKS
        if self._unstick_ticks > 0:
            self._unstick_ticks -= 1
            inp.mx, inp.my = self._unstick_dir
        return inp


class _CombatMixin:
    """Shared aim/fire/weapon-select logic for bots that fight like Aggro:
    jittered aim (fire only once the jitter is under ~8 degrees, mimicking
    imperfect human tracking), range-appropriate movement, and sensible
    weapon switching."""

    def _init_combat(self) -> None:
        self._aim_jitter = 0.0
        self._strafe_sign = 1

    def _combat_input(self, session: GameSession, snapshot: dict,
                       enemies_in_room: list[dict], mobile: bool) -> InputFrame:
        px, py = snapshot["pos"]
        nearest = min(enemies_in_room, key=lambda e: _dist(e["pos"], (px, py)))
        ex, ey = nearest["pos"]
        dx, dy = ex - px, ey - py
        dist = math.hypot(dx, dy) or 1e-6
        true_angle = math.atan2(dy, dx)

        self._aim_jitter += self.rng.uniform(-0.05, 0.05)
        self._aim_jitter = max(-0.22, min(0.22, self._aim_jitter))
        aim_angle = true_angle + self._aim_jitter
        adx, ady = math.cos(aim_angle), math.sin(aim_angle)
        tx, ty = px + adx * dist, py + ady * dist

        inp = InputFrame()
        inp.ax, inp.ay = necore.mat_apply(session.cam, tx, ty)
        # fire discipline scales with range: only shoot when the current
        # error would actually land on the target's silhouette
        target_r = session.sim.get_radius(nearest["id"]) \
            if session.sim.exists(nearest["id"]) else 8.0
        allowed = max(math.radians(3.0), math.atan2(target_r * 0.9, dist))
        inp.fire = abs(self._aim_jitter) < max(allowed, AIM_ERR_FIRE * 0.4)
        inp.weapon = choose_weapon(snapshot, dist, len(enemies_in_room))
        inp.alt = (len(enemies_in_room) >= 3 and snapshot["lightning_ready"]
                   and "lightning" in snapshot["weapons"])

        if mobile:
            weapon_name = WEAPON_ORDER[inp.weapon - 1] if inp.weapon else snapshot["weapon"]
            ux, uy = dx / dist, dy / dist
            perp = (-uy, ux)
            if weapon_name == "knife":
                move_room = (ux, uy)
            elif dist < STRAFE_RANGE_MIN:
                move_room = (-ux, -uy)
            elif dist > STRAFE_RANGE_MAX:
                move_room = (ux, uy)
            else:
                j = self.rng.uniform(-0.3, 0.3)
                move_room = (perp[0] * self._strafe_sign + j * ux,
                             perp[1] * self._strafe_sign + j * uy)
                if self.rng.random() < 0.02:
                    self._strafe_sign *= -1
            mvx, mvy = _norm(move_room)
            sx, sy = necore.mat_apply_dir(session.cam, mvx, mvy)
            inp.mx, inp.my = _norm((sx, sy))
        return inp


class AggroBot(_CombatMixin, _UnstickMixin, Bot):
    """Primary campaign-clearing bot: fights whatever's in the room, seeks
    medkits when hurt and safe, otherwise beelines for the exit (detouring
    for ammo when critically low)."""

    def __init__(self, seed: int = 0):
        super().__init__(seed)
        self._init_combat()
        self._init_unstick()

    def step(self, snapshot: dict, session: GameSession) -> InputFrame:
        proom = snapshot["room"]
        px, py = snapshot["pos"]
        enemies_in_room = [e for e in snapshot["enemies"] if e["room"] == proom]

        if enemies_in_room:
            inp = self._combat_input(session, snapshot, enemies_in_room, mobile=True)
        else:
            inp = InputFrame()
            medkits = [p for p in snapshot["pickups"]
                       if p["room"] == proom and p["kind"] == "medkit"]
            if snapshot["hp"] < 40 and medkits:
                target = min(medkits, key=lambda p: _dist(p["pos"], (px, py)))
                inp.mx, inp.my = nav_to_point(session, px, py, target["pos"])
            else:
                inp.mx, inp.my = self._navigate(session, snapshot)
            inp.ax, inp.ay = session.screen_w / 2.0, session.screen_h / 2.0

        return self._apply_unstick(px, py, inp)

    def _navigate(self, session: GameSession, snapshot: dict) -> tuple[float, float]:
        proom = snapshot["room"]
        ammo = snapshot["ammo"]
        # keys first: a locked exit or door outranks everything but survival
        needed = set(snapshot.get("door_keys_needed", []))
        if snapshot.get("exit_key_needed"):
            needed.add(snapshot["exit_key_needed"])
        if needed:
            wanted = {f"key_{k}" for k in needed}
            keys = [p for p in snapshot["pickups"]
                    if p["kind"] in wanted and p["hops"] >= 0]
            if keys:
                target = min(keys, key=lambda p: p["hops"])
                target_point = target["pos"] if target["room"] == proom else None
                return nav_to_room(session, snapshot, target["room"], target_point)
        # gate enemies: hunt the kind holding the exit shut
        if snapshot.get("exit_gate_remaining", 0):
            kind = snapshot["exit_gate_kind"]
            prey = [e for e in snapshot["enemies"]
                    if e["kind"] == kind and e["hops"] >= 0]
            if prey:
                target = min(prey, key=lambda e: e["hops"])
                return nav_to_room(session, snapshot, target["room"], None)
        if sum(ammo.values()) <= 6:
            candidates = [p for p in snapshot["pickups"]
                          if p["kind"].startswith("ammo_") and p["hops"] >= 0]
            if candidates:
                target = min(candidates, key=lambda p: p["hops"])
                target_point = target["pos"] if target["room"] == proom else None
                return nav_to_room(session, snapshot, target["room"], target_point)
        return nav_to_exit(session, snapshot)


class PacifistBot(_UnstickMixin, Bot):
    """Never fires. Flees any enemy sharing its room, otherwise navigates
    toward the exit exactly like AggroBot's non-combat movement."""

    def __init__(self, seed: int = 0):
        super().__init__(seed)
        self._init_unstick()

    def step(self, snapshot: dict, session: GameSession) -> InputFrame:
        proom = snapshot["room"]
        px, py = snapshot["pos"]
        inp = InputFrame(fire=False, alt=False)
        enemies_in_room = [e for e in snapshot["enemies"] if e["room"] == proom]

        if enemies_in_room:
            nearest = min(enemies_in_room, key=lambda e: _dist(e["pos"], (px, py)))
            ex, ey = nearest["pos"]
            inp.mx, inp.my = nav_to_point(session, px, py, (2 * px - ex, 2 * py - ey))
            inp.ax, inp.ay = necore.mat_apply(session.cam, ex, ey)
        else:
            inp.mx, inp.my = nav_to_exit(session, snapshot)
            inp.ax, inp.ay = session.screen_w / 2.0, session.screen_h / 2.0

        return self._apply_unstick(px, py, inp)


class CamperBot(_CombatMixin, Bot):
    """Holds position. Never travels except a small side-to-side strafe
    while actively fighting; fires at whatever's in the room."""

    def __init__(self, seed: int = 0):
        super().__init__(seed)
        self._init_combat()
        self._strafe_phase = 0.0

    def step(self, snapshot: dict, session: GameSession) -> InputFrame:
        proom = snapshot["room"]
        px, py = snapshot["pos"]
        enemies_in_room = [e for e in snapshot["enemies"] if e["room"] == proom]

        if enemies_in_room:
            inp = self._combat_input(session, snapshot, enemies_in_room, mobile=False)
            nearest = min(enemies_in_room, key=lambda e: _dist(e["pos"], (px, py)))
            ex, ey = nearest["pos"]
            dist = _dist((ex, ey), (px, py)) or 1e-6
            perp = (-(ey - py) / dist, (ex - px) / dist)
            self._strafe_phase += 0.15
            s = math.sin(self._strafe_phase) * 0.6
            sx, sy = necore.mat_apply_dir(session.cam, perp[0] * s, perp[1] * s)
            ml = math.hypot(sx, sy)
            if ml > 0.6:
                sx, sy = sx / ml * 0.6, sy / ml * 0.6
            inp.mx, inp.my = sx, sy
        else:
            inp = InputFrame()
            inp.ax, inp.ay = session.screen_w / 2.0, session.screen_h / 2.0

        return inp


class ExplorerBot(_CombatMixin, _UnstickMixin, Bot):
    """Beelines for the nearest unvisited room (BFS/hop-distance over the
    room graph), tracking `snapshot['room']` over time. Fights like
    AggroBot when threatened; heads for the exit once every reachable room
    has been seen."""

    def __init__(self, seed: int = 0):
        super().__init__(seed)
        self._init_combat()
        self._init_unstick()
        self.visited: set[int] = set()

    def step(self, snapshot: dict, session: GameSession) -> InputFrame:
        proom = snapshot["room"]
        px, py = snapshot["pos"]
        self.visited.add(proom)
        enemies_in_room = [e for e in snapshot["enemies"] if e["room"] == proom]

        if enemies_in_room:
            inp = self._combat_input(session, snapshot, enemies_in_room, mobile=True)
        else:
            inp = InputFrame()
            target_room = self._pick_unvisited(session, proom)
            if target_room is not None:
                inp.mx, inp.my = nav_to_room(session, snapshot, target_room)
            else:
                inp.mx, inp.my = nav_to_exit(session, snapshot)
            inp.ax, inp.ay = session.screen_w / 2.0, session.screen_h / 2.0

        return self._apply_unstick(px, py, inp)

    def _pick_unvisited(self, session: GameSession, proom: int) -> int | None:
        best_room, best_hops = None, None
        for r in range(session.sim.num_rooms()):
            if r in self.visited:
                continue
            hops = session.sim.hop_distance(proom, r)
            if hops < 0:
                continue
            if best_hops is None or hops < best_hops:
                best_hops, best_room = hops, r
        return best_room
