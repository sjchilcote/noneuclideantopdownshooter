"""Pure-Python editor model.

Operates directly on the RESOLVED level dict -- the exact JSON shape written
to `levels/*.json` (see `perihelion.levels` for the loader/format doc). Each
room's `verts` are absolute authoring-canvas coordinates; the model mutates
that dict in place and can write it straight back out with `json.dumps`.

No pygame import anywhere in this module -- `game/tests/test_editor.py`
exercises it headlessly, and `editor/view.py` is the only place pygame is
allowed to appear.
"""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

LEVEL_VERSION = 2

ENEMY_TYPES = ["husk", "mite", "spitter", "brute", "shrieker", "warden"]
PICKUP_TYPES = [
    "ammo_9mm", "ammo_shell", "ammo_cell", "medkit",
    "weapon_smg", "weapon_shotgun", "weapon_rail", "implant_lightning",
    "key_red", "key_blue", "key_gold", "key_void",
]
# Types that live in a room's own `entities` list (spawnable by GameSession).
ROOM_ENTITY_TYPES = set(ENEMY_TYPES) | set(PICKUP_TYPES)
# Full palette order for the E-tool cycle (player/exit move the singleton
# markers instead of creating a room entity; terminal appends to lore).
ENTITY_PALETTE = ["player", "exit"] + ENEMY_TYPES + PICKUP_TYPES + ["terminal"]

KEY_PRESETS = ["red", "blue", "gold", "void"]
GATE_KIND_PRESETS = ["", *ENEMY_TYPES]

UNDO_CAP = 100

_ENTER_ROOM_RE = re.compile(r"^enter_room:(\d+)$")


# ---------------------------------------------------------------------------
# pure geometry helpers
# ---------------------------------------------------------------------------


def _shoelace(verts) -> float:
    n = len(verts)
    a = 0.0
    for i in range(n):
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a * 0.5


def canonical_winding(verts: list) -> list:
    """Reverse verts if needed so the shoelace area is negative (engine
    canonical: y-down visual-CCW). Matches LevelBuilder.poly / loader."""
    if _shoelace(verts) > 0:
        return list(reversed(verts))
    return list(verts)


def convex_flags(verts, eps: float = 1e-6) -> list:
    """Per-vertex 'offending' flags: True where the polygon is reflex at
    that vertex. Collinear vertices (doorway-split walls have these by
    design) read as False -- only a genuine sign flip against the overall
    winding counts as concave."""
    n = len(verts)
    if n < 3:
        return [True] * n
    shoe = _shoelace(verts)
    if abs(shoe) < 1e-9:
        return [True] * n  # degenerate / zero-area
    sign = 1.0 if shoe > 0 else -1.0
    flags = []
    for i in range(n):
        p0 = verts[i - 1]
        p1 = verts[i]
        p2 = verts[(i + 1) % n]
        e1x, e1y = p1[0] - p0[0], p1[1] - p0[1]
        e2x, e2y = p2[0] - p1[0], p2[1] - p1[1]
        cross = e1x * e2y - e1y * e2x
        flags.append(cross * sign < -eps)
    return flags


def _point_in_poly(x: float, y: float, poly) -> bool:
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_at = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_at:
                inside = not inside
        j = i
    return inside


