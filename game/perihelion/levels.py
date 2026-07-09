"""Level format v2: JSON in, built necore.Sim out.

Rooms are authored as absolute vertex lists on an editor canvas; the engine
re-centers each room on its centroid, so every entity/prop position in the
file is converted to room-local coordinates by subtracting that centroid.
Doors are pending connections: the rooms are NOT connected until unlocked at
runtime (a locked door is genuinely a wall — you cannot see through it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

LEVEL_VERSION = 2


@dataclass
class EntitySpec:
    type: str
    pos: tuple[float, float]  # room-local (post-centroid)
    props: dict = field(default_factory=dict)


@dataclass
class DoorSpec:
    a: int
    ea: int
    b: int
    eb: int
    key: str  # key id, e.g. "red"; "" = opens by level trigger


@dataclass
class TerminalSpec:
    room: int
    pos: tuple[float, float]
    text: str


@dataclass
class RadioLine:
    trigger: str  # "start" | "enter_room:<idx>" | "kills:<n>" | "pickup:<key>" | "exit"
    text: str


@dataclass
class Level:
    name: str
    tier: int
    room_verts: list[list[tuple[float, float]]]  # local coords (centroid at 0)
    room_centroids: list[tuple[float, float]]  # authoring-canvas centroids
    room_seeds: list[int]
    connects: list[tuple[int, int, int, int]]
    connects_x: list[tuple[int, int, int, int, tuple]]
    doors: list[DoorSpec]
    entities: list[tuple[int, EntitySpec]]  # (room, spec)
    player_room: int
    player_pos: tuple[float, float]
    exit_room: int
    exit_pos: tuple[float, float]
    intro: str
    radio: list[RadioLine]
    terminals: list[TerminalSpec]
    ambience: str


def _centroid(verts: list[tuple[float, float]]) -> tuple[float, float]:
    # Area-weighted centroid, matching engine add_room re-centering.
    n = len(verts)
    a = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % n]
        w = x0 * y1 - x1 * y0
        a += w
        cx += (x0 + x1) * w
        cy += (y0 + y1) * w
    if abs(a) < 1e-12:
        return (sum(v[0] for v in verts) / n, sum(v[1] for v in verts) / n)
    return (cx / (3.0 * a), cy / (3.0 * a))


def load_level(path: str | Path) -> Level:
    data = json.loads(Path(path).read_text())
    return level_from_dict(data)


def level_from_dict(data: dict) -> Level:
    if data.get("version", LEVEL_VERSION) != LEVEL_VERSION:
        raise ValueError(f"level version {data.get('version')} != {LEVEL_VERSION}")
    room_verts: list[list[tuple[float, float]]] = []
    room_centroids: list[tuple[float, float]] = []
    room_seeds: list[int] = []
    entities: list[tuple[int, EntitySpec]] = []

    for ri, room in enumerate(data["rooms"]):
        verts = [tuple(v) for v in room["verts"]]
        c = _centroid(verts)
        room_centroids.append(c)
        room_verts.append([(x - c[0], y - c[1]) for x, y in verts])
        room_seeds.append(int(room.get("detail_seed", ri * 7919 + 13)))
        for e in room.get("entities", []):
            ex, ey = e["pos"]
            entities.append(
                (
                    ri,
                    EntitySpec(
                        type=e["type"],
                        pos=(ex - c[0], ey - c[1]),
                        props=dict(e.get("props", {})),
                    ),
                )
            )

    def local(ri: int, pos) -> tuple[float, float]:
        c = room_centroids[ri]
        return (pos[0] - c[0], pos[1] - c[1])

    player = data["player"]
    exit_ = data.get("exit")
    doors = [DoorSpec(**d) for d in data.get("doors", [])]
    lore = data.get("lore", {})
    radio = [RadioLine(**r) for r in lore.get("radio", [])]
    terminals = [
        TerminalSpec(t["room"], local(t["room"], t["pos"]), t["text"])
        for t in lore.get("terminals", [])
    ]
    return Level(
        name=data.get("name", "?"),
        tier=int(data.get("tier", 1)),
        room_verts=room_verts,
        room_centroids=room_centroids,
        room_seeds=room_seeds,
        connects=[tuple(c) for c in data.get("connects", [])],
        connects_x=[
            (c[0], c[1], c[2], c[3], tuple(c[4])) for c in data.get("connects_x", [])
        ],
        doors=doors,
        entities=entities,
        player_room=int(player["room"]),
        player_pos=local(player["room"], player["pos"]),
        exit_room=int(exit_["room"]) if exit_ else -1,
        exit_pos=local(exit_["room"], exit_["pos"]) if exit_ else (0.0, 0.0),
        intro=lore.get("intro", ""),
        radio=radio,
        terminals=terminals,
        ambience=data.get("ambience", "amb_drone_early"),
    )


def save_level(level_dict: dict, path: str | Path) -> None:
    level_dict = dict(level_dict)
    level_dict["version"] = LEVEL_VERSION
    Path(path).write_text(json.dumps(level_dict, indent=1))


# ---------------------------------------------------------------------------
# Programmatic authoring helpers (used by the campaign generator and tests).
# ---------------------------------------------------------------------------


class LevelBuilder:
    """Accumulates rooms/connections in authoring (absolute-canvas) coords and
    emits a level dict. Rooms may be placed anywhere on the canvas — including
    on top of each other; only connections define adjacency."""

    def __init__(self, name: str, tier: int = 1, ambience: str = "amb_drone_early"):
        self.data: dict = {
            "version": LEVEL_VERSION,
            "name": name,
            "tier": tier,
            "ambience": ambience,
            "rooms": [],
            "connects": [],
            "connects_x": [],
            "doors": [],
            "player": None,
            "exit": None,
            "lore": {"intro": "", "radio": [], "terminals": []},
        }

    def room(self, verts, detail_seed: int | None = None) -> int:
        r = {"verts": [list(v) for v in verts], "entities": []}
        if detail_seed is not None:
            r["detail_seed"] = detail_seed
        self.data["rooms"].append(r)
        return len(self.data["rooms"]) - 1

    def rect(self, x, y, w, h, seed=None) -> int:
        return self.room([(x, y), (x, y + h), (x + w, y + h), (x + w, y)], seed)

    def ngon(self, cx, cy, r, n, phase=0.0, seed=None) -> int:
        import math

        verts = []
        for i in range(n):
            a = phase + i * 2.0 * math.pi / n
            verts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return self.room(verts, seed)

    def connect(self, a, ea, b, eb):
        self.data["connects"].append([a, ea, b, eb])

    def connect_x(self, a, ea, b, eb, m9):
        self.data["connects_x"].append([a, ea, b, eb, list(m9)])

    def door(self, a, ea, b, eb, key: str):
        self.data["doors"].append({"a": a, "ea": ea, "b": b, "eb": eb, "key": key})

    def entity(self, room: int, type_: str, pos, **props):
        e = {"type": type_, "pos": list(pos)}
        if props:
            e["props"] = props
        self.data["rooms"][room]["entities"].append(e)

    def player(self, room: int, pos):
        self.data["player"] = {"room": room, "pos": list(pos)}

    def exit(self, room: int, pos):
        self.data["exit"] = {"room": room, "pos": list(pos)}

    def intro(self, text: str):
        self.data["lore"]["intro"] = text

    def radio(self, trigger: str, text: str):
        self.data["lore"]["radio"].append({"trigger": trigger, "text": text})

    def terminal(self, room: int, pos, text: str):
        self.data["lore"]["terminals"].append(
            {"room": room, "pos": list(pos), "text": text}
        )

    def build(self) -> Level:
        if self.data["player"] is None:
            raise ValueError("level has no player spawn")
        return level_from_dict(self.data)

    def to_dict(self) -> dict:
        return self.data
