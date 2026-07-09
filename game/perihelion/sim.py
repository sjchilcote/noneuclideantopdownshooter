"""GameSession: the deterministic core of PERIHELION.

Pure python + necore. No pygame, no wall-clock, no I/O. Same level + seed +
input sequence => bit-identical run. The renderer and audio system consume
`session.fx` (per-tick effect intents) and `session.decals`; tests and bots
consume `snapshot()` and `metrics`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from random import Random

import necore

from .levels import Level

DT = 1.0 / 60.0
TICK_RATE = 60

GROUP_PLAYER = 0
GROUP_ENEMY = 1
GROUP_PBULLET = 2
GROUP_EBULLET = 3
GROUP_PICKUP = 4

ACTIVE_HOPS = 5

PLAYER_HP = 100
PLAYER_RADIUS = 6.5
PLAYER_ACCEL = 820.0
PLAYER_FRICTION = 5.6  # terminal speed ~133 u/s (discrete 60Hz tick)
PLAYER_MASS = 1.2

# name: (damage, cooldown_ticks, speed, spread_rad, pellets, ammo_type, ammo_per_shot, sound)
WEAPONS: dict[str, dict] = {
    "knife": dict(dmg=9, cd=22, ammo=None, sound="knife_swing", range=27.0, arc=math.radians(55)),
    "pistol": dict(dmg=12, cd=20, speed=1500.0, spread=math.radians(1.6), pellets=1,
                   ammo="9mm", per=1, sound="pistol_fire", kick=2.2),
    "smg": dict(dmg=7, cd=6, speed=1350.0, spread=math.radians(5.5), pellets=1,
                ammo="9mm", per=1, sound="smg_fire", kick=1.6),
    "shotgun": dict(dmg=6, cd=54, speed=1150.0, spread=math.radians(11.0), pellets=8,
                    ammo="shell", per=1, sound="shotgun_fire", kick=7.0),
    "rail": dict(dmg=42, cd=84, ammo="cell", per=1, sound="rail_fire", pierce=3, kick=5.0),
    "lightning": dict(dmg=26, cd=None, speed=720.0, sound="lightning_fire",
                      radius=110.0, force=1500.0),
    "tau": dict(dmg=9, cd=7, speed=1900.0, spread=math.radians(2.0), pellets=1,
                ammo="cell", per=1, sound="tau_fire", kick=2.6, bounces=2),
    "hole": dict(cd=18, sound="terminal_open"),
}
WEAPON_ORDER = ["knife", "pistol", "smg", "shotgun", "rail", "lightning",
                "tau", "hole"]
TAU_CHARGE_FULL = 80        # ticks of held charge for max damage
TAU_OVERCHARGE = 160        # holding past this hurts
HOLE_WIDTH = 15.0           # player diameter 13 + clearance; brutes (27) excluded
HOLE_RANGE = 160.0
HOLE_CORRIDOR_LEN = 36.0
LIGHTNING_RECHARGE_TICKS = 60 * 9

# Speed doctrine (Teleglitch): base walk slightly SLOWER than the player
# (discrete-tick terminal; player ~133 u/s) so spacing is a real skill; the
# husk/brute lunge is the burst that punishes carelessness. Mites nearly
# match player speed and win by numbers.
ENEMIES: dict[str, dict] = {
    "husk": dict(hp=15, radius=8.0, mass=1.0, accel=430.0, fric=3.2, touch_dmg=12,
                 touch_cd=38, alert_snd="enemy_alert_husk", die_snd="enemy_die_husk",
                 score=1),
    "mite": dict(hp=4, radius=4.0, mass=0.35, accel=690.0, fric=4.5, touch_dmg=4,
                 touch_cd=24, alert_snd="enemy_alert_mite", die_snd="enemy_die_mite",
                 score=1),
    "spitter": dict(hp=18, radius=9.0, mass=1.4, accel=340.0, fric=3.8, touch_dmg=8,
                    touch_cd=45, alert_snd="enemy_alert_husk", die_snd="enemy_die_husk",
                    spit_cd=95, spit_speed=380.0, spit_dmg=9, keep_min=110.0,
                    keep_max=190.0, score=2),
    "brute": dict(hp=65, radius=13.5, mass=7.0, accel=260.0, fric=2.6, touch_dmg=24,
                  touch_cd=55, alert_snd="enemy_alert_husk", die_snd="enemy_die_brute",
                  score=4),
    "shrieker": dict(hp=10, radius=7.0, mass=0.8, accel=520.0, fric=3.4, touch_dmg=0,
                     touch_cd=60, alert_snd="shrieker_scream", die_snd="enemy_die_mite",
                     scream_cd=60 * 5, score=3),
    "warden": dict(hp=340, radius=16.0, mass=12.0, accel=330.0, fric=2.4, touch_dmg=30,
                   touch_cd=48, alert_snd="shrieker_scream", die_snd="enemy_die_brute",
                   spit_cd=70, spit_speed=460.0, spit_dmg=13, keep_min=0.0,
                   keep_max=100.0, score=25),
}

PICKUPS: dict[str, dict] = {
    "ammo_9mm": dict(radius=5.0, amount=30),
    "ammo_shell": dict(radius=5.0, amount=7),
    "ammo_cell": dict(radius=5.0, amount=8),
    "medkit": dict(radius=6.0, amount=35),
    "weapon_smg": dict(radius=7.0),
    "weapon_shotgun": dict(radius=7.0),
    "weapon_rail": dict(radius=7.0),
    "weapon_tau": dict(radius=7.0),
    "portable_hole": dict(radius=6.0),
    "safe_room_core": dict(radius=7.0),
    "turret": dict(radius=6.0),
    "implant_lightning": dict(radius=7.0),
    "key_red": dict(radius=5.5), "key_blue": dict(radius=5.5),
    "key_gold": dict(radius=5.5), "key_void": dict(radius=5.5),
}

DROP_TABLES = {
    "husk": [(0.35, "ammo_9mm"), (0.08, "medkit")],
    "mite": [(0.04, "ammo_9mm")],
    "spitter": [(0.30, "ammo_shell"), (0.08, "medkit")],
    "brute": [(0.55, "ammo_cell"), (0.25, "medkit")],
    "shrieker": [(0.5, "ammo_9mm")],
    "warden": [],
}


@dataclass
class InputFrame:
    mx: float = 0.0  # screen-space move -1..1
    my: float = 0.0
    ax: float = 240.0  # aim, internal-screen pixels
    ay: float = 135.0
    fire: bool = False
    alt: bool = False
    interact: bool = False
    weapon: int = 0  # 0 = keep, 1..6 select WEAPON_ORDER[i-1]

    def pack(self) -> list:
        return [round(self.mx, 4), round(self.my, 4), round(self.ax, 2),
                round(self.ay, 2), int(self.fire), int(self.alt),
                int(self.interact), self.weapon]

    @staticmethod
    def unpack(row: list) -> "InputFrame":
        return InputFrame(row[0], row[1], row[2], row[3],
                          bool(row[4]), bool(row[5]), bool(row[6]), row[7])


class GameSession:
    def __init__(self, level: Level, seed: int = 0,
                 screen: tuple[int, int] = (480, 270), zoom: float = 1.35,
                 player_state: dict | None = None, difficulty: str = "normal"):
        self.level = level
        self.difficulty = difficulty
        self._hp_mul = 1.35 if difficulty == "hard" else 1.0
        self._dmg_mul = 1.25 if difficulty == "hard" else 1.0
        self.rng = Random(seed)
        self.seed = seed
        self.screen_w, self.screen_h = screen
        self.zoom = zoom
        self.tick_count = 0
        self.dead = False
        self.complete = False
        self.freeze = 0  # hitstop ticks

        # --- engine world ---
        s = necore.Sim()
        self.sim = s
        for verts in level.room_verts:
            s.add_room(verts)
        for a, ea, b, eb in level.connects:
            s.connect(a, ea, b, eb)
        for a, ea, b, eb, m9 in level.connects_x:
            s.connect_with_xform(a, ea, b, eb, m9)
        # collision matrix
        for g in range(5):
            for h in range(5):
                s.set_collision_pair(g, h, False)
        s.set_collision_pair(GROUP_PLAYER, GROUP_ENEMY, True)
        s.set_collision_pair(GROUP_ENEMY, GROUP_ENEMY, True)
        s.set_collision_pair(GROUP_PBULLET, GROUP_ENEMY, True)
        s.set_collision_pair(GROUP_EBULLET, GROUP_PLAYER, True)
        # your own rounds CAN come back: mirrors and ricochets are honest
        s.set_collision_pair(GROUP_PBULLET, GROUP_PLAYER, True)

        # --- doors (pending connections) ---
        self.doors: list[dict] = []
        self.door_edges: dict[tuple[int, int], str] = {}
        for d in level.doors:
            rec = dict(a=d.a, ea=d.ea, b=d.b, eb=d.eb, key=d.key, open=False)
            self.doors.append(rec)
            self.door_edges[(d.a, d.ea)] = d.key
            self.door_edges[(d.b, d.eb)] = d.key

        # --- player ---
        st = player_state or {}
        self.pid = s.spawn(level.player_room, *level.player_pos,
                           PLAYER_RADIUS, PLAYER_MASS, GROUP_PLAYER)
        s.set_props(self.pid, rest_wall=0.0, rest_ent=0.05, max_substep=6.0)
        self.hp = st.get("hp", PLAYER_HP)
        self.ammo = dict(st.get("ammo", {"9mm": 48, "shell": 0, "cell": 0}))
        self.weapons = list(st.get("weapons", ["knife", "pistol"]))
        self.keys: set[str] = set()
        self.weapon = st.get("weapon", "pistol")
        if self.weapon not in self.weapons:
            self.weapon = self.weapons[-1]
        self.lightning_charge = LIGHTNING_RECHARGE_TICKS  # full
        self.cooldown = 0
        self.hurt_cd = 0
        self.aim = (1.0, 0.0)
        self.holes = int(st.get("holes", 0))
        self.hole_mark: tuple | None = None  # (room, edge, t0, t1, x, y)
        self.tau_charge = 0
        self.cloister: dict | None = None  # {sanctum, corridor, links, attached}
        self.turrets: dict[int, dict] = {}

        # --- camera: player-room local -> internal screen ---
        px, py = level.player_pos
        self.cam = necore.mat_mul(
            necore.mat_mul(necore.mat_translate(self.screen_w / 2, self.screen_h / 2),
                           necore.mat_scale(zoom, zoom)),
            necore.mat_translate(-px, -py))

        # --- scripted/world objects ---
        self.enemies: dict[int, dict] = {}
        self.bullets: dict[int, dict] = {}
        self.pickups: dict[int, dict] = {}
        self.terminals: list[dict] = [
            dict(room=t.room, pos=t.pos, text=t.text, read=False)
            for t in level.terminals
        ]
        for room, spec in level.entities:
            self._spawn_from_spec(room, spec)

        self.exit_room = level.exit_room
        self.exit_pos = level.exit_pos
        self.wave = 0
        self.wave_timer = 60 * 6 if level.vigil else -1
        if st.get("cloister"):
            self._build_cloister()

        # --- output channels ---
        self.fx: list[tuple] = []  # drained by app each tick
        self.decals: dict[int, list] = {}  # room -> [(kind,x,y,size,angle)]
        self.radio_queue: list[str] = []
        self._radio_fired: set[str] = set()
        self.metrics = dict(ticks=0, shots=0, hits=0, kills=0, dmg_dealt=0.0,
                            wave=0,
                            dmg_taken=0.0, pickups=0, transfers=0, deaths=0,
                            rooms_visited={level.player_room}, hp_series=[],
                            completed=False)
        self._maybe_radio("start")

    # ------------------------------------------------------------------
    # spawning
    # ------------------------------------------------------------------

    def _spawn_from_spec(self, room: int, spec) -> None:
        t = spec.type
        if t in ENEMIES:
            eid = self.spawn_enemy(room, spec.pos, t)
            if "hp" in spec.props:
                self.enemies[eid]["hp"] = float(spec.props["hp"]) * self._hp_mul
            if spec.props.get("tether"):
                self.enemies[eid]["tether"] = True
        elif t in PICKUPS:
            self.spawn_pickup(room, spec.pos, t)
        elif t == "player":
            pass  # player spawn handled by level.player
        else:
            raise ValueError(f"unknown entity type {t!r} in level")

    def spawn_enemy(self, room: int, pos, kind: str) -> int:
        d = ENEMIES[kind]
        eid = self.sim.spawn(room, pos[0], pos[1], d["radius"], d["mass"], GROUP_ENEMY)
        self.sim.set_props(eid, rest_wall=0.0, rest_ent=0.2, max_substep=8.0)
        self.enemies[eid] = dict(kind=kind, hp=d["hp"] * self._hp_mul, state="idle",
                                 touch_cd=0, spit_cd=0, scream_cd=0,
                                 wander_cd=0, buff=0)
        return eid

    def spawn_pickup(self, room: int, pos, kind: str) -> int:
        d = PICKUPS[kind]
        eid = self.sim.spawn(room, pos[0], pos[1], d["radius"], 100.0, GROUP_PICKUP)
        self.sim.set_props(eid, transfers=False)
        self.pickups[eid] = dict(kind=kind)
        return eid

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _snd(self, name: str, room: int, pos, vol: float = 1.0):
        self.fx.append(("sound", name, room, pos[0], pos[1], vol))

    def _shake(self, mag: float):
        self.fx.append(("shake", mag))

    def _hitstop(self, ticks: int):
        self.freeze = max(self.freeze, ticks)

    def _decal(self, room: int, kind: str, x: float, y: float,
               size: float, angle: float = 0.0):
        lst = self.decals.setdefault(room, [])
        lst.append((kind, x, y, size, angle))
        if len(lst) > 250:
            del lst[0: len(lst) - 250]

    def _maybe_radio(self, trigger: str):
        for line in self.level.radio:
            if line.trigger == trigger and trigger + "|" + line.text not in self._radio_fired:
                self._radio_fired.add(trigger + "|" + line.text)
                self.radio_queue.append(line.text)
                self.fx.append(("radio", line.text))

    def player_pos(self):
        _, px, py, *_ = self.sim.get(self.pid)
        return px, py

    def player_room(self) -> int:
        return self.sim.get_room(self.pid)

    WAKE_TICKS = {"husk": 32, "mite": 18, "spitter": 26, "brute": 45,
                  "shrieker": 12, "warden": 20}

    def alert_enemies(self, room: int, hops: int):
        for eid, e in self.enemies.items():
            if e["state"] != "idle":
                continue  # hunting already, or mid-wake (keep the beat)
            er = self.sim.get_room(eid)
            d = self.sim.hop_distance(er, room)
            if 0 <= d <= hops:
                e["state"] = "waking"
                e["wake"] = self.WAKE_TICKS[e["kind"]]
                if d == 0:
                    _, ex, ey, *_ = self.sim.get(eid)
                    self._snd(ENEMIES[e["kind"]]["alert_snd"], er, (ex, ey), 0.8)
                    self.fx.append(("alerted", er, ex, ey))

    # ------------------------------------------------------------------
    # the tick
    # ------------------------------------------------------------------

    def tick(self, inp: InputFrame) -> None:
        self.fx = []
        self.tick_count += 1
        self.metrics["ticks"] = self.tick_count
        if self.tick_count % 60 == 0:
            self.metrics["hp_series"].append(self.hp)
        if self.dead or self.complete:
            return
        if self.freeze > 0:
            self.freeze -= 1
            return

        s = self.sim
        proom = self.player_room()
        s.set_active_within(proom, ACTIVE_HOPS)

        self._player_control(inp, proom)
        self._enemy_ai(proom)

        # friction (artistic, so it lives here not in the engine)
        self._apply_friction(self.pid, PLAYER_FRICTION)
        for eid, e in self.enemies.items():
            self._apply_friction(eid, ENEMIES[e["kind"]]["fric"])

        events = s.step(DT)
        self._consume_events(events)
        self.sweep_bullets()

        self._turret_tick()
        self._pickup_scan(proom)
        self._terminal_scan(proom, inp)
        self._exit_scan(proom)

        if self.level.vigil:
            self._vigil_tick(proom)
        if self.cooldown > 0:
            self.cooldown -= 1
        if self.hurt_cd > 0:
            self.hurt_cd -= 1
        self.lightning_charge = min(LIGHTNING_RECHARGE_TICKS, self.lightning_charge + 1)

        # camera follow (after physics; transfers already re-based the matrix)
        px2, py2 = self.player_pos()
        spx, spy = necore.mat_apply(self.cam, px2, py2)
        k = min(1.0, 7.0 * DT)
        self.cam = necore.mat_mul(
            necore.mat_translate((self.screen_w / 2 - spx) * k,
                                 (self.screen_h / 2 - spy) * k),
            self.cam)

    # ------------------------------------------------------------------

    def _apply_friction(self, eid: int, fric: float):
        try:
            _, _, _, vx, vy, _, _ = self.sim.get(eid)
        except Exception:
            return
        f = max(0.0, 1.0 - fric * DT)
        self.sim.set_vel(eid, vx * f, vy * f)

    def _player_control(self, inp: InputFrame, proom: int):
        s = self.sim
        # weapon select
        if 1 <= inp.weapon <= len(WEAPON_ORDER):
            w = WEAPON_ORDER[inp.weapon - 1]
            if w in self.weapons:
                self.weapon = w
        # aim
        inv = necore.mat_inv(self.cam)
        awx, awy = necore.mat_apply(inv, inp.ax, inp.ay)
        _, px, py, vx, vy, _, _ = s.get(self.pid)
        dx, dy = awx - px, awy - py
        dl = math.hypot(dx, dy)
        if dl > 1e-6:
            s.set_dir(self.pid, dx / dl, dy / dl)
            self.aim = (dx / dl, dy / dl)
        else:
            self.aim = s.get(self.pid)[5:7]
        # move (screen-space -> room-space through inverse camera rotation)
        mlen = math.hypot(inp.mx, inp.my)
        if mlen > 1e-6:
            mlen = min(1.0, mlen)
            mdx, mdy = necore.mat_apply_dir(inv, inp.mx, inp.my)
            ml = math.hypot(mdx, mdy)
            if ml > 1e-9:
                ax_, ay_ = mdx / ml * mlen, mdy / ml * mlen
                s.set_vel(self.pid, vx + ax_ * PLAYER_ACCEL * DT,
                          vy + ay_ * PLAYER_ACCEL * DT)
        # fire
        if inp.fire and self.cooldown <= 0:
            self._fire(proom, px, py)
        # alt: tau charge when tau is in hand, lightning implant otherwise
        if self.weapon == "tau" and "tau" in self.weapons:
            if inp.alt and self.ammo.get("cell", 0) > 0:
                self.tau_charge += 1
                if self.tau_charge == 1:
                    self._snd("tau_charge", proom, (px, py), 0.8)
                if self.tau_charge > TAU_OVERCHARGE:
                    self._damage_player(12, proom)
                    self._snd("tau_overcharge_hurt", proom, (px, py))
                    self.tau_charge = 0
            elif self.tau_charge > 0:
                self._fire_tau_charged(proom, px, py)
                self.tau_charge = 0
        elif inp.alt and self.lightning_charge >= LIGHTNING_RECHARGE_TICKS \
                and "lightning" in self.weapons:
            self._fire_lightning(proom, px, py)

    def _fire(self, proom: int, px: float, py: float):
        w = WEAPONS[self.weapon]
        adx, ady = self.aim
        if self.weapon == "lightning":
            # the implant fires the same whether triggered or selected
            self.cooldown = 18
            if self.lightning_charge >= LIGHTNING_RECHARGE_TICKS:
                self._fire_lightning(proom, px, py)
            else:
                self._snd("dry_click", proom, (px, py))
            return
        if self.weapon == "hole":
            self.cooldown = w["cd"]
            self._hole_shot(proom, px, py, adx, ady)
            return
        if self.weapon == "knife":
            self.cooldown = w["cd"]
            self._snd("knife_swing", proom, (px, py))
            self.metrics["shots"] += 1
            hit_any = False
            for eid in list(self.sim.room_entities(proom)):
                e = self.enemies.get(eid)
                if not e:
                    continue
                _, ex, ey, *_ = self.sim.get(eid)
                ddx, ddy = ex - px, ey - py
                dist = math.hypot(ddx, ddy)
                reach = w["range"] + self.sim.get_radius(eid)
                if dist < 1e-6 or dist > reach:
                    continue
                ang = math.atan2(ddy, ddx) - math.atan2(ady, adx)
                ang = (ang + math.pi) % (2 * math.pi) - math.pi
                if abs(ang) <= w["arc"]:
                    self._damage_enemy(eid, w["dmg"], (ddx / dist, ddy / dist), 260.0)
                    hit_any = True
            if hit_any:
                self._snd("knife_hit", proom, (px, py))
                self._shake(1.5)
            return
        ammo_t = w.get("ammo")
        if ammo_t and self.ammo.get(ammo_t, 0) < w.get("per", 1):
            self.cooldown = 18
            self._snd("dry_click", proom, (px, py))
            return
        if ammo_t:
            self.ammo[ammo_t] -= w.get("per", 1)
        self.cooldown = w["cd"]
        self.metrics["shots"] += 1
        self._snd(w["sound"], proom, (px, py))
        self._shake(w.get("kick", 2.0))
        mx_, my_ = px + adx * (PLAYER_RADIUS + 5), py + ady * (PLAYER_RADIUS + 5)
        self.fx.append(("flash", proom, mx_, my_, 26.0))
        if self.weapon == "rail":
            self._fire_rail(proom, px, py, adx, ady)
        else:
            _, _, _, pvx, pvy, _, _ = self.sim.get(self.pid)
            for _ in range(w.get("pellets", 1)):
                ang = math.atan2(ady, adx) + self.rng.uniform(-w["spread"], w["spread"])
                spd = w["speed"] * self.rng.uniform(0.95, 1.05)
                bid = self.sim.spawn(proom, mx_, my_, 1.6, 0.002, GROUP_PBULLET)
                self.sim.set_props(bid, rest_wall=0.0, rest_ent=0.0, max_substep=3.2)
                self.sim.set_vel(bid, math.cos(ang) * spd + pvx * 0.4,
                                 math.sin(ang) * spd + pvy * 0.4)
                self.sim.set_dir(bid, math.cos(ang), math.sin(ang))
                self.bullets[bid] = dict(kind="bullet", dmg=w["dmg"], ttl=90)
                if self.weapon == "tau":
                    self.bullets[bid].update(kind="tau", ttl=140,
                                             bounces=w.get("bounces", 0))
                    self.sim.set_props(bid, rest_wall=1.0)
        # gunfire is loud: it travels the graph
        self.alert_enemies(proom, self.level.alert_hops)

    def _fire_rail(self, proom, px, py, adx, ady):
        ox, oy, room = px + adx * (PLAYER_RADIUS + 3), py + ady * (PLAYER_RADIUS + 3), proom
        dx, dy = adx, ady
        ignore = self.pid
        w = WEAPONS["rail"]
        for _ in range(w["pierce"]):
            hit = self.sim.raycast(room, ox, oy, dx, dy, 8, 2000.0,
                                   1 << GROUP_ENEMY, ignore)
            kind = hit[0]
            if kind == "ent":
                _, eid, hroom, hx, hy, dist, hops, m9 = hit
                self._damage_enemy(eid, w["dmg"], (dx, dy), 420.0)
                r = self.sim.get_radius(eid) if self.sim.exists(eid) else 8.0
                ox, oy, room, ignore = hx + dx * (2 * r + 1.0), hy + dy * (2 * r + 1.0), hroom, eid
            else:
                if kind == "wall":
                    _, hroom, hedge, hx, hy, dist, hops, m9 = hit
                    self._decal(hroom, "scorch", hx, hy, 4.0)
                break
        # visual tracer that flies the same path
        bid = self.sim.spawn(proom, px + adx * (PLAYER_RADIUS + 3),
                             py + ady * (PLAYER_RADIUS + 3), 1.2, 0.0005, GROUP_PBULLET)
        self.sim.set_props(bid, rest_wall=0.0, max_substep=4.0)
        self.sim.set_vel(bid, adx * 5200.0, ady * 5200.0)
        self.bullets[bid] = dict(kind="tracer", dmg=0, ttl=14)
        self._hitstop(2)

    def _fire_lightning(self, proom, px, py):
        self.lightning_charge = 0
        adx, ady = self.aim
        w = WEAPONS["lightning"]
        _, _, _, pvx, pvy, _, _ = self.sim.get(self.pid)
        bid = self.sim.spawn(proom, px + adx * (PLAYER_RADIUS + 6),
                             py + ady * (PLAYER_RADIUS + 6), 3.0, 0.02, GROUP_PBULLET)
        self.sim.set_props(bid, rest_wall=0.0, max_substep=4.0)
        self.sim.set_vel(bid, adx * w["speed"] + pvx * 0.5, ady * w["speed"] + pvy * 0.5)
        self.bullets[bid] = dict(kind="dart", dmg=w["dmg"], ttl=240)
        self._snd("lightning_fire", proom, (px, py))
        self._shake(4.0)
        self.alert_enemies(proom, self.level.alert_hops + 1)

    def _fire_tau_charged(self, proom, px, py):
        adx, ady = self.aim
        frac = min(1.0, self.tau_charge / TAU_CHARGE_FULL)
        cost = min(self.ammo.get("cell", 0), 5)
        if cost <= 0:
            self._snd("dry_click", proom, (px, py))
            return
        self.ammo["cell"] -= cost
        power = frac * (0.4 + 0.6 * cost / 5.0)
        dmg = 18 + 46 * power
        _, _, _, pvx, pvy, _, _ = self.sim.get(self.pid)
        bid = self.sim.spawn(proom, px + adx * (PLAYER_RADIUS + 5),
                             py + ady * (PLAYER_RADIUS + 5), 2.2, 0.006,
                             GROUP_PBULLET)
        self.sim.set_props(bid, rest_wall=1.0, max_substep=4.0)
        self.sim.set_vel(bid, adx * 2600.0 + pvx * 0.3, ady * 2600.0 + pvy * 0.3)
        self.bullets[bid] = dict(kind="taucharged", dmg=dmg, ttl=160, bounces=3)
        self.metrics["shots"] += 1
        self._snd("tau_charged_fire", proom, (px, py))
        self._shake(4.0 + 5.0 * power)
        self._hitstop(2)
        self.fx.append(("flash", proom, px + adx * 12, py + ady * 12, 30.0))
        self.alert_enemies(proom, self.level.alert_hops)

    # ------------------------------------------------------------------
    # portable hole
    # ------------------------------------------------------------------

    def _hole_shot(self, proom, px, py, adx, ady):
        if self.holes <= 0:
            self._snd("dry_click", proom, (px, py))
            return
        hit = self.sim.raycast(proom, px, py, adx, ady, 0, HOLE_RANGE, 0, self.pid)
        if hit[0] != "wall":
            self._snd("dry_click", proom, (px, py), 0.5)
            return
        _, room, edge, hx, hy, dist, hops, m9 = hit
        x1, y1, x2, y2 = self.sim.edge_endpoints(room, edge)
        elen = math.hypot(x2 - x1, y2 - y1)
        along = (hx - x1) * (x2 - x1) / elen + (hy - y1) * (y2 - y1) / elen
        half = HOLE_WIDTH / 2.0
        if along < half + 2.0 or along > elen - half - 2.0:
            self._snd("dry_click", proom, (px, py), 0.5)
            return
        t0, t1 = (along - half) / elen, (along + half) / elen
        if self.cloister is not None:
            if room in (self.cloister["sanctum"], self.cloister["corridor"]):
                self._snd("dry_click", proom, (px, py), 0.5)
                return
            mid = self.sim.split_edge(room, edge, t0, t1)
            self._shift_edge_maps(room, edge)
            self.cloister["links"].append((room, mid))
            self._attach_cloister(len(self.cloister["links"]) - 1)
            self.holes -= 1
            self._decal(room, "scorch", hx, hy, 8.0)
            self._snd("door_unlock", room, (hx, hy))
            self.fx.append(("holeopen", room, hx, hy))
            self._shake(2.5)
            return
        if self.hole_mark is None:
            self.hole_mark = (room, edge, t0, t1, hx, hy)
            self._decal(room, "scorch", hx, hy, 5.0)
            self._snd("terminal_type", room, (hx, hy))
            self.fx.append(("holemark", room, hx, hy))
            return
        m_room, m_edge, m_t0, m_t1, mx, my = self.hole_mark
        if m_room == room and m_edge == edge:
            self._snd("dry_click", proom, (px, py), 0.5)
            return
        # split the FIRST mark's wall first; if the second mark shares the
        # room with a later edge index, account for the insertion shift
        if m_room == room and edge > m_edge:
            edge += 2
        mid_a = self.sim.split_edge(m_room, m_edge, m_t0, m_t1)
        self._shift_edge_maps(m_room, m_edge)
        mid_b = self.sim.split_edge(room, edge, t0, t1)
        self._shift_edge_maps(room, edge)
        if m_room == room and mid_a > edge:
            mid_a += 2  # the second split renumbered the first doorway
        w = HOLE_WIDTH
        cor = self.sim.add_room([(0.0, 0.0), (0.0, w),
                                 (HOLE_CORRIDOR_LEN, w), (HOLE_CORRIDOR_LEN, 0.0)])
        self.sim.connect(m_room, mid_a, cor, 0)
        self.sim.connect(room, mid_b, cor, 2)
        self.level.room_seeds.append(cor * 7919 + 13)
        self.holes -= 1
        self.hole_mark = None
        self._snd("door_unlock", room, (hx, hy))
        self.fx.append(("holeopen", room, hx, hy))
        self._shake(3.0)

    def _shift_edge_maps(self, room: int, edge: int):
        """A split inserted two edges after `edge` in `room`; every python-
        side (room, edge) reference beyond it shifts by 2."""
        remapped = {}
        for (r, e), k in self.door_edges.items():
            remapped[(r, e + 2 if r == room and e > edge else e)] = k
        self.door_edges = remapped
        for d in self.doors:
            if d["a"] == room and d["ea"] > edge:
                d["ea"] += 2
            if d["b"] == room and d["eb"] > edge:
                d["eb"] += 2
        if self.cloister:
            self.cloister["links"] = [
                (r, e + 2 if r == room and e > edge else e)
                for (r, e) in self.cloister["links"]]

    # ------------------------------------------------------------------
    # the vigil: the wave director. Things still come through. They are met.
    # ------------------------------------------------------------------

    # no shriekers: a thing that flees forever stalls a holdout
    VIGIL_COSTS = (("mite", 1), ("husk", 2), ("spitter", 4), ("brute", 7))
    VIGIL_LINES = (
        "Ratio: Contacts. Petal breach, multiple.",
        "Ratio: Another push. The count holds.",
        "Ratio: They are learning the doors. So are you.",
        "Ratio: Wave logged. The heart is still yours.",
        "Ratio: More of them. I have stopped counting individuals.",
    )

    def _vigil_tick(self, proom: int):
        if self.wave_timer > 0:
            self.wave_timer -= 1
            return
        if any(e for e in self.enemies.values()):
            # stragglers do not stall the watch: after a grace period the
            # next push comes through anyway
            self.wave_stall = self.wave_stall + 1 if hasattr(self, "wave_stall") else 1
            if self.wave_stall < 60 * 60:
                return
        self.wave_stall = 0
        self.wave += 1
        self.metrics["wave"] = self.wave
        budget = 3 + 2 * self.wave
        # spawn away from the player: petal rooms only (never room 0's heart
        # unless the player left it)
        rooms = [r for r in range(self.sim.num_rooms())
                 if r != proom and (self.cloister is None or
                 r not in (self.cloister["sanctum"], self.cloister["corridor"]))]
        spawned = 0
        while budget > 0 and spawned < 22:
            kinds = [(k, c) for k, c in self.VIGIL_COSTS if c <= budget]
            if self.wave >= 5 and self.wave % 5 == 0 and spawned == 0:
                kind, cost = "warden", budget  # a fresh print at the door
            else:
                kind, cost = kinds[self.rng.randrange(len(kinds))]
            room = rooms[self.rng.randrange(len(rooms))]
            a = self.rng.uniform(0, 6.28)
            eid = self.spawn_enemy(room, (55 * math.cos(a), 55 * math.sin(a)), kind)
            self.enemies[eid]["state"] = "hunt"
            budget -= cost
            spawned += 1
        self.wave_timer = 60 * 8
        self._snd("stinger_wrongness", proom, self.player_pos(), 0.5)
        if self.wave % 3 == 1:
            line = self.VIGIL_LINES[(self.wave // 3) % len(self.VIGIL_LINES)]
            self.radio_queue.append(line)
            self.fx.append(("radio", line))
        # the seed keeps the pantry stocked between pushes
        if self.wave % 2 == 0:
            kind = "medkit" if self.wave % 4 == 0 else                 ("ammo_shell" if self.wave % 3 == 0 else "ammo_9mm")
            a = self.rng.uniform(0, 6.28)
            self.spawn_pickup(0, (60 * math.cos(a), 60 * math.sin(a)), kind)

    # ------------------------------------------------------------------
    # the cloister (safe room): an isolated pocket with no address,
    # linked to wherever the portable hole has cut
    # ------------------------------------------------------------------

    def _build_cloister(self):
        if self.cloister is not None:
            return
        self.hole_mark = None  # paired-mode marks cannot complete anymore
        s = self.sim
        verts = []
        for i in range(8):
            a = math.radians(22.5) - i * math.pi / 4.0
            verts.append((85.0 * math.cos(a), 85.0 * math.sin(a)))
        sanctum = s.add_room(verts)
        elen = 2 * 85.0 * math.sin(math.pi / 8.0)
        t0 = 0.5 - 7.5 / elen
        t1 = 0.5 + 7.5 / elen
        door = s.split_edge(sanctum, 4, t0, t1)
        corridor = s.add_room([(0.0, 0.0), (0.0, 15.0), (36.0, 15.0), (36.0, 0.0)])
        s.connect(sanctum, door, corridor, 0)
        self.cloister = dict(sanctum=sanctum, corridor=corridor,
                             links=[], attached=None)
        # the anti-looter guardians, re-sworn: invincible, player-loyal
        for tx, ty in ((-30.0, -34.0), (-30.0, 34.0)):
            tid = s.spawn(sanctum, tx, ty, 6.0, 50.0, GROUP_PICKUP)
            s.set_props(tid, transfers=False)
            self.turrets[tid] = dict(cd=0)
        # the seed keeps the pantry stocked
        self.spawn_pickup(sanctum, (30.0, -20.0), "medkit")
        self.spawn_pickup(sanctum, (30.0, 20.0), "ammo_9mm")
        self.level.room_seeds.extend([sanctum * 7919 + 13, corridor * 7919 + 13])

    def _attach_cloister(self, idx: int):
        c = self.cloister
        if c["attached"] is not None:
            self.sim.disconnect(c["corridor"], 2)
        room, edge = c["links"][idx]
        self.sim.connect(room, edge, c["corridor"], 2)
        c["attached"] = idx

    def _rotate_cloister(self):
        c = self.cloister
        if c and len(c["links"]) > 1 and c["attached"] is not None:
            self._attach_cloister((c["attached"] + 1) % len(c["links"]))

    def _turret_tick(self):
        if not self.turrets:
            return
        s = self.sim
        for tid, t in self.turrets.items():
            if t["cd"] > 0:
                t["cd"] -= 1
                continue
            room = s.get_room(tid)
            _, tx, ty, *_ = s.get(tid)
            best, bd = None, 1e18
            for eid in s.room_entities(room):
                if eid in self.enemies:
                    _, ex, ey, *_ = s.get(eid)
                    d = (ex - tx) ** 2 + (ey - ty) ** 2
                    if d < bd:
                        best, bd = (ex, ey), d
            if best is None:
                continue
            t["cd"] = 16
            dx, dy = best[0] - tx, best[1] - ty
            dl = math.hypot(dx, dy) or 1e-6
            nx, ny = dx / dl, dy / dl
            bid = s.spawn(room, tx + nx * 8, ty + ny * 8, 1.6, 0.002, GROUP_PBULLET)
            s.set_props(bid, rest_wall=0.0, max_substep=3.2)
            s.set_vel(bid, nx * 1200.0, ny * 1200.0)
            self.bullets[bid] = dict(kind="turret", dmg=6, ttl=40)
            self._snd("smg_fire", room, (tx, ty), 0.35)
            self.fx.append(("flash", room, tx + nx * 8, ty + ny * 8, 14.0))

    def _detonate_dart(self, bid: int, room: int, x: float, y: float):
        w = WEAPONS["lightning"]
        self.fx.append(("lightning", room, x, y, w["radius"]))
        self._snd("lightning_fire", room, (x, y), 1.0)
        self._shake(9.0)
        self._hitstop(5)
        self._decal(room, "scorch", x, y, 22.0)
        for eid in list(self.sim.room_entities(room)):
            e = self.enemies.get(eid)
            if not e:
                continue
            _, ex, ey, evx, evy, _, _ = self.sim.get(eid)
            d = math.hypot(ex - x, ey - y)
            if d > w["radius"]:
                continue
            fall = 1.0 - d / w["radius"]
            nx, ny = ((ex - x) / d, (ey - y) / d) if d > 1e-6 else (1.0, 0.0)
            self.sim.set_vel(eid, evx + nx * w["force"] * fall,
                             evy + ny * w["force"] * fall)
            self._damage_enemy(eid, w["dmg"] * (0.4 + 0.6 * fall), (nx, ny), 0.0)

    # ------------------------------------------------------------------

    def _damage_enemy(self, eid: int, dmg: float, ndir, knock: float):
        e = self.enemies.get(eid)
        if e is None:
            return
        e["hp"] -= dmg
        e["state"] = "hunt"
        self.metrics["hits"] += 1
        self.metrics["dmg_dealt"] += dmg
        room = self.sim.get_room(eid)
        _, ex, ey, evx, evy, _, _ = self.sim.get(eid)
        if knock > 0.0:
            m = ENEMIES[e["kind"]]["mass"]
            self.sim.set_vel(eid, evx + ndir[0] * knock / m, evy + ndir[1] * knock / m)
        self._snd("hit_flesh", room, (ex, ey), 0.8)
        self._decal(room, "blood", ex + self.rng.uniform(-4, 4),
                    ey + self.rng.uniform(-4, 4), self.rng.uniform(3, 7),
                    self.rng.uniform(0, 6.28))
        self.fx.append(("hitflash", eid))
        if e["hp"] <= 0:
            self._kill_enemy(eid, room, (ex, ey), ndir)

    def _kill_enemy(self, eid: int, room: int, pos, ndir):
        e = self.enemies.pop(eid)
        kind = e["kind"]
        d = ENEMIES[kind]
        self.metrics["kills"] += 1
        self._snd(d["die_snd"], room, pos)
        self._decal(room, "corpse_" + kind, pos[0], pos[1],
                    d["radius"], math.atan2(ndir[1], ndir[0]))
        for i in range(int(d["radius"])):
            a = self.rng.uniform(0, 6.28)
            r = self.rng.uniform(2, d["radius"] * 1.8)
            self._decal(room, "blood", pos[0] + math.cos(a) * r,
                        pos[1] + math.sin(a) * r, self.rng.uniform(2, 5), a)
        self.fx.append(("gib", room, pos[0], pos[1], int(d["radius"]),
                        (ndir[0], ndir[1])))
        self._hitstop(4 if kind in ("husk", "mite") else 7)
        self._shake(2.5)
        self.sim.remove(eid)
        # drops
        for p, kind_ in DROP_TABLES[kind]:
            if self.rng.random() < p:
                self.spawn_pickup(room, (pos[0] + self.rng.uniform(-6, 6),
                                         pos[1] + self.rng.uniform(-6, 6)), kind_)
                break
        # nearby enemies hear the death
        self.alert_enemies(room, 1)
        self._maybe_radio(f"kills:{self.metrics['kills']}")

    def _damage_player(self, dmg: float, room: int):
        if self.hurt_cd > 0 or self.dead:
            return
        self.hurt_cd = 30
        dmg *= self._dmg_mul
        self.hp -= dmg
        self.metrics["dmg_taken"] += dmg
        px, py = self.player_pos()
        self._snd("player_hurt", room, (px, py))
        self._shake(min(8.0, 2.0 + dmg * 0.25))
        self.fx.append(("playerhurt", dmg))
        self._decal(room, "blood", px + self.rng.uniform(-5, 5),
                    py + self.rng.uniform(-5, 5), self.rng.uniform(3, 6))
        if self.hp <= 0:
            self.dead = True
            self.metrics["deaths"] += 1
            self._snd("player_die", room, (px, py))
            self.fx.append(("playerdie",))
            self._decal(room, "corpse_player", px, py, PLAYER_RADIUS)

    # ------------------------------------------------------------------

    def _enemy_ai(self, proom: int):
        s = self.sim
        active = set(s.rooms_within(proom, ACTIVE_HOPS))
        px, py = self.player_pos()
        for eid, e in list(self.enemies.items()):
            room = s.get_room(eid)
            if room not in active:
                continue
            kind = e["kind"]
            d = ENEMIES[kind]
            _, ex, ey, evx, evy, edx, edy = s.get(eid)
            for k in ("touch_cd", "spit_cd", "scream_cd", "wander_cd"):
                if e.get(k, 0) > 0:
                    e[k] -= 1
            if e.get("buff", 0) > 0:
                e["buff"] -= 1

            if e["state"] == "idle":
                if room == proom:
                    # the notice beat: growl first, charge after — the
                    # player always gets the first move
                    e["state"] = "waking"
                    e["wake"] = self.WAKE_TICKS[kind]
                    self._snd(d["alert_snd"], room, (ex, ey), 0.9)
                    self.fx.append(("alerted", room, ex, ey))
                    ddx, ddy = px - ex, py - ey
                    dl = math.hypot(ddx, ddy) or 1e-6
                    s.set_dir(eid, ddx / dl, ddy / dl)
                    continue
                else:
                    # aimless drift
                    if e["wander_cd"] <= 0:
                        e["wander_cd"] = self.rng.randrange(90, 240)
                        a = self.rng.uniform(0, 6.28)
                        e["wander"] = (math.cos(a), math.sin(a))
                    wx, wy = e.get("wander", (0.0, 0.0))
                    s.set_vel(eid, evx + wx * d["accel"] * 0.25 * DT,
                              evy + wy * d["accel"] * 0.25 * DT)
                    continue

            if e["state"] == "waking":
                e["wake"] = e.get("wake", 0) - 1
                if e["wake"] <= 0:
                    e["state"] = "hunt"
                continue

            # hunting: audible before visible — the dread channel
            e["groan_cd"] = e.get("groan_cd", self.rng.randrange(60, 200)) - 1
            if e["groan_cd"] <= 0:
                e["groan_cd"] = self.rng.randrange(140, 260)
                self._snd(d["alert_snd"], room, (ex, ey), 0.35)
            accel = d["accel"] * (1.25 if e.get("buff", 0) > 0 else 1.0)
            if kind == "shrieker":
                self._shrieker_ai(eid, e, room, proom, ex, ey, accel)
                continue
            if room == proom:
                ddx, ddy = px - ex, py - ey
                dist = math.hypot(ddx, ddy) or 1e-6
                nx, ny = ddx / dist, ddy / dist
                s.set_dir(eid, nx, ny)
                # husks lunge: a sudden burst inside close range reads as an
                # attack, not a shove
                if kind in ("husk", "brute") and dist < 95.0 \
                        and e.get("lunge_cd", 0) <= 0:
                    e["lunge_cd"] = 120 if kind == "husk" else 150
                    burst = 300.0 if kind == "husk" else 240.0
                    s.set_vel(eid, evx + nx * burst, evy + ny * burst)
                    self._snd(d["alert_snd"], room, (ex, ey), 0.55)
                if e.get("lunge_cd", 0) > 0:
                    e["lunge_cd"] -= 1
                # warden enrage below half health
                if kind == "warden" and not e.get("enraged") \
                        and e["hp"] < ENEMIES["warden"]["hp"] * 0.5:
                    e["enraged"] = True
                    e["buff"] = 10 ** 9
                    self._snd("shrieker_scream", room, (ex, ey), 1.0)
                    self.fx.append(("scream", room, ex, ey))
                keep_min = d.get("keep_min")
                if keep_min is not None and d.get("spit_cd") is not None:
                    # ranged: hold the band, spit on cooldown
                    if dist < d["keep_min"]:
                        s.set_vel(eid, evx - nx * accel * DT, evy - ny * accel * DT)
                    elif dist > d["keep_max"]:
                        s.set_vel(eid, evx + nx * accel * DT, evy + ny * accel * DT)
                    if e["spit_cd"] <= 0:
                        e["spit_cd"] = d["spit_cd"] // 2 if e.get("enraged") \
                            else d["spit_cd"]
                        self._spit(eid, room, ex, ey, nx, ny, d)
                        if e.get("enraged"):
                            # radial burst: the warden's room fills with spit
                            for k in range(6):
                                a2 = k * math.pi / 3 + self.tick_count * 0.05
                                self._spit(eid, room, ex, ey,
                                           math.cos(a2), math.sin(a2), d)
                    if kind != "warden":
                        continue
                s.set_vel(eid, evx + nx * accel * DT, evy + ny * accel * DT)
            else:
                if e.get("tether"):
                    continue  # arena guardian: holds its ground
                edge = s.next_edge(room, proom)
                if edge < 0:
                    continue
                mx_, my_ = s.edge_midpoint(room, edge)
                ddx, ddy = mx_ - ex, my_ - ey
                dist = math.hypot(ddx, ddy) or 1e-6
                s.set_dir(eid, ddx / dist, ddy / dist)
                s.set_vel(eid, evx + ddx / dist * accel * DT,
                          evy + ddy / dist * accel * DT)

    def _spit(self, eid, room, ex, ey, nx, ny, d):
        bid = self.sim.spawn(room, ex + nx * (d["radius"] + 4),
                             ey + ny * (d["radius"] + 4), 2.5, 0.01, GROUP_EBULLET)
        self.sim.set_props(bid, rest_wall=0.0, max_substep=3.0)
        ang = math.atan2(ny, nx) + self.rng.uniform(-0.06, 0.06)
        self.sim.set_vel(bid, math.cos(ang) * d["spit_speed"],
                         math.sin(ang) * d["spit_speed"])
        self.bullets[bid] = dict(kind="spit", dmg=d["spit_dmg"], ttl=180)
        self._snd("spitter_shoot", room, (ex, ey), 0.9)

    def _shrieker_ai(self, eid, e, room, proom, ex, ey, accel):
        s = self.sim
        d = ENEMIES["shrieker"]
        px, py = self.player_pos()
        if e["scream_cd"] <= 0:
            e["scream_cd"] = d["scream_cd"]
            self._snd("shrieker_scream", room, (ex, ey), 1.0)
            self.fx.append(("scream", room, ex, ey))
            for oid, oe in self.enemies.items():
                if oid == eid:
                    continue
                orr = s.get_room(oid)
                hd = s.hop_distance(orr, room)
                if 0 <= hd <= 2:
                    oe["state"] = "hunt"
                    oe["buff"] = 60 * 5
        if room == proom:
            ddx, ddy = ex - px, ey - py  # away from player
            dist = math.hypot(ddx, ddy) or 1e-6
            _, _, _, evx, evy, _, _ = s.get(eid)
            s.set_dir(eid, ddx / dist, ddy / dist)
            s.set_vel(eid, evx + ddx / dist * accel * DT, evy + ddy / dist * accel * DT)

    # ------------------------------------------------------------------

    def _consume_events(self, events):
        for ev in events:
            tag = ev[0]
            if tag == "transfer":
                _, ent, from_room, to_room, edge, m9 = ev
                if ent == self.pid:
                    if self.cloister and to_room == self.cloister["sanctum"]:
                        self._rotate_cloister()
                    # camera re-base: zero visible change by construction
                    self.cam = necore.mat_mul(self.cam, necore.mat_inv(m9))
                    self.metrics["transfers"] += 1
                    self.metrics["rooms_visited"].add(to_room)
                    self._maybe_radio(f"enter_room:{to_room}")
            elif tag == "wall":
                _, ent, room, edge, px_, py_, nx, ny, speed = ev
                b = self.bullets.get(ent)
                if b is not None and b["kind"] != "spit" \
                        and self.door_edges.get((room, edge)) == "shoot":
                    # a cracked wall gives way
                    for d in self.doors:
                        if not d["open"] and d["key"] == "shoot" and (
                                (d["a"], d["ea"]) == (room, edge)
                                or (d["b"], d["eb"]) == (room, edge)):
                            d["open"] = True
                            self.sim.connect(d["a"], d["ea"], d["b"], d["eb"])
                            self.door_edges.pop((d["a"], d["ea"]), None)
                            self.door_edges.pop((d["b"], d["eb"]), None)
                            self._snd("door_unlock", room, (px_, py_))
                            self._decal(room, "scorch", px_, py_, 10.0)
                            self._shake(3.0)
                            self.fx.append(("holeopen", room, px_, py_))
                            break
                if b is not None:
                    if b["kind"] in ("tau", "taucharged") and b.get("bounces", 0) > 0:
                        b["bounces"] -= 1
                        self._snd("ricochet", room, (px_, py_), 0.5)
                        self.fx.append(("spark", room, px_, py_, nx, ny))
                        continue  # engine already reflected it (rest_wall=1)
                    if b["kind"] == "spit":
                        self._decal(room, "splat", px_, py_, 4.0)
                    elif b["kind"] == "dart":
                        self._detonate_dart(ent, room, px_, py_)
                    elif b["kind"] == "bullet":
                        self._decal(room, "chip", px_, py_, 2.0)
                        self._snd("hit_wall", room, (px_, py_), 0.35)
                        self.fx.append(("spark", room, px_, py_, nx, ny))
                    self.sim.remove(ent)
                    self.bullets.pop(ent, None)
            elif tag == "contact":
                _, a, b, cx, cy, nx, ny, rel = ev
                self._contact(a, b, cx, cy, nx, ny)

    def _contact(self, a: int, b: int, cx: float, cy: float, nx: float, ny: float):
        # normalize order: identify roles
        for x, y in ((a, b), (b, a)):
            bx = self.bullets.get(x)
            if bx is not None and y in self.enemies:
                if bx["kind"] == "dart":
                    room = self.sim.get_room(x) if self.sim.exists(x) \
                        else self.sim.get_room(y)
                    self._detonate_dart(x, room, cx, cy)
                elif bx["kind"] in ("bullet", "tau", "taucharged", "turret"):
                    self._damage_enemy(y, bx["dmg"], (nx if x == b else -nx, ny if x == b else -ny), 90.0)
                self.sim.remove(x)
                self.bullets.pop(x, None)
                return
            if bx is not None and y == self.pid:
                room = self.sim.get_room(y)
                if bx["kind"] == "spit":
                    self._damage_player(bx["dmg"], room)
                elif bx["kind"] == "dart":
                    self._detonate_dart(x, room, cx, cy)
                    px_, py_ = self.player_pos()
                    self._damage_player(WEAPONS["lightning"]["dmg"] * 0.6, room)
                elif bx["kind"] == "turret":
                    pass  # the guardians do not miss that badly
                else:
                    # a round you fired found its way back through the fold
                    self._damage_player(bx["dmg"] * 0.75, room)
                self.sim.remove(x)
                self.bullets.pop(x, None)
                return
        if a == self.pid or b == self.pid:
            eid = b if a == self.pid else a
            e = self.enemies.get(eid)
            if e and e["touch_cd"] <= 0:
                d = ENEMIES[e["kind"]]
                if d["touch_dmg"] > 0:
                    e["touch_cd"] = d["touch_cd"]
                    self._damage_player(d["touch_dmg"], self.sim.get_room(self.pid))

    # ------------------------------------------------------------------

    def _pickup_scan(self, proom: int):
        px, py = self.player_pos()
        for eid in list(self.sim.room_entities(proom)):
            p = self.pickups.get(eid)
            if p is None:
                continue
            _, x, y, *_ = self.sim.get(eid)
            if math.hypot(x - px, y - py) > PLAYER_RADIUS + PICKUPS[p["kind"]]["radius"] + 2.0:
                continue
            kind = p["kind"]
            if kind.startswith("ammo_"):
                t = kind[5:]
                self.ammo[t] = self.ammo.get(t, 0) + PICKUPS[kind]["amount"]
                self._snd("pickup_ammo", proom, (x, y))
            elif kind == "medkit":
                if self.hp > 70:
                    continue  # leave it for later — scarcity respects foresight
                self.hp = min(PLAYER_HP, self.hp + PICKUPS[kind]["amount"])
                self._snd("pickup_medkit", proom, (x, y))
            elif kind.startswith("weapon_"):
                w = kind[7:]
                if w not in self.weapons:
                    self.weapons.append(w)
                    self.weapon = w
                self.ammo_bonus_for(w)
                self._snd("pickup_ammo", proom, (x, y))
                self.fx.append(("weapon", w))
            elif kind == "safe_room_core":
                self._build_cloister()
                if "hole" not in self.weapons:
                    self.weapons.append("hole")
                self.holes += 2
                self._snd("pickup_key", proom, (x, y))
                self.fx.append(("weapon", "cloister"))
                text = ("Ratio: Testator work. A detached subgraph — a room "
                        "with no address. Your seed has already shaken hands "
                        "with it. You have a cloister now. It follows you.")
                self.radio_queue.append(text)
                self.fx.append(("radio", text))
            elif kind == "turret":
                continue  # not a pickup; the guardians are furniture
            elif kind == "portable_hole":
                self.holes += 1
                if "hole" not in self.weapons:
                    self.weapons.append("hole")
                self._snd("pickup_key", proom, (x, y))
                self.fx.append(("weapon", "hole"))
            elif kind == "implant_lightning":
                if "lightning" not in self.weapons:
                    self.weapons.append("lightning")
                self._snd("pickup_key", proom, (x, y))
                self.fx.append(("weapon", "lightning"))
            elif kind.startswith("key_"):
                key = kind[4:]
                self.keys.add(key)
                self._snd("pickup_key", proom, (x, y))
                self._maybe_radio(f"pickup:{key}")
                self._unlock_doors(key)
            self.metrics["pickups"] += 1
            self.sim.remove(eid)
            self.pickups.pop(eid, None)

    def ammo_bonus_for(self, w: str):
        bonus = {"smg": ("9mm", 30), "shotgun": ("shell", 8), "rail": ("cell", 6),
                 "tau": ("cell", 10)}
        if w in bonus:
            t, n = bonus[w]
            self.ammo[t] = self.ammo.get(t, 0) + n

    def _unlock_doors(self, key: str):
        for d in self.doors:
            if d["key"] == key and not d["open"]:
                d["open"] = True
                self.sim.connect(d["a"], d["ea"], d["b"], d["eb"])
                self.door_edges.pop((d["a"], d["ea"]), None)
                self.door_edges.pop((d["b"], d["eb"]), None)
                mx, my = self.sim.edge_midpoint(d["a"], d["ea"])
                self._snd("door_unlock", d["a"], (mx, my))

    def _terminal_scan(self, proom: int, inp: InputFrame):
        if not inp.interact:
            return
        px, py = self.player_pos()
        for t in self.terminals:
            if t["room"] != proom or t["read"]:
                continue
            if math.hypot(t["pos"][0] - px, t["pos"][1] - py) < 26.0:
                t["read"] = True
                self.fx.append(("terminal", t["text"]))
                self._snd("terminal_open", proom, t["pos"])

    def _exit_scan(self, proom: int):
        if self.exit_room < 0 or proom != self.exit_room:
            return
        px, py = self.player_pos()
        if math.hypot(self.exit_pos[0] - px, self.exit_pos[1] - py) >= 18.0:
            return
        lvl = self.level
        if lvl.exit_key and lvl.exit_key not in self.keys:
            if "exit_locked" not in self._radio_fired:
                self._radio_fired.add("exit_locked")
                text = ("Ratio: The way out doesn't answer. It wants the "
                        f"{lvl.exit_key} seal.")
                self.radio_queue.append(text)
                self.fx.append(("radio", text))
            return
        if lvl.exit_gate_kind and any(
                e["kind"] == lvl.exit_gate_kind for e in self.enemies.values()):
            if "exit_gated" not in self._radio_fired:
                self._radio_fired.add("exit_gated")
                text = ("Ratio: The way out doesn't answer. Something in "
                        "here is holding it shut. Something big.")
                self.radio_queue.append(text)
                self.fx.append(("radio", text))
            return
        self.complete = True
        self.metrics["completed"] = True
        self._maybe_radio("exit")

    # ------------------------------------------------------------------
    # bullets ttl (called from tick loop indirectly, cheap sweep)
    # ------------------------------------------------------------------

    def sweep_bullets(self):
        for bid in list(self.bullets):
            b = self.bullets[bid]
            b["ttl"] -= 1
            if b["ttl"] <= 0:
                if b["kind"] == "dart" and self.sim.exists(bid):
                    _, x, y, *_ = self.sim.get(bid)
                    self._detonate_dart(bid, self.sim.get_room(bid), x, y)
                self.sim.remove(bid)
                del self.bullets[bid]

    # ------------------------------------------------------------------
    # queries for renderer / bots / tests
    # ------------------------------------------------------------------

    def visible(self, max_depth: int = 14, max_instances: int = 96):
        proom = self.player_room()
        px, py = self.player_pos()
        # the camera apex is the player (strict LOS from the character)
        return self.sim.visible_set(proom, self.cam, px, py,
                                    float(self.screen_w), float(self.screen_h),
                                    max_depth, max_instances)

    def snapshot(self) -> dict:
        proom = self.player_room()
        px, py = self.player_pos()
        enemies = []
        for eid, e in self.enemies.items():
            r = self.sim.get_room(eid)
            _, x, y, *_ = self.sim.get(eid)
            enemies.append(dict(id=eid, kind=e["kind"], room=r, pos=(x, y),
                                hp=e["hp"], state=e["state"],
                                hops=self.sim.hop_distance(r, proom)))
        pickups = []
        for eid, p in self.pickups.items():
            r = self.sim.get_room(eid)
            _, x, y, *_ = self.sim.get(eid)
            pickups.append(dict(id=eid, kind=p["kind"], room=r, pos=(x, y),
                                hops=self.sim.hop_distance(r, proom)))
        return dict(
            tick=self.tick_count, hp=self.hp, dead=self.dead,
            complete=self.complete, room=proom, pos=(px, py),
            weapon=self.weapon, weapons=list(self.weapons), ammo=dict(self.ammo),
            keys=set(self.keys),
            lightning_ready=self.lightning_charge >= LIGHTNING_RECHARGE_TICKS,
            holes=self.holes, tau_charge=self.tau_charge,
            cloister=(dict(links=len(self.cloister["links"]),
                           attached=self.cloister["attached"])
                      if self.cloister else None),
            enemies=enemies, pickups=pickups,
            exit_room=self.exit_room,
            exit_next_edge=self.sim.next_edge(proom, self.exit_room)
            if self.exit_room >= 0 else -1,
            exit_key_needed=self.level.exit_key
            if self.level.exit_key and self.level.exit_key not in self.keys
            else "",
            exit_gate_kind=self.level.exit_gate_kind,
            exit_gate_remaining=sum(
                1 for e in self.enemies.values()
                if e["kind"] == self.level.exit_gate_kind)
            if self.level.exit_gate_kind else 0,
            door_keys_needed=sorted(
                {d["key"] for d in self.doors if not d["open"] and d["key"]}
                - self.keys),
        )
