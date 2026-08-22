"""daw_fault_suite — §15 fault injection for the session DAW.

    uv run python tools/musicgen/daw_fault_suite.py

Every P0 lie from DAW_UX_PLAN.md is FORCED and the INDICATOR (not
just the audio) is asserted. Runs against a synthetic 35s recording +
two synthetic banks in a temp dir grafted onto MUSIC_ROOTS — no real
bank is ever touched, every force is fast, and partial suite failures
name their force. Exit 0 only if every force passes.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/musicgen"))
sys.path.insert(0, str(ROOT / "tools/playtest"))
import daw                                              # noqa: E402
import mkvideo as MK                                    # noqa: E402
from perihelion import uievent                          # noqa: E402

RATE = 44100
BPM = 110.0
BAR_S = 240.0 / BPM
BARS = 8
N_BAR = int(BAR_S * RATE)
F0 = 220.0          # fixture prayer tone; replacements use 330
TMP = Path(tempfile.mkdtemp(prefix="daw_faults_"))
BANKROOT = TMP / "banks"
REC = TMP / "rec"
MK.MUSIC_ROOTS.append(BANKROOT)

PASSED, FAILED = [], []


# ---------------------------------------------------------------- fixtures
def tone(freq, n, amp=0.2):
    t = np.arange(n) / RATE
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([x, x], axis=1)


def clicks(n, amp=0.3):
    x = np.zeros(n, np.float32)
    x[:: RATE // 4] = amp
    return np.stack([x, x], axis=1)


def wwav(path, data, sr=RATE, subtype="PCM_16"):
    sf.write(str(path), data, sr, subtype=subtype)


def make_bank(name, f0):
    d = BANKROOT / name
    d.mkdir(parents=True, exist_ok=True)
    n = N_BAR * BARS
    wwav(d / "prayer.wav", tone(f0, n))
    wwav(d / "bed_t3.wav", tone(f0 * 0.75, n, 0.15))
    wwav(d / "drums.wav", clicks(n))
    wwav(d / "bass_brute.wav", tone(55, n, 0.25))
    wwav(d / "lead_smg.wav", tone(f0 * 2, n, 0.15))
    wwav(d / "riser.wav", tone(600, 2 * N_BAR, 0.2))
    wwav(d / "riser_half.wav", tone(700, N_BAR, 0.2))
    wwav(d / "sting.wav", tone(880, RATE // 2, 0.3))
    wwav(d / "stab.wav", tone(120, RATE // 3, 0.3))
    wwav(d / "prayer_tail.wav",
         tone(f0, N_BAR) * np.linspace(1, 0, N_BAR)[:, None])
    (d / "bank.json").write_text(json.dumps(dict(
        title=f"tutti_{name.removeprefix('album_')}", bpm=BPM,
        bars=BARS, sections=[["vigil", 0, 4], ["develop", 4, 8]])))
    return d


def bar_ev(t, idx, lanes):
    body = "|".join(f"{ln}:{k}:{g:.3f}" for ln, k, g in lanes)
    return dict(t=t, kind="music_bar", name=f"{idx}|{body}",
                vol=1.0, pan=0.5)


def make_rec():
    REC.mkdir(parents=True, exist_ok=True)
    evs = [dict(t=0.0, kind="music_bank", name="album_fitest",
                vol=1.0, pan=0.5)]
    for k in range(14):
        t = k * BAR_S
        lanes = [("holy", "prayer", 0.5), ("bed", "bed_t3", 0.4)]
        if 2 <= k <= 5:
            lanes.append(("drums", "drums", 0.7))
        if k == 3:
            lanes.append(("bass", "bass_brute", 0.6))
        if k == 4:
            lanes.append(("bass", "bass_brute~f", 0.6))
        if 4 <= k <= 6:
            lanes.append(("lead", "lead_smg", 0.5))
        if k == 10:
            evs.append(dict(t=t, kind="music_bank",
                            name="album_fitest2", vol=1.0, pan=0.5))
        evs.append(bar_ev(t, k + 1, lanes))
        evs.append(dict(t=t, kind="music_valslp",
                        name="0.80,0.20,0.10", vol=1.0, pan=0.5))
    evs.append(dict(t=5 * BAR_S, kind="music_jump", name="12",
                    vol=1.0, pan=0.5))
    evs.append(dict(t=6 * BAR_S, kind="music_jump", name="3~s",
                    vol=1.0, pan=0.5))
    evs.append(dict(t=4 * BAR_S + 0.1, kind="music_riser", name="0.6",
                    vol=1.0, pan=0.5))
    evs.append(dict(t=6 * BAR_S, kind="music_riser", name="0.0",
                    vol=1.0, pan=0.5))
    evs.append(dict(t=7 * BAR_S, kind="music_riser2", name="0.8",
                    vol=1.0, pan=0.5))
    evs.append(dict(t=8 * BAR_S, kind="music_sting", name="1",
                    vol=1.0, pan=0.5))
    evs.append(dict(t=8.5 * BAR_S, kind="music_stab", name="1",
                    vol=1.0, pan=0.5))
    evs.append(dict(t=9 * BAR_S + 1.0, kind="music_halt", name="0",
                    vol=1.0, pan=0.5))
    evs.sort(key=lambda e: e["t"])
    (REC / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in evs))


# ---------------------------------------------------------------- helpers
def mk_app(rec=REC, video=None, use=None):
    (rec / "daw_session.json").unlink(missing_ok=True)
    return daw.App(rec, video, headless=True, use=use)


def wait(pred, timeout=30, what=""):
    t0 = time.time()
    while not pred():
        time.sleep(0.05)
        if time.time() - t0 > timeout:
            raise AssertionError(f"timeout waiting for {what}")


def ready(app, timeout=30):
    wait(lambda: app.status.startswith("ready"), timeout,
         f"ready (status={app.status!r})")


def has_note(app, sub):
    return any(sub in txt for _, txt, _ in app.notes)


def close(app):
    app._quit = True
    app.player.pause()


def peak_freq(buf, t0, t1):
    seg = buf[int(t0 * RATE):int(t1 * RATE), 0].astype(np.float32)
    F = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    return float(np.fft.rfftfreq(len(seg), 1 / RATE)[int(F.argmax())])


def force(name):
    def deco(fn):
        fn._force = name
        return fn
    return deco


def restore(name="prayer.wav", f=F0, bank="album_fitest"):
    wwav(BANKROOT / bank / name, tone(f, N_BAR * BARS))


# ---------------------------------------------------------------- forces
@force("P0.1 48k wav → red message, old mix keeps playing")
def f_48k(app):
    old_buf = app.player.buf
    d = tone(F0, int(48000 * BAR_S * BARS))
    sf.write(str(BANKROOT / "album_fitest/prayer.wav"), d, 48000,
             subtype="PCM_16")
    wait(lambda: app.status.startswith("RENDER FAILED")
         and "48 kHz" in app.status, 15, "48k refusal")
    assert app.status_kind == "err"
    assert app.player.buf is old_buf, "old mix was dropped"
    # the currency chip may not claim 'current' over a failed rebuild
    assert app._built_change < app._change_no, \
        "audio claimed current while the new file failed to render"
    restore()
    ready(app)
    wait(lambda: app._built_change >= app._change_no, 5,
         "currency restored")


@force("P0.1 24-bit wav → red message names the fix")
def f_24bit(app):
    wwav(BANKROOT / "album_fitest/prayer.wav",
         tone(F0, N_BAR * BARS), subtype="PCM_24")
    wait(lambda: app.status.startswith("RENDER FAILED")
         and "24-bit" in app.status, 15, "24-bit refusal")
    restore()
    ready(app)


@force("P0.6 aiff drop → 'export WAV/OGG', no rebuild")
def f_aiff(app):
    n0 = app.mix_no
    (BANKROOT / "album_fitest/prayer.aiff").write_bytes(b"\0" * 500)
    wait(lambda: has_note(app, "export WAV/OGG"), 10, "aiff note")
    time.sleep(2.0)
    assert app.mix_no == n0, "aiff triggered a rebuild"
    (BANKROOT / "album_fitest/prayer.aiff").unlink()
    app.notes.clear()


@force("P0.6 misnamed wav → 'not a stem this session plays'")
def f_misnamed(app):
    n0 = app.mix_no
    wwav(BANKROOT / "album_fitest/prayer (1).wav", tone(F0, N_BAR))
    wait(lambda: has_note(app, "not a stem this session plays"), 10,
         "misnamed note")
    time.sleep(2.0)
    assert app.mix_no == n0, "misnamed file triggered a rebuild"
    (BANKROOT / "album_fitest/prayer (1).wav").unlink()
    app.notes.clear()


@force("P0.2 truncated wav → RENDER FAILED, old mix playable")
def f_truncated(app):
    old_buf = app.player.buf
    (BANKROOT / "album_fitest/drums.wav").write_bytes(
        b"RIFF\x00\x00\x00\x00WAVEfmt garbage")
    wait(lambda: app.status.startswith("RENDER FAILED"), 15,
         "truncated refusal")
    assert app.player.buf is old_buf
    d = BANKROOT / "album_fitest"
    wwav(d / "drums.wav", clicks(N_BAR * BARS))
    ready(app)


@force("P0.4+36 slow 3-chunk copy → settle ack, ONE rebuild, final file")
def f_slow_copy(app):
    n0 = app.mix_no
    seen = set()
    stop = threading.Event()

    def spy():
        while not stop.is_set():
            seen.add(app.status.split("(")[0].strip())
            time.sleep(0.03)
    th = threading.Thread(target=spy, daemon=True)
    th.start()
    # a DAW bounce lands in chunks: write thirds, 0.35s apart
    full = tone(330.0, N_BAR * BARS)
    tmp = BANKROOT / "album_fitest/prayer.wav"
    import io as _io
    b = _io.BytesIO()
    sf.write(b, full, RATE, subtype="PCM_16", format="WAV")
    raw = b.getvalue()
    third = len(raw) // 3
    with open(tmp, "wb") as fh:
        fh.write(raw[:third]); fh.flush(); os.fsync(fh.fileno())
        time.sleep(0.35)
        fh.write(raw[third:2 * third]); fh.flush(); os.fsync(fh.fileno())
        time.sleep(0.35)
        fh.write(raw[2 * third:])
    ready(app, 30)
    stop.set()
    assert app.mix_no == n0 + 1, \
        f"expected exactly ONE rebuild, got {app.mix_no - n0}"
    assert app._built_change >= app._change_no, \
        "chip still claims NOT LATEST after the rebuild landed"
    assert any(s.startswith("detected") for s in seen), \
        f"no settle acknowledgement seen: {seen}"
    assert not any(s.startswith("RENDER FAILED") for s in seen), \
        "a partial file reached the renderer"
    pf = peak_freq(app.player.buf, 0.2, BAR_S)
    assert abs(pf - 330.0) < 15, f"mix is not the FINAL file ({pf}Hz)"


@force("P0.5 short stem → 'later bars silent' warning, render ok")
def f_short_stem(app):
    wwav(BANKROOT / "album_fitest/lead_smg.wav",
         tone(F0 * 2, 2 * N_BAR, 0.15))
    wait(lambda: any("later bars silent" in m and "lead_smg" in m
                     for m, _ in app.health), 15, "short-stem warning")
    ready(app)
    restore("lead_smg.wav", F0 * 2)
    ready(app)
    wait(lambda: not any("lead_smg" in m for m, _ in app.health), 10,
         "warning cleared")


@force("P0.3 watcher: exception survives; dead thread restarts")
def f_watchdog(app):
    real_scan = app._scan
    state = {"boom": True}

    def bad_scan():
        if state["boom"]:
            state["boom"] = False
            raise RuntimeError("injected")
        return real_scan()
    app._scan = bad_scan
    wait(lambda: has_note(app, "watcher error"), 10, "watcher error note")
    beat0 = app._watch_beat
    wait(lambda: app._watch_beat > beat0, 10, "watcher kept beating")
    app._scan = real_scan

    class Dead:
        @staticmethod
        def is_alive():
            return False
    app._watch_thread = Dead()
    app.step()
    assert app._watch_thread.is_alive(), "watchdog did not restart"
    assert has_note(app, "watcher died — restarted")
    app.notes.clear()


@force("P0.9 mute+solo same lane → mute wins, display agrees")
def f_mute_solo(app):
    app.muted, app.solo = {"drums"}, {"drums"}
    app.rebuild(src="mutes")
    ready(app)
    assert app._is_muted("drums"), "display rule says drums plays"
    assert int(np.abs(app.player.buf).max()) == 0, \
        "muted+soloed lane audibly played"
    app.muted, app.solo = set(), set()
    app.rebuild(src="mutes")
    ready(app)


@force("P0.12 M/S spam → coalesced, final state correct")
def f_spam(app):
    rms0 = float(np.sqrt((app.player.buf.astype(np.float64) ** 2)
                         .mean()))
    for _ in range(3):      # 6 toggles = even = back to baseline
        app.muted ^= {"drums"}
        app.rebuild(src="mutes")
        app.muted ^= {"drums"}
        app.rebuild(src="mutes")
    ready(app)
    rms1 = float(np.sqrt((app.player.buf.astype(np.float64) ** 2)
                         .mean()))
    assert abs(rms1 - rms0) < 1.0, f"final mix wrong ({rms0}→{rms1})"
    assert not app.muted


@force("addendum 31 superseded render may not write CLIP")
def f_stale_clip(app):
    app.clip = "SENTINEL"
    n0 = app.mix_no
    app._render(daw._apply_mutes(app.proj.events, set(), set()),
                app._gen - 1, "stale", True)
    assert app.clip == "SENTINEL", "stale render wrote the CLIP verdict"
    assert app.mix_no == n0
    app.clip = False


@force("addendum 30 audio-backend death → err + kept playhead + R heals")
def f_audio_death(app):
    app.player.seek(4.0)

    class Boom:
        def play(self, *a):
            raise RuntimeError("device gone")

        def queue(self, *a):
            raise RuntimeError("device gone")

        def stop(self):
            raise RuntimeError("device gone")

        def get_queue(self):
            raise RuntimeError("device gone")

        def get_busy(self):
            return False
    app.player.ch = Boom()
    app.player.play()
    assert app.player.err, "audio death not surfaced"
    assert not app.player.playing
    assert app.player.retry(), "retry failed on a live backend"
    assert app.player.err is None


@force("video: REAL playback at native rate; frame_for race-free")
def f_video_playback(app):
    vid = ROOT / "out/gauntlet_winning_session_v1.mp4"
    vp = daw.VideoPlayer(vid)
    try:
        assert abs(vp.fps - 15.0) < 0.01, f"probed fps {vp.fps}"
        # sweep a 3s playback clock; every native frame must present
        seen = set()
        t0 = time.time()
        base = 100.0
        while time.time() - t0 < 4.0:
            vf = vp.frame_for(base + (time.time() - t0))
            if vf is not None:
                seen.add(round(vf[0], 3))
            time.sleep(1 / 60)
        assert len(seen) >= 40, \
            f"only {len(seen)} distinct frames in ~4s (want ~60 @15fps)"
        # concurrent frame_for/seek hammer across restarts → no crash
        errs = []

        def hammer():
            for i in range(200):
                try:
                    vp.frame_for(base + (i % 37))
                except Exception as exc:
                    errs.append(exc)
        ths = [threading.Thread(target=hammer) for _ in range(2)]
        [t.start() for t in ths]
        [t.join() for t in ths]
        assert not errs, f"frame_for raced: {errs[0]}"
        # backward seek restarts and lands on-frame
        vp.frame_for(50.0)
        wait(lambda: vp.frame_for(50.0) is not None
             and abs(vp.frame_for(50.0)[0] - 50.0) < 0.5, 10,
             "backward seek on-frame")
    finally:
        vp.stop()


@force("P0.11 ffmpeg missing → one red line, no spawn storm")
def f_no_ffmpeg(app):
    vid = ROOT / "out/gauntlet_winning_session_v1.mp4"
    real_popen = daw.subprocess.Popen
    calls = []

    def no_ffmpeg(*a, **k):
        calls.append(1)
        raise FileNotFoundError("ffmpeg")
    vp = daw.VideoPlayer(vid)
    daw.subprocess.Popen = no_ffmpeg
    try:
        vp.frame_for(1.0)
        assert vp.err and "ffmpeg not found" in vp.err
        n = len(calls)
        for i in range(20):
            vp.frame_for(float(i))
        assert len(calls) == n, "spawn storm after ffmpeg death"
    finally:
        daw.subprocess.Popen = real_popen
        vp.stop()


@force("P0.11 missing video file → red, not a silent non-feature")
def f_no_video(app):
    vp = daw.VideoPlayer(Path("/nonexistent/session.mp4"))
    assert vp.err and "not found" in vp.err


@force("addendum 33c mp4 overwrite → stream restarts on new content")
def f_mp4_swap(app):
    m = TMP / "tiny.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=red:s=64x36:d=3", str(m)], check=True)
    vp = daw.VideoPlayer(m)
    try:
        wait(lambda: vp.frame_for(1.0) is not None, 10, "first frame")
        gen0 = vp._gen
        os.utime(m, (time.time() + 5, time.time() + 5))
        vp._stat_t = 0.0
        vp.frame_for(1.0)
        assert vp._gen > gen0, "mtime change did not restart the stream"
        wait(lambda: vp.frame_for(1.0) is not None, 10,
             "fresh frames after overwrite")
    finally:
        vp.stop()


@force("addendum 34 wrong-session video → correspondence warning")
def f_wrong_video(app):
    m = TMP / "tiny.mp4"
    a2 = mk_app(video=m)
    try:
        wait(lambda: "wrong session" in a2.video_note, 15,
             "correspondence warning")
    finally:
        close(a2)


@force("addendum 35 PRAYER.WAV → case warning, not a silent no-op")
def f_case(app):
    wwav(BANKROOT / "album_fitest/PRAYER.WAV", tone(F0, N_BAR))
    wait(lambda: has_note(app, "case matters"), 10, "case note")
    (BANKROOT / "album_fitest/PRAYER.WAV").unlink()
    app.notes.clear()


@force("addendum 35 mtime-preserving restore → size key catches it")
def f_mtime_restore(app):
    p = BANKROOT / "album_fitest/prayer.wav"
    v1 = daw._cached_load_stem(p)
    st = p.stat()
    wwav(p, tone(330.0, N_BAR * BARS + 777))   # different size
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    v2 = daw._cached_load_stem(p)
    assert len(v1) != len(v2), "stale cache served after restore"
    n0 = app.mix_no
    wait(lambda: app.mix_no > n0, 15, "watcher caught size-only change")
    ready(app)
    restore()
    ready(app)


@force("P0.7 reload into muted lane → note condition holds")
def f_muted_reload(app):
    app.muted = {"drums"}
    app.rebuild(src="mutes")
    ready(app)
    wwav(BANKROOT / "album_fitest/drums.wav", clicks(N_BAR * BARS))
    wait(lambda: app._last_reload
         and "drums" in app._last_reload[1], 15, "reload lanes")
    ready(app)
    dead = {ln for ln in app._last_reload[1] if app._is_muted(ln)}
    assert dead == {"drums"}, f"muted-lane chip wouldn't show: {dead}"
    app.muted = set()
    app.rebuild(src="mutes")
    ready(app)


@force("P0.7 companion stem note (prayer without prayer_tail)")
def f_companion(app):
    restore()
    wait(lambda: has_note(app, "prayer_tail"), 15, "companion note")
    ready(app)
    app.notes.clear()


@force("P0.8 renamed bank dir → red health line names the silence")
def f_renamed_bank(app):
    src, dst = BANKROOT / "album_fitest2", BANKROOT / "album_fitest2_x"
    os.rename(src, dst)
    try:
        wait(lambda: any("bank not found" in m and "fitest2" in m
                         for m, _ in app.health), 20, "red bank line")
    finally:
        os.rename(dst, src)
    wait(lambda: not any("bank not found" in m for m, _ in app.health),
         20, "bank recovered")
    ready(app)


@force("P0.8 bank.json edit → ruler re-parses (no stale sections)")
def f_bankjson_edit(app):
    p = BANKROOT / "album_fitest/bank.json"
    meta = json.loads(p.read_text())
    meta["sections"][0][0] = "ritual"
    p.write_text(json.dumps(meta))
    wait(lambda: app.proj.banks[0][3] is not None
         and app.proj.banks[0][3]["sections"][0][0] == "ritual", 20,
         "sections reparse")
    ready(app)
    meta["sections"][0][0] = "vigil"
    p.write_text(json.dumps(meta))
    wait(lambda: app.proj.banks[0][3]["sections"][0][0] == "vigil", 20,
         "sections restored")
    ready(app)


@force("addendum 37 scrub storm during hot-swaps → no torn state")
def f_scrub_race(app):
    errs = []
    stop = threading.Event()

    def scrub():
        i = 0
        while not stop.is_set():
            try:
                app._seek((i % 30) + 0.1)
            except Exception as exc:
                errs.append(exc)
            i += 1
    th = threading.Thread(target=scrub, daemon=True)
    th.start()
    for _ in range(3):
        app.rebuild(src="race")
        ready(app)
    stop.set()
    th.join(1)
    assert not errs, f"seek raced the swap: {errs[0]}"
    assert 0 <= app.player.playhead() <= app.proj.dur


@force("item 42 overview bins align to the ruler span")
def f_overview_align(app):
    buf = app.player.buf
    nz = np.nonzero(np.abs(buf[:, 0]) > 3)[0]
    t_end = nz[-1] / RATE
    ov = app.overview[0]
    w = len(ov)
    i_end = int(t_end / app.proj.dur * w)
    assert ov[max(0, i_end - 3):i_end].max() > 0.001, \
        "audio missing just before its true end"
    tail = ov[min(w, i_end + 3):]
    assert tail.size == 0 or tail.max() < 0.01, \
        f"energy drawn {((w - i_end) * app.proj.dur / w):.1f}s past the end"


@force("item 40 crossfade window modeled + transitional title")
def f_xfade(app):
    assert len(app.proj.xfades) == 1
    t0, t1, old, new = app.proj.xfades[0]
    assert abs((t1 - t0) - 2 * BAR_S) < 0.01
    assert app.proj.xfade_at((t0 + t1) / 2) == (old, new)
    assert old == "tutti_fitest" and new == "tutti_fitest2"
    assert app.proj.xfade_at(t1 + 0.1) is None


@force("item 41 ~f stripped at parse, drawn as fade")
def f_farewell(app):
    bar4 = app.proj.bars[4]
    key, g, fade = bar4[2]["bass"]
    assert key == "bass_brute" and fade is True
    assert not any("~f" in k for k in app.proj.played_keys)


@force("P0.14 halts + stab markers modeled")
def f_marks(app):
    assert len(app.proj.halts) == 1
    ht, resume = app.proj.halts[0]
    nxt = min(b[0] for b in app.proj.bars if b[0] > ht)
    assert resume == nxt
    kinds = {k for _, k, _ in app.proj.marks}
    assert {"music_stab", "music_sting", "music_riser",
            "music_riser2", "music_jump", "music_halt"} <= kinds
    assert len(app.proj.riser_spans) == 1


@force("P1.17 NO-TAPS recording explains its dead transport")
def f_no_taps(app):
    r2 = TMP / "rec_notaps"
    r2.mkdir(exist_ok=True)
    (r2 / "events.jsonl").write_text(json.dumps(
        dict(t=0.0, kind="music_bank", name="album_fitest",
             vol=1.0, pan=0.5)) + "\n" + json.dumps(
        dict(t=5.0, kind="frame", name="x", vol=1.0, pan=0.5)))
    a2 = mk_app(rec=r2)
    try:
        wait(lambda: "no music taps" in a2.status, 20, "no-taps status")
        assert a2.status_kind == "err"
        a2.handle(uievent.Event(uievent.KEYDOWN,
                                key=uievent.K_SPACE, mod=0,
                                unicode=" "))
        assert has_note(a2, "still rendering") or a2.player.buf is None
    finally:
        close(a2)


@force("P0.13 CLI startup failures are clean messages")
def f_cli(app):
    env = dict(os.environ, SDL_VIDEODRIVER="dummy",
               SDL_AUDIODRIVER="dummy")
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools/musicgen/daw.py"),
         "/nonexistent_rec"], capture_output=True, text=True, env=env,
        timeout=60)
    assert r.returncode != 0
    assert "recording not found" in r.stderr
    assert "Traceback" not in r.stderr, r.stderr
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools/musicgen/daw.py"),
         str(REC), "--use", "album_nope"], capture_output=True,
        text=True, env=env, timeout=60)
    assert r.returncode != 0
    assert "not a usable bank" in r.stderr
    assert "Traceback" not in r.stderr, r.stderr


@force("P1.16 session recall round-trip")
def f_recall(app):
    app.player.seek(12.0)
    app.muted = {"bed"}
    app.loop = (2.0, 4.0)
    app._save_session()
    a2 = daw.App(REC, None, headless=True)   # no session wipe here
    try:
        assert abs(a2.player.t - 12.0) < 0.2
        assert a2.muted == {"bed"}
        assert a2.loop == (2.0, 4.0)
        assert has_note(a2, "session restored")
        ready(a2)
    finally:
        close(a2)
        (REC / "daw_session.json").unlink(missing_ok=True)
    app.muted = set()
    app.loop = None
    app.rebuild(src="mutes")
    ready(app)
    # per-pass override recall: pass 1 re-scored, pass 0 untouched
    app._use = {1: "album_fitest"}
    app._save_session()
    a3 = daw.App(REC, None, headless=True)
    try:
        assert a3._use == {1: "album_fitest"}, a3._use
        assert a3.proj.banks[1][2] == "album_fitest"
        assert a3.proj.banks[0][2] == "album_fitest"
        assert a3.proj.orig_banks == ["album_fitest",
                                      "album_fitest2"]
        ready(a3)
    finally:
        close(a3)
        (REC / "daw_session.json").unlink(missing_ok=True)
    app._use = {}


@force("P1.15 A/B toggles to the PREVIOUS mix and back")
def f_ab(app):
    assert app.prev_mix is not None, "no previous mix after rebuilds"
    cur = app.player.buf
    app._toggle_ab()
    assert app.ab_prev and app.player.buf is app.prev_mix[0]
    app._toggle_ab()
    assert not app.ab_prev and app.player.buf is cur


@force("P1.17 SPACE at the end restarts from 0")
def f_end_restart(app):
    app.player.seek(app.player.end_t())
    app.player.play()
    assert app.player.playhead() < 1.0, "did not restart from 0"
    app.player.pause()
    app.player.seek(0.0)


@force("P1.17 loudness anchor never latches from a muted mix")
def f_anchor(app):
    a2 = mk_app()
    try:
        a2.muted = {"drums"}        # race the initial render
        a2.rebuild(src="mutes")
        ready(a2)
        muted_pk = float(np.abs(a2.player.buf).max())
        # the guard: either no latch yet (provisional scaling), or a
        # latch from the FULL mix — never 0.9 anchored to a muted peak
        if a2.anchor is not None:
            assert abs(muted_pk / 32767 - 0.9) > 0.02, \
                "anchor latched onto the MUTED mix's peak"
        a2.muted = set()
        a2.rebuild(src="mutes")
        ready(a2)
        assert a2.anchor is not None, "full mix did not latch anchor"
        assert not a2.clip, "full mix clipped under the latched anchor"
        assert abs(float(np.abs(a2.player.buf).max()) / 32767 - 0.9) \
            < 0.02, "full mix is not anchored at 0.9"
    finally:
        close(a2)


@force("P2 features: zoom, loop, bounce, marker/section jumps, goto, copy")
def f_features(app):
    app.player.pause()
    app.player.seek(10.0)
    app._zoom(2.0)
    v0, v1 = app.view
    assert abs((v1 - v0) - app.proj.dur / 2) < 1.0
    app.view = None
    # selection = loop: wraps at the end, clamps from outside, and a
    # NORMAL seek clears it (director's model)
    app.loop = (2.0, 4.0)
    app.player.seek(3.9)
    app.player.play()
    time.sleep(0.4)
    app.step()
    assert app.player.playhead() < 3.5, "selection did not loop"
    app.player.pause()
    app.player.seek(20.0)           # internal seek: box stays
    app.step()
    assert app.player.playhead() < 4.1, \
        "playhead escaped the selection (clamp missing)"
    # bounce the selection
    app._bounce()
    fn = REC / "bounce_0002-0004.wav"
    assert fn.exists()
    info = sf.info(str(fn))
    assert abs(info.frames - 2 * RATE) <= 2
    assert has_note(app, "bounced")
    # a user seek dismisses the selection
    app._seek_user(10.0)
    assert app.loop is None, "user seek did not clear the selection"
    assert abs(app.player.playhead() - 10.0) < 0.01
    # marker / section jumps
    app.player.seek(0.0)
    app._jump_mark(+1)
    first_mark = min(t for t, _, _ in app.proj.marks)
    assert abs(app.player.playhead() - first_mark) < 0.01
    app.player.seek(0.0)
    app._jump_sect(+1)
    assert abs(app.player.playhead() - app.proj.sect_starts[1]) < 0.01
    # goto
    app._goto = "0:05"
    app._goto_commit()
    assert abs(app.player.playhead() - 5.0) < 0.01
    app._goto = "junk"
    try:
        app._goto_commit()
    except Exception as exc:
        raise AssertionError(f"bad goto crashed: {exc}")
    # copy (clipboard may not exist headless — must not crash)
    app._copy_timestamp()
    assert has_note(app, "/ bar ") or has_note(app, "copied")


@force("picker: a brand-new bank (any name) appears immediately")
def f_new_bank(app):
    d = BANKROOT / "fresh_delivery"     # deliberately NOT album_*
    d.mkdir()
    (d / "bank.json").write_text(json.dumps(dict(
        title="tutti_fresh", bpm=110, bars=8,
        sections=[["vigil", 0, 8]])))
    try:
        assert "fresh_delivery" in app.available_banks(), \
            "new bank invisible to the picker"
    finally:
        shutil.rmtree(d)
    assert "fresh_delivery" not in app.available_banks()


@force("ONE bank.json schema: incomplete files gated with the fix "
       "named; a complete one-section bank scores")
def f_incomplete_bank(app):
    # a single-loop bank with the COMPLETE schema (the out/banks
    # single-loop builds after the 2026-07-18 data fix)
    good = BANKROOT / "single_loop"
    good.mkdir()
    (good / "bank.json").write_text(json.dumps(dict(
        melody="x", title="tutti_x_loop", bpm=110.0, bars=8,
        sections=[["develop", 0, 8]])))
    wwav(good / "prayer.wav", tone(220.0, N_BAR * BARS))
    # an incomplete one (no sections): data to be FIXED, not admitted
    bro = BANKROOT / "broken_bank"
    bro.mkdir()
    (bro / "bank.json").write_text(json.dumps(
        dict(melody="y", bpm=110.0, bars=8)))
    # fixture root only: the real repo's banks would push the
    # fixture's rows past the picker's visible cap
    real_roots = MK.MUSIC_ROOTS[:]
    MK.MUSIC_ROOTS[:] = [BANKROOT]
    a2 = mk_app()
    try:
        ready(a2)
        names = a2.available_banks()
        assert "single_loop" in names and "broken_bank" in names
        assert a2._bank_ok("single_loop"), "complete bank gated"
        assert not a2._bank_ok("broken_bank"), \
            "incomplete bank.json passed the gate"
        # the picker dims the incomplete one; clicking names the fix
        a2.picker = True
        a2.draw()
        r, nm, ok = next(row for row in a2._picker_rows
                         if row[1] == "broken_bank")
        assert not ok
        a2.handle(uievent.Event(uievent.MOUSEBUTTONDOWN, button=1,
                                pos=(r.centerx, r.centery)))
        assert a2._use == {} and has_note(a2, "incomplete bank.json")
        a2.picker = False
        # the complete single-loop bank scores end to end
        a2.set_bank("single_loop", pass_idx=0)
        assert a2.proj.section_at(0.1) == "develop"
        a2.draw()
        ready(a2)
        assert a2.proj.banks[0][2] == "single_loop"
        pf = peak_freq(a2.player.buf, 0.2, BAR_S)
        assert abs(pf - 220.0) < 15, "single-loop bank did not sound"
        # Project refuses the incomplete one cleanly, no traceback
        try:
            daw.Project(REC, use={0: "broken_bank"})
            raise AssertionError("incomplete bank accepted by Project")
        except SystemExit as exc:
            assert "sections" in str(exc)
    finally:
        MK.MUSIC_ROOTS[:] = real_roots
        close(a2)
        shutil.rmtree(good)
        shutil.rmtree(bro)
        (REC / "daw_session.json").unlink(missing_ok=True)


@force("render modal: timeline greyed whenever nothing is playable")
def f_render_modal(app):
    a2 = mk_app()
    try:
        def strip_mean(a):
            a.draw()
            px = a.screen                   # (W, H, 3) numpy frame
            return float(px[a.x0:a.x1,
                            a.y_sect:a.y_sect + 10].mean())
        ready(a2)
        bright = strip_mean(a2)
        a2.set_bank("album_fitest2")
        assert a2.player.buf is None, \
            "set_bank left the OLD score's audio playable"
        dim = strip_mean(a2)
        assert dim < bright * 0.75, \
            f"timeline not greyed during re-score ({dim:.0f} vs " \
            f"{bright:.0f})"
        ready(a2)
        assert a2.player.buf is not None
        assert strip_mean(a2) > dim * 1.2, "modal did not lift"
    finally:
        close(a2)


@force("addendum 38 quit-frame R spawns nothing")
def f_quit_purity(app):
    a2 = mk_app()
    try:
        ready(a2)
        gen0 = a2._gen
        a2.injected.append(uievent.Event(
            uievent.KEYDOWN, key=uievent.K_ESCAPE, mod=0, unicode=""))
        a2.injected.append(uievent.Event(
            uievent.KEYDOWN, key=uievent.K_r, mod=0, unicode="r"))
        a2.run()                    # returns on the ESC
        assert a2._gen == gen0, "R after quit spawned a rebuild"
    finally:
        close(a2)


# ---------------------------------------------------------------- runner
def main():
    make_bank("album_fitest", F0)
    make_bank("album_fitest2", 262.0)
    make_rec()
    app = mk_app()
    ready(app, 60)
    forces = [f_48k, f_24bit, f_aiff, f_misnamed, f_truncated,
              f_slow_copy, f_short_stem, f_watchdog, f_mute_solo,
              f_spam, f_stale_clip, f_audio_death, f_video_playback,
              f_no_ffmpeg, f_no_video, f_mp4_swap, f_wrong_video,
              f_case, f_mtime_restore, f_muted_reload, f_companion,
              f_renamed_bank, f_bankjson_edit, f_scrub_race,
              f_overview_align, f_xfade, f_farewell, f_marks,
              f_no_taps, f_cli, f_recall, f_ab, f_end_restart,
              f_anchor, f_features, f_new_bank, f_incomplete_bank,
              f_render_modal, f_quit_purity]
    for fn in forces:
        t0 = time.time()
        try:
            fn(app)
            PASSED.append(fn._force)
            print(f"PASS  {fn._force}  ({time.time() - t0:.1f}s)",
                  flush=True)
        except Exception as exc:
            FAILED.append((fn._force, exc))
            print(f"FAIL  {fn._force}: {type(exc).__name__}: {exc}",
                  flush=True)
    close(app)
    print(f"\n[daw_fault_suite] {len(PASSED)} passed, "
          f"{len(FAILED)} failed")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