def _point_seg_dist2(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 < 1e-12:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def _vertex_delete_edge_map(n: int, vi: int) -> dict:
    """old edge index -> new edge index, or None if that edge touched the
    removed vertex (its shape is gone; any connection bound to it must be
    dropped -- reattaching it to a differently-shaped edge would be a lie)."""
    ids = list(range(n))
    new_ids = [i for i in ids if i != vi]
    n2 = len(new_ids)
    old_edges = [(ids[i], ids[(i + 1) % n]) for i in range(n)]
    new_edges = [(new_ids[i], new_ids[(i + 1) % n2]) for i in range(n2)]
    lookup = {pair: idx for idx, pair in enumerate(new_edges)}
    mapping = {}
    for oe, pair in enumerate(old_edges):
        mapping[oe] = None if vi in pair else lookup.get(pair)
    return mapping


def _blank_level() -> dict:
    return {
        "version": LEVEL_VERSION,
        "name": "untitled",
        "tier": 1,
        "ambience": "amb_drone_early",
        "rooms": [],
        "connects": [],
        "connects_x": [],
        "doors": [],
        "player": None,
        "exit": None,
        "lore": {"intro": "", "radio": [], "terminals": []},
    }


def _normalize(d: dict) -> dict:
    """Fill in missing optional keys so the rest of the model never has to
    guard against a hand-edited/partial file. Never raises on missing keys;
    a genuinely broken `rooms` entry will surface later via validate()."""
    d = dict(d)
    d.setdefault("version", LEVEL_VERSION)
    d.setdefault("name", "untitled")
    d.setdefault("tier", 1)
    d.setdefault("ambience", "amb_drone_early")
    d["rooms"] = list(d.get("rooms") or [])
    for room in d["rooms"]:
        room.setdefault("verts", [])
        room.setdefault("entities", [])
    d["connects"] = list(d.get("connects") or [])
    d["connects_x"] = list(d.get("connects_x") or [])
    d["doors"] = list(d.get("doors") or [])
    d.setdefault("player", None)
    d.setdefault("exit", None)
    lore = dict(d.get("lore") or {})
    lore.setdefault("intro", "")
    lore["radio"] = list(lore.get("radio") or [])
    lore["terminals"] = list(lore.get("terminals") or [])
    d["lore"] = lore
    return d


# ---------------------------------------------------------------------------
# EditorModel
# ---------------------------------------------------------------------------


class EditorModel:
    """All editor state lives here except pygame view/input concerns.

    `self.data` is the literal level dict (same shape as the JSON on disk).
    Selection is a tuple:
        ("room", ri) ("vertex", ri, vi) ("entity", ri, ei)
        ("player",) ("exit",) ("terminal", ti)
        ("connect", kind, idx)   kind in {"connect", "connect_x", "door"}
    """

    def __init__(self) -> None:
        self.data: dict = _blank_level()
        self.path: Path | None = None
        self.selection = None
        self._undo: list = []
        self._redo: list = []
        self._saved_snapshot: dict = copy.deepcopy(self.data)
        self.last_errors: list = []

    # -- dirty / undo -----------------------------------------------------

    @property
    def dirty(self) -> bool:
        return self.data != self._saved_snapshot

    def snapshot(self) -> None:
        """Push the CURRENT state to the undo stack. Call before mutating."""
        self._undo.append(copy.deepcopy(self.data))
        if len(self._undo) > UNDO_CAP:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self.data))
        if len(self._redo) > UNDO_CAP:
            self._redo.pop(0)
        self.data = self._undo.pop()
        self.selection = None
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self.data))
        if len(self._undo) > UNDO_CAP:
            self._undo.pop(0)
        self.data = self._redo.pop()
        self.selection = None
        return True

    # -- file ops -----------------------------------------------------

    def new(self) -> None:
        self.data = _blank_level()
        self.path = None
        self.selection = None
        self._undo.clear()
        self._redo.clear()
        self._saved_snapshot = copy.deepcopy(self.data)
        self.last_errors = []

    def load(self, path) -> list:
        """Returns a list of error strings (empty = success). On failure
        the model is left untouched -- a bad load never clobbers good state."""
        try:
            raw = Path(path).read_text()
            d = json.loads(raw)
        except Exception as exc:
            return [f"load failed: {exc}"]
        if not isinstance(d, dict):
            return ["load failed: root is not a JSON object"]
        try:
            d = _normalize(d)
        except Exception as exc:
            return [f"load failed: malformed level ({exc})"]
        self.data = d
        self.path = Path(path)
        self.selection = None
        self._undo.clear()
        self._redo.clear()
        self._saved_snapshot = copy.deepcopy(self.data)
        self.last_errors = []
        return []

    def _write_out(self, path) -> None:
        out = dict(self.data)
        out["version"] = LEVEL_VERSION
        Path(path).write_text(json.dumps(out, indent=1))

    def save(self, path=None) -> list:
        """Validation-gated save. Returns the (non-empty) error list and
        refuses to write if invalid."""
        errs = self.validate()
        if errs:
            return errs
        target = Path(path) if path is not None else self.path
        if target is None:
            return ["no file path to save to"]
        self._write_out(target)
        self.path = target
        self._saved_snapshot = copy.deepcopy(self.data)
        return []

    def export(self, path) -> list:
        """Validation-gated write to an arbitrary path that does NOT touch
        self.path or the dirty/saved-snapshot bookkeeping -- used by the F5
        test-play export so it never hijacks "the file Ctrl+S writes to"."""
        errs = self.validate()
        if errs:
            return errs
        self._write_out(path)
        return []

    # -- validation -----------------------------------------------------

    def validate(self) -> list:
        errs: list = []
        rooms = self.data.get("rooms", [])
        n_rooms = len(rooms)

        for ri, room in enumerate(rooms):
            try:
                verts = room.get("verts", [])
                if len(verts) < 3:
                    errs.append(f"room {ri}: fewer than 3 vertices")
                    continue
                if _shoelace(verts) >= 0:
                    errs.append(f"room {ri}: wrong winding (author y-down visual-CCW)")
                bad = [i for i, f in enumerate(convex_flags(verts)) if f]
                if bad:
                    errs.append(f"room {ri}: concave/degenerate at vertex {bad}")
            except Exception as exc:
                errs.append(f"room {ri}: malformed ({exc})")

        player = self.data.get("player")
        if not player:
            errs.append("no player spawn")
        elif not (isinstance(player.get("room"), int) and 0 <= player["room"] < n_rooms):
            errs.append("player spawn room index out of range")

        exit_ = self.data.get("exit")
        if not exit_:
            errs.append("no exit")
        elif not (isinstance(exit_.get("room"), int) and 0 <= exit_["room"] < n_rooms):
            errs.append("exit room index out of range")

        used: dict = {}

        def check(ri, ei, label) -> bool:
            if not (isinstance(ri, int) and 0 <= ri < n_rooms):
                errs.append(f"{label}: room {ri!r} out of range")
                return False
            nv = len(rooms[ri].get("verts", []))
            if not (isinstance(ei, int) and 0 <= ei < nv):
                errs.append(f"{label}: room {ri} edge {ei!r} out of range")
                return False
            return True

        def touch(ri, ei, label) -> None:
            used.setdefault((ri, ei), []).append(label)

        for idx, c in enumerate(self.data.get("connects", [])):
            label = f"connects[{idx}]"
            try:
                a, ea, b, eb = c[0], c[1], c[2], c[3]
            except Exception:
                errs.append(f"{label}: malformed entry")
                continue
            if check(a, ea, label) and check(b, eb, label):
                touch(a, ea, label)
                touch(b, eb, label)

        for idx, c in enumerate(self.data.get("connects_x", [])):
            label = f"connects_x[{idx}]"
            try:
                a, ea, b, eb = c[0], c[1], c[2], c[3]
            except Exception:
                errs.append(f"{label}: malformed entry")
                continue
            if check(a, ea, label) and check(b, eb, label):
                touch(a, ea, label)
                touch(b, eb, label)

        for idx, d in enumerate(self.data.get("doors", [])):
            label = f"doors[{idx}]"
            try:
                a, ea, b, eb = d.get("a"), d.get("ea"), d.get("b"), d.get("eb")
            except Exception:
                errs.append(f"{label}: malformed entry")
                continue
            if check(a, ea, label) and check(b, eb, label):
                touch(a, ea, label)
                touch(b, eb, label)

        for (ri, ei), labels in used.items():
            uniq = sorted(set(labels))
            if len(uniq) > 1:
                errs.append(
                    f"edge room{ri}#{ei} used by multiple connections: {', '.join(uniq)}"
                )

        self.last_errors = errs
        return errs

    # -- geometry helpers -----------------------------------------------

    def edge_endpoints(self, ri: int, ei: int):
        verts = self.data["rooms"][ri]["verts"]
        n = len(verts)
        return verts[ei % n], verts[(ei + 1) % n]

    def edge_midpoint(self, ri: int, ei: int):
        a, b = self.edge_endpoints(ri, ei)
        return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)

    def edge_length(self, ri: int, ei: int) -> float:
        a, b = self.edge_endpoints(ri, ei)
        return math.hypot(b[0] - a[0], b[1] - a[1])

    # -- room ops -----------------------------------------------------

    def add_rect_room(self, x: float, y: float, w: float, h: float) -> int:
        verts = [[x, y], [x, y + h], [x + w, y + h], [x + w, y]]
        return self._add_room(verts)

    def add_poly_room(self, verts) -> int:
        return self._add_room(canonical_winding([list(v) for v in verts]))

    def _add_room(self, verts) -> int:
        self.snapshot()
        self.data.setdefault("rooms", []).append(
            {"verts": [list(v) for v in verts], "entities": []}
        )
        return len(self.data["rooms"]) - 1

    def move_room(self, ri: int, dx: float, dy: float) -> None:
        self.snapshot()
        self._translate_room(ri, dx, dy)

    def _translate_room(self, ri: int, dx: float, dy: float) -> None:
        room = self.data["rooms"][ri]
        room["verts"] = [[v[0] + dx, v[1] + dy] for v in room["verts"]]
        for e in room.get("entities", []):
            e["pos"] = [e["pos"][0] + dx, e["pos"][1] + dy]
        player = self.data.get("player")
        if player and player.get("room") == ri:
            player["pos"] = [player["pos"][0] + dx, player["pos"][1] + dy]
        exit_ = self.data.get("exit")
        if exit_ and exit_.get("room") == ri:
            exit_["pos"] = [exit_["pos"][0] + dx, exit_["pos"][1] + dy]
        for t in self.data.get("lore", {}).get("terminals", []):
            if t.get("room") == ri:
                t["pos"] = [t["pos"][0] + dx, t["pos"][1] + dy]

    def set_vertex(self, ri: int, vi: int, x: float, y: float) -> None:
        self.snapshot()
        self.data["rooms"][ri]["verts"][vi] = [x, y]

    def delete_vertex(self, ri: int, vi: int) -> bool:
        rooms = self.data.get("rooms", [])
        if not (0 <= ri < len(rooms)):
            return False
        verts = rooms[ri]["verts"]
        n = len(verts)
        if n <= 3 or not (0 <= vi < n):
            return False  # never drop a room below a triangle
        self.snapshot()
        mapping = _vertex_delete_edge_map(n, vi)
        del verts[vi]

        def fix(room_field, edge_field):
            if room_field != ri:
                return edge_field
            return mapping.get(edge_field)

        new_connects = []
        for c in self.data.get("connects", []):
            try:
                a, ea, b, eb = c[0], c[1], c[2], c[3]
            except Exception:
                continue
            nea, neb = fix(a, ea), fix(b, eb)
            if nea is None or neb is None:
                continue
            new_connects.append([a, nea, b, neb])
        self.data["connects"] = new_connects

        new_cx = []
        for c in self.data.get("connects_x", []):
            try:
                a, ea, b, eb, m = c[0], c[1], c[2], c[3], c[4]
            except Exception:
                continue
            nea, neb = fix(a, ea), fix(b, eb)
            if nea is None or neb is None:
                continue
            new_cx.append([a, nea, b, neb, m])
        self.data["connects_x"] = new_cx

        new_doors = []
        for d in self.data.get("doors", []):
            a, ea, b, eb = d.get("a"), d.get("ea"), d.get("b"), d.get("eb")
            nea, neb = fix(a, ea), fix(b, eb)
            if nea is None or neb is None:
                continue
            nd = dict(d)
            nd["ea"], nd["eb"] = nea, neb
            new_doors.append(nd)
        self.data["doors"] = new_doors

        self.selection = None
        return True

    def delete_room(self, ri: int) -> None:
        rooms = self.data.get("rooms", [])
        if not (0 <= ri < len(rooms)):
            return
        self.snapshot()
        del rooms[ri]

        def remap(idx):
            if idx is None:
                return None
            if idx == ri:
                return None
            return idx - 1 if idx > ri else idx

        new_connects = []
        for c in self.data.get("connects", []):
            try:
                a, ea, b, eb = c[0], c[1], c[2], c[3]
            except Exception:
                continue
            na, nb = remap(a), remap(b)
            if na is None or nb is None:
                continue
            new_connects.append([na, ea, nb, eb])
        self.data["connects"] = new_connects

        new_cx = []
        for c in self.data.get("connects_x", []):
            try:
                a, ea, b, eb, m = c[0], c[1], c[2], c[3], c[4]
            except Exception:
                continue
            na, nb = remap(a), remap(b)
            if na is None or nb is None:
                continue
            new_cx.append([na, ea, nb, eb, m])
        self.data["connects_x"] = new_cx

        new_doors = []
        for d in self.data.get("doors", []):
            na, nb = remap(d.get("a")), remap(d.get("b"))
            if na is None or nb is None:
                continue
            nd = dict(d)
            nd["a"], nd["b"] = na, nb
            new_doors.append(nd)
        self.data["doors"] = new_doors

        player = self.data.get("player")
        if player:
            nr = remap(player.get("room"))
            self.data["player"] = None if nr is None else dict(player, room=nr)

        exit_ = self.data.get("exit")
        if exit_:
            nr = remap(exit_.get("room"))
            self.data["exit"] = None if nr is None else dict(exit_, room=nr)

        lore = self.data.setdefault("lore", {"intro": "", "radio": [], "terminals": []})
        new_terms = []
        for t in lore.get("terminals", []):
            nr = remap(t.get("room"))
            if nr is None:
                continue
            new_terms.append(dict(t, room=nr))
        lore["terminals"] = new_terms

        new_radio = []
        for r in lore.get("radio", []):
            trig = r.get("trigger", "")
            m = _ENTER_ROOM_RE.match(trig)
            if m:
                nr = remap(int(m.group(1)))
                if nr is None:
                    continue
                r = dict(r, trigger=f"enter_room:{nr}")
            new_radio.append(r)
        lore["radio"] = new_radio

        self.selection = None

    # -- entity ops -----------------------------------------------------

    def add_entity(self, ri: int, type_: str, x: float, y: float, props: dict | None = None) -> int:
        if type_ not in ROOM_ENTITY_TYPES:
            raise ValueError(f"unknown room-entity type {type_!r}")
        self.snapshot()
        ent = {"type": type_, "pos": [x, y]}
        if props:
            ent["props"] = dict(props)
        self.data["rooms"][ri]["entities"].append(ent)
        return len(self.data["rooms"][ri]["entities"]) - 1

    def move_entity(self, ri: int, ei: int, x: float, y: float) -> None:
        self.snapshot()
        self.data["rooms"][ri]["entities"][ei]["pos"] = [x, y]

    def delete_entity(self, ri: int, ei: int) -> None:
        self.snapshot()
        del self.data["rooms"][ri]["entities"][ei]

    def set_player(self, ri: int, x: float, y: float) -> None:
        self.snapshot()
        self.data["player"] = {"room": ri, "pos": [x, y]}

    def set_exit(self, ri: int, x: float, y: float) -> None:
        self.snapshot()
        prev = self.data.get("exit") or {}
        ex = {"room": ri, "pos": [x, y]}
        if prev.get("key"):
            ex["key"] = prev["key"]
        if prev.get("gate_kind"):
            ex["gate_kind"] = prev["gate_kind"]
        self.data["exit"] = ex

    def set_exit_key(self, key: str) -> None:
        self.snapshot()
        ex = self.data.get("exit")
        if not ex:
            return
        if key:
            ex["key"] = key
        else:
            ex.pop("key", None)

    def set_exit_gate_kind(self, kind: str) -> None:
        self.snapshot()
        ex = self.data.get("exit")
        if not ex:
            return
        if kind:
            ex["gate_kind"] = kind
        else:
            ex.pop("gate_kind", None)

    def add_terminal(self, ri: int, x: float, y: float, text: str) -> int:
        self.snapshot()
        lore = self.data.setdefault("lore", {"intro": "", "radio": [], "terminals": []})
        lore.setdefault("terminals", []).append({"room": ri, "pos": [x, y], "text": text})
        return len(lore["terminals"]) - 1

    def move_terminal(self, ti: int, x: float, y: float) -> None:
        self.snapshot()
        self.data["lore"]["terminals"][ti]["pos"] = [x, y]

    def delete_terminal(self, ti: int) -> None:
        self.snapshot()
        del self.data["lore"]["terminals"][ti]

    def set_terminal_text(self, ti: int, text: str) -> None:
        self.snapshot()
        self.data["lore"]["terminals"][ti]["text"] = text

    # -- connection ops -----------------------------------------------------

    def connect_edges(self, ra: int, ea: int, rb: int, eb: int) -> None:
        """Same edge twice (ra==rb and ea==eb) is a deliberate self/mirror
        connect -- matches shipped levels (e.g. l06.json [2,1,2,1])."""
        self.snapshot()
        self.data.setdefault("connects", []).append([ra, ea, rb, eb])

    def connect_door(self, ra: int, ea: int, rb: int, eb: int, key: str) -> None:
        self.snapshot()
        self.data.setdefault("doors", []).append(
            {"a": ra, "ea": ea, "b": rb, "eb": eb, "key": key}
        )

    def delete_connection(self, kind: str, idx: int) -> None:
        self.snapshot()
        field = {"connect": "connects", "connect_x": "connects_x", "door": "doors"}[kind]
        lst = self.data.get(field, [])
        if 0 <= idx < len(lst):
            del lst[idx]

    # -- picking / selection -----------------------------------------------------

    def nearest_edge(self, x: float, y: float, tol: float):
        """Nearest raw polygon edge (any room), for connect-mode picking --
        distinct from nearest_connection, which finds existing connection
        arcs rather than unclaimed edges."""
        best = None
        bd = tol * tol
        for ri, room in enumerate(self.data.get("rooms", [])):
            verts = room.get("verts", [])
            n = len(verts)
            for ei in range(n):
                a, b = verts[ei], verts[(ei + 1) % n]
                d = _point_seg_dist2(x, y, a[0], a[1], b[0], b[1])
                if d <= bd:
                    bd = d
                    best = (ri, ei)
        return best

    def nearest_room(self, x: float, y: float):
        hit = None
        for ri, room in enumerate(self.data.get("rooms", [])):
            if _point_in_poly(x, y, room.get("verts", [])):
                hit = ri  # last (topmost-drawn) room containing the point wins
        return hit

    def nearest_vertex(self, x: float, y: float, tol: float):
        best = None
        bd = tol * tol
        for ri, room in enumerate(self.data.get("rooms", [])):
            for vi, v in enumerate(room.get("verts", [])):
                d = (v[0] - x) ** 2 + (v[1] - y) ** 2
                if d <= bd:
                    bd = d
                    best = (ri, vi)
        return best

    def nearest_entity_like(self, x: float, y: float, tol: float):
        best = None
        bd = tol * tol
        for ri, room in enumerate(self.data.get("rooms", [])):
            for ei, e in enumerate(room.get("entities", [])):
                p = e.get("pos", [0, 0])
                d = (p[0] - x) ** 2 + (p[1] - y) ** 2
                if d <= bd:
                    bd = d
                    best = ("entity", ri, ei)
        player = self.data.get("player")
        if player:
            p = player.get("pos", [0, 0])
            d = (p[0] - x) ** 2 + (p[1] - y) ** 2
            if d <= bd:
                bd = d
                best = ("player",)
        exit_ = self.data.get("exit")
        if exit_:
            p = exit_.get("pos", [0, 0])
            d = (p[0] - x) ** 2 + (p[1] - y) ** 2
            if d <= bd:
                bd = d
                best = ("exit",)
        for ti, t in enumerate(self.data.get("lore", {}).get("terminals", [])):
            p = t.get("pos", [0, 0])
            d = (p[0] - x) ** 2 + (p[1] - y) ** 2
            if d <= bd:
                bd = d
                best = ("terminal", ti)
        return best

    def nearest_connection(self, x: float, y: float, tol: float):
        state = {"best": None, "bd": tol * tol}

        def consider(kind, idx, ri, ei, rj, ej):
            try:
                mx1, my1 = self.edge_midpoint(ri, ei)
                mx2, my2 = self.edge_midpoint(rj, ej)
            except (IndexError, TypeError, KeyError):
                return
            d = _point_seg_dist2(x, y, mx1, my1, mx2, my2)
            if d <= state["bd"]:
                state["bd"] = d
                state["best"] = ("connect", kind, idx)

        for idx, c in enumerate(self.data.get("connects", [])):
            try:
                consider("connect", idx, c[0], c[1], c[2], c[3])
            except Exception:
                continue
        for idx, c in enumerate(self.data.get("connects_x", [])):
            try:
                consider("connect_x", idx, c[0], c[1], c[2], c[3])
            except Exception:
                continue
        for idx, d in enumerate(self.data.get("doors", [])):
            try:
                consider("door", idx, d.get("a"), d.get("ea"), d.get("b"), d.get("eb"))
            except Exception:
                continue
        return state["best"]

    def pick(self, x: float, y: float, tol: float):
        v = self.nearest_vertex(x, y, tol)
        if v is not None:
            return ("vertex", v[0], v[1])
        e = self.nearest_entity_like(x, y, tol)
        if e is not None:
            return e
        c = self.nearest_connection(x, y, tol)
        if c is not None:
            return c
        r = self.nearest_room(x, y)
        if r is not None:
            return ("room", r)
        return None

    def delete_selected(self) -> bool:
        sel = self.selection
        if sel is None:
            return False
        kind = sel[0]
        if kind == "room":
            self.delete_room(sel[1])
        elif kind == "vertex":
            self.delete_vertex(sel[1], sel[2])
        elif kind == "entity":
            self.delete_entity(sel[1], sel[2])
        elif kind == "player":
            self.snapshot()
            self.data["player"] = None
        elif kind == "exit":
            self.snapshot()
            self.data["exit"] = None
        elif kind == "terminal":
            self.delete_terminal(sel[1])
        elif kind == "connect":
            self.delete_connection(sel[1], sel[2])
        else:
            return False
        self.selection = None
        return True
