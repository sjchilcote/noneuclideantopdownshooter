"""Instrument lab — audition every part slot's instrument + planned material.

    uv run python tools/musicgen/instrument_lab.py

Left: melody menu. Rows: one per part slot of STEM_COMPOSITION_DESIGN —
concept, the preset that plays it, and what it plays. Click a row (or
press its key) to hear that instrument performing its planned material
from the selected melody. Renders are cached per (melody, slot) in the
scratchpad; first click on a row renders in the background (row shows
"rendering..."), then plays.

Slot instruments are read from vital_bank.SLOTS (the director's
picks through real Vital) — the UI labels come from that table, so
what you read is what renders. Non-synth voices: monk = Delay Lama,
wall = chug kit samples, drums = TR-909, bell = authored.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soundgen"))

import generate_bank as G                     # noqa: E402
import riffs                                  # noqa: E402
import harmony                                # noqa: E402
import vital_bank as VB                       # noqa: E402

SR = 44100
CACHE = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
             "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b"
             "/scratchpad/musicgen/lab_cache")
CACHE.mkdir(parents=True, exist_ok=True)


def _mono(x):
    return x.mean(axis=1) if x.ndim == 2 else x


def _patch_path(cat_name):
    return G._odin_patch(cat_name)


_CTX = {}


def _context(key, ev):
    """Mono fight-bed (wall + drums) a combat voice is auditioned over."""
    if key not in _CTX:
        w = r_wall(ev)
        d = r_drums(ev)
        n = max(len(w), len(d))
        m = np.zeros(n)
        m[:len(w)] += w.mean(axis=1) if w.ndim == 2 else w
        m[:len(d)] += d * 0.8
        _CTX[key] = m / (np.abs(m).max() + 1e-9)
    return _CTX[key]


def _chant_head(events, n_notes=8):
    out = []
    for p, d in events:
        out.append((p, d))
        if p is not None and sum(1 for q, _ in out if q is not None) >= n_notes:
            break
    return out


def _first_rest_answer(events):
    """The lead's planned material: the chant's opening figure, one
    octave up, as the ANSWER placed after the first breath (design law:
    counter-melody lives in the chant's rest windows)."""
    head = [(p + 12, max(d // 2, 1)) for p, d in _chant_head(events, 6)
            if p is not None]
    return head


# ---- slot renderers: (melody events) -> mono/stereo float array -----------

def r_monk(ev):
    step = 60.0 / 72.0 / 4
    vows = [None if p is None else (-0.5 if d >= 8 else 0.2)
            for p, d in _chant_head(ev, 16)]
    x = G.render_vocal(_chant_head(ev, 16), step, base_midi=50, vowels=vows)
    x = x / (np.abs(x).max() + 1e-9)
    return G.hall(x, 1.4).T


def r_choir(ev):
    roots = G.bar_roots(ev, 4)
    seq = []
    for bar, r in enumerate(roots):
        for n in (50 + r, 57 + r):
            seq.append((n, bar * G.BAR, G.BAR * 0.97, 100))
    x = VB.render_seq(*VB.SLOTS["choir"], seq, 4 * G.BAR, tail_s=1.5)
    return G.hall(x / (np.abs(x).max() + 1e-9), 1.3).T


def r_organ_holy(ev):
    roots = G.bar_roots(ev, 4)
    seq = []
    for bar, r in enumerate(roots):
        for n in (26 + r, 38 + r, 45 + r):
            seq.append((n, bar * G.BAR, G.BAR * 0.97, 100))
    x = VB.render_seq(*VB.SLOTS["organ_holy"], seq, 4 * G.BAR, tail_s=1.2)
    return G.hall(x / (np.abs(x).max() + 1e-9), 1.1).T


def r_organ_def(ev):
    """Defiant organ: melody accents only (the riff's open slots),
    stabbed dry — the machine shouting the tune's skeleton."""
    riff = riffs.riff_16(ev, n_bars=4, accents=riffs.ACCENTS_B,
                         chord_roots=harmony.roots_16("pressure", 4))
    seq = []
    t = 0
    for pp, steps, art in riff:
        if art == "open":
            for n in (50 + pp, 57 + pp):
                seq.append((n, t * G.STEP, G.STEP * steps * 1.4, 112))
        t += steps
    x = VB.render_seq(*VB.SLOTS["organ_defiant"], seq, t * G.STEP)
    return x / (np.abs(x).max() + 1e-9) * 0.9


def r_bell(ev):
    x = np.zeros(int(SR * 5))
    G.place_mono(x, G.bell_hit(0.8), 0.2)
    G.place_mono(x, G.bell_hit(0.5), 2.4)
    return G.hall(x, 1.3).T


def _wall_take(ev, seed, drive_db):
    """One take of the riff, the ALBUM's programming language (pro-tier
    piano-roll reconstruction of t02/t07): STRICT grid, flat velocity
    with downbeat accents only, all re-picked, chugs hard-gated to
    silence, power chords on accents. The wall is the HARMONIC-RHYTHM
    voice: it punches the pressure cycle's chords, not the melody
    (harmony.py 'pressure' — bII leaning on home, fought off)."""
    import synth as sy
    rng = np.random.default_rng(seed)
    roots = harmony.roots_16("pressure", 4)
    riff = riffs.riff_16(ev, n_bars=4, accents=riffs.ACCENTS_A,
                         chord_roots=roots)
    out = np.zeros(int(4 * G.BAR * SR) + SR)
    t = 0
    for p, steps, art in riff:
        on_grid = t * G.STEP            # no timing jitter: the grid IS
        #                                 the album's feel
        if art == "open":
            for iv, g in ((12, 1.0), (19, 0.8), (24, 0.55)):
                h = G.voices.chug_note(rng, p + iv,
                                       G.STEP * steps * 1.8, 0.0, g)
                G.place_mono(out, h, on_grid)
        else:
            vel = 1.0 if t % 16 == 0 else 0.62   # accent = downbeat only
            h = G.voices.chug_note(rng, p, G.STEP * 1.05, 0.85, vel)
            # binary gate: chop to the slot, 3ms fade -> true silence
            n_gate = int(G.STEP * 0.92 * SR)
            if len(h) > n_gate:
                h = h[:n_gate].copy()
                h[-132:] *= np.linspace(1, 0, 132)
            G.place_mono(out, h, on_grid)
        t += steps
    out = G.voices.amp(out * 0.75 / (np.abs(out).max() + 1e-9), drive_db)
    return sy.highpass(out, 120)


def r_wall(ev):
    """TWO independent takes hard L/R — the album's double-track law;
    the decorrelation between takes is the 'band' cue, not jitter."""
    L = _wall_take(ev, 11, 18.0)
    R = _wall_take(ev, 22, 19.0)
    n = min(len(L), len(R))
    st = np.stack([L[:n], R[:n]], axis=1)
    return st / (np.abs(st).max() + 1e-9) * 0.9


def r_drums(ev):
    rng = np.random.default_rng(5)
    d = np.zeros(int(4 * G.BAR * SR) + SR)
    kick = G.K.kick_knob(25, 25, 50)
    for bar in range(4):
        for pos, vel, inst in [(0, 1.0, "kick"), (8, .95, "snare"),
                               (4, .85, "kick"), (12, .5, "kick")]:
            x = kick * (0.6 + 0.4 * vel) if inst == "kick" \
                else G.K.hit("snare", vel, rng)
            G.K.place(d, x, bar * G.BAR + pos * G.STEP)
        for pos in range(0, 16, 2):
            acc = .75 if pos % 8 == 4 else (.5 if pos % 4 == 0 else .35)
            G.K.place(d, G.K.hit("chh", acc, rng),
                      bar * G.BAR + pos * G.STEP)
    return d / (np.abs(d).max() + 1e-9) * 0.9


def r_bass_deep(ev):
    roots = G.bar_roots(ev, 4)
    seq = [(26 + r, bar * G.BAR, G.BAR * 0.95, 110)
           for bar, r in enumerate(roots)]
    x = VB.render_seq(*VB.SLOTS["bass_deep"], seq, 4 * G.BAR)
    return x / (np.abs(x).max() + 1e-9) * 0.9


def r_bass_fm(ev):
    """The album's bass law: PERFECT UNISON with the wall riff — same
    notes, same gates, root register, one hybrid tone with the guitars.
    Rendered as ONE continuous sequence (envelope/LFO continuity), not
    note-by-note pastes."""
    riff = riffs.riff_16(ev, n_bars=4, accents=riffs.ACCENTS_A,
                         chord_roots=harmony.roots_16("pressure", 4))
    seq = []
    t = 0
    for pp, steps, art in riff:
        vel = 118 if art == "open" else 96      # flat-loud, accent bump
        gate = steps * 0.92 if art == "mute" else steps * 1.6
        seq.append((38 + pp, t * G.STEP, gate * G.STEP, vel))
        t += steps
    total = t * G.STEP
    x = VB.render_seq(*VB.SLOTS["bass_fm"], seq, total)
    return x / (np.abs(x).max() + 1e-9) * 0.9


def _mk_bed(tier):
    def r(ev):
        # loop-shaped: the note holds to the END of the clip (a bed never
        # releases in-game; a dying tail in the demo reads as "doesn't
        # loop" — director 2026-07-15)
        n = 38 - 2 * (tier - 1)
        dur = 8.0
        y = VB.render_seq(*VB.SLOTS[f"bed_t{tier}"],
                          [(n, 0.0, dur, 100), (n - 12, 0.0, dur, 90)],
                          dur, tail_s=0.0)
        y = y[:int(dur * 44100)]
        e = int(0.05 * 44100)
        y[-e:] *= np.linspace(1, 0, e)
        return y / (np.abs(y).max() + 1e-9) * 0.85
    return r


def _mk_lead(wname):
    kind, sel, oct_shift = G.WEAPON_LEADS[wname]

    def r(ev):
        line = riffs.lead_phrase(_chant_head(ev, 12), factor=2)
        # ONE continuous sequence with slight overlaps: the synth hears
        # a played line (legato/glide/envelope continuity), not pasted
        # single-note renders
        seq = []
        t = 0.0
        for p, d in line:
            if p is not None:
                seq.append((62 + p + oct_shift, t * G.STEP,
                            (d + 0.5) * G.STEP, 108))
            t += d
        total = t * G.STEP
        x = VB.render_seq(*VB.SLOTS[f"lead_{wname}"], seq, total)
        x = x / (np.abs(x).max() + 1e-9)
        # IN CONTEXT (director: a naked line always sounds like a
        # lesson): the lead sits over its fight — wall + drums bed at
        # low gain, lead upfront
        bed = _context(id(ev), ev)
        n = max(len(x), len(bed))
        mix = np.zeros(n)
        mix[:len(bed)] += bed * 0.30
        mix[:len(x)] += x * 0.95
        return mix / (np.abs(mix).max() + 1e-9) * 0.9
    return r


def _mk_cell(ename):
    cells, patch_sel = G.ENEMY_CELLS[ename]

    def r(ev):
        roots = G.bar_roots(ev, 4)
        seq = []
        for bar, rt in enumerate(roots):
            for pos, semi, dsteps in cells:
                seq.append((38 + rt + semi,
                            bar * G.BAR + pos * G.STEP,
                            dsteps * G.STEP * 0.9, 106))
        x = VB.render_seq(*VB.SLOTS[f"cell_{ename}"], seq, 4 * G.BAR)
        return x / (np.abs(x).max() + 1e-9) * 0.9
    return r


def _mk_spec_sample(path, trim_s=8.0):
    def r(ev):
        import specimen_kit as SP
        x = SP.load(str(path))[:int(trim_s * SR)]
        return x / (np.abs(x).max() + 1e-9) * 0.85
    return r


def _mk_spec_bass(path, src_midi):
    """Keyed Specimen one-shot as the riff's bass voice (sampler
    repitch), unison with the wall's pressure cycle."""
    def r(ev):
        import specimen_kit as SP
        riff = riffs.riff_16(ev, n_bars=4, accents=riffs.ACCENTS_A,
                             chord_roots=harmony.roots_16("pressure", 4))
        out = np.zeros(int(4 * G.BAR * SR) + SR)
        t = 0
        for p, steps, art in riff:
            y = SP.keyed(path, src_midi, 38 + p)
            n_gate = int(G.STEP * (steps * 0.92 if art == "mute"
                                   else steps * 1.6) * SR)
            y = y[:n_gate]
            g = 1.0 if art == "open" else 0.7
            G.place_mono(out, y * g, t * G.STEP)
            t += steps
        return out / (np.abs(out).max() + 1e-9) * 0.9
    return r


def _specimen_slots():
    import specimen_kit as SP
    rows = []
    want_atmo = ["Nightmare Tension", "Earth Hole", "Breathing Cave",
                 "Dark Blue"]
    cat = SP.catalog()
    def find(c, name):
        for cc, nm, f, midi, bpm in cat:
            if cc == c and nm == name:
                return f, midi
        return None, None
    for nm in want_atmo:
        f, _ = find("ATMO", nm)
        if f:
            rows.append((f"spec_atmo:{nm[:12]}", f"Specimen '{nm}'",
                         "bed candidate", _mk_spec_sample(f, 10)))
    for nm in ["Impact Braaam", "Contagist Punch"]:
        f, _ = find("IMP", nm)
        if f:
            rows.append((f"spec_imp:{nm[:12]}", f"Specimen '{nm}'",
                         "sting candidate", _mk_spec_sample(f, 6)))
    for cc, nm, f, midi, bpm in cat:
        if cc == "RISE":
            rows.append((f"spec_rise:{nm[:11]}", f"Specimen '{nm}'",
                         "riser candidate", _mk_spec_sample(f, 8)))
    f, midi = find("BASS", "Lava Bass")
    if f:
        rows.append(("spec_bass:LavaBass", "Specimen 'Lava Bass' C#2",
                     "riff via sampler", _mk_spec_bass(f, midi)))
    return rows


def build_slots():
    slots = [
        ("monk", "Delay Lama (the album's voice)", "the chant, free grid",
         r_monk),
        ("choir", "Odin2 'Choir Aahs 1 [RS]'", "chord tones over pedal",
         r_choir),
        ("organ_holy", "Odin2 'Church Organ' +16'", "progression, sanctuary",
         r_organ_holy),
        ("organ_defiant", "Odin2 '666-001-Organ'", "stabs in chant rests",
         r_organ_def),
        ("bell", "authored bell", "phrase-end tolls", r_bell),
        ("wall", "chug kit (real samples)", "pedal 8ths on bar roots",
         r_wall),
        ("drums", "TR-909 (real machine)", "half-time backbone", r_drums),
        ("bass_deep", "Odin2 'DeepBass [Photonic]'", "pedal whole notes",
         r_bass_deep),
        ("bass_fm", "Odin2 'Growly FM Bass [XR]'", "driving 8ths",
         r_bass_fm),
    ]
    for t in range(1, 5):
        nm = G.BEDS[t][1]
        slots.append((f"bed_t{t}", f"Odin2 '{nm}'", f"stage {t} drone",
                      _mk_bed(t)))
    for w, (kind, sel, _o) in G.WEAPON_LEADS.items():
        pname = sel[1] if kind == "odin" else f"Dexed voice {sel}"
        slots.append((f"lead_{w}", pname, "answer in the rest window",
                      _mk_lead(w)))
    for e in G.ENEMY_CELLS:
        slots.append((f"cell_{e}", G.ENEMY_CELLS[e][1][1],
                      "that enemy's bass cell", _mk_cell(e)))
    slots += _specimen_slots()
    # the label NEVER lies: any slot cast in vital_bank.SLOTS shows its
    # actual preset (single source of truth), not a hardcoded string
    fixed = []
    for name, preset, mat, fn in slots:
        if name in VB.SLOTS:
            bank, stem = VB.SLOTS[name]
            preset = f"Vital: {stem} [{bank}]"
        fixed.append((name, preset, mat, fn))
    return fixed


def cache_path(mel, slot):
    return CACHE / f"{mel}__{slot}.wav"


def render_all(only_melody: str | None = None):
    """Batch mode: render every (melody, slot) clip to the cache, once,
    upfront. The player never renders anything."""
    import soundfile as sf
    slots = build_slots()
    melodies = [only_melody] if only_melody else list(G.MELODIES)
    todo = [(m, s) for m in melodies for s in slots
            if not cache_path(m, s[0]).exists()]
    print(f"{len(todo)} clips to render")
    for k, (mel, (name, _p, _m, fn)) in enumerate(todo):
        try:
            x = fn(G.MELODIES[mel])
            if x.ndim == 1:
                x = np.stack([x, x], axis=1)
            sf.write(str(cache_path(mel, name)),
                     (np.clip(x, -1, 1) * 32767).astype(np.int16),
                     SR, subtype="PCM_16")
            print(f"[{k + 1}/{len(todo)}] {mel}/{name}", flush=True)
        except Exception as exc:
            print(f"[{k + 1}/{len(todo)}] {mel}/{name} FAILED: {exc}",
                  file=sys.stderr, flush=True)


def main():
    """The player. It plays wav files from the cache; that is all it
    does. Missing files show as dim rows saying so (run --render)."""
    import mgui
    from perihelion import fb2d, text, uievent
    W, H = 1240, 760
    disp = mgui.Display(W, H, "PERIHELION instrument lab")
    screen = disp.fb
    font, big = 14, 17            # text.blit_text sizes (FSEX300)
    player = mgui.OneShot(mgui.audio())

    melodies = list(G.MELODIES)
    slots = build_slots()
    mel_i = 0
    playing = None

    rows_top = 46
    row_h = 21
    clock = mgui.Clock()
    running = True
    while running:
        mel = melodies[mel_i]
        for ev in disp.events():
            if ev.type == uievent.QUIT:
                running = False
            elif ev.type == uievent.KEYDOWN:
                if ev.key == uievent.K_ESCAPE:
                    running = False
                elif ev.key == uievent.K_UP:
                    mel_i = (mel_i - 1) % len(melodies)
                elif ev.key == uievent.K_DOWN:
                    mel_i = (mel_i + 1) % len(melodies)
            elif ev.type == uievent.MOUSEBUTTONDOWN:
                x, y = ev.pos
                if x < 220:
                    i = (y - rows_top) // 25
                    if 0 <= i < len(melodies):
                        mel_i = i
                elif x > 240:
                    i = (y - rows_top) // row_h
                    if 0 <= i < len(slots):
                        cp = cache_path(mel, slots[i][0])
                        if cp.exists():
                            player.play(cp)
                            playing = slots[i][0]

        fb2d.fill(screen, (15, 15, 19))

        def txt(s, x, y, c=(200, 200, 200), f=font):
            text.blit_text(screen, s, x, y, c, f)

        txt("MELODY (up/down)", 12, 20, (240, 220, 160), big)
        for i, m in enumerate(melodies):
            if i == mel_i:
                fb2d.rect(screen, (85, 65, 35),
                          (10, rows_top + i * 25 - 2, 205, 22))
            txt(m, 14, rows_top + i * 25,
                (255, 240, 200) if i == mel_i else (170, 170, 170))
        txt("SLOT              INSTRUMENT                     MATERIAL"
            "              (click = play once)", 250, 20,
            (240, 220, 160), big)
        for i, (name, preset, mat, _fn) in enumerate(slots):
            y = rows_top + i * row_h
            have = cache_path(mel, name).exists()
            if not have:
                col, note = (95, 95, 105), "not rendered"
            elif playing == name:
                col, note = (140, 230, 140), ""
            else:
                col, note = (195, 195, 195), ""
            txt(f"{name:16s}  {preset:30.30s} {mat:24.24s} {note}",
                250, y, col)
        disp.flip()
        clock.tick(30)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--render":
        render_all(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        main()
