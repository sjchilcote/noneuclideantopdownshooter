"""Vital preset scout — screen .vital banks for slot candidates.

    uv run python tools/musicgen/preset_scout.py render   # phase 1
    uv run python tools/musicgen/preset_scout.py probe    # phase 2
    uv run python tools/musicgen/preset_scout.py top      # shortlist

Phase 1: every preset renders short standard phrases through Vitalium
(ctypes host) in the roles its name plausibly fits (name keywords widen
to all roles for unknowns): bass riff cell (D1..D2), lead line (D4),
sustained pad chord (D3). Cached to scratchpad/preset_scout/.
Phase 2: flash scores each render against the slot brief (the
director's law: flash for individual instruments only).
Phase 3: prints the top candidates per slot for the lab.

Results in preset_scout_scores.json (committed — the renders aren't).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

S = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
         "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b"
         "/scratchpad/musicgen")
BANKS = {
    "tngkaos": S / "tngkaos/TngKaos/Presets",
    "5years": S / "fiveyears/5 Years of Vital/Presets",
}
OUT = S / "preset_scout"
SCORES = Path(__file__).parent / "preset_scout_scores.json"
SR = 44100

ROLE_KEYS = {
    "bass": ["bass", "sub", "reese", "808", "low"],
    "lead": ["lead", "pluck", "arp", "keys", "stab", "acid", "saw",
             "synth", "solo"],
    "pad": ["pad", "choir", "string", "ambi", "atmo", "drone", "angel",
            "altar", "space", "sphere"],
}
# probe phrases per role: (notes as (midi, t, dur, vel), total_s)
PHRASES = {
    "bass": ([(38, 0.0, 0.4, 110), (38, 0.5, 0.4, 96),
              (41, 1.0, 0.4, 110), (38, 1.5, 0.7, 118)], 2.6),
    "lead": ([(62, 0.0, 0.45, 108), (65, 0.5, 0.45, 108),
              (63, 1.0, 0.45, 108), (62, 1.5, 0.9, 112)], 2.8),
    "pad": ([(50, 0.0, 2.4, 100), (57, 0.0, 2.4, 100),
             (62, 0.0, 2.4, 96)], 3.2),
}
BRIEFS = {
    "bass": "A synth bass for dark industrial-metal combat music: heavy,"
            " gritty, aggressive low end with harmonic body; would sit"
            " under distorted guitars. Not soft, not funky-clean.",
    "lead": "A lead synth voice for dark industrial combat music in a"
            " retro-futuristic cosmic-horror game: cutting, characterful,"
            " aggressive or eerie. Not cheerful EDM, not thin.",
    "pad": "A sustained pad/atmosphere for a dark derelict-station"
           " sanctuary: vast, haunted, reverent or dreadful. Not bright,"
           " not new-age pleasant.",
}


def roles_for(name: str):
    low = name.lower()
    roles = [r for r, keys in ROLE_KEYS.items()
             if any(k in low for k in keys)]
    return roles or list(ROLE_KEYS)      # unknown -> try all


def all_presets():
    out = []
    for bank, root in BANKS.items():
        if root.exists():
            out += [(bank, p) for p in sorted(root.glob("*.vital"))]
    return out


def phase_render():
    import soundfile as sf
    from vst2_host import Vst2Synth
    OUT.mkdir(exist_ok=True)
    so = S / "vital/VitalInstaller/lib/vst/Vital.so"
    synth = Vst2Synth(so)
    todo = []
    for bank, p in all_presets():
        for role in roles_for(p.stem):
            wav = OUT / f"{bank}__{p.stem}__{role}.wav"
            if not wav.exists():
                todo.append((bank, p, role, wav))
    print(f"{len(todo)} renders to do", flush=True)
    for i, (bank, p, role, wav) in enumerate(todo):
        try:
            synth.set_chunk(p.read_bytes() + b"\0")
            seq, total = PHRASES[role]
            x = synth.render(seq, total, tail_s=0.8)
            pk = float(np.abs(x).max())
            if pk < 1e-4:
                continue                    # silent in this role: skip
            x = x / pk * 0.85
            sf.write(str(wav), x.astype(np.float32), SR)
        except Exception as exc:
            print(f"  {p.stem}/{role} FAILED: {exc}", file=sys.stderr,
                  flush=True)
        if (i + 1) % 50 == 0:
            print(f"[{i + 1}/{len(todo)}]", flush=True)
    print("render phase done", flush=True)


def phase_probe(n_max: int | None = None):
    sys.path.insert(0, str(Path(__file__).resolve()
                           .parents[1] / "playtest"))
    from audio_judge import judge
    scores = json.loads(SCORES.read_text()) if SCORES.exists() else {}
    wavs = sorted(OUT.glob("*.wav"))
    todo = [w for w in wavs if w.stem not in scores]
    if n_max:
        todo = todo[:n_max]
    print(f"{len(todo)} probes to do", flush=True)
    for i, w in enumerate(todo):
        role = w.stem.rsplit("__", 1)[1]
        try:
            r = judge(str(w), BRIEFS[role], n_passes=1)
            scores[w.stem] = dict(p=r["p_shippable"],
                                  match=r["matches_spec"],
                                  summary=r["summary"][:160])
        except Exception as exc:
            print(f"  {w.stem} probe failed: {exc}", file=sys.stderr,
                  flush=True)
        if (i + 1) % 25 == 0:
            SCORES.write_text(json.dumps(scores, indent=1))
            print(f"[{i + 1}/{len(todo)}] saved", flush=True)
    SCORES.write_text(json.dumps(scores, indent=1))
    print("probe phase done:", len(scores), "scored", flush=True)


def phase_top(k: int = 8):
    scores = json.loads(SCORES.read_text())
    by_role: dict[str, list] = {}
    for stem, s in scores.items():
        bank_preset, role = stem.rsplit("__", 1)
        by_role.setdefault(role, []).append((s["p"], bank_preset,
                                             s["summary"]))
    for role, items in sorted(by_role.items()):
        items.sort(reverse=True)
        print(f"== {role} (top {k} of {len(items)})")
        for p, name, summ in items[:k]:
            print(f"  {p:.2f}  {name}")
            print(f"        {summ}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "render"
    if cmd == "render":
        phase_render()
    elif cmd == "probe":
        phase_probe(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif cmd == "top":
        phase_top()
