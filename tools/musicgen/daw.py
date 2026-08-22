"""PERIHELION session DAW — the winning run as a scrub-able project.

    uv run python tools/musicgen/daw.py                # the winning session
    uv run python tools/musicgen/daw.py REC_DIR        # any taps recording

Opens gauntlet_winning_session_v1 (649s, full 4-boss clear) as a DAW
project window: video monitor, transport, section/bank ruler, the three
value automation curves, one track strip per lane with its gain
automation and clip content, and event markers (jumps, risers, slams,
stings, stabs, death halts).

The mix is rebuilt from the recording's decision log by the SAME
offline mixer that renders the shipped videos, reading the SAME bank
folders the game reads — what you hear is what the game plays.

REPLACE-AND-HEAR: the tool watches every bank folder this session
uses. Overwrite any stem file (drop a new prayer.wav into the bank
folder) and the mix rebuilds in ~1-2s at the same playhead — scrub
back, listen again, iterate. WAV beats OGG on the same name in the
same folder, so dropping `prayer.wav` next to `prayer.ogg` auditions
your replacement without deleting the original.

Press ? in the app for the full key/legend overlay. Highlights:
  SPACE play/pause · click/drag scrub · arrows bar (SHIFT 10s)
  , . markers · UP/DOWN sections · + - zoom · drag ruler = selection
  (loops + B bounces; a seek clears it)
  M/S mute/solo · A hear previous mix · G/click clock go-to · C copy
  B bounce · R full reload/retry · ESC close overlay / quit
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import queue
import subprocess
import sys
import threading
import time
import wave as wavemod
from collections import deque
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/playtest"))
sys.path.insert(0, str(ROOT / "tools/musicgen"))
import mkvideo as MK                                    # noqa: E402
import mgui                                             # noqa: E402
from mgui import Rect                                   # noqa: E402
from perihelion import fb2d, text, uievent              # noqa: E402
from perihelion.audio import EngineChannel, EngineSound  # noqa: E402

DEFAULT_REC = ROOT / "out/winning_session_v1_rec"
DEFAULT_VIDEO = ROOT / "out/gauntlet_winning_session_v1.mp4"

RATE = MK.RATE
CHUNK_S = 0.1
CHUNK = int(CHUNK_S * RATE)
SETTLE_S = 0.6          # a file must sit still this long before rebuild

LANES = ["holy", "bed", "drums", "wall", "groove", "lead", "lead2",
         "bass", "boss"]
FX = "fx"          # riser / riser_half / sting / stab as one mute group
LANE_COL = {
    "holy": (212, 175, 96), "bed": (110, 110, 140),
    "drums": (200, 120, 70), "wall": (205, 85, 85),
    "groove": (220, 160, 90), "lead": (120, 200, 160),
    "lead2": (90, 160, 130), "bass": (140, 110, 200),
    "boss": (230, 70, 110), FX: (170, 170, 170),
}
SECT_COL = {
    "vigil": (52, 84, 120), "ritual": (84, 62, 130),
    "entry": (130, 112, 48), "develop": (140, 84, 40),
    "peak": (150, 42, 42), "outro": (48, 105, 70),
    "rebuild": (55, 100, 100),
}
VAL_COL = ((120, 170, 220), (250, 140, 40), (255, 60, 60))  # P/C/S
ONE_SHOTS = ("riser", "riser_half", "sting", "stab", "prayer_tail")
AUDIOISH = (".aiff", ".aif", ".mp3", ".flac", ".m4a", ".opus", ".aac")
STATUS_COL = {"ok": (140, 220, 140), "busy": (240, 200, 100),
              "warn": (255, 170, 80), "err": (255, 90, 90)}


class StemContractError(Exception):
    """A stem file the game/mixer contract cannot accept."""


def _bank_valid(meta) -> bool:
    """THE bank.json schema: bpm, bars, sections. One schema, no
    partial acceptance — an incomplete file is data to be fixed, and
    the gate says so instead of letting a half-described bank in."""
    try:
        return float(meta["bpm"]) > 0 and int(meta["bars"]) > 0 \
            and isinstance(meta["sections"], list) \
            and len(meta["sections"]) > 0
    except (KeyError, TypeError, ValueError):
        return False


# cross-rebuild stem cache keyed by (path, mtime, size): a rebuild
# after one replaced file re-decodes ONLY that file. Size is in the
# key because a timestamp-preserving restore (cp -p, git checkout)
# can collide with a cached mtime and replay stale audio.
_stem_cache: dict = {}
_stem_lock = threading.Lock()
_orig_load_stem = MK._load_stem


def _describe_format(info, suffix: str) -> str:
    bits = {"PCM_16": "16-bit", "PCM_24": "24-bit", "PCM_32": "32-bit",
            "FLOAT": "32-bit float", "DOUBLE": "64-bit float",
            "PCM_U8": "8-bit"}.get(info.subtype, info.subtype)
    return f"{bits} {info.samplerate / 1000:g} kHz"


def _cached_load_stem(p):
    with _stem_lock:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        v = _stem_cache.get(key)
        if v is not None:
            return v
        try:
            info = sf.info(str(p))
        except Exception as exc:
            raise StemContractError(
                f"{p.name}: unreadable ({exc}) — re-export it") from exc
        if info.samplerate != RATE:
            raise StemContractError(
                f"{p.name} is {_describe_format(info, p.suffix)} — "
                f"export 16-bit 44.1 kHz WAV")
        if p.suffix.lower() == ".wav" and info.subtype != "PCM_16":
            raise StemContractError(
                f"{p.name} is {_describe_format(info, p.suffix)} — "
                f"export 16-bit 44.1 kHz WAV")
        v = _orig_load_stem(p)
        for k in [k for k in _stem_cache if k[0] == key[0]]:
            del _stem_cache[k]
        _stem_cache[key] = v
        return v


MK._load_stem = _cached_load_stem


def _apply_mutes(events: list, muted: set, solo: set) -> list:
    """Mute/solo happens in the DECISION LOG, not the mixer: a muted
    lane's bar entries are rewritten to silence and the mixer renders
    them exactly as if the engine had never played that lane.

    One rule is the single source of truth for audio AND display
    (App._is_muted mirrors it): a lane is silenced iff it is muted, or
    a solo exists and the lane is not in it. Mute wins over solo on
    the same lane, and unknown lane names cannot leak through a solo.
    """
    if not muted and not solo:
        return events

    def dead(ln):
        return ln in muted or (solo and ln not in solo)

    out = []
    for e in events:
        k = e["kind"]
        if k in ("music_riser", "music_riser2", "music_sting",
                 "music_stab") and dead(FX):
            continue
        if k == "music_bar":
            parts = e["name"].split("|")
            new = [parts[0]]
            for lane in parts[1:]:
                ln = lane.rsplit(":", 2)[0]
                new.append(f"{ln}:silence:0.000" if dead(ln) else lane)
            e = dict(e, name="|".join(new))
        out.append(e)
    return out


class Project:
    """The recording, parsed once for display."""

    def __init__(self, rec: Path, use: str | None = None):
        evfile = rec / "events.jsonl" if rec.is_dir() else rec
        try:
            self.events = [json.loads(l) for l in
                           evfile.read_text().splitlines() if l.strip()]
        except FileNotFoundError:
            raise SystemExit(f"recording not found: {evfile}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SystemExit(f"can't read {evfile}: {exc}")
        # the RECORDED bank of every pass, before any override — the
        # picker names these as "(as recorded: …)"
        self.orig_banks = [e["name"] for e in self.events
                           if e["kind"] == "music_bank"]
        if use:
            # audition banks under this session's decisions (the mixer
            # wraps form positions by each bank's own bar count).
            # str = every pass (CLI --use); dict {pass_idx: name} =
            # per-pass overrides, so transitions in and out of a
            # replaced pass stay auditionable against its neighbors.
            per_pass = None if isinstance(use, str) \
                else {int(k): v for k, v in use.items()}
            for nm in ([use] if per_pass is None
                       else set(per_pass.values())):
                d = MK._resolve_bank(nm)
                ok = False
                if d is not None:
                    try:
                        ok = _bank_valid(json.loads(
                            (d / "bank.json").read_text()))
                    except Exception:
                        ok = False
                if not ok:
                    raise SystemExit(
                        f"--use {nm}: not a usable bank (needs "
                        f"bank.json with bpm + bars + sections) "
                        f"under {[str(r) for r in MK.MUSIC_ROOTS]}")
            out, bi = [], -1
            for e in self.events:
                if e["kind"] == "music_bank":
                    bi += 1
                    if per_pass is None:
                        e = dict(e, name=use)
                    elif bi in per_pass:
                        e = dict(e, name=per_pass[bi])
                out.append(e)
            self.events = out
        self.dur = max(e["t"] for e in self.events) + 2.0
        self.bars = []      # (t, form_idx, {lane: (key, gain, fade)})
        for e in self.events:
            if e["kind"] != "music_bar":
                continue
            parts = e["name"].split("|")
            lanes = {}
            for lane in parts[1:]:
                ln, key, g = lane.rsplit(":", 2)
                fade = key.endswith("~f")   # farewell bar: ramps to 0
                if fade:
                    key = key[:-2]
                key = key.partition("@")[0]  # free-running voice index
                lanes[ln] = (key, float(g), fade)
            self.bars.append((e["t"], int(parts[0]), lanes))
        self.vals = [(e["t"],
                      tuple(float(v) for v in e["name"].split(",")))
                     for e in self.events if e["kind"] == "music_valslp"]
        bank_evs = [e for e in self.events if e["kind"] == "music_bank"]
        self.banks = []         # (t0, t1, name, meta|None, dir|None)
        for i, e in enumerate(bank_evs):
            t1 = bank_evs[i + 1]["t"] if i + 1 < len(bank_evs) \
                else self.dur
            d = MK._resolve_bank(e["name"])
            meta = None
            if d is not None:
                try:
                    meta = json.loads((d / "bank.json").read_text())
                except Exception:
                    meta = None
                if meta is not None and not _bank_valid(meta):
                    meta = None     # health() names the reason in red
                if meta is None:
                    d = None
            self.banks.append((e["t"], t1, e["name"], meta, d))
        self.marks = [(e["t"], e["kind"], str(e["name"]))
                      for e in self.events
                      if e["kind"] in ("music_jump", "music_halt",
                                       "music_sting", "music_stab",
                                       "music_riser2")]
        r_on, prev = [], 0.0
        for e in self.events:
            if e["kind"] == "music_riser":
                v = float(e["name"])
                if v > 0.01 and prev <= 0.01:
                    r_on.append((e["t"], "music_riser", ""))
                prev = v
        self.marks += r_on
        ts = [b[0] for b in self.bars]
        self.bar_s = float(np.median(np.diff(ts))) if len(ts) > 2 else 2.18
        # death-halt spans: music stops DEAD until the next bar tap
        self.halts = []
        bar_ts = [b[0] for b in self.bars]
        for t, kind, _ in self.marks:
            if kind == "music_halt":
                nxt = next((bt for bt in bar_ts if bt > t), self.dur)
                self.halts.append((t, nxt))
        # riser strike envelopes: the one-shot swells from its onset
        # into a strike exactly 2 machine bars later
        self.riser_spans = []
        for t, kind, _ in self.marks:
            if kind == "music_riser":
                _, meta, _ = self.bank_at(t)
                bs = 240.0 / float(meta["bpm"]) if meta else self.bar_s
                self.riser_spans.append((t, t + 2.0 * bs))
        # bank-rotation crossfade windows: for ~2 bars after a switch
        # the OLD bank's fading continuation is ~half the audible mix
        self.xfades = []        # (t0, t1, old_title, new_title)
        for prev_b, cur_b in zip(self.banks, self.banks[1:]):
            om, nm = prev_b[3], cur_b[3]
            obs = 240.0 / float(om["bpm"]) if om else self.bar_s
            self.xfades.append(
                (cur_b[0], cur_b[0] + 2.0 * obs,
                 (om or {}).get("title", prev_b[2]),
                 (nm or {}).get("title", cur_b[2])))
        # section starts (incl. bank switches) for UP/DOWN navigation
        self.sect_starts = []
        prev_sect = None
        for bt, _, _ in self.bars:
            s = self.section_at(bt + 0.01)
            if s != prev_sect:
                self.sect_starts.append(bt)
                prev_sect = s
        # every stem key this session actually plays (base names) —
        # the watcher's "is this drop even audible?" reference
        self.played_keys = set()
        for _, _, lanes in self.bars:
            for key, g, _ in lanes.values():
                if key not in ("silence", "None"):
                    self.played_keys.add(key)
        kinds = {e["kind"] for e in self.events}
        if "music_riser" in kinds:
            self.played_keys.add("riser")
        if "music_riser2" in kinds:
            self.played_keys.add("riser_half")
        if "music_sting" in kinds:
            self.played_keys.add("sting")
        if "music_stab" in kinds:
            self.played_keys.add("stab")
        if "prayer" in self.played_keys:
            self.played_keys.add("prayer_tail")

    def bank_at(self, t):
        for t0, t1, name, meta, d in self.banks:
            if t0 <= t < t1:
                return name, meta, d
        if self.banks:
            return self.banks[-1][2], self.banks[-1][3], self.banks[-1][4]
        return None, None, None

    def bar_at(self, t):
        lo, hi = 0, len(self.bars) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.bars[mid][0] <= t:
                lo = mid
            else:
                hi = mid - 1
        return self.bars[lo] if self.bars else (0.0, 0, {})

    def section_at(self, t):
        _, meta, _ = self.bank_at(t)
        if not meta:
            return ""
        idx = self.bar_at(t)[1] % int(meta["bars"])
        for s, a, b in meta["sections"]:    # _bank_valid guarantees
            if a <= idx < b:                # sections exist wherever
                return s                    # a meta survives parse
        return ""

    def xfade_at(self, t):
        for t0, t1, old, new in self.xfades:
            if t0 <= t < t1:
                return old, new
        return None

    def watch_dirs(self):
        """Every folder whose files can change this mix — both music
        roots for each bank name, so a change to a SHADOWED copy can
        be flagged instead of silently ignored."""
        dirs = []
        for _, _, name, _, _ in self.banks:
            for root in MK.MUSIC_ROOTS:
                d = root / name
                # missing dirs stay in the watch list: a renamed bank
                # must be SEEN coming back (the scan skips them safely)
                if d not in dirs:
                    dirs.append(d)
        return dirs

    def health(self):
        """Per-bank contract warnings (wrong-length stems, missing
        banks) — cheap header reads only, recomputed every rebuild.
        Resolution is done FRESH here, not from parse-time caches: a
        bank renamed mid-session must go red on the next rebuild."""
        msgs = []
        seen = set()
        for _, _, name, _meta, _d in self.banks:
            if name in seen:
                continue
            seen.add(name)
            d = MK._resolve_bank(name)
            meta = None
            if d is not None:
                try:
                    meta = json.loads((d / "bank.json").read_text())
                except Exception:
                    d = None
            if meta is not None and not _bank_valid(meta):
                msgs.append((f"{name}: incomplete bank.json (needs "
                             f"bpm + bars + sections) — those spans "
                             f"play SILENCE", "err"))
                continue
            if meta is None or d is None:
                msgs.append((f"bank not found: {name} — those spans "
                             f"play SILENCE", "err"))
                continue
            n_bar = 240.0 / float(meta["bpm"]) * RATE
            n_form = n_bar * int(meta["bars"])
            for f in sorted(d.iterdir()):
                if f.suffix.lower() not in (".wav", ".ogg") or \
                        f.stem in ONE_SHOTS:
                    continue
                try:
                    frames = sf.info(str(f)).frames
                except Exception:
                    continue    # unreadable → render guard names it
                if abs(frames - n_form) > 0.005 * n_form:
                    have = frames / n_bar
                    msgs.append(
                        (f"{name}/{f.name} is ~{have:.1f} bars, form "
                         f"needs {meta['bars']} — later bars silent",
                         "warn"))
        return msgs


class Player:
    """Chunk-streamed playback with instant seek (the engine's own
    queue trick, pointed at the rendered session mix). The engine
    mixer is THREAD-BOUND (necore.AudioMixer is a thread-affine
    platform object), so one dedicated audio thread owns every mixer
    call; play/pause/seek/set_buffer marshal onto it SYNCHRONOUSLY,
    so callers still see failures immediately. A backend death
    (PipeWire restart, device unplug) sets .err and keeps the
    last-good playhead instead of killing the process. The idle side
    of the same thread advances the chunk queue, so a slow draw or a
    heavy render can never starve playback (P3.25)."""

    def __init__(self):
        self.err = None
        self._plock = threading.RLock()
        self.audio = None
        self.ch = None
        self.buf = None                # int16 (N, 2)
        self.playing = False
        self.t = 0.0
        self._idx = 0
        self._wall = 0.0
        self._sounds = (None, None)
        self._cmds = queue.Queue()
        self._audio_thread = threading.Thread(target=self._audio_loop,
                                              daemon=True)
        self._audio_thread.start()
        self._call(self._init_backend)

    # ---- the audio thread owns the mixer ------------------------------
    def _call(self, fn, *args):
        """Run fn on the audio thread and return its result (raising
        what it raised) — the mixer may only be touched there."""
        if threading.current_thread() is self._audio_thread:
            return fn(*args)
        done = threading.Event()
        box = {}
        self._cmds.put((fn, args, done, box))
        if not done.wait(30.0):
            raise RuntimeError(f"audio thread stalled on {fn.__name__}")
        if "exc" in box:
            raise box["exc"]
        return box.get("ret")

    def _audio_loop(self):
        while True:
            try:
                fn, args, done, box = self._cmds.get(timeout=0.03)
            except queue.Empty:
                try:
                    self._poll()
                except Exception as exc:
                    with self._plock:
                        self.err = f"{exc}"
                        self.playing = False
                continue
            try:
                box["ret"] = fn(*args)
            except BaseException as exc:  # marshal even panics back
                box["exc"] = exc
            done.set()

    def _init_backend(self):
        self.audio = mgui.Audio()      # created ON the audio thread
        if self.audio.mixer is None:
            self.ch = None
            self.err = "audio unavailable: no output device"
        else:
            self.ch = EngineChannel(self.audio, 0)

    def _free_sounds(self, sounds):
        for s in sounds:
            if s is not None:
                s.free()

    def end_t(self):
        return len(self.buf) / RATE if self.buf is not None else 0.0

    def set_buffer(self, buf):
        self._call(self._set_buffer, buf)

    def _set_buffer(self, buf):
        with self._plock:
            was = self.playing
            t = self.playhead()
            self.buf = buf
            self._seek(t)
            if was:
                self._play()

    def _chunk(self, i):
        a = i * CHUNK
        if self.buf is None or a >= len(self.buf):
            return None
        seg = self.buf[a:a + CHUNK]
        if len(seg) < CHUNK:
            seg = np.vstack([seg, np.zeros((CHUNK - len(seg), 2),
                                           np.int16)])
        return EngineSound.from_array(self.audio,
                                      np.ascontiguousarray(seg))

    def playhead(self):
        if not self.playing:
            return self.t
        return min(self._idx * CHUNK_S + (time.time() - self._wall),
                   self.end_t())

    def seek(self, t):
        self._call(self._seek, t)

    def _seek(self, t):
        with self._plock:
            self.t = max(0.0, min(t, self.end_t()))
            if self.playing:
                self._start()

    def _fail(self, exc):
        self.t = self._idx * CHUNK_S      # last-good playhead
        self.playing = False
        self.err = f"{exc}"

    def _start(self):
        try:
            self._idx = int(self.t / CHUNK_S)
            c0, c1 = self._chunk(self._idx), self._chunk(self._idx + 1)
            if c0 is None:
                self._pause()
                return
            self.ch.play(c0)
            if c1 is not None:
                self.ch.queue(c1)
            self._free_sounds(self._sounds)
            self._sounds = (c0, c1)
            self._wall = time.time()
        except (RuntimeError, AttributeError, OSError) as exc:
            self._fail(exc)

    def play(self):
        self._call(self._play)

    def _play(self):
        with self._plock:
            if self.buf is None or self.err:
                return
            if self.t >= self.end_t() - 0.05:
                self.t = 0.0            # SPACE at the end restarts
            self.playing = True
            self._start()

    def pause(self):
        self._call(self._pause)

    def _pause(self):
        with self._plock:
            self.t = self.playhead()
            self.playing = False
            try:
                if self.ch is not None:
                    self.ch.stop()
            except (RuntimeError, OSError) as exc:
                self._fail(exc)

    def _poll(self):
        with self._plock:
            if not self.playing or self.err:
                return
            try:
                if self.ch.get_queue() is None:
                    self._idx += 1
                    self._wall = time.time()
                    nxt = self._chunk(self._idx + 1)
                    if nxt is not None:
                        self.ch.queue(nxt)
                        old = self._sounds[0]
                        self._sounds = (self._sounds[1], nxt)
                        if old is not None:
                            old.free()
                    elif not self.ch.get_busy():
                        self._pause()
                        self.t = self.end_t()   # designed end state
            except (RuntimeError, OSError) as exc:
                self._fail(exc)

    def retry(self):
        """R after an audio failure: re-init the mixer backend."""
        return self._call(self._retry)

    def _retry(self):
        with self._plock:
            aud = mgui.Audio()          # fresh, ON the audio thread
            if aud.mixer is None:
                self.err = "audio unavailable: no output device"
                return False
            self.audio = aud
            self.ch = EngineChannel(aud, 0)
            self._sounds = (None, None)   # ids died with the old mixer
            self.err = None
            return True


class VideoPlayer:
    """REAL video playback for the monitor panes — not frame-grabbing.

    One persistent ffmpeg process decodes forward from the playhead
    and pipes raw frames; every draw presents the frame whose pts
    matches the audio clock. The shipped mp4 is natively 15fps and
    decodes ~12x realtime here, so playback is every-frame smooth,
    and seeks/scrubs simply restart the stream (rate-limited) and are
    on-frame in ~0.2s. Paused shows the exact playhead frame from the
    SAME pipeline — there is no separate still-extraction path.

    Honesty rules survive the rewrite: missing file / dead ffmpeg is
    one red line, not a silent non-feature; a regenerated mp4 restarts
    the stream (mtime watch); the presented frame carries its pts so
    staleness is visible (dim + lag badge)."""

    SIZE = (640, 360)               # decode size = lightbox size
    BUFFER = 30                     # ~2s ahead; the pipe throttles

    def __init__(self, video: Path | None):
        self.err = None
        self.size = self.SIZE
        self.video = None
        if video is not None:
            if video.exists():
                self.video = video
            else:
                self.err = f"video unavailable (not found: {video})"
        self.fps = 15.0
        self._frames = deque()      # (pts, surf) decoded, unpresented
        self._flock = threading.Lock()
        self._shown = None          # (pts, surf) currently presented
        self._mini = (None, None)   # one-slot 320x180 downscale cache
        self._gen = 0
        self._proc = None
        self._t0 = 0.0
        self._start_wall = 0.0
        self._last_start = 0.0
        self._fails = 0
        self._mtime = 0
        self._stat_t = time.time()
        if self.video:
            self._mtime = self.video.stat().st_mtime_ns
            try:
                out = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v",
                     "-show_entries", "stream=r_frame_rate", "-of",
                     "csv=p=0", str(self.video)],
                    capture_output=True, timeout=10).stdout.decode()
                num, _, den = out.strip().partition("/")
                self.fps = float(num) / float(den or 1)
            except Exception:
                pass                # fallback only affects pts spacing

    # ---- stream lifecycle ------------------------------------------------
    def _start(self, t0):
        self._gen += 1
        gen = self._gen
        self._kill()
        with self._flock:
            self._frames.clear()
        t0 = max(0.0, t0)
        try:
            self._proc = subprocess.Popen(
                ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}",
                 "-i", str(self.video),
                 "-vf", f"scale={self.size[0]}:{self.size[1]}",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            self.err = "video unavailable (ffmpeg not found)"
            self._proc = None
            return
        self._t0 = t0
        self._start_wall = self._last_start = time.time()
        threading.Thread(target=self._reader,
                         args=(self._proc, t0, gen),
                         daemon=True).start()

    def _kill(self):
        if self._proc is not None:
            try:
                self._proc.kill()
            except OSError:
                pass
            self._proc = None

    def stop(self):
        self._gen += 1
        self._kill()

    def retry(self):
        """R after a video failure: forget it and stream fresh."""
        self.err = None
        self._fails = 0
        self.stop()

    def _reader(self, p, t0, gen):
        fsz = self.size[0] * self.size[1] * 3
        n = 0
        while gen == self._gen:
            if len(self._frames) >= self.BUFFER:
                time.sleep(0.02)    # full buffer: the pipe stalls
                continue            # ffmpeg for us — zero CPU parked
            data = p.stdout.read(fsz)
            if not data or len(data) < fsz:
                break
            # (h, w, 3) rows from ffmpeg -> the (w, h, 3) fb2d order
            frame = np.frombuffer(data, dtype=np.uint8) \
                .reshape(self.size[1], self.size[0], 3) \
                .transpose(1, 0, 2)
            with self._flock:
                self._frames.append((t0 + n / self.fps, frame))
            n += 1
        if gen != self._gen:
            return
        if n == 0 and p.poll() not in (None, 0):
            self._fails += 1
            if self._fails >= 3:
                cause = ""
                try:
                    cause = p.stderr.read(200).decode().strip()[:60]
                except Exception:
                    pass
                self.err = ("video unavailable "
                            f"({cause or 'decode failed'})")
        elif n > 0:
            self._fails = 0

    # ---- presentation ----------------------------------------------------
    def _covered(self, t):
        """Can the running stream serve t without a restart?"""
        p = self._proc
        if p is None:
            return False
        with self._flock:
            newest = self._frames[-1][0] if self._frames else None
            oldest = self._frames[0][0] if self._frames else None
        shown = self._shown[0] if self._shown else None
        if p.poll() is not None and newest is None:
            # drained: EOF legitimately parks on the last frame;
            # a failed decode does not get to park
            return p.returncode == 0 and shown is not None \
                and t >= shown - 0.6 / self.fps
        # the lower bound is the frame being PRESENTED — the oldest
        # buffered frame is the NEXT one, legitimately ahead of t
        # (judging by it read normal playback as a backward seek and
        # restarted the stream every rate-limit period)
        lo = shown if shown is not None else \
            (oldest if oldest is not None else self._t0)
        if t < lo - 0.6 / self.fps:
            return False            # backward seek
        hi = newest if newest is not None else \
            self._t0 + (time.time() - self._start_wall) * 6.0
        return t <= hi + 1.5        # slightly ahead: reader catches up

    def frame_for(self, t):
        """The (pts, surf) to present at playhead t — audio is the
        clock. Returns None only while a fresh stream warms up."""
        if not self.video or self.err:
            return None
        self._check_mtime()
        if not self._covered(t) and \
                time.time() - self._last_start > 0.25:
            self._start(t)          # rate-limited: scrub-drag makes
            #                         at most 4 restarts/s
        with self._flock:
            while self._frames and \
                    self._frames[0][0] <= t + 0.5 / self.fps:
                self._shown = self._frames.popleft()
        return self._shown

    def mini(self, frame):
        if self._mini[0] != id(frame):
            # exact 2x box filter (decode is 640x360, pane is 320x180)
            a = frame.astype(np.uint16)
            small = ((a[0::2, 0::2] + a[1::2, 0::2]
                      + a[0::2, 1::2] + a[1::2, 1::2]) // 4) \
                .astype(np.uint8)
            self._mini = (id(frame), small)
        return self._mini[1]

    def _check_mtime(self):
        if time.time() - self._stat_t < 1.0:
            return
        self._stat_t = time.time()
        try:
            mt = self.video.stat().st_mtime_ns
        except OSError:
            self.err = "video unavailable (file vanished)"
            return
        if mt != self._mtime:
            self._mtime = mt        # regenerated mp4: stream fresh
            self._shown = None
            self.stop()


class App:
    def __init__(self, rec: Path, video: Path | None,
                 headless: bool = False, use: str | None = None):
        # parse the recording BEFORE any window exists: startup
        # failures are one clean message, not a traceback after a
        # window flash (P0.13)
        self.rec = rec
        self.proj = Project(rec, use=use)
        # overrides live per bank PASS: {pass_idx: bank_name}. The
        # CLI --use string means "score every pass with this bank".
        if isinstance(use, str):
            self._use = {i: use for i in range(len(self.proj.banks))}
        else:
            self._use = dict(use or {})
        self.W, self.H = 1280, 720
        self.display = mgui.Display(self.W, self.H,
                                    "PERIHELION session DAW",
                                    headless=headless)
        self.screen = self.display.fb          # (W, H, 3) uint8
        self.font = 13          # text.blit_text sizes (FSEX300)
        self.small = 11
        self.big = 17
        self.injected: list = []    # test-injected uievent.Events
        self.player = Player()
        self.video = VideoPlayer(video)
        self.video_note = ""
        # interaction state
        self._goto = None           # typed go-to buffer, None = inactive
        self.video_big = False
        self.picker = False         # bank-picker overlay open
        self._picker_rows = []      # (rect, bank-name-or-None)
        self.help_on = False
        self.curve_off: set = set()  # hidden P/C/S curves (indices)
        self.sel = None             # selected track (keyboard M/S)
        self._hit = {}              # element -> rect, rebuilt per draw
        self._hover = (None, 0.0)   # (element, hover-start wall time)
        self._bank_ok_cache = {}    # name -> (bank.json mtime, ok)
        self.muted: set = set()
        self.solo: set = set()
        # view / loop
        self.view = None            # (v0, v1) zoom window; None = all
        self.loop = None            # (a, b) selection: while it
        #   exists the playhead lives inside it (clamped, wraps at
        #   the end) and B bounces it; a normal seek clears it
        self.dragging = False
        self._ruler_press = None    # (x, t) pending ruler click/drag
        self._arrow_held = None     # (key, mod, t0, last_fire)
        # status machinery — single writer (_set_status), generation
        # guarded, severity-kinded; everything else derives from work
        self.status = "rendering…"
        self.status_kind = "busy"
        self.status_t = time.time()
        self._slock = threading.Lock()
        self.notes = deque(maxlen=4)    # (wall_t, text, kind)
        self.health: list = self.proj.health()
        self.clip = False
        self.clip_info = (0.0, 0.0)     # (dB over, t of loudest)
        self.anchor = None          # loudness anchor: 0.9/peak of the
        #   FIRST FULL (unmuted) mix, latched once; a louder
        #   replacement must SOUND louder across rebuilds
        self.mix_no = 0
        self.mix_src = "initial"
        self.mix_at = ""
        self.cur_mix = None         # (buf, label)
        self.prev_mix = None        # the A/B undo of a hot-swap
        self.ab_prev = False
        self.render_t0 = time.time()
        self.est_render = None      # seconds; persisted per session
        self.overview = None        # (bins_L, bins_R)
        self._gen = 0
        self._lock = threading.Lock()
        self._quit = False
        self._last_reload = None    # (names, lanes) of last file swap
        self._static = None         # (key, surface, hitmap) draw cache
        # watcher state
        self._watch_dirs = self.proj.watch_dirs()
        self._mtimes = self._scan()
        self._watch_beat = time.time()
        self._shadow_note = ""
        # audio currency: 'current' iff the COMMITTED mix includes
        # every detected file change (watermark, not a boolean — a
        # mutes-rebuild racing a settling drop cannot clear staleness)
        self._change_no = 0
        self._built_change = -1
        self._stale_since = time.time()
        # timeline geometry
        self.x0, self.x1 = 128, self.W - 12
        self.rows = {}
        y = 236
        self.y_ruler = y; y += 20
        self.y_sect = y; y += 14
        self.y_wave = y; y += 64
        self.y_vals = y; y += 56
        for ln in LANES + [FX]:
            self.rows[ln] = y
            y += 26
        self.y_marks = y
        self._load_session()
        if video is not None and video.exists():
            threading.Thread(target=self._probe_video_len,
                             daemon=True).start()
        self.rebuild("rendering…", src="initial")
        self._watch_thread = threading.Thread(target=self._watch,
                                              daemon=True)
        self._watch_thread.start()

    # ---- status / notes (single writer) ---------------------------------
    def _set_status(self, text, kind, gen=None):
        with self._slock:
            if gen is not None and gen != self._gen:
                return              # a superseded render may not speak
            self.status = text
            self.status_kind = kind
            self.status_t = time.time()

    def _note(self, text, kind="warn"):
        if any(t == text for _, t, _ in self.notes):
            return                  # never stutter the same truth
        self.notes.append((time.time(), text, kind))

    # ---- session recall (§7: make the slip cheap, not the quit) ---------
    def _session_file(self):
        base = self.rec if self.rec.is_dir() else self.rec.parent
        return base / "daw_session.json"

    def _load_session(self):
        try:
            s = json.loads(self._session_file().read_text())
        except Exception:
            return
        self.player.t = float(s.get("t", 0.0))
        self.muted = {ln for ln in s.get("muted", []) if ln}
        self.solo = {ln for ln in s.get("solo", []) if ln}
        self.sel = s.get("sel")
        self.curve_off = set(s.get("curve_off", []))
        self.loop = tuple(s["loop"]) if s.get("loop") else None
        self.view = tuple(s["view"]) if s.get("view") else None
        self.est_render = s.get("est_render")
        if not self._use:           # CLI --use wins over recall
            u = s.get("use")
            if isinstance(u, str):  # pre-per-pass session files
                u = {i: u for i in range(len(self.proj.banks))}
            u = {int(k): v for k, v in (u or {}).items()
                 if self._bank_ok(v)}
            if u:
                self._use = u
                self.proj = Project(self.rec, use=u)
        # a restored --use may have replaced self.proj: the watcher
        # must watch the folders of the project we actually score
        self._watch_dirs = self.proj.watch_dirs()
        self._mtimes = self._scan()
        if s.get("t"):
            self._note(f"session restored — playhead "
                       f"{int(s['t']//60)}:{int(s['t']%60):02d}", "ok")

    def _save_session(self):
        try:
            self._session_file().write_text(json.dumps(dict(
                t=self.player.playhead(), muted=sorted(self.muted),
                solo=sorted(self.solo), sel=self.sel,
                curve_off=sorted(self.curve_off),
                loop=list(self.loop) if self.loop else None,
                view=list(self.view) if self.view else None,
                est_render=self.est_render, use=self._use)))
        except OSError as exc:
            print(f"[daw] session save failed: {exc}", file=sys.stderr)

    def _probe_video_len(self):
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "csv=p=0",
                 str(self.video.video)],
                capture_output=True, timeout=10).stdout
            vd = float(out.strip())
        except Exception:
            return
        if abs(vd - self.proj.dur) > 3.0:
            self.video_note = (f"video is {vd:.0f}s but recording is "
                               f"{self.proj.dur:.0f}s — wrong session?")

    # ---- render pipeline -------------------------------------------------
    def rebuild(self, note="rebuilding…", src="edit", reparse=False):
        if reparse:
            try:
                proj = Project(self.rec, use=self._use)
                self.proj = proj
                self._watch_dirs = proj.watch_dirs()
                self._static = None
            except SystemExit as exc:
                self._set_status(f"RENDER FAILED: {exc} — R retries",
                                 "err")
                return
        self._gen += 1
        gen = self._gen
        self._set_status(note, "busy")
        self.render_t0 = time.time()
        mutes, solo = set(self.muted), set(self.solo)
        evs = _apply_mutes(self.proj.events, mutes, solo)
        threading.Thread(target=self._render,
                         args=(evs, gen, src, not (mutes or solo),
                               self._change_no),
                         daemon=True).start()

    def _is_muted(self, ln):
        """THE effective-mute rule — same predicate _apply_mutes uses,
        so audio and display cannot disagree (mute wins over solo)."""
        return ln in self.muted or (self.solo and ln not in self.solo)

    def _render(self, evs, gen, src, unmuted, change_no=0):
        try:
            time.sleep(0.05)            # coalesce M/S spam cheaply
            if gen != self._gen:
                return
            t0 = time.time()
            cold = not _stem_cache
            mix = np.zeros((int(self.proj.dur * RATE) + RATE, 2),
                           np.float32)
            ok = MK._mix_music_rich(mix, evs, self.proj.dur)
            if gen != self._gen:
                return                  # superseded by a newer rebuild
            if not ok:
                self._set_status("no music taps in this recording — "
                                 "nothing to play", "err", gen)
                return
            pk = float(np.abs(mix).max()) or 1.0
            if unmuted and self.anchor is None:
                # latch the loudness anchor ONLY from a full mix: a
                # mute-during-first-render race must not anchor 0.9 to
                # a partial mix (set even if this render is already
                # superseded — the peak is a property of the session)
                self.anchor = 0.9 / pk
            scale = self.anchor if self.anchor is not None else 0.9 / pk
            out = mix * scale
            apk = float(np.abs(out).max())
            clip = apk > 1.0
            t_loud = float(np.abs(out).max(axis=1).argmax()) / RATE
            db_over = 20.0 * np.log10(apk) if apk > 0 else 0.0
            # trim to the ruler's span: player end, overview and ruler
            # must agree on ONE session length (item 42's real root)
            buf = (np.clip(out[:int(self.proj.dur * RATE)], -1, 1)
                   * 32767).astype(np.int16)
            ov = self._overview(buf)
            dt = time.time() - t0
            with self._lock:
                if gen != self._gen:
                    return
                self.mix_no += 1
                if self.cur_mix is not None:
                    self.prev_mix = self.cur_mix
                self.cur_mix = (buf, f"#{self.mix_no} ({src})")
                self.ab_prev = False
                self.player.set_buffer(buf)
                self.overview = ov
                # CLIP verdict commits INSIDE the gen-checked lock: a
                # discarded render may not display its verdict against
                # a newer, playing mix (addendum 31)
                self.clip = clip
                self.clip_info = (db_over, t_loud)
                self.mix_src = src
                self.mix_at = time.strftime("%H:%M:%S")
                self._built_change = change_no
                self._static = None
                if cold:
                    self.est_render = dt
            # health = ~150 file-header reads: off the critical path,
            # AFTER the mix is audible (it only feeds the panel)
            self.health = self.proj.health()
            self._set_status(f"ready ({dt:.1f}s)", "ok", gen)
        except StemContractError as exc:
            self._set_status(f"RENDER FAILED: {exc} — R retries",
                             "err", gen)
        except Exception as exc:
            self._set_status(f"RENDER FAILED: {type(exc).__name__}: "
                             f"{exc} — R retries", "err", gen)

    def _overview(self, buf):
        w = self.x1 - self.x0
        n = int(self.proj.dur * RATE)   # bin over the RULER's span,
        out = []                        # not the buffer's padded tail
        for chn in (0, 1):
            mono = buf[:n, chn].astype(np.float32) / 32767.0
            m = len(mono) // w * w
            out.append(np.abs(mono[:m].reshape(w, -1)).max(axis=1))
        return tuple(out)

    # ---- file watcher ----------------------------------------------------
    def _scan(self):
        mt = {}
        for d in self._watch_dirs:
            try:
                files = list(d.iterdir())
            except OSError:
                continue                # renamed/removed bank dir —
                #                         health() names it in red
            for f in files:
                try:
                    st = f.stat()
                    mt[str(f)] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    pass
        return mt

    def _watch(self):
        """Guarded forever-loop: replace-and-hear must never silently
        stop. Any exception is one visible note, then the loop goes
        on; the main loop additionally restarts a dead thread."""
        while not self._quit:
            try:
                self._watch_once()
            except Exception as exc:
                self._note(f"watcher error: {type(exc).__name__}: "
                           f"{exc} — recovering", "err")
                time.sleep(1.0)

    def _watch_once(self):
        time.sleep(0.7)
        self._watch_beat = time.time()
        mt = self._scan()
        changed = [p for p in mt if mt[p] != self._mtimes.get(p)] + \
                  [p for p in self._mtimes if p not in mt]
        if not changed:
            return
        self._mtimes = mt
        relevant, reparse = [], False
        for p in changed:
            pp = Path(p)
            suf = pp.suffix.lower()
            if pp.name == "bank.json":
                relevant.append(pp)
                reparse = True
            elif suf in (".wav", ".ogg"):
                exact = (pp.stem in self.proj.played_keys
                         and pp.suffix == suf)
                if exact:
                    relevant.append(pp)
                elif pp.stem.lower() in self.proj.played_keys:
                    self._note(f"{pp.name} — case matters here: "
                               f"rename to {pp.stem.lower()}{suf}",
                               "warn")
                elif p in mt:           # ignore deletions of extras
                    self._note(f"{pp.name} — not a stem this session "
                               f"plays (session plays: prayer, "
                               f"bed_t*, lead_*, …)", "warn")
            elif suf in AUDIOISH and p in mt:
                self._note(f"{pp.name} ignored — export WAV/OGG",
                           "warn")
            elif pp.name == "daw_session.json":
                pass
        if not relevant:
            return
        if self._built_change >= self._change_no:
            self._stale_since = time.time()     # was current until now
        self._change_no += 1
        names = ", ".join(sorted({p.name for p in relevant})[:3])
        # acknowledge the save the moment it is seen (addendum 36),
        # then wait for QUIESCENCE: a slow bounce/multi-file export
        # rebuilds once, from complete files, not per write chunk
        self._set_status(f"detected {names} — settling…", "busy")
        last_change = time.time()
        while time.time() - last_change < SETTLE_S:
            time.sleep(0.25)
            self._watch_beat = time.time()
            m2 = self._scan()
            if m2 != self._mtimes:
                self._mtimes = m2
                last_change = time.time()
        # shadow check: does the changed file actually win resolution?
        # (wav beats ogg in-folder; first MUSIC_ROOT wins across roots)
        self._shadow_note = ""
        for pp in relevant:
            d = MK._resolve_bank(pp.parent.name)
            if d is not None and d != pp.parent:
                self._shadow_note = (f"⚠ {pp.name} changed in a "
                                     f"SHADOWED copy — {d} wins")
        # which lanes did this touch? (muted-lane + companion notes)
        stems = {p.stem for p in relevant}
        lanes = set()
        for _, _, bl in self.proj.bars:
            for ln, (key, g, _f) in bl.items():
                if key in stems:
                    lanes.add(ln)
        if stems & set(ONE_SHOTS):
            lanes.add(FX)
        self._last_reload = (names, lanes)
        if "prayer" in stems and "prayer_tail" not in stems and \
                any((d / "prayer_tail.wav").exists() or
                    (d / "prayer_tail.ogg").exists()
                    for d in self._watch_dirs):
            self._note("new prayer still plays the OLD prayer_tail at "
                       "loop seams — replace prayer_tail.wav too",
                       "warn")
        self.rebuild(f"reload: {names}", src=names, reparse=reparse)

    # ---- bank switching (per-pass overrides) ------------------------------
    def available_banks(self):
        """Every folder with a bank.json under the music roots —
        scanned LIVE, any name: a brand-new bank dropped while the
        app runs appears in the picker immediately."""
        names, seen = [], set()
        for root in MK.MUSIC_ROOTS:
            if not root.exists():
                continue
            for d in sorted(root.iterdir()):
                if d.is_dir() and (d / "bank.json").exists() \
                        and d.name not in seen:
                    seen.add(d.name)
                    names.append(d.name)
        return names

    def _bank_ok(self, name):
        """Can this bank actually be scored with? (bank.json parses
        and meets the mixer's bpm+bars contract; cached by mtime)"""
        d = MK._resolve_bank(name)
        if d is None:
            return False
        try:
            st = (d / "bank.json").stat().st_mtime_ns
        except OSError:
            return False
        c = self._bank_ok_cache.get(name)
        if c is not None and c[0] == st:
            return c[1]
        try:
            ok = _bank_valid(json.loads(
                (d / "bank.json").read_text()))
        except Exception:
            ok = False
        self._bank_ok_cache[name] = (st, ok)
        return ok

    def _pass_at(self, t):
        for i, (t0, t1, *_rest) in enumerate(self.proj.banks):
            if t0 <= t < t1:
                return i
        return max(0, len(self.proj.banks) - 1)

    def set_bank(self, name, pass_idx=None):
        """Re-score ONE bank pass — the one under the playhead — with
        the named bank (None restores its recorded bank). Neighboring
        passes keep their scoring, so the transitions in and out of
        the change stay auditionable."""
        t = self.player.playhead()
        if pass_idx is None:
            pass_idx = self._pass_at(t)
        new = dict(self._use)
        if name is None:
            new.pop(pass_idx, None)
        else:
            new[pass_idx] = name
        self.player.pause()
        with self._lock:
            # the old score's audio is not this timeline's truth:
            # unplayable-until-rendered, and the modal says so
            self.player.buf = None
        self._use = new
        self.proj = Project(self.rec, use=new or None)
        self._watch_dirs = self.proj.watch_dirs()
        self._mtimes = self._scan()
        self.anchor = None          # fresh loudness anchor per score
        self.player.t = min(t, self.proj.dur - 1.0)
        self._static = None
        self._save_session()
        self.rebuild(f"scoring pass {pass_idx + 1} with "
                     f"{name or 'its recorded bank'}…",
                     src=f"pass{pass_idx + 1}: {name or 'recorded'}")

    def _goto_commit(self):
        txt = (self._goto or "").strip()
        self._goto = None
        if not txt:
            return
        try:
            if ":" in txt:
                m, s = txt.split(":", 1)
                t = int(m) * 60 + float(s or 0)
            else:
                t = float(txt)
            self._seek_user(t)
        except ValueError:
            self._set_status(f"can't read '{txt}' — use mm:ss or "
                             f"seconds", "warn")

    # ---- navigation helpers ---------------------------------------------
    def _seek(self, t):
        # input-side seeks share the render-commit lock: scrubbing
        # during a hot-swap must not race the buffer swap (addendum 37)
        with self._lock:
            self.player.seek(max(0.0, min(t, self.proj.dur)))

    def _seek_user(self, t):
        """A NORMAL seek — clears the selection (the green box owns
        the playhead while it exists; seeking away dismisses it)."""
        if self.loop is not None:
            self.loop = None
            self._static = None
        self._seek(t)

    def _nudge_bar(self, direction):
        """Arrow nudge lands on ACTUAL bar taps, not median arithmetic."""
        ts = [b[0] for b in self.proj.bars]
        if not ts:
            return
        t = self.player.playhead()
        i = bisect.bisect_right(ts, t + 0.02) - 1
        j = max(0, min(len(ts) - 1, i + direction))
        self._seek_user(ts[j])

    def _jump_mark(self, direction):
        ts = sorted(t for t, _, _ in self.proj.marks)
        if not ts:
            return
        t = self.player.playhead()
        nxt = [m for m in ts if m > t + 0.05] if direction > 0 else \
              [m for m in reversed(ts) if m < t - 0.05]
        if nxt:
            self._seek_user(nxt[0])

    def _jump_sect(self, direction):
        ts = self.proj.sect_starts
        if not ts:
            return
        t = self.player.playhead()
        nxt = [m for m in ts if m > t + 0.05] if direction > 0 else \
              [m for m in reversed(ts) if m < t - 0.05]
        if nxt:
            self._seek_user(nxt[0])

    def _zoom(self, factor):
        """Stepped zoom about the playhead; the overview strip stays
        the full-length navigator."""
        v0, v1 = self.view or (0.0, self.proj.dur)
        span = (v1 - v0) / factor
        span = max(5.0, min(self.proj.dur, span))
        c = self.player.playhead()
        v0 = max(0.0, min(c - span / 2, self.proj.dur - span))
        self.view = None if span >= self.proj.dur - 1e-6 \
            else (v0, v0 + span)
        self._static = None

    def _copy_timestamp(self):
        t = self.player.playhead()
        _, meta, _ = self.proj.bank_at(t)
        name = (meta or {}).get("title",
                                self.proj.bank_at(t)[0] or "?")
        bars = int(meta["bars"]) if meta else 1
        txt = (f"{int(t//60):02d}:{int(t%60):02d} / bar "
               f"{self.proj.bar_at(t)[1] % bars} / {name}")
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"],
                    ["xsel", "-ib"]):
            try:
                subprocess.run(cmd, input=txt.encode(), timeout=3,
                               check=True, capture_output=True)
                self._note(f"copied: {txt}", "ok")
                return
            except (OSError, subprocess.SubprocessError):
                continue
        self._note(f"clipboard unavailable — {txt}", "warn")

    def _bounce(self):
        with self._lock:
            buf = self.player.buf
        if buf is None:
            self._note("nothing to bounce yet", "warn")
            return
        if self.loop:
            a, b = self.loop
        else:
            a, b = 0.0, len(buf) / RATE
        seg = buf[int(a * RATE):int(b * RATE)]
        base = self.rec if self.rec.is_dir() else self.rec.parent
        fn = base / (f"bounce_{int(a//60):02d}{int(a%60):02d}-"
                     f"{int(b//60):02d}{int(b%60):02d}.wav")
        try:
            with wavemod.open(str(fn), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(np.ascontiguousarray(seg).tobytes())
            self._note(f"bounced {b-a:.1f}s → {fn.name}", "ok")
        except OSError as exc:
            self._note(f"bounce failed: {exc}", "err")

    def _toggle_ab(self):
        if self.prev_mix is None:
            self._note("no previous mix yet — A/B arms after the "
                       "first rebuild", "warn")
            return
        with self._lock:
            self.ab_prev = not self.ab_prev
            buf, _ = self.prev_mix if self.ab_prev else self.cur_mix
            self.player.set_buffer(buf)

    def _retry_all(self):
        """R: the one recover-everything gesture."""
        with _stem_lock:
            _stem_cache.clear()
        if self.player.err:
            self.player.retry()
        if self.video.err and self.video.video:
            self.video.retry()
        self.rebuild("full reload", src="R", reparse=True)

    # ---- interaction -----------------------------------------------------
    def handle(self, ev):
        if ev.type == uievent.KEYDOWN:
            if self._goto is not None:      # time-entry mode owns keys
                if ev.key == uievent.K_ESCAPE:
                    self._goto = None
                elif ev.key == uievent.K_RETURN:
                    self._goto_commit()
                elif ev.key == uievent.K_BACKSPACE:
                    self._goto = self._goto[:-1]
                elif ev.unicode and ev.unicode in "0123456789:.":
                    self._goto += ev.unicode
                return True
            if self.help_on:
                if ev.key in (uievent.K_ESCAPE, mgui.K_F1) or \
                        ev.unicode == "?":
                    self.help_on = False
                return True
            if ev.key == uievent.K_ESCAPE:
                if self.picker:
                    self.picker = False
                elif self.video_big:
                    self.video_big = False
                else:
                    return False
            elif ev.unicode == "?" or ev.key == mgui.K_F1:
                self.help_on = True
            elif ev.key == uievent.K_SPACE:
                if self.player.buf is None:
                    self._note("no mix yet — playback starts when "
                               "rendering finishes", "busy")
                else:
                    (self.player.pause if self.player.playing
                     else self.player.play)()
            elif ev.key == uievent.K_r:
                self._retry_all()
            elif ev.key == uievent.K_a:
                self._toggle_ab()
            elif ev.key == uievent.K_g:
                self._goto = ""
            elif ev.key == uievent.K_c:
                self._copy_timestamp()
            elif ev.key == uievent.K_b:
                self._bounce()
            elif ev.key == uievent.K_l:
                if self.loop:
                    self.loop = None
                    self._static = None
                else:
                    self._note("drag on the ruler to select a range "
                               "(playback loops it; B bounces it)",
                               "warn")
            elif ev.key == uievent.K_m and self.sel:
                self.muted ^= {self.sel}
                self.rebuild(src="mutes")
            elif ev.key == uievent.K_s and self.sel:
                self.solo ^= {self.sel}
                self.rebuild(src="mutes")
            elif ev.key == mgui.K_COMMA:
                self._jump_mark(-1)
            elif ev.key == mgui.K_PERIOD:
                self._jump_mark(+1)
            elif ev.key == uievent.K_UP:
                self._jump_sect(-1)
            elif ev.key == uievent.K_DOWN:
                self._jump_sect(+1)
            elif ev.key in (mgui.K_PLUS, mgui.K_EQUALS,
                            mgui.K_KP_PLUS):
                self._zoom(2.0)
            elif ev.key in (mgui.K_MINUS, mgui.K_KP_MINUS):
                self._zoom(0.5)
            elif ev.key == uievent.K_0:
                self.view = None
                self._static = None
            elif ev.key in (uievent.K_LEFT, uievent.K_RIGHT):
                self._arrow_step(ev.key, ev.mod)
                self._arrow_held = (ev.key, ev.mod,
                                    time.time() + 0.3, 0.0)
            elif ev.key == mgui.K_HOME:
                self._seek_user(0.0)
            elif ev.key == mgui.K_END:
                self._seek_user(self.proj.dur)
        elif ev.type == uievent.KEYUP:
            if self._arrow_held and ev.key == self._arrow_held[0]:
                self._arrow_held = None
        elif ev.type == uievent.MOUSEBUTTONDOWN and ev.button == 1:
            x, y = ev.pos
            if self.help_on:
                self.help_on = False
                return True
            if self.picker:
                for r, name, ok in self._picker_rows:
                    if r.collidepoint(x, y):
                        if not ok:
                            self._note(f"{name}: incomplete bank.json"
                                       f" (needs bpm + bars + "
                                       f"sections) — fix the file to "
                                       f"score with it", "warn")
                            return True     # picker stays open
                        self.picker = False
                        self.set_bank(name)
                        return True
                self.picker = False
                return True
            if self.video_big:
                self.video_big = False
                return True
            for el, r in self._hit.items():
                if not r.collidepoint(x, y):
                    continue
                if el.startswith(("mark:", "legend:")) or el == "ruler":
                    continue        # hover-only: clicks fall through
                    #                 to the scrub surface beneath
                if el == "play_glyph":
                    (self.player.pause if self.player.playing
                     else self.player.play)()
                elif el == "time_readout":
                    self._goto = ""
                elif el == "clip_chip":
                    if abs(self.player.playhead()
                           - self.clip_info[1]) < 0.5:
                        self.clip = False   # 2nd click: reset latch
                    else:
                        self._seek_user(self.clip_info[1])
                elif el == "ab_chip":
                    self._toggle_ab()
                elif el == "bank_title":
                    self.picker = True
                elif el == "video_monitor":
                    self.video_big = True
                elif el == "help_glyph":
                    self.help_on = True
                elif el.startswith("curve:"):
                    self.curve_off ^= {int(el.split(":")[1])}
                    self._static = None
                elif el.startswith("name:"):
                    ln = el.split(":")[1]
                    self.sel = None if self.sel == ln else ln
                    self._static = None
                elif el.startswith("mute:"):
                    self.muted ^= {el.split(":")[1]}
                    self.rebuild(src="mutes")
                elif el.startswith("solo:"):
                    self.solo ^= {el.split(":")[1]}
                    self.rebuild(src="mutes")
                return True
            if self.x0 <= x <= self.x1:
                if self.y_ruler <= y <= self.y_ruler + 18:
                    # ruler: click seeks, DRAG sets the loop region
                    self._ruler_press = (x, self._xt(x))
                    return True
                if self.y_wave <= y <= self.y_wave + 60:
                    # overview strip = absolute navigator (zoom-proof)
                    f = (x - self.x0) / (self.x1 - self.x0)
                    self._seek_user(f * self.proj.dur)
                    self.dragging = "abs"
                    return True
                if self.y_sect <= y <= self.y_marks + 22:
                    self._seek_user(self._xt(x))
                    self.dragging = "view"
        elif ev.type == uievent.MOUSEBUTTONUP:
            if self._ruler_press is not None:
                px, pt = self._ruler_press
                if abs(ev.pos[0] - px) <= 5:
                    self._seek_user(pt)     # a click, not a drag
                self._ruler_press = None
            self.dragging = False
        elif ev.type == uievent.MOUSEMOTION:
            if self._ruler_press is not None and \
                    abs(ev.pos[0] - self._ruler_press[0]) > 5:
                a, b = sorted((self._ruler_press[1],
                               self._xt(ev.pos[0])))
                self.loop = (a, b)
                self._static = None
            elif getattr(self, "dragging", False) == "abs":
                f = (ev.pos[0] - self.x0) / (self.x1 - self.x0)
                self._seek_user(max(0.0, min(1.0, f)) * self.proj.dur)
            elif getattr(self, "dragging", False):
                self._seek_user(self._xt(ev.pos[0]))
        return True

    def _arrow_step(self, key, mod):
        if mod & uievent.KMOD_SHIFT:
            d = 10.0 if key == uievent.K_RIGHT else -10.0
            self._seek_user(self.player.playhead() + d)
        else:
            self._nudge_bar(+1 if key == uievent.K_RIGHT else -1)

    # ---- drawing ----------------------------------------------------------
    def _view(self):
        return self.view or (0.0, self.proj.dur)

    def _tx(self, t):
        v0, v1 = self._view()
        return self.x0 + int((self.x1 - self.x0) * (t - v0)
                             / max(1e-6, v1 - v0))

    def _xt(self, x):
        v0, v1 = self._view()
        f = (x - self.x0) / max(1, self.x1 - self.x0)
        return v0 + max(0.0, min(1.0, f)) * (v1 - v0)

    def _ox(self, t):
        return self.x0 + int((self.x1 - self.x0) * t / self.proj.dur)

    def txt(self, s, x, y, c=(200, 200, 200), f=None, surf=None,
            maxw=None):
        target = surf if surf is not None else self.screen
        size = f or self.font
        if maxw is not None and text.measure(s, size)[0] > maxw:
            while s and text.measure(s + "…", size)[0] > maxw:
                s = s[:-1]
            s += "…"
        text.blit_text(target, s, x, y, c, size)

    def _chip(self, s, x, y, kind, hit=None, surf=None, maxw=None):
        full = s
        cap = min(420, maxw) if maxw is not None else 420
        trunc = False
        while len(s) > 8 and text.measure(s + "…", self.font)[0] > cap - 10:
            s = s[:-2]
            trunc = True
        if trunc:
            s += "…"
        w = text.measure(s, self.font)[0] + 10
        col = STATUS_COL[kind]
        bg = tuple(c // 5 for c in col)
        target = surf if surf is not None else self.screen
        fb2d.rect(target, bg, (x, y, w, 18))
        fb2d.rect(target, col, (x, y, w, 18), 1)
        self.txt(s, x + 5, y + 2, col, surf=surf)
        if hit:
            self._hit[hit] = Rect(x, y, w, 18)
        elif trunc:
            # a cut-off message is unread truth: hover expands it in
            # full, foregrounded (director feedback)
            key = f"chipfull:{len(self._chip_full)}"
            self._chip_full[key] = full
            self._hit[key] = Rect(x, y, w, 18)
        return x + w + 8

    def draw(self):
        scr = self.screen
        proj = self.proj                # one snapshot per frame
        fb2d.fill(scr, (18, 18, 22))
        self._hit = {}
        self._chip_full = {}
        t = self.player.playhead()
        v0, v1 = self._view()

        # ---- static timeline layer (P3.27) --------------------------
        key = (id(proj), self.mix_no, self.view, frozenset(self.muted),
               frozenset(self.solo), self.sel,
               frozenset(self.curve_off), self.loop)
        if self._static is None or self._static[0] != key:
            # opaque layer prefilled with the screen's own background —
            # the old transparent-layer composite sat over this same
            # constant fill, so the result is pixel-identical
            surf = np.empty((self.W, self.H - 236, 3), np.uint8)
            surf[...] = (18, 18, 22)
            hits = {}
            self._draw_timeline(surf, hits, proj)
            self._static = (key, surf, hits)
        fb2d.blit(scr, self._static[1], 0, 236)
        for el, r in self._static[2].items():
            self._hit[el] = r

        # ONE frame per draw serves both panes (audio is the clock).
        # While nothing is playable the stream stays down: on laptop
        # cores the ffmpeg decode visibly slowed the first render
        vf = self.video.frame_for(t) \
            if self.video.video and not self.video.err \
            and self.player.buf is not None else None
        self._draw_transport(scr, proj, t)
        self._draw_panel(scr, proj, t)
        if not self.video_big:      # the lightbox covers the mini pane
            self._draw_video(scr, t, vf)

        # playhead over the static layer
        if v0 <= t <= v1:
            px = self._tx(t)
            fb2d.line(scr, (255, 255, 255), (px, self.y_ruler),
                             (px, self.y_marks + 22))
        opx = self._ox(t)
        fb2d.line(scr, (255, 255, 255), (opx, self.y_wave),
                         (opx, self.y_wave + 58), 1)

        # per-track stem key at the playhead (P2.24)
        _, _, blanes = proj.bar_at(t)
        for ln in LANES:
            keyg = blanes.get(ln)
            if keyg and keyg[0] not in ("silence", "None") \
                    and keyg[1] > 0.001:
                self.txt(keyg[0], 50, self.rows[ln] + 13,
                         (120, 120, 135), self.small, maxw=74)

        if self.player.buf is None:
            # nothing playable: the render/err state is MODAL over a
            # greyed timeline — a live-looking timeline with a dead
            # SPACE read as broken (director feedback)
            self._draw_render_modal(scr)
        self._draw_overlays(scr, proj, t, vf)
        self._draw_tooltip()
        self.display.flip()

    # ---- transport & status ---------------------------------------------
    def _draw_transport(self, scr, proj, t):
        fb2d.rect(scr, (28, 28, 34), (0, 0, self.W, 36))
        if self.player.buf is None:
            glyph = "…"
        elif self.player.playing:
            glyph = "||"
        elif t >= self.player.end_t() - 0.05 and self.player.end_t():
            glyph = "↺"
        else:
            glyph = ">"
        self.txt(glyph, 14, 8, (240, 220, 160), self.big)
        self._hit["play_glyph"] = Rect(8, 2, 34, 30)
        bar_t, bar_idx, _ = proj.bar_at(t)
        name, meta, d = proj.bank_at(t)
        sect = proj.section_at(t)
        if self._goto is not None:
            fb2d.rect(scr, (50, 50, 30), (44, 6, 130, 24))
            fb2d.rect(scr, (240, 220, 160), (44, 6, 130, 24), 1)
            self.txt(f"{self._goto}_", 50, 10, (255, 255, 200),
                     self.big)
        else:
            mm, ss = divmod(int(t), 60)
            self.txt(f"{mm:02d}:{ss:02d}.{int((t % 1) * 10)}", 48, 10,
                     (255, 255, 255), self.big)
        self._hit["time_readout"] = Rect(44, 6, 130, 24)
        self.txt(f"bar {bar_idx % (meta['bars'] if meta else 1):>2}"
                 f"  {sect:<8}", 180, 10, (240, 220, 160), self.big)
        xf = proj.xfade_at(t)
        if xf:
            title = f"{xf[0]} → {xf[1]}"    # rotation crossfade: the
            col = (255, 200, 120)           # OLD bank is still sounding
        else:
            title = (meta or {}).get("title", str(name))
            col = (200, 200, 220)
        self.txt(title, 350, 10, col, self.big, maxw=290)
        self._hit["bank_title"] = Rect(346, 4, 300, 28)
        # status chip: color-coded, flashes on transition, one writer
        flash = time.time() - self.status_t < 0.35
        kind = self.status_kind
        x = 652
        if self.player.buf is None and kind == "busy":
            el = time.time() - self.render_t0
            s = f"{self.status} {el:.0f}s"
            if self.est_render:
                frac = min(1.0, el / self.est_render)
                s += f" ({frac * 100:.0f}%)"
            x = self._chip(s, x, 9, "busy")
        else:
            x = self._chip(self.status, x, 9, kind)
        if flash:
            fb2d.rect(scr, (255, 255, 255),
                             (652, 9, x - 660, 18), 1)
        limit = self.W - 34             # chips never cover the ? glyph
        if self.clip:
            db, tl = self.clip_info
            x = self._chip(f"CLIP +{db:.1f}dB @ {int(tl//60)}:"
                           f"{int(tl%60):02d}", x, 9, "err",
                           hit="clip_chip", maxw=limit - x)
        if self.ab_prev and self.prev_mix:
            label = self.prev_mix[1].split(" ")[0]
            x = self._chip(f"hearing PREVIOUS {label} — A returns",
                           x, 9, "warn", hit="ab_chip", maxw=limit - x)
        self.txt("?", self.W - 22, 8, (170, 170, 190), self.big)
        self._hit["help_glyph"] = Rect(self.W - 28, 2, 26, 30)
        # line 2: mix identity + liveness chips (all derived)
        y2 = 40
        x2 = 12
        if self.mix_no:
            self.txt(f"mix #{self.mix_no} · {self.mix_src} · "
                     f"{self.mix_at}", x2, y2 + 2, (150, 150, 165),
                     maxw=300)
            x2 = 320
        # binary currency chip: quiet static text when fine; numbers
        # tick only in the wrong states (director: don't grab
        # attention when everything is ok)
        beat = time.time() - self._watch_beat
        alive = self._watch_thread.is_alive()
        if not alive:
            x2 = self._chip("watcher DIED — restarting", x2, y2, "err")
        elif beat > 5.0:
            x2 = self._chip(f"watcher stalled {beat:.0f}s", x2, y2,
                            "warn")
        elif self._built_change < self._change_no:
            age = time.time() - self._stale_since
            x2 = self._chip(f"NOT LATEST AUDIO — {age:.0f}s", x2, y2,
                            "warn")
        else:
            x2 = self._chip(f"watching {len(self._watch_dirs)} "
                            f"folders · current", x2, y2, "ok")
        if self.player.err:
            x2 = self._chip(f"AUDIO FAILED: {self.player.err} — R "
                            f"retries", x2, y2, "err")
        if self._shadow_note:
            x2 = self._chip(self._shadow_note, x2, y2, "warn")
        # muted-lane truth for the last reload (derived, not stored)
        if self._last_reload:
            names, lanes = self._last_reload
            dead = {ln for ln in lanes if self._is_muted(ln)}
            if dead:
                self._chip(f"{names} → {'/'.join(sorted(dead))} is "
                           f"muted — unmute to hear", x2, y2, "warn",
                           maxw=self.W - 344 - x2)
        # a chip can truncate; an ERROR'S REMEDY may not — mirror the
        # full red status on its own full-width line
        if self.status_kind == "err":
            self.txt(self.status, 12, 224, STATUS_COL["err"], maxw=920)
        # transient notes (bottom-left of the panel area)
        yy = 208
        now = time.time()
        for ts, text, kind in list(self.notes):
            if now - ts < 8.0:
                self.txt(text, 12, yy, STATUS_COL[kind], maxw=780)
                yy -= 16

    # ---- info panel -------------------------------------------------------
    def _draw_panel(self, scr, proj, t):
        rec_name = self.rec.name if self.rec.is_dir() else \
            self.rec.parent.name
        self.txt(f"SESSION  {rec_name}", 12, 60, (240, 220, 160))
        self.txt(f"length {int(proj.dur // 60)}:"
                 f"{int(proj.dur % 60):02d}   {len(proj.bars)} bars   "
                 f"{len(proj.banks)} bank passes", 12, 78)
        yy = 98
        seen = set()
        for _, _, nm, meta, dd in proj.banks:
            if nm in seen:
                continue
            seen.add(nm)
            if meta is None:
                self.txt(f"{nm:<22} NOT FOUND — plays silence", 12, yy,
                         STATUS_COL["err"], maxw=560)
            else:
                spec = (f"{meta['bpm']:g}bpm · {meta['bars']} bars · "
                        f"stem {240.0 / meta['bpm'] * meta['bars']:.1f}s"
                        f" · 44.1k/16-bit")
                self.txt(f"{nm:<22} {spec}", 12, yy, (150, 150, 160),
                         maxw=560)
            yy += 15
            if yy > 175:
                self.txt(f"… +{len({b[2] for b in proj.banks}) - len(seen)} more",
                         12, yy, (120, 120, 135))
                break
        for msg, kind in self.health[:2]:
            self.txt(msg, 12, yy, STATUS_COL[kind], maxw=580)
            yy += 15
        if len(self.health) > 2:
            self.txt(f"… +{len(self.health) - 2} more warnings (see "
                     f"check_bank)", 12, yy, STATUS_COL["warn"])
            yy += 15
        self.txt("replace any stem file in a bank folder → auto-reload"
                 " at the same playhead", 12, min(yy + 2, 192),
                 (170, 190, 170))
        self.txt("SPACE play · drag scrub · ,/. markers · ±0 zoom · "
                 "drag ruler select · M/S · A prev mix · B bounce · "
                 "? all keys", 128, self.y_marks + 42, (120, 120, 135))

    # ---- video pane -------------------------------------------------------
    def _draw_video(self, scr, t, vf):
        vx, vy = self.W - 332, 44
        if self.video.err:
            fb2d.rect(scr, (40, 24, 24), (vx, vy, 320, 40))
            self.txt(self.video.err, vx + 6, vy + 12,
                     STATUS_COL["err"], maxw=308)
            return
        if self.video.video is None:
            self.txt("no video attached (--video PATH)", vx + 40,
                     vy + 80, (100, 100, 115))
            return
        if vf is not None:
            pts, native = vf
            fb2d.blit(scr, self.video.mini(native), vx, vy)
            lag = abs(pts - t)
            if lag > 1.0:
                # a running stream tracks the playhead within a frame;
                # a visible lag means it is warming up after a seek —
                # dim says "not current", the badge marks a real stall
                fb2d.alpha_fill(scr, (0, 0, 0), 130,
                                (vx, vy, 320, 180))
            if lag > 2.5:
                self.txt(f"video behind by {lag:.0f}s", vx + 8, vy + 8,
                         STATUS_COL["warn"])
        else:
            self.txt("starting video…", vx + 100, vy + 84,
                     (120, 120, 135))
        fb2d.rect(scr, (70, 70, 80), (vx, vy, 320, 180), 1)
        self._hit["video_monitor"] = Rect(vx, vy, 320, 180)
        if self.video_note:
            self.txt(self.video_note, vx, vy + 184, STATUS_COL["warn"],
                     maxw=320)

    # ---- timeline (static layer) ------------------------------------------
    def _draw_timeline(self, surf, hits, proj):
        off = 236                       # surface y offset

        def T(y):
            return y - off

        v0, v1 = self._view()
        span = v1 - v0
        # ruler with zoom-adaptive ticks
        fb2d.rect(surf, (26, 26, 32),
                         (self.x0, T(self.y_ruler),
                          self.x1 - self.x0, 16))
        step = next((s for s in (1, 5, 10, 30, 60, 120)
                     if (self.x1 - self.x0) * s / span >= 55), 120)
        m = int(v0 // step) * step
        while m <= v1:
            if m >= v0:
                x = self._tx(m)
                fb2d.line(surf, (80, 80, 95),
                                 (x, T(self.y_ruler)),
                                 (x, T(self.y_ruler) + 16))
                self.txt(f"{m // 60}:{m % 60:02d}", x + 3,
                         T(self.y_ruler) + 1, (140, 140, 155),
                         surf=surf)
            m += step
        # the selection box on the ruler (loops + bounces; any normal
        # seek clears it, so it is always live-green)
        if self.loop:
            a, b = self.loop
            xa, xb = self._tx(max(a, v0)), self._tx(min(b, v1))
            if xb > xa:
                col = (120, 220, 160)
                fb2d.alpha_fill(surf, col, 70,
                                (xa, T(self.y_ruler), xb - xa, 16))
                fb2d.rect(surf, col,
                                 (xa, T(self.y_ruler), xb - xa, 16), 1)
        # the ruler itself is a hover target: nothing on screen said
        # what dragging here selects (director feedback)
        hits["ruler"] = Rect(self.x0, self.y_ruler,
                                    self.x1 - self.x0, 18)
        # bank switch lines + labels
        for t0, t1, nm, meta, _ in proj.banks:
            if not (v0 - 1 <= t0 <= v1 + 1) or t0 == 0.0:
                continue
            x = self._tx(t0)
            fb2d.line(surf, (240, 220, 160), (x, T(self.y_sect)),
                             (x, T(self.y_marks) + 14))
        for t0, t1, nm, meta, _ in proj.banks:
            if t1 < v0 or t0 > v1:
                continue
            label = (meta or {}).get("title", nm)
            self.txt(label, max(self._tx(t0), self.x0) + 3,
                     T(self.y_marks) + 24, (200, 190, 150), self.small,
                     surf=surf,
                     maxw=max(20, self._tx(min(t1, v1))
                              - max(self._tx(t0), self.x0) - 6))
        # sections with labels
        spans = []
        for (bt, bidx, _), nxt in zip(
                proj.bars, proj.bars[1:] + [(proj.dur, 0, {})]):
            if nxt[0] < v0 or bt > v1:
                continue
            sec = proj.section_at(bt + 0.01)
            if spans and spans[-1][2] == sec:
                spans[-1] = (spans[-1][0], nxt[0], sec)
            else:
                spans.append((bt, nxt[0], sec))
        for a, b, sec in spans:
            x, xe = self._tx(max(a, v0)), self._tx(min(b, v1))
            fb2d.rect(surf, SECT_COL.get(sec, (50, 50, 60)),
                             (x, T(self.y_sect), max(1, xe - x), 10))
            if xe - x > 44 and sec:
                self.txt(sec, x + 3, T(self.y_sect) - 1,
                         (230, 230, 240), self.small, surf=surf,
                         maxw=xe - x - 4)
        # rotation-crossfade windows (the OLD bank is still sounding)
        for t0, t1, old, new in proj.xfades:
            if t1 < v0 or t0 > v1:
                continue
            xa, xb = self._tx(max(t0, v0)), self._tx(min(t1, v1))
            if xb <= xa:
                continue
            band = fb2d.overlay(xb - xa, 12)
            fb2d.fill(band, (255, 200, 120, 60))
            for i in range(0, xb - xa, 6):
                fb2d.line(band, (255, 200, 120, 140),
                          (i, 12), (min(i + 6, xb - xa), 0))
            fb2d.blit(surf, band, xa, T(self.y_sect))
            hits[f"mark:xfade:{xa}"] = Rect(
                xa, self.y_sect, xb - xa, 12)
        # waveform overview — ALWAYS the full session (navigator)
        fb2d.rect(surf, (24, 24, 30),
                         (self.x0, T(self.y_wave),
                          self.x1 - self.x0, 58))
        ov = self.overview
        if ov is not None:
            mid = T(self.y_wave) + 29
            for i in range(len(ov[0])):
                hL = int(ov[0][i] * 27)
                hR = int(ov[1][i] * 27)
                fb2d.line(surf, (90, 130, 110),
                                 (self.x0 + i, mid - hL),
                                 (self.x0 + i, mid))
                fb2d.line(surf, (80, 118, 128),
                                 (self.x0 + i, mid),
                                 (self.x0 + i, mid + hR))
        # halt spans: silence is drawn as silence (full-height red)
        for ht, resume in proj.halts:
            xa, xb = self._ox(ht), self._ox(resume)
            fb2d.alpha_fill(surf, (255, 60, 60), 60,
                            (xa, T(self.y_wave), max(2, xb - xa), 58))
        if self.view:
            xa = self._ox(v0)
            xb = self._ox(v1)
            fb2d.rect(surf, (240, 220, 160),
                             (xa, T(self.y_wave), max(2, xb - xa), 58),
                             1)
            self.txt("zoom", xa + 3, T(self.y_wave) + 44,
                     (240, 220, 160), self.small, surf=surf)
        # value automation (P/C/S)
        fb2d.rect(surf, (24, 24, 30),
                         (self.x0, T(self.y_vals),
                          self.x1 - self.x0, 50))
        for vi, vname in enumerate(("PRAYER", "CONTEMPT", "STALWART")):
            col = tuple(c // 3 for c in VAL_COL[vi]) \
                if vi in self.curve_off else VAL_COL[vi]
            self.txt(vname, 50, T(self.y_vals) + 2 + vi * 15, col,
                     surf=surf)
            hits[f"curve:{vi}"] = Rect(
                46, self.y_vals + vi * 15, 80, 15)
        vis = [(vt, v) for vt, v in proj.vals if v0 <= vt <= v1]
        stride = max(1, len(vis) // (self.x1 - self.x0))
        for vi in range(3):
            if vi in self.curve_off:
                continue
            pts = [(self._tx(vt), T(self.y_vals) + 48 - int(v[vi] * 46))
                   for vt, v in vis[::stride]]
            if len(pts) > 1:
                fb2d.lines(surf, VAL_COL[vi], False, pts)
        # lane tracks
        for ln in LANES + [FX]:
            ry = T(self.rows[ln])
            eff_muted = self._is_muted(ln)
            hcol = (255, 240, 200) if ln in self.solo and not eff_muted \
                else (110, 110, 120) if eff_muted else (200, 200, 210)
            fb2d.rect(surf, (60, 40, 40) if ln in self.muted
                             else (36, 36, 44), (4, ry, 18, 16))
            self.txt("M", 8, ry + 1, (255, 150, 150) if ln in self.muted
                     else (150, 150, 160), surf=surf)
            hits[f"mute:{ln}"] = Rect(4, self.rows[ln], 18, 16)
            fb2d.rect(surf, (60, 60, 30) if ln in self.solo
                             else (36, 36, 44), (26, ry, 18, 16))
            self.txt("S", 31, ry + 1, (255, 240, 140) if ln in self.solo
                     else (150, 150, 160), surf=surf)
            hits[f"solo:{ln}"] = Rect(26, self.rows[ln], 18, 16)
            if self.sel == ln:
                fb2d.rect(surf, (70, 65, 40), (46, ry, 80, 12))
            self.txt(ln, 50, ry + 1, hcol, surf=surf)
            hits[f"name:{ln}"] = Rect(46, self.rows[ln], 80, 19)
            fb2d.rect(surf, (24, 24, 29),
                             (self.x0, ry, self.x1 - self.x0, 22))
            if ln == FX:
                continue
            col = LANE_COL[ln]
            dim = 0.25 if eff_muted else 1.0
            for (bt, bidx, lanes), nxt in zip(
                    proj.bars, proj.bars[1:] + [(proj.dur, 0, {})]):
                if nxt[0] < v0 or bt > v1:
                    continue
                key, g, fade = lanes.get(ln, ("silence", 0.0, False))
                if g <= 0.001 or key == "silence":
                    continue
                x, xe = self._tx(max(bt, v0)), self._tx(min(nxt[0], v1))
                h = max(2, int(20 * min(1.0, g)))
                c = tuple(int(v * (0.35 + 0.65 * g) * dim) for v in col)
                if fade and xe - x >= 3:
                    # farewell bar (~f): the lane RAMPS TO ZERO across
                    # this bar — drawn as its shape, a right taper
                    fb2d.polygon(surf, c, [
                        (x, ry + 21), (x, ry + 21 - h),
                        (xe, ry + 21 - max(1, h // 5)), (xe, ry + 21)])
                else:
                    fb2d.rect(surf, c, (x, ry + 21 - h,
                                               max(1, xe - x), h))
        # FX / event markers — every glyph is a hover target carrying
        # the same tooltip as its legend twin
        ry = T(self.rows[FX])
        for t0, t1 in proj.riser_spans:     # 2-bar swell → strike
            if t1 < v0 or t0 > v1:
                continue
            xa, xb = self._tx(t0), self._tx(t1)
            fb2d.line(surf, (200, 120, 220), (xa, ry + 18),
                             (xb, ry + 3))
            fb2d.line(surf, (240, 180, 255), (xb, ry + 1),
                             (xb, ry + 20), 2)
        for mt_, kind, nm in proj.marks:
            if not (v0 <= mt_ <= v1):
                continue
            if kind == "music_halt" or \
                    (kind == "music_jump" and nm.endswith("~s")):
                continue        # halts draw as full spans below
            x = self._tx(mt_)
            self._mark_glyph(surf, kind, x, ry)
            hits[f"mark:{kind}:{x}"] = Rect(
                x - 5, self.rows[FX], 11, 22)
        # death halts: full-height red spans — silence LOOKS like
        # silence across every row, not a 20px tick
        for ht, resume in proj.halts:
            if resume < v0 or ht > v1:
                continue
            xa = self._tx(max(ht, v0))
            xb = self._tx(min(resume, v1))
            fb2d.alpha_fill(surf, (255, 60, 60), 36,
                            (xa, T(self.y_sect), max(2, xb - xa),
                             self.y_marks + 22 - self.y_sect))
            fb2d.line(surf, (255, 70, 70),
                             (xa, T(self.y_sect)),
                             (xa, T(self.y_marks) + 22), 2)
            hits[f"mark:music_halt:{xa}"] = Rect(
                xa - 4, self.rows[FX], 9, 22)
        # inline marker legend under the fx header: the same glyphs
        # the row uses, hover any for its meaning
        lx = 10
        for kind in ("music_jump", "music_riser", "music_riser2",
                     "music_sting", "music_stab", "music_halt",
                     "xfade"):
            self._mark_glyph(surf, kind, lx, T(self.y_marks))
            hits[f"legend:{kind}"] = Rect(
                lx - 6, self.y_marks, 13, 22)
            lx += 17

    # ---- overlays ---------------------------------------------------------
    def _draw_render_modal(self, scr):
        """No playable mix (first render, bank re-score, no-taps or a
        failed first render): grey the timeline and say why, front and
        center — the chip alone required knowing what the chip means."""
        fb2d.alpha_fill(scr, (0, 0, 0), 165,
                        (0, 236, self.W, self.H - 236))
        box = Rect(self.W // 2 - 310, 372, 620, 96)
        col = STATUS_COL[self.status_kind]
        fb2d.rect(scr, (24, 24, 30), box)
        fb2d.rect(scr, col, box, 2)
        self.txt(self.status, box.x + 20, box.y + 14, col, self.big,
                 maxw=box.w - 40)
        if self.status_kind == "busy":
            el = time.time() - self.render_t0
            if self.est_render:
                frac = min(1.0, el / self.est_render)
                fb2d.rect(scr, (50, 50, 60),
                                 (box.x + 20, box.y + 46,
                                  box.w - 40, 10))
                fb2d.rect(scr, col,
                                 (box.x + 20, box.y + 46,
                                  int((box.w - 40) * frac), 10))
                sub = (f"{el:.0f}s of ~{self.est_render:.0f}s — "
                       f"SPACE plays as soon as the mix is ready")
            else:
                sub = (f"{el:.0f}s — SPACE plays as soon as the mix "
                       f"is ready")
            self.txt(sub, box.x + 20, box.y + 64, (190, 190, 200),
                     maxw=box.w - 40)
        elif self.status_kind == "err":
            self.txt("nothing playable until this is fixed",
                     box.x + 20, box.y + 64, (190, 190, 200),
                     maxw=box.w - 40)

    def _draw_overlays(self, scr, proj, t, vf):
        if self.video_big:
            bw, bh = self.video.size
            bx, by = (self.W - bw) // 2, (self.H - bh) // 2
            fb2d.alpha_fill(scr, (0, 0, 0), 170)
            if vf is not None:
                fb2d.blit(scr, vf[1], bx, by)
                if abs(vf[0] - t) > 1.0:
                    fb2d.alpha_fill(scr, (0, 0, 0), 130,
                                    (bx, by, bw, bh))
            fb2d.rect(scr, (200, 200, 210), (bx, by, bw, bh), 2)
            self.txt("click or ESC to close", bx + 4, by + bh + 6,
                     (170, 170, 180))
        if self.picker:
            pi = self._pass_at(t)
            orig = self.proj.orig_banks[pi] \
                if pi < len(self.proj.orig_banks) else "?"
            over = self._use.get(pi)
            names = [None] + self.available_banks()
            hidden = 0
            max_rows = (self.H - 130) // 24
            if len(names) > max_rows:   # visible cap, never silent
                hidden = len(names) - max_rows
                names = names[:max_rows]
            ph = 24 * len(names) + 36 + (16 if hidden else 0)
            prc = Rect(350, 40, 340, ph)
            fb2d.rect(scr, (30, 30, 38), prc)
            fb2d.rect(scr, (240, 220, 160), prc, 1)
            self.txt(f"score pass {pi + 1} (at the playhead) with:",
                     prc.x + 10, prc.y + 8, (240, 220, 160),
                     maxw=prc.w - 20)
            self._picker_rows = []
            yy = prc.y + 30
            for nm in names:
                r = Rect(prc.x + 6, yy, prc.w - 12, 22)
                ok = nm is None or self._bank_ok(nm)
                cur = (nm == over)
                if cur:
                    fb2d.rect(scr, (60, 55, 35), r)
                label = nm or f"(as recorded: {orig})"
                if not ok:
                    label += "  (incomplete bank.json)"
                self.txt(label, r.x + 6, r.y + 3,
                         (255, 240, 200) if cur
                         else (200, 200, 210) if ok
                         else (110, 110, 120), maxw=r.w - 10)
                self._picker_rows.append((r, nm, ok))
                yy += 24
            if hidden:
                self.txt(f"… +{hidden} more banks (folder names "
                         f"sort first)", prc.x + 10, yy + 2,
                         (170, 170, 185), self.small,
                         maxw=prc.w - 20)
        if self.help_on:
            self._draw_help(scr)

    HELP_KEYS = [
        ("SPACE", "play / pause (at the end: restart)"),
        ("click/drag", "scrub — timeline seeks in the zoom window; "
                       "the waveform strip seeks the whole session"),
        ("LEFT/RIGHT", "previous / next bar (SHIFT: 10 s)"),
        (", .", "previous / next event marker"),
        ("UP/DOWN", "previous / next section start"),
        ("+ - 0", "zoom in / out / reset (about the playhead)"),
        ("drag ruler", "select a range: playback loops inside the "
                       "green box and B bounces it — any seek (or L) "
                       "clears it"),
        ("HOME/END", "start / end"),
        ("M / S", "mute / solo the selected track (click a track "
                  "name to select; boxes always work)"),
        ("A", "A/B: hear the PREVIOUS mix (undo of a hot-swap)"),
        ("G  or click clock", "type a time (mm:ss or seconds), ENTER"),
        ("C", "copy 'mm:ss / bar / bank' for feedback notes"),
        ("B", "bounce loop region (or full mix) to a wav"),
        ("R", "full reload — re-read every file, retry audio/video"),
        ("ESC", "close overlay / cancel entry / quit (session is "
                "saved and restored)"),
    ]
    HELP_LEGEND = [
        ((240, 200, 100), "▽", "jump — the form leapt to a new bar "
                               "(soft loop steers ~s are not drawn)"),
        ((200, 120, 220), "△+line", "riser: 2-bar swell into its "
                                    "strike (the tall tick)"),
        ((255, 120, 80), "△", "half-riser (ambush swell)"),
        ((240, 220, 160), "●", "sting (win hit)"),
        ((160, 220, 255), "◆", "stab (damage hit)"),
        ((255, 70, 70), "▌span", "death halt — ALL music dead until "
                                 "the next bar tap"),
        ((255, 200, 120), "hatch", "bank rotation crossfade — the old "
                                   "bank is still fading out here"),
    ]

    def _wrap(self, s, maxw):
        """Word-wrap for the help overlay: help never truncates."""
        words, lines, cur = s.split(" "), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if text.measure(trial, self.font)[0] > maxw and cur:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines

    def _draw_help(self, scr):
        fb2d.alpha_fill(scr, (0, 0, 0), 235)
        self.txt("KEYS", 80, 40, (240, 220, 160), self.big)
        y = 74
        for k, desc in self.HELP_KEYS:
            self.txt(k, 80, y, (255, 240, 200))
            for ln in self._wrap(desc, 440):
                self.txt(ln, 260, y, (190, 190, 200))
                y += 18
            y += 8
        self.txt("MARKERS", 740, 40, (240, 220, 160), self.big)
        y = 74
        for col, glyph, desc in self.HELP_LEGEND:
            self.txt(glyph, 740, y, col)
            for ln in self._wrap(desc, 450):
                self.txt(ln, 800, y, (190, 190, 200))
                y += 18
            y += 10
        for para in (
                "Values vs faders: P/C/S curves are the game's "
                "DECISIONS; lane heights are the gains it chose.",
                "Replace-and-hear: overwrite any stem in a bank "
                "folder — the mix rebuilds at the same playhead."):
            y += 12
            for ln in self._wrap(para, 450):
                self.txt(ln, 740, y, (170, 190, 170))
                y += 18
        self.txt("? or ESC closes", 80, self.H - 40, (150, 150, 165))

    MARK_TIPS = {
        "music_jump": "Jump — the form leapt to a new bar (soft ~s "
                      "steers are not drawn)",
        "music_riser": "Riser — 2-bar swell into its strike (the "
                       "tall tick)",
        "music_riser2": "Half-riser — ambush swell",
        "music_sting": "Sting — win hit",
        "music_stab": "Stab — damage hit",
        "music_halt": "Death halt — ALL music dead until the next "
                      "bar tap",
        "xfade": "Bank rotation crossfade — the old bank is still "
                 "fading out here",
    }

    @staticmethod
    def _mark_glyph(surf, kind, x, ry):
        """One glyph vocabulary for the FX row AND its legend — they
        can never drift apart."""
        if kind == "music_halt":
            fb2d.line(surf, (255, 70, 70), (x, ry + 1),
                             (x, ry + 20), 2)
        elif kind == "music_sting":
            fb2d.circle(surf, (240, 220, 160), (x, ry + 10), 4)
        elif kind == "music_stab":
            fb2d.polygon(surf, (160, 220, 255),
                                [(x, ry + 4), (x + 4, ry + 10),
                                 (x, ry + 16), (x - 4, ry + 10)])
        elif kind == "music_riser":
            fb2d.polygon(surf, (200, 120, 220),
                                [(x, ry + 18), (x - 4, ry + 4),
                                 (x + 4, ry + 4)])
        elif kind == "music_riser2":
            fb2d.polygon(surf, (255, 120, 80),
                                [(x, ry + 18), (x - 3, ry + 8),
                                 (x + 3, ry + 8)])
        elif kind == "music_jump":
            fb2d.polygon(surf, (240, 200, 100),
                                [(x, ry + 4), (x - 3, ry + 14),
                                 (x + 3, ry + 14)])
        elif kind == "xfade":
            for i in (-5, -1, 3):
                fb2d.line(surf, (255, 200, 120),
                                 (x + i - 2, ry + 16),
                                 (x + i + 3, ry + 5))

    TOOLTIPS = {
        "play_glyph": "Play / pause (SPACE)",
        "time_readout": "Click, type a time (mm:ss or seconds), "
                        "ENTER jumps",
        "bank_title": "Click: score the pass under the playhead with "
                      "a different bank (its neighbors keep theirs)",
        "clip_chip": "Mix over full scale — click: jump to the "
                     "loudest point; click again: reset",
        "ab_chip": "Hearing the previous mix — click or A returns",
        "video_monitor": "Click: enlarge video",
        "help_glyph": "All keys + marker legend (?)",
        "ruler": "Drag: select a range — playback loops inside it, "
                 "B bounces it. Click: seek (clears the selection).",
        "curve:0": "PRAYER value - click to show/hide the curve",
        "curve:1": "CONTEMPT value - click to show/hide the curve",
        "curve:2": "STALWART value - click to show/hide the curve",
    }

    def _tooltip_for(self, el):
        if el.startswith("chipfull:"):
            return self._chip_full.get(el)
        if el.startswith(("mark:", "legend:")):
            return self.MARK_TIPS.get(el.split(":")[1])
        if el in self.TOOLTIPS:
            return self.TOOLTIPS[el]
        if el.startswith("mute:"):
            return f"Mute '{el[5:]}' (re-mixes in ~1s)"
        if el.startswith("solo:"):
            return f"Solo '{el[5:]}' (re-mixes in ~1s)"
        if el.startswith("name:"):
            return (f"Click: select '{el[5:]}' — M/S keys then "
                    f"mute/solo it")
        return None

    def _draw_tooltip(self):
        if self.picker or self.video_big or self.help_on or \
                self._goto is not None:
            return
        mx, my = self.display.mouse_pos
        over = next((el for el, r in self._hit.items()
                     if r.collidepoint(mx, my)), None)
        if over != self._hover[0]:
            self._hover = (over, time.time())
            return
        if over is None:
            return
        dwell = 0.15 if over.startswith("chipfull:") else 0.45
        if time.time() - self._hover[1] < dwell:
            return
        tip = self._tooltip_for(over)
        if not tip:
            return
        lines = self._wrap(tip, 480)
        w = max(text.measure(l, self.font)[0] for l in lines)
        h = 18 * len(lines)
        tx = min(mx + 14, self.W - w - 14)
        ty = min(my + 18, self.H - h - 12)
        fb2d.rect(self.screen, (235, 225, 180),
                         (tx - 6, ty - 4, w + 12, h + 8))
        fb2d.rect(self.screen, (120, 110, 80),
                         (tx - 6, ty - 4, w + 12, h + 8), 1)
        for i, l in enumerate(lines):
            text.blit_text(self.screen, l, tx, ty + i * 18,
                           (20, 20, 24), self.font)

    # ---- main loop --------------------------------------------------------
    def step(self):
        # selection = loop: the playhead lives inside the green box —
        # wraps at the end, clamped if it's somehow outside (box just
        # created elsewhere, or restored by session recall)
        if self.loop:
            a, b = self.loop
            ph = self.player.playhead()
            if self.player.playing and ph >= b - 0.02:
                self._seek(a)
            elif ph < a - 0.02 or ph > b + 0.02:
                self._seek(a)
        # follow-playhead while zoomed
        if self.view and self.player.playing:
            v0, v1 = self.view
            t = self.player.playhead()
            if t > v1 - (v1 - v0) * 0.05 or t < v0:
                span = v1 - v0
                nv0 = max(0.0, min(t - span * 0.1,
                                   self.proj.dur - span))
                self.view = (nv0, nv0 + span)
                self._static = None
        # arrow-key repeat (manual: repeat must not reach M/S/etc)
        if self._arrow_held:
            k, mod, t0, last = self._arrow_held
            now = time.time()
            if now >= t0 and now - last >= 0.07:
                self._arrow_step(k, mod)
                self._arrow_held = (k, mod, t0, now)
        # watcher watchdog: a dead thread restarts, visibly
        if not self._watch_thread.is_alive() and not self._quit:
            self._note("watcher died — restarted", "err")
            self._watch_thread = threading.Thread(target=self._watch,
                                                  daemon=True)
            self._watch_thread.start()

    def run(self):
        clock = mgui.Clock()
        running = True
        while running:
            evs, self.injected = self.injected, []
            evs.extend(self.display.events())
            for ev in evs:
                if ev.type == uievent.QUIT or not self.handle(ev):
                    running = False
                    break               # no ghost events after quit
            self.step()
            self.draw()
            # while the modal is up every UI frame steals GIL time
            # from the render thread — 24fps is plenty for a progress
            # bar and buys the mixer its core back
            clock.tick(24 if self.player.buf is None else 60)
        self._quit = True
        self._save_session()
        self.video.stop()           # no orphaned ffmpeg after quit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rec", nargs="?", default=str(DEFAULT_REC),
                    help="recording dir (events.jsonl) or the file")
    ap.add_argument("--video", default=None,
                    help="mp4 for the frame monitor (default: the "
                         "winning-session video when rec is default)")
    ap.add_argument("--use", default=None, metavar="BANK",
                    help="audition ONE bank (e.g. album_mytrack) under "
                         "this session's decisions, replacing all the "
                         "session's banks")
    a = ap.parse_args()
    rec = Path(a.rec)
    if not (rec / "events.jsonl").exists() and not rec.is_file():
        raise SystemExit(f"recording not found: {rec} (need a dir "
                         f"with events.jsonl, or the file itself)")
    video = Path(a.video) if a.video else \
        (DEFAULT_VIDEO if Path(a.rec) == DEFAULT_REC else None)
    # the toolchain's headless convention (captures, soaks, CI)
    headless = os.environ.get("SDL_VIDEODRIVER") == "dummy"
    App(rec, video, headless=headless, use=a.use).run()


if __name__ == "__main__":
    main()
