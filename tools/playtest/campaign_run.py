"""Sequential campaign playtest: the real difficulty instrument.

Mirrors the shipping app's rules: player state (hp floor 40, ammo, weapons)
carries between levels; death retries the SAME level with the state it was
entered with; a level failed MAX_RETRIES times aborts the run.

Usage: uv run python tools/playtest/campaign_run.py [--seed N] [--bot aggro]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "game"))

from perihelion.levels import load_level  # noqa: E402
from perihelion.sim import GameSession, PLAYER_HP  # noqa: E402
from perihelion.testkit import bots  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MAX_RETRIES = 6
MAX_TICKS = 60 * 420


def run_level(level, bot, seed, player_state):
    s = GameSession(level, seed=seed, player_state=player_state)
    t = 0
    while not s.dead and not s.complete and t < MAX_TICKS:
        t += 1
        s.tick(bot.step(s.snapshot(), s))
    outcome = "complete" if s.complete else ("died" if s.dead else "timeout")
    return outcome, s


def run_campaign(bot_name: str, seed: int, verbose=True):
    manifest = json.loads((ROOT / "levels" / "campaign.json").read_text())
    bot_cls = {"aggro": bots.AggroBot, "pacifist": bots.PacifistBot,
               "explorer": bots.ExplorerBot}[bot_name]
    state = None
    report = []
    for li, rel in enumerate(manifest["levels"], 1):
        level = load_level(ROOT / rel)
        entry_state = dict(state) if state else None
        attempts = 0
        while True:
            attempts += 1
            bot = bot_cls(seed=seed * 1000 + li * 17 + attempts)
            outcome, s = run_level(level, bot, seed + attempts, entry_state)
            if outcome == "complete":
                state = dict(hp=max(s.hp, 40), ammo=dict(s.ammo),
                             weapons=list(s.weapons), weapon=s.weapon)
                break
            if attempts >= MAX_RETRIES:
                break
        m = s.metrics
        report.append(dict(level=level.name, attempts=attempts,
                           outcome=outcome, secs=m["ticks"] // 60,
                           kills=m["kills"], hp_end=s.hp,
                           ammo=sum(s.ammo.values()),
                           weapons=len(s.weapons)))
        if verbose:
            r = report[-1]
            print(f"L{li:02d} {level.name[:24]:24s} tries={attempts} "
                  f"{outcome:8s} {r['secs']:3d}s kills={r['kills']:2d} "
                  f"hp={max(0, round(s.hp)):3d} ammo={r['ammo']:3d} "
                  f"weps={r['weapons']}")
        if outcome != "complete":
            if verbose:
                print(f"CAMPAIGN FAILED at L{li:02d} after {attempts} tries")
            return report, False
    if verbose:
        print("CAMPAIGN CLEARED")
    return report, True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--bot", default="aggro")
    args = ap.parse_args()
    report, cleared = run_campaign(args.bot, args.seed)
    total_tries = sum(r["attempts"] for r in report)
    print(f"\ntotal attempts: {total_tries} over {len(report)} levels")
