"""bell_sting — the sting bell, from a REAL bell (director 2026-07-17).

"That bell clip is NOT an appropriate stinger ... substitute for an
_on-key_ sample of a large bell ringing _once_ ... use the deepest
bell you can - get it down bordering on sub-bass territory."

Source: Ylanne Vinyl Church Bells (Joonas Ylanne / AV-Ylanne, v1.1),
Decent Sampler freeware -- sounds free for commercial use, instrument
itself not redistributable. The sample pack stays in the scratchpad
(never committed); only rendered stings ship. See SOURCES_LICENSES.md.

ChurchBell1.wav measured: perceived strike ~C5 (prime 530Hz, +22
cents), zero leading silence. We resample it down to a strike tone of
MIDI 38 + tonic root -- the same root the boss sub-bass lane is built
on (26 + r, one octave below), so the bell is on-key by construction
and its hum partial sits at ~37Hz: bordering on sub-bass.

    uv run python tools/musicgen/bell_sting.py render   # all banks
    uv run python tools/musicgen/bell_sting.py judge    # variants A-D
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))

import tutti as T                    # noqa: E402
import tr909_kit as K                # noqa: E402
import harmony                       # noqa: E402
from tutti_bank import _write        # noqa: E402

SR, BAR = T.SR, T.BAR
ROOT = Path(__file__).resolve().parents[2]
BANKS = ROOT / "out/banks"
SHIPPED = ROOT / "game/assets/music"
BELL_WAV = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
                "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-"
                "c9dc90e4fe0b/scratchpad/bells/ChurchBell1.wav")
SRC_MIDI = 72.22          # measured perceived strike (C5 +22 cents)


def deep_bell(target_midi: float, max_s: float = 8.0) -> np.ndarray:
    x, sr = sf.read(str(BELL_WAV), dtype="float32")
    if x.ndim == 2:
        x = x.mean(axis=1)
    # resample to SR and pitch down in one interp: all partials scale
    # together, keeping the bell's inharmonic character
    factor = (SR / sr) * 2.0 ** ((SRC_MIDI - target_midi) / 12.0)
    n2 = int(len(x) * factor)
    y = np.interp(np.linspace(0.0, len(x) - 1.0, n2),
                  np.arange(len(x)), x).astype(np.float64)
    n_max = int(max_s * SR)
    if len(y) > n_max:
        tail = np.ones(n_max)
        f0 = int(0.6 * n_max)
        tail[f0:] = np.linspace(1.0, 0.0, n_max - f0) ** 2
        y = y[:n_max] * tail
    # kill infra-rumble the 3-octave drop drags along
    from scipy.signal import butter, sosfilt
    sos = butter(2, 24.0, btype="highpass", fs=SR, output="sos")
    y = sosfilt(sos, y)
    return y / (np.abs(y).max() + 1e-9)


def build_sting(rec, rng, variant: str = "swell") -> np.ndarray:
    r0 = harmony.roots_16(rec["form"][0][2], 1)[0]
    bell = deep_bell(38.0 + r0)
    out = np.zeros(int(4.0 * BAR * SR))
    crash = K.hit("crash", 1.0, rng)
    rev = crash[::-1] * np.linspace(0.0, 1.0, len(crash)) ** 1.5
    # only the LAST 0.7s of the reversed crash: the full tail leaves
    # >1s of near-silence at the head -- the sting must SPEAK the
    # instant it fires (the old bell clip's leading silence is exactly
    # what the director banned)
    rev = rev[-int(0.7 * SR):]
    t_land = len(rev) / SR * 0.92
    if variant == "bare":
        # ONE bell, one ring -- but a lone 73Hz strike vanishes under
        # a full combat mix (Gemini: 'completely lacks the resolving
        # toll'). The same strike's upper octaves give the single
        # bell its natural bright partials back.
        T.place(out, bell, 0.0)
        T.place(out, deep_bell(50.0 + r0, max_s=6.0) * 0.4, 0.0)
        T.place(out, deep_bell(62.0 + r0, max_s=4.0) * 0.12, 0.0)
    elif variant == "swell":
        T.place(out, rev * 0.6, 0)
        T.place(out, bell, t_land)
    elif variant == "swell_crash":
        T.place(out, rev * 0.6, 0)
        T.place(out, crash * 0.5, t_land)
        T.place(out, bell, t_land)
    return out


def build_riser(rec) -> np.ndarray:
    """The riser IS the bell, reversed (director 2026-07-17): the same
    deep on-key bell played backwards swells for exactly 2 bars and
    ends at its own strike -- the engine triggers it as a one-shot so
    the swell's payoff lands right where the sting toll answers."""
    r0 = harmony.roots_16(rec["form"][0][2], 1)[0]
    bell = deep_bell(38.0 + r0, max_s=2.0 * BAR)
    rev = bell[::-1]
    # 60ms de-click: reversed audio otherwise ENDS on the strike's
    # attack sample -- a full-scale one-sample cliff (Gemini heard it
    # as 'cuts off abruptly before the downbeat'). The resolution is
    # the sting toll landing on the next 8th.
    fade = int(0.06 * SR)
    rev[-fade:] *= np.cos(np.linspace(0, np.pi / 2, fade)) ** 2
    return rev / (np.abs(rev).max() + 1e-9) * 0.9


