"""boss_probe — batch-run the bot headless and measure BOSS MUSIC.

    uv run python tools/musiccal/boss_probe.py --level levels/gauntlet4.json \
        --seeds 1000:1016 [--procs 8] [--max-ticks 64800]

Per seed: farm-exact session (tune_pass_rate.one()'s construction, the
same loop farm_record replays) with a tick-clock MusicSystem attached;
captures the music taps in memory and reports outcome + boss-music
engagement. A FULL boss trigger is operationalized from the engine's
own thresholds (music.py): a contiguous run of >=4 bars with the boss
lane (overlay_boss) at gain >=0.20 (stalwart ~0.90+), peaking >=0.45
(stalwart ~0.94), with the drums_boss kit engaged inside the run.

Also reports death diagnostics (tick, polygon kind, wardens down) so the
same tool drives bot iteration.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))

FULL_MIN_BARS = 4
FULL_GAIN = 0.20
FULL_PEAK = 0.45


def one(args):
    seed, level_path, max_ticks, skill, godmode = args
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from perihelion.audio import Audio
    from perihelion.levels import load_level
    from perihelion.music import MUSIC_ROOT, MusicSystem
    from perihelion.sim import GameSession
    from perihelion.testkit.humanbot import DEFAULT_SKILL, HumanBot
    from perihelion.testkit.loadouts import FULL_LOADOUT

    taps = []
    tick = [0]

    def tap(kind, name, vol, pan):
        taps.append((tick[0] / 60.0, kind, name))

    state = dict(FULL_LOADOUT)
    state["max_hp"] = state["hp"] = FULL_LOADOUT["max_hp"]
    # godmode is the CONTENT instrument: an unkillable bot walks the
    # whole gauntlet so arena music can be measured without the bot's
    # survival skill confounding it
    state["dmg_taken_mul"] = 0.0 if godmode else 1.0
    level = load_level(Path(level_path))
    session = GameSession(level, seed=seed, player_state=state,
                          screen=(640, 360), zoom=0.45)
    session.music_tier = getattr(level, "tier", 1)
    bot = HumanBot(seed, skill=skill if skill is not None
                   else DEFAULT_SKILL)
    audio = Audio(mute=True)
    audio.tap = tap
    banks = sorted(p for p in MUSIC_ROOT.glob("album_*")
                   if (p / "bank.json").exists())
    music = MusicSystem(audio, enabled=True, bank_dirs=banks or None,
                        tick_clock=True)

    n_wardens0 = sum(1 for e in session.enemies.values()
                     if e["kind"] == "warden")
    t = 0
    flight = []     # per-6-tick: (t, ppolygon, hp, warden_hp, n_hunt)
    while t < max_ticks and not session.dead and not session.complete:
        snap = session.snapshot()
        inp = bot.step(snap, session)
        session.tick(inp)
        audio.handle_sounds(session, session.fx)
        music.update(session)
        if t % 6 == 0:
            ppolygon_ = snap.get("polygon")
            whp = max((e["hp"] for e in snap.get("enemies", ())
                       if e["kind"] == "warden"
                       and e["polygon"] == ppolygon_), default=None)
            nh = sum(1 for e in snap.get("enemies", ())
                     if e["polygon"] == ppolygon_ and e["kind"] != "warden"
                     and e["state"] in ("hunt", "waking"))
            flight.append((t, ppolygon_, snap.get("hp"), whp, nh))
        tick[0] += 1
        t += 1
    # ---- encounter records (Sol 2 §1, lean): a contiguous span of
    # co-polygon warden samples = one encounter
    encounters = []
    cur = None
    for ft, fr, fhp, fwhp, fnh in flight:
        if fwhp is not None:
            if cur is None or fr != cur["polygon"] or \
                    ft - cur["last_t"] > 360:
                cur = dict(polygon=fr, t0=ft, hp0=fhp, whp0=fwhp,
                           last_t=ft, hp_end=fhp, whp_end=fwhp,
                           whp_355=None, max_hunt=fnh)
                encounters.append(cur)
            cur["last_t"] = ft
            cur["hp_end"] = fhp
            cur["whp_end"] = fwhp
            cur["max_hunt"] = max(cur["max_hunt"], fnh)
            if cur["whp_355"] is None and ft - cur["t0"] >= 355:
                cur["whp_355"] = fwhp
    enc_out = []
    for e in encounters:
        if e["last_t"] - e["t0"] < 60:
            continue                # a walk-past, not a fight
        won = e["whp_end"] is not None and e["whp_end"] <= 0.0
        enc_out.append(dict(
            t0=round(e["t0"] / 60.0, 1),
            dur=round((e["last_t"] - e["t0"]) / 60.0, 1),
            hp0=e["hp0"], hp_end=e["hp_end"],
            whp0=round(e["whp0"]), whp_355=e["whp_355"],
            max_hunt=e["max_hunt"]))

    outcome = ("complete" if session.complete
               else "death" if session.dead else "timeout")
    wardens_left = sum(1 for e in session.enemies.values()
                       if e["kind"] == "warden")
    death_polygon_kind = death_co = None
    if session.dead:
        ppolygon = session.player_polygon()
        try:
            death_polygon_kind = level.polygon_kinds[ppolygon]
        except Exception:
            death_polygon_kind = "?"
        death_co = sorted(v["kind"] for k, v in session.enemies.items()
                          if session.sim.get_polygon(k) == ppolygon)[:8]
        snap = session.snapshot()
        death_ammo = {k: v for k, v in snap.get("ammo", {}).items()}
        death_weapon = snap.get("weapon")

    # ---- boss-music analysis from the captured taps -------------------
    boss_bars = []      # (t, boss_gain, drums_key)
    for tt, kind, name in taps:
        if kind != "music_bar":
            continue
        lanes = {}
        for part in name.split("|")[1:]:
            ln, k, g = part.rsplit(":", 2)
            lanes[ln] = (k, float(g))
        bg = lanes.get("boss", ("silence", 0.0))
        dk = lanes.get("drums", ("silence", 0.0))[0]
        boss_bars.append((tt, bg[1] if bg[0] != "silence" else 0.0, dk))
    runs, cur = [], None
    for tt, g, dk in boss_bars:
        if g >= FULL_GAIN:
            if cur is None:
                cur = dict(t0=tt, t1=tt, bars=0, peak=0.0, kit=False)
            cur["t1"] = tt
            cur["bars"] += 1
            cur["peak"] = max(cur["peak"], g)
            cur["kit"] |= dk.startswith("drums_boss")
        elif cur is not None:
            runs.append(cur)
            cur = None
    if cur is not None:
        runs.append(cur)
    full = [r for r in runs
            if r["bars"] >= FULL_MIN_BARS and r["peak"] >= FULL_PEAK
            and r["kit"]]
    return dict(seed=seed, outcome=outcome, ticks=t,
                diag=dict(getattr(bot, "diag", {})),
                kills=session.metrics.get("kills", 0),
                wardens_down=n_wardens0 - wardens_left,
                n_wardens=n_wardens0,
                death_polygon=death_polygon_kind, death_co=death_co,
                death_ammo=locals().get("death_ammo"),
                death_weapon=locals().get("death_weapon"),
                encounters=enc_out,
                boss_runs=[(round(r["t0"], 1), round(r["t1"], 1),
                            r["bars"], round(r["peak"], 2), r["kit"])
                           for r in runs],
                full_triggers=len(full))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="levels/gauntlet4.json")
    ap.add_argument("--seeds", default="1000:1016",
                    help="a:b range or comma list")
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--max-ticks", type=int, default=64800)
    ap.add_argument("--json", default=None,
                    help="also dump per-seed results to this path")
    ap.add_argument("--skill", type=float, default=None)
    ap.add_argument("--godmode", action="store_true")
    a = ap.parse_args()
    if ":" in a.seeds:
        lo, hi = a.seeds.split(":")
        seeds = list(range(int(lo), int(hi)))
    else:
        seeds = [int(s) for s in a.seeds.split(",")]
    jobs = [(s, a.level, a.max_ticks, a.skill, a.godmode)
            for s in seeds]
    with ProcessPoolExecutor(max_workers=a.procs) as ex:
        results = list(ex.map(one, jobs))
    clears = [r for r in results if r["outcome"] == "complete"]
    for r in results:
        rt = " ".join(f"{t0:.0f}-{t1:.0f}({b}b,{p})"
                      for t0, t1, b, p, k in r["boss_runs"]) or "-"
        dc = ",".join(r.get("death_co") or []) or "-"
        dg = r.get("diag") or {}
        am = r.get("death_ammo") or {}
        wstr = (f" w={r.get('death_weapon')} "
                f"ammo={sum(am.values()) if am else '-'}") \
            if r["outcome"] == "death" else ""
        print(f"seed {r['seed']}: {r['outcome']:8s} "
              f"t={r['ticks']/60:5.0f}s kills={r['kills']:3d} "
              f"wardens {r['wardens_down']}/{r['n_wardens']} "
              f"full_triggers={r['full_triggers']} "
              f"death={r['death_polygon']}[{dc}] "
              f"fun={dg.get('funnel',0)} dod={dg.get('dodge',0)} "
              f"runs: {rt}{wstr}")
    print(f"\nclear rate {len(clears)}/{len(results)} "
          f"({100*len(clears)/max(1,len(results)):.0f}%)")
    if clears:
        ft = [r["full_triggers"] for r in clears]
        print(f"full boss triggers on clears: min={min(ft)} "
              f"mean={sum(ft)/len(ft):.1f} "
              f"(goal: >=3 in the winning run)")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
