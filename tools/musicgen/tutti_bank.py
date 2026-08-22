"""Tutti -> dynamic chunk bank (task 33 core).

    uv run python tools/musicgen/tutti_bank.py [melody]

One lane-collecting compose() pass turns a finished album track into
the bank the in-game chunk-queue engine (music.py rich mode) consumes.
The form position advances through the REAL composition while the
factors gate lanes — the instrument then drives today's generator:

    prayer.wav    holy lane (monk, choir, bells) — the faith, always
    stalwart.wav  drums + wall (stereo) + bass + tells — the Test
    contempt.wav  fm bass + flourish — the dismissive machinery
    bed_t1..4     drone spine (one texture per section already)
    riser/sting   tension effect + accent
    lead_<w>      the lead lane re-voiced per weapon (10 renders)
    bass_<kind>   enemy cells on the recipe's fm voice

Known v1 limitation (logged): drums live in stalwart only, so a
pure-contempt state is drum-less until per-factor drum variants land.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_bank as GB          # noqa: E402  (ENEMY_CELLS patterns)
import gordon_chain as gc           # noqa: E402
import harmony                      # noqa: E402
import riffs                        # noqa: E402
import tr909_kit as K               # noqa: E402
import tutti as T                   # noqa: E402
import vital_bank as VB             # noqa: E402
from tutti import BAR, SR, STEP     # noqa: E402


def _dc_kill(x):
    """10Hz highpass at the write chokepoint: DC rides in from some
    patches (lhomme overlay pedal measured 0.065 mean, per-bar up to
    0.11) and every bar-boundary gain step on a DC pedestal is an
    audible click -- 'pops on every clip transition'. 10Hz leaves
    40Hz sub-bass untouched."""
    from scipy.signal import butter, sosfilt
    sos = butter(2, 10.0, btype="highpass", fs=SR, output="sos")
    if x.ndim == 2:
        return np.stack([sosfilt(sos, x[:, 0]),
                         sosfilt(sos, x[:, 1])], axis=1)
    return sosfilt(sos, x)


def _fold_tail(x, trim_n):
    """FL-style loopable render (director 2026-07-16): the render runs
    past the form end to catch the instruments' sustain; that extra
    chunk is SUMMED into chunk[0] before trimming, so any wrap or jump
    landing on bar 0 carries the ringing tail instead of a hard cut.
    (Linear playback just hears a slightly richer opening bar --
    exactly what an FL loopable render sounds like.)"""
    bar_n = int(BAR * SR)
    if len(x) < trim_n + bar_n // 4:
        return x                     # nothing rendered past the form
    tail = np.array(x[trim_n:trim_n + bar_n], dtype=x.dtype, copy=True)
    if len(tail) < bar_n:
        pad = [(0, bar_n - len(tail))] + [(0, 0)] * (x.ndim - 1)
        tail = np.pad(tail, pad)
    fade = int(0.1 * SR)
    env = np.linspace(1.0, 0.0, fade)
    if x.ndim == 2:
        tail[-fade:] *= env[:, None]
    else:
        tail[-fade:] *= env
    # RELEASE-LEVEL CAP (director: chunk0 came out 'way louder than
    # the rest' -- pad voices release at near-sustain level, so the
    # raw sum can double the head's energy). The folded bar may sit
    # at most ~+1dB over the stem's median bar; the added tail is
    # scaled to fit (decorrelated-power estimate, then verified).
    n_bar2 = bar_n
    def _rms(seg):
        return float(np.sqrt((seg ** 2).mean() + 1e-12))
    body = x[:n_bar2]
    bars = max(1, trim_n // n_bar2)
    med = float(np.median([_rms(x[i * n_bar2:(i + 1) * n_bar2])
                           for i in range(bars)]))
    cap = med * 1.12
    b, t = _rms(body), _rms(tail)
    k = 1.0
    if t > 1e-6 and (b ** 2 + t ** 2) ** 0.5 > cap:
        k = max(0.0, (max(0.0, cap ** 2 - b ** 2)) ** 0.5 / t)
    x[:n_bar2] = body + tail * k
    if _rms(x[:n_bar2]) > cap * 1.15 and k > 0:   # verify, correct once
        x[:n_bar2] = body + tail * (k * 0.6)
    return x


def _write(path, x, trim_n):
    import soundfile as sf
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    x = _dc_kill(x)
    dc = np.abs(x[:trim_n].mean(axis=0)).max()
    if dc > 0.003:
        raise ValueError(f"{path.name}: residual DC {dc:.4f} after "
                         f"highpass -- pops on every gain step")
    x = x[:trim_n]
    pk = np.abs(x).max()
    if pk > 1.0:
        x = x / pk
    sf.write(str(path), (np.clip(x, -1, 1) * 32767).astype(np.int16),
             SR, subtype="PCM_16")
    print(f"  {path.name:22s} {len(x)/SR:6.1f}s", flush=True)


def _assert_no_silent_bars(x, total_bars, name, floor_db=-15.0):
    """FAIL FAST at build time: a stem that SUDDENLY GOES SILENT FOR
    MULTIPLE BARS ships a lie -- the engine holds the lane 'on' while
    nothing sounds. A single quiet bar is a breath (director round 2:
    'it doesn't need to be literally constant'); two or more in a row
    crash the build."""
    n_bar = int(BAR * SR)
    rms = np.array([np.sqrt((x[i * n_bar:(i + 1) * n_bar] ** 2).mean()
                            + 1e-12) for i in range(total_bars)])
    med = float(np.median(rms))
    db = 20 * np.log10(rms / med)
    runs, start = [], None
    for i, v in enumerate(db):
        if v < floor_db and start is None:
            start = i
        elif v >= floor_db and start is not None:
            if i - start >= 2:
                runs.append((start, i - 1, round(float(db[start]), 1)))
            start = None
    if start is not None and total_bars - start >= 2:
        runs.append((start, total_bars - 1, round(float(db[start]), 1)))
    if runs:
        raise ValueError(f"{name}: silent for multiple bars at "
                         f"{runs} (below {floor_db}dB of median)")



_LAST_FILLS_TRACK = None


def _fill_monk_gaps(prayer, monk_far, total_bars, mel,
                    landing_bars=(), voice=None, monk_near=None):
    """The composed holy lane is kept verbatim ('the monk voice you
    had was perfect'); two kinds of hole get the DISTANT monk drifting
    in -- from his phrase start, faded, never a mid-phrase splice:
    - stretches of 2+ quiet bars (a single quiet bar is a breath);
    - any quiet LANDING bar (section starts): form steering jumps to
      those exact bars (every home-coming, every vigil-loop pass,
      every session start), so a breath there is a pothole -- the
      52.35s cut-to-nothing was the becalmed return landing on
      prayer[0] at -37dBFS.

    DETECTION RUNS ON THE VOICE, NOT THE COMPOSITE (2026-07-17, the
    night's hardest-won lesson): prayer = voice + spine*0.3, and the
    spine underlay kept every bar's RMS healthy while the VOICE sat
    in composed multi-bar rests -- the full-mix probe heard "cut-out
    -> gone 5-10s -> slam-in" at the SAME form positions across two
    different runs while every composite-RMS check said "present."
    Pass the bare holy lane as `voice`; fills are still summed into
    the composite.
    """
    n_bar = int(BAR * SR)
    out = prayer.copy()
    det = voice if voice is not None else out
    rms = np.array([np.sqrt((det[i * n_bar:(i + 1) * n_bar] ** 2).mean()
                            + 1e-12) for i in range(total_bars)])
    # median over SOUNDING bars only: with sparse phrase placement
    # the rests would drag a global median down and hide themselves
    snd_bars = rms[rms > 1e-4]
    med = float(np.median(snd_bars)) if len(snd_bars) else 1e-4
    db = 20 * np.log10(rms / med)
    if voice is not None:
        print("  voice map (dB rel sounding median): " +
              " ".join(f"{i}:{v:.0f}" for i, v in enumerate(db)),
              flush=True)
    # -15 rel median is the CODIFIED floor (same as the build crash
    # alarm). A -11 experiment filled media_vita's composed pianissimo
    # bars 4-5 and LOST the labeled A/B at that spot three rounds
    # running -- a quiet composed passage is not a dropout, and a fill
    # that fades away mid-stretch reads worse than honest quiet. The
    # law's scope is corrupted/silent samples, not soft bars.
    QUIET_DB = -15.0
    quiet = db < QUIET_DB
    fills = 0
    fills_track = np.zeros_like(out)
    for lb in landing_bars:
        if lb < total_bars and db[lb] < -12.0:
            t0 = lb * n_bar
            seg = monk_far[: 2 * n_bar].copy()
            fade = int(0.4 * SR)
            seg[:fade] *= np.linspace(0.0, 1.0, fade)
            seg[-fade:] *= np.linspace(1.0, 0.0, fade)
            end = min(len(out), t0 + len(seg))
            out[t0:end] += seg[:end - t0] * 0.4
            fills_track[t0:end] += seg[:end - t0] * 0.4
            fills += 1
    # recompute after landing fills so gap detection sees them --
    # fills count as voice (they ARE the distant monk)
    det2 = (det + fills_track) if voice is not None else out
    rms = np.array([np.sqrt((det2[i * n_bar:(i + 1) * n_bar] ** 2)
                            .mean() + 1e-12)
                    for i in range(total_bars)])
    quiet = 20 * np.log10(rms / med) < QUIET_DB
    i = 0
    while i < total_bars - 1:
        if quiet[i] and quiet[i + 1]:
            j = i
            while j < total_bars and quiet[j]:
                j += 1
            t0 = i * n_bar
            # the CLOSE monk, not the distant one: a hall-washed dark
            # voice at 0.5 disappears under the battle wall (probe
            # heard "completely absent" straight through the first
            # distant-monk fills) -- the composed sung bars use the
            # close voice and stay audible in the same mix
            src = monk_near if monk_near is not None else monk_far
            need = (j - i) * n_bar + n_bar // 2
            # slice from the render's most CONTINUOUSLY-SUNG stretch,
            # not from its head: taken from bar 0, the chant's own
            # internal phrase rests landed exactly on the hole being
            # patched (idumea bars 5-6 got the melody's rest bars --
            # the probe heard the "fill" and it was silence)
            sb = max(1, len(src) // n_bar - (need // n_bar + 1))
            bar_rms = [np.sqrt((src[k * n_bar:(k + 1) * n_bar] ** 2)
                               .mean() + 1e-12)
                       for k in range(len(src) // n_bar)]
            best, best_score = 0, -1.0
            for st in range(sb):
                w = bar_rms[st:st + need // n_bar + 1]
                sc = min(w) if w else 0.0
                if sc > best_score:
                    best, best_score = st, sc
            seg = src[best * n_bar: best * n_bar + need].copy()
            fade = int(0.5 * SR)
            seg[:fade] *= np.linspace(0.0, 1.0, fade)
            # exit over a FULL BAR: the 0.5s exit chopped monk_far
            # mid-phrase ("abruptly chops the vocal mid-syllable",
            # labeled A/B at the 175.5s fill) -- the fill must leave
            # as a fade, not an edit
            xfade = min(len(seg), n_bar)
            seg[-xfade:] *= np.linspace(1.0, 0.0, xfade)
            end = min(len(out), t0 + len(seg))
            # 0.5, not 0.35: these are VOICE-REST bridges that must
            # stay audible under a combat mix, not calm-landing dabs
            # 1.0: measured -17.5dBFS at 0.6 vs sung bars -14 --
            # ~6dB under what survives a heavy develop mix (the probe
            # called healthy-gain fill bars "completely absent");
            # _write's peak guard owns clipping safety
            out[t0:end] += seg[:end - t0] * 1.0
            fills_track[t0:end] += seg[:end - t0] * 1.0
            fills += 1
            i = j
        else:
            i += 1
    if fills:
        print(f"  prayer: filled {fills} silent stretch(es)", flush=True)
    global _LAST_FILLS_TRACK
    _LAST_FILLS_TRACK = fills_track
    return out


def _band_ratio(x) -> float:
    """low-band (40-180Hz) vs lead-band (180-1200Hz) energy of a
    render's first 20s -- 'did the output land in the right frequency
    band' as the director framed it. Pitch trackers lied here (noisy
    patches, subsonic rumble bins); band energy responds monotonically
    to octave shifts on every voice we probed."""
    seg = x[: int(20 * SR)]
    F = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    fr = np.fft.rfftfreq(len(seg), 1 / SR)
    lo = float(F[(fr >= 40) & (fr < 180)].sum())
    mid = float(F[(fr >= 180) & (fr < 1200)].sum())
    return lo / (mid + 1e-9)


BASS_RATIO = 3.0   # low band must dominate 3:1 -- bass_brute's
#                    unshifted render measures 2.1 and the director
#                    heard it competing with the lead, so 2.1 must fail


def _render_bass_in_band(voice, seq, total_s, tail, name):
    """Render, MEASURE the output, and re-render an octave down until
    the energy actually lands in the bass band (the PATCH decides the
    sounding octave, not the MIDI note). Crashes if -24 still fails."""
    ratio = None
    for shift in (0, -12, -24):
        sq = []
        for nn, t, d, v in seq:
            n2 = nn + shift
            while n2 < 12:      # octave-fold: MIDI can't go negative,
                n2 += 12        # and pitch class is what matters
            sq.append((n2, t, d, v))
        x = VB.render_seq(*voice, sq, total_s, tail)
        ratio = _band_ratio(x)
        if ratio >= BASS_RATIO:
            print(f"  {name}: band ratio {ratio:.1f} at "
                  f"{shift} semitones", flush=True)
            return x
    # percussive cells (mite ticks) keep transient energy mid-band at
    # any pitch: the designed bass voicing for those is the filtered
    # tick. Lowpass is a SOUND-DESIGN stage here, not error-hiding --
    # the outcome is still measured and still crashes if wrong.
    import synth as sy
    # cutoff must sit BELOW the mid-band boundary (180Hz) or the
    # residue between cutoff and boundary keeps failing the ratio;
    # applied twice for slope
    x = sy.lowpass(sy.lowpass(x, 160), 160)
    ratio2 = _band_ratio(x)
    if ratio2 >= BASS_RATIO:
        print(f"  {name}: band ratio {ratio2:.1f} after -24 + "
              f"160Hz lowpass x2", flush=True)
        return x
    raise ValueError(f"{name}: low/mid ratio {ratio2:.2f} < "
                     f"{BASS_RATIO} even at -24 + lowpass")


def build(mel: str, outdir: Path):
    rec = T.RECIPES[mel]
    total_bars = sum(b for _, b, _ in rec["form"])
    n = int(total_bars * BAR * SR)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[{rec['title']}] {total_bars} bars -> {outdir}", flush=True)

    _st, lanes, ctx = T.compose(mel, collect_lanes=True)

    # prayer: the ORIGINAL composed monk/choir/bells, verbatim; the
    # one fix is the gap fill (director: "I just asked you to fix
    # that one thing")
    landing = []
    pos = 0
    for _stype, sbars, _prog in rec["form"]:
        landing.append(pos)
        pos += sbars
    # PRAYER ships its loop tail as a SEPARATE stem instead of the
    # baked fold: chunk[0] with a baked tail plays a phantom second
    # voice whenever form steering JUMPS to bar 0 from mid-form (the
    # 53.5s doubled-voice defect on the isolated-channel sweep, entry
    # 17->0). The mixer/engine overlay prayer_tail only on the true
    # last->0 wrap; every other lane keeps the baked fold (a doubled
    # pad release is inaudible; a doubled monk is not).
    prayer_raw = lanes["holy"] + lanes["spine"] * 0.3
    bar_n = int(BAR * SR)
    if len(prayer_raw) >= n + bar_n // 4:
        tail = np.array(prayer_raw[n:n + bar_n], copy=True)
        if len(tail) < bar_n:
            tail = np.pad(tail, [(0, bar_n - len(tail))] +
                          [(0, 0)] * (tail.ndim - 1))
        fade = int(0.1 * SR)
        env = np.linspace(1.0, 0.0, fade)
        tail[-fade:] *= env[:, None] if tail.ndim == 2 else env
        _write(outdir / "prayer_tail.wav", tail, bar_n)
    prayer = _fill_monk_gaps(prayer_raw, ctx["monk_far"], total_bars,
                             mel, landing_bars=landing,
                             voice=lanes["monksig"],
                             monk_near=ctx["monk"])
    _assert_no_silent_bars(prayer[:n], total_bars, f"{mel}/prayer")
    # FAIL FAST on chant coverage: after fills, no bar-pair may lack
    # an audible CLOSE-monk presence (monksig + the fills). This is
    # the alarm that was missing the whole night of 2026-07-17 --
    # every audio-level proxy said "present" while listeners heard
    # the chant vanish for 5-10s stretches.
    cov = lanes["monksig"][:n] + _LAST_FILLS_TRACK[:n]
    bar_n2 = int(BAR * SR)
    cr = np.array([np.sqrt((cov[i * bar_n2:(i + 1) * bar_n2] ** 2)
                           .mean() + 1e-12) for i in range(total_bars)])
    cs = cr[cr > 1e-4]
    cmed = float(np.median(cs)) if len(cs) else 1e-4
    cdb = 20 * np.log10(cr / cmed)
    holes = [i for i in range(total_bars - 1)
             if cdb[i] < -15.0 and cdb[i + 1] < -15.0]
    if holes:
        raise ValueError(f"{mel}: chant coverage holes at bar pairs "
                         f"{holes} -- the fills did not close them")
    _write(outdir / "prayer.wav", prayer, n)

    # stalwart/contempt: FORM-WIDE renders. The album lanes are
    # section-local (dies_irae's walls are digitally silent through
    # develop -- any fight the steering parked there lost the chug).
    # The engine may gain ANY stem at ANY form position, so every
    # dynamic bank stem must carry content at every position, exactly
    # like the leads and enemy basses always did.
    import synth as sy
    events = GB.MELODIES[mel]
    roots16 = []
    for _stype, sbars, prog in rec["form"]:
        roots16 += harmony.roots_16(prog, sbars)
    riff = riffs.riff_16(events, n_bars=total_bars,
                         accents=T._ACC[rec["accents"][0]],
                         chord_roots=roots16)
    wl = T.wall_take(rec, riff, rec["seeds"][0], 18.0)
    wr = T.wall_take(rec, riff, rec["seeds"][1], 19.0)
    bseq, btot = T._bass_seq_from_riff(riff)
    wb = sy.highpass(T.vb_seq_raw(rec["bass"], bseq, btot, 0.4), 90)
    subl = sy.lowpass(T._sub_layer(bseq, btot), 90)
    m = min(len(wb), len(subl))
    wb = wb[:m] + subl[:m] * 0.55
    L_ = np.zeros(n + int(BAR * SR))   # +1 bar so the sustain past
    R_ = np.zeros(n + int(BAR * SR))   # the form end exists to fold
    T.place(L_, wl * 0.7, 0)
    T.place(R_, wr * 0.7, 0)
    T.place(L_, wb * 0.6, 0)
    T.place(R_, wb * 0.6, 0)
    _write(outdir / "stalwart.wav",
           _fold_tail(np.stack([L_, R_], axis=1), n), n)

    r3 = riffs.riff_16(events, n_bars=total_bars,
                       accents=T._ACC[rec["accents"][1]],
                       chord_roots=roots16)
    fseq, ftot = T._bass_seq_from_riff(r3, base=38)
    fm = T.vb_seq_raw(rec["fm"], fseq, ftot, 0.3)
    fl = []
    for bar in range(1, total_bars, 2):
        fl.append((62 + roots16[bar * 16], bar * BAR + 8 * STEP,
                   3 * STEP, 100))
    fx = T.vb_seq_raw(rec["flour"], fl, total_bars * BAR, 0.5)
    C_ = np.zeros(n + int(BAR * SR))
    T.place(C_, fm * 0.6, 0)
    T.place(C_, fx * 0.3, 0)
    _write(outdir / "contempt.wav", _fold_tail(C_, n), n)
    # drums: FORM-WIDE kit render (the album lane is composed-silent
    # in calm sections, but drums are selectable from combat>0.03
    # while the combat floor only steers >=0.35 -- a sub-threshold
    # skirmish in a ritual bar played audible-gain drums pointed at
    # silence). The ENGINE gates drums by combat; the stem must have
    # the kit everywhere.
    rngd = np.random.default_rng(rec["seeds"][2])
    dh_full = T.drums(rec, total_bars, rngd,
                      fills_at=tuple(range(7, total_bars, 8)))
    kit = np.zeros(n + int(BAR * SR))
    T.place(kit, T.drum_bus(dh_full) * 0.7, 0)
    _write(outdir / "drums.wav", _fold_tail(kit, n), n)
    spine_folded = _fold_tail(lanes["spine"].copy(), n)
    for tier in range(1, 5):
        _write(outdir / f"bed_t{tier}.wav", spine_folded, n)

    # sting + riser come from THE bell (bell_sting.py is the single
    # source: deep on-key chapel bell; the riser is the same bell
    # reversed). If the Ylanne sample is missing this CRASHES the
    # build -- the bell is part of the bank, not an optional garnish.
    import bell_sting as BS
    rng = np.random.default_rng(rec["seeds"][0])
    # BARE bell (director, verbatim: 'an on-key sample of a large
    # bell ringing once'): the RISER is the swell now -- a pre-swell
    # on the sting doubled the gesture and left a dead gap when the
    # two chained
    stg = BS.build_sting_amen(rec, rng)   # ranked 4/4: the choir
    #                                        resolves; no bell overlay
    _write(outdir / "sting.wav", stg, len(stg))
    rsr = BS.build_riser(rec)
    _write(outdir / "riser.wav", rsr, len(rsr))

    # weapon leads: the develop-lead line re-voiced per weapon across
    # the whole form (same phrase logic as sec_develop)
    events = GB.MELODIES[mel]
    frag = riffs.lead_phrase(
        [(p, d) for p, d in events if p is not None][:8], factor=2)
    lseq = []
    for k in range((total_bars + 3) // 4):   # CEIL: 34-bar forms
    #   left bars 30-33 with no phrase at all (floor division) --
    #   a 4-bar dead hole in every lead of every 34-bar bank
        tt = k * 4 * BAR
        for pnote, d in frag:
            lseq.append((62 + pnote, tt, (d + 0.5) * STEP, 108))
            tt += d * STEP
    for w, sel in VB.SLOTS.items():
        if not w.startswith("lead_"):
            continue
        x = VB.render_seq(*sel, lseq, total_bars * BAR, 2.5)
        x = x / (np.abs(x).max() + 1e-9)
        _write(outdir / f"{w}.wav", _fold_tail(x * 0.8, n), n)

    # enemy cells on the recipe's fm voice, over the form's own roots
    roots = []
    for stype, bars, prog in rec["form"]:
        roots += harmony.roots_16(prog, bars)[::16]
    for kind, (cells, _sel) in GB.ENEMY_CELLS.items():
        seq = []
        for bar, r in enumerate(roots):
            for pos, semi, dsteps in cells:
                seq.append((38 + r + semi, bar * BAR + pos * STEP,
                            dsteps * STEP * 0.9, 106))
        x = _render_bass_in_band(rec["fm"], seq, total_bars * BAR,
                                 2.5, f"{mel}/bass_{kind}")
        x = x / (np.abs(x).max() + 1e-9)
        _write(outdir / f"bass_{kind}.wav", _fold_tail(x * 0.8, n), n)

    secs, pos = [], 0
    for stype, bars, _p in rec["form"]:
        secs.append([stype, pos, pos + bars])
        pos += bars
    # sections written AT THE SOURCE: the engine's strict loader
    # refuses a sectionless bank.json, so a bank rebuilt without the
    # boss_stems pass can no longer ship a silently steering-less form
    (outdir / "bank.json").write_text(json.dumps(
        dict(melody=mel, title=rec["title"], bpm=T.BPM, bars=total_bars,
             sections=secs)))
    print("bank complete", flush=True)
    # AUTO-SHIP: out/banks and game/assets/music are two copies of the
    # same truth, and the night of 2026-07-17 proved the failure mode:
    # every render after midnight mixed from a stale shipped copy while
    # the rebuilt wavs sat unheard in out/banks -- the director listened
    # to a "fixed" video containing none of the fixes. A build that does
    # not ship is a build that never happened; the divergence window is
    # now structurally zero. (ship_banks is mtime-incremental: only the
    # stems this build changed get re-encoded.)
    import ship_banks
    ship_banks.main()


if __name__ == "__main__":
    mel = sys.argv[1] if len(sys.argv) > 1 else "dies_irae"
    T.check_uniqueness()
    build(mel, Path("out/banks") / f"album_{mel}")