def build_sting_halled(rec, rng) -> np.ndarray:
    """The bell fired THROUGH the song's own polygon: rendered into the
    same hall as the holy lane, ducked -4dB -- punctuation that lives
    inside the mix instead of a sound effect on top (director
    overnight goal)."""
    import generate_bank as G
    bare = build_sting(rec, rng, "bare")
    x = G.hall(bare, 2.4).T.mean(axis=1)
    return x / (np.abs(x).max() + 1e-9) * 0.63


def build_sting_amen(rec, rng) -> np.ndarray:
    """No bell: the CHOIR resolves -- a two-chord amen cadence on the
    track's own choir voice, through the holy hall. The most
    'part of the song' punctuation possible: the song itself says
    amen at the kill."""
    import generate_bank as G
    r0 = harmony.roots_16(rec["form"][0][2], 1)[0]
    cs = [(50 + r0 + 5, 0.0, 1.2 * BAR, 92),     # subdominant color
          (57 + r0 + 5, 0.0, 1.2 * BAR, 88),
          (50 + r0, 1.0 * BAR, 2.2 * BAR, 96),   # home
          (57 + r0, 1.0 * BAR, 2.2 * BAR, 92),
          (62 + r0, 1.0 * BAR, 2.2 * BAR, 88)]
    import vital_bank as VB
    ch = VB.render_seq(*rec["choir"], cs, 3.5 * BAR, 1.5)
    x = G.hall(ch, 2.0).T.mean(axis=1)
    return x / (np.abs(x).max() + 1e-9) * 0.7


def build_riser_half(rec) -> np.ndarray:
    """Half-bar micro-riser for AMBUSH slams (director overnight goal:
    even the panic slam gets 'maybe half a bar of come up and/or a
    half-bar riser'): the reversed bell's final half bar -- pure
    swell into strike."""
    full = build_riser(rec)
    half = full[-int(0.5 * BAR * SR):].copy()
    fade = int(0.03 * SR)
    half[:fade] *= np.linspace(0.0, 1.0, fade)
    return half


def render():
    for mel in T.RECIPES:
        rec = T.RECIPES[mel]
        rng = np.random.default_rng(rec["seeds"][0])
        # AMEN adoption (sting_rank, 4/4 across 2 contexts x 2 reps):
        # the release punctuation is the track's choir cadence
        stg = build_sting_amen(rec, rng)
        rsr = build_riser(rec)
        rh = build_riser_half(rec)
        d = BANKS / f"album_{mel}"
        if (d / "bank.json").exists():
            _write(d / "sting.wav", stg, len(stg))
            _write(d / "riser.wav", rsr, len(rsr))
            _write(d / "riser_half.wav", rh, len(rh))
        print(f"[{mel}] deep-bell sting + reversed-bell riser written")
        # (shipping to game/assets is ship_banks.py's job -- one path)


def judge():
    from judge_track import _ask_multi, _stereo_mp3
    import sting_iter as SI
    mel = "dies_irae"
    rec = T.RECIPES[mel]
    bank = BANKS / f"album_{mel}"
    rng = np.random.default_rng(7)
    tmp = Path(tempfile.mkdtemp(prefix="bell_"))
    ctx = SI.context_mix(bank)
    at = int(10 * BAR * SR)

    def with_sting(s):
        m = ctx.copy()
        m[at:at + len(s)] += s[:len(m) - at] * 0.9
        return m / (np.abs(m).max() + 1e-9) * 0.9

    old = SI.load(bank, "sting", 1.0)
    clips = []
    for name, x in (("old", with_sting(old)),
                    ("bare", with_sting(build_sting(rec, rng, "bare"))),
                    ("swell", with_sting(build_sting(rec, rng, "swell"))),
                    ("swell_crash",
                     with_sting(build_sting(rec, rng, "swell_crash")))):
        w = tmp / f"{name}.wav"
        sf.write(str(w), x, SR)
        mp3 = tmp / f"{name}.mp3"
        _stereo_mp3(w, mp3, max_s=50.0)
        clips.append(mp3)
    prompt = (
        "Four versions of the same industrial-metal game-music combat "
        "passage. In each, a STING (a single accent event marking a "
        "threat spike) lands about 22 seconds in. The sting differs: "
        "A uses a bright clanging bell; B a single very deep church "
        "bell strike alone; C the same deep bell entered via a short "
        "reversed-cymbal swell; D the swell plus a cymbal crash on the "
        "landing. Judge each sting for: reads as an intentional "
        "MUSICAL event; on-key with the track; weight/menace; any "
        "clutter or glitchiness. Respond ONLY with JSON: "
        "{\"per_clip\": {\"A\": {\"musical\": 1-10, \"weight\": 1-10, "
        "\"note\": \"..\"}, ...}, \"ranking\": [best..worst], "
        "\"verdict\": \"one sentence\"}")
    print(json.dumps(_ask_multi(clips, prompt), indent=1))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "judge"
    (render if mode == "render" else judge)()
