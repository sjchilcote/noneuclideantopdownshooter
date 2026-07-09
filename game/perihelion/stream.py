"""One seamless world: campaign levels stream into a single live sim.

"Levels" are chunks of rooms lazy-loaded as the player approaches. Chunk k's
exit pad becomes a carved doorway into a transit spine (two long corridor
rooms, kind "transit"); entering the spine loads chunk k+1, carves its entry
doorway near the authored player spawn, and joins the worlds. The far side
of every spine is a fresh security zone: held keys clear on arrival.

Death reprints the frame at the current chunk's entry with the state it was
first entered with — the seed keeps its checkpoints. The final chunk keeps
its real exit pad, which ends the campaign.
"""

from __future__ import annotations

import math

from .levels import Level, load_level
from .sim import GameSession

SPINE_LEN = 260.0
SPINE_W = 70.0
DOOR_W = 70.0


class WorldStreamer:
    def __init__(self, session: GameSession, level_paths: list[str],
                 start_chunk: int = 0):
        self.session = session
        self.paths = list(level_paths)
        self.start_chunk = start_chunk
        # chunk records: {offset, n_rooms, level, entry_room, entry_pos,
        #                 spine_rooms (tuple | None), loaded_next}
        self.chunks: list[dict] = []
        self.current = 0
        self.entry_states: dict[int, dict] = {}
        self._last_room = session.player_room()
        self.on_chunk_entered = None  # callback(chunk_idx, name)
        self.on_campaign_complete = None

        first = session.level  # session was constructed with chunk start_chunk
        rec = dict(offset=0, n_rooms=len(first.room_verts), level=first,
                   entry_room=first.player_room, entry_pos=first.player_pos,
                   spine_rooms=None, loaded_next=False)
        self.chunks.append(rec)
        self.entry_states[0] = self._snapshot_state()
        session.exit_enabled = self._is_final(0)
        if self._is_final(0):
            self._point_exit_at(0)
        else:
            self._build_spine(0)
            self._retarget()

    # ------------------------------------------------------------------

    def _is_final(self, chunk_idx: int) -> bool:
        return self.start_chunk + chunk_idx >= len(self.paths) - 1

    def _retarget(self) -> None:
        """Keep the (disabled) exit marker pointing at the way forward so
        route queries — and bots — always have a heading: the spine while
        the next chunk is unloaded, its entry room once it exists."""
        s = self.session
        cur = self.chunks[self.current]
        if self._is_final(self.current):
            return
        if self.current + 1 < len(self.chunks):
            nxt = self.chunks[self.current + 1]
            s.exit_room = nxt["entry_room"] + nxt["offset"]
            s.exit_pos = nxt["entry_pos"]
        elif cur["spine_rooms"]:
            s.exit_room = cur["spine_rooms"][1]
            s.exit_pos = (0.0, 0.0)

    def _point_exit_at(self, chunk_idx: int) -> None:
        s = self.session
        c = self.chunks[chunk_idx]
        lvl = c["level"]
        s.exit_room = lvl.exit_room + c["offset"]
        s.exit_pos = lvl.exit_pos
        s.level.exit_key = lvl.exit_key
        s.level.exit_gate_kind = lvl.exit_gate_kind
        # the gate only counts guardians of THIS chunk; stragglers from
        # earlier decks hold no doors here
        s.exit_gate_rooms = (c["offset"], c["offset"] + c["n_rooms"])

    def _snapshot_state(self) -> dict:
        s = self.session
        return dict(hp=max(int(s.hp), 40), ammo=dict(s.ammo),
                    weapons=list(s.weapons), weapon=s.weapon,
                    holes=s.holes, cloister=s.cloister is not None)

    def _restore_state(self, st: dict) -> None:
        s = self.session
        s.hp = st["hp"]
        s.ammo = dict(st["ammo"])
        s.weapons = list(st["weapons"])
        s.weapon = st["weapon"]
        s.holes = st["holes"]
        s.keys = set()
        s.tau_charge = 0
        s.hole_mark = None

    def room_chunk(self, room: int) -> int:
        for i, c in enumerate(self.chunks):
            if c["offset"] <= room < c["offset"] + c["n_rooms"]:
                return i
            if c["spine_rooms"] and room in c["spine_rooms"]:
                return i
        return self.current

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def _carve_in_chunk(self, chunk_rec, room: int, pos) -> tuple[int, int]:
        """Carve a doorway near (room, pos); if that room has no carvable
        wall (portal-saturated rooms exist: the Fold's core, the tesseract),
        BFS outward within the chunk to the nearest room that does."""
        s = self.session
        lo = chunk_rec["offset"]
        hi = lo + chunk_rec["n_rooms"]
        mid = s.carve_door(room, pos, DOOR_W)
        if mid is not None:
            return room, mid
        seen = {room}
        frontier = [room]
        while frontier:
            nxt_frontier = []
            for r in frontier:
                for p in s.sim.room_portals(r):
                    if p is None:
                        continue
                    tr = p[0]
                    if tr in seen or not (lo <= tr < hi):
                        continue
                    seen.add(tr)
                    mid = s.carve_door(tr, (0.0, 0.0), DOOR_W)
                    if mid is not None:
                        return tr, mid
                    nxt_frontier.append(tr)
            frontier = nxt_frontier
        raise RuntimeError(f"chunk at offset {lo}: no carvable wall anywhere")

    def _build_spine(self, chunk_idx: int) -> None:
        """Carve a doorway near chunk k's exit pad into a two-room transit
        spine. Its far end stays sealed until the next chunk loads."""
        s = self.session
        c = self.chunks[chunk_idx]
        lvl: Level = c["level"]
        exit_room, mid = self._carve_in_chunk(
            c, lvl.exit_room + c["offset"], lvl.exit_pos)
        spine_a = s.sim.add_room([(0.0, 0.0), (0.0, SPINE_W),
                                  (SPINE_LEN, SPINE_W), (SPINE_LEN, 0.0)])
        spine_b = s.sim.add_room([(0.0, 0.0), (0.0, SPINE_W),
                                  (SPINE_LEN, SPINE_W), (SPINE_LEN, 0.0)])
        # spine rect edges: 0 = west end (len W), 2 = east end
        s.sim.connect(exit_room, mid, spine_a, 0)
        s.sim.connect(spine_a, 2, spine_b, 0)
        c["spine_rooms"] = (spine_a, spine_b)
        s.level.room_seeds.extend([spine_a * 7919 + 13, spine_b * 7919 + 13])
        s.level.room_kinds.extend(["transit", "transit"])
        s.level.room_verts.extend([[(-130.0, -35.0), (-130.0, 35.0),
                                    (130.0, 35.0), (130.0, -35.0)]] * 2)
        s.level.room_centroids.extend([(0.0, 0.0), (0.0, 0.0)])
        # the tight-beam relay: reading it plays the between-chunk exchange
        conv_idx = self.start_chunk + chunk_idx
        s.terminals.append(dict(room=spine_a, pos=(0.0, 0.0),
                                text=f"__CONV__{conv_idx}", read=False))

    def _load_next(self, chunk_idx: int) -> None:
        """The player entered chunk k's spine: stream chunk k+1 and join."""
        c = self.chunks[chunk_idx]
        if c["loaded_next"] or self._is_final(chunk_idx):
            return
        c["loaded_next"] = True
        s = self.session
        path = self.paths[self.start_chunk + chunk_idx + 1]
        nxt = load_level(path)
        offset = s.append_chunk(nxt)
        rec = dict(offset=offset, n_rooms=len(nxt.room_verts), level=nxt,
                   entry_room=nxt.player_room, entry_pos=nxt.player_pos,
                   spine_rooms=None, loaded_next=False)
        entry_room, mid = self._carve_in_chunk(
            rec, nxt.player_room + offset, nxt.player_pos)
        rec["entry_room"] = entry_room - offset
        rec["entry_pos"] = (0.0, 0.0) if entry_room != nxt.player_room + offset \
            else nxt.player_pos
        spine_b = c["spine_rooms"][1]
        s.sim.connect(spine_b, 2, entry_room, mid)
        self.chunks.append(rec)
        if not self._is_final(chunk_idx + 1):
            self._build_spine(chunk_idx + 1)

    # ------------------------------------------------------------------
    # per-tick
    # ------------------------------------------------------------------

    def tick(self) -> None:
        s = self.session
        room = s.player_room()
        if room == self._last_room:
            return
        self._last_room = room
        cur = self.chunks[self.current]
        # entering the spine streams the next chunk in
        if cur["spine_rooms"] and room in cur["spine_rooms"]:
            self._load_next(self.current)
            self._retarget()
            return
        # crossing into the next chunk's rooms: arrival
        if self.current + 1 < len(self.chunks):
            nxt = self.chunks[self.current + 1]
            if nxt["offset"] <= room < nxt["offset"] + nxt["n_rooms"]:
                self.current += 1
                self.entry_states[self.current] = self._snapshot_state()
                s.keys = set()  # a new security zone honors no old badges
                s.exit_enabled = self._is_final(self.current)
                if s.exit_enabled:
                    self._point_exit_at(self.current)
                else:
                    self._retarget()
                name = nxt["level"].name
                s.fx.append(("locname", name))
                amb = nxt["level"].ambience
                s.fx.append(("ambience", amb))
                if self.on_chunk_entered:
                    self.on_chunk_entered(
                        self.start_chunk + self.current, name)

    # ------------------------------------------------------------------
    # death
    # ------------------------------------------------------------------

    def respawn(self) -> None:
        """The seed prints a fresh frame at the current chunk's entry with
        the state it was first entered with. The chunk's dead rise again;
        its unclaimed supplies are restocked."""
        s = self.session
        c = self.chunks[self.current]
        lo, hi = c["offset"], c["offset"] + c["n_rooms"]
        for eid in [e for e in s.bullets]:
            s.sim.remove(eid)
        s.bullets.clear()
        for eid in [e for e, rec in s.enemies.items()
                    if lo <= s.sim.get_room(e) < hi]:
            s.sim.remove(eid)
            s.enemies.pop(eid, None)
        for eid in [e for e, rec in s.pickups.items()
                    if lo <= s.sim.get_room(e) < hi]:
            s.sim.remove(eid)
            s.pickups.pop(eid, None)
        lvl: Level = c["level"]
        for room, spec in lvl.entities:
            s._spawn_from_spec(room + c["offset"], spec)
        # doors of this chunk re-lock only if their key is re-collectable;
        # simpler and kinder: opened doors stay open.
        self._restore_state(self.entry_states[self.current])
        entry_room = c["entry_room"] + c["offset"]
        px, py = c["entry_pos"]
        s.sim.set_pos(s.pid, px, py)
        # engine set_pos does not move room membership; re-seat via a
        # remove/spawn would lose the id, so use the sim's own transfer:
        if s.sim.get_room(s.pid) != entry_room:
            self._reseat_player(entry_room, (px, py))
        s.sim.set_vel(s.pid, 0.0, 0.0)
        s.dead = False
        s.freeze = 0
        s.metrics["deaths"] += 1
        import necore
        s.cam = necore.mat_mul(
            necore.mat_mul(
                necore.mat_translate(s.screen_w / 2, s.screen_h / 2),
                necore.mat_scale(s.zoom, s.zoom)),
            necore.mat_translate(-px, -py))
        s.fx.append(("locname", lvl.name))

    def _reseat_player(self, room: int, pos) -> None:
        """Move the player's engine entity to another room."""
        s = self.session
        import necore
        old = s.pid
        st = s.sim.get(old)
        s.sim.remove(old)
        s.pid = s.sim.spawn(room, pos[0], pos[1], 6.5, 1.2, 0)
        s.sim.set_props(s.pid, rest_wall=0.0, rest_ent=0.05, max_substep=6.0)
        s.sim.set_dir(s.pid, st[5], st[6])
