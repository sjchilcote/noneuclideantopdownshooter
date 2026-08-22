"""Preset browser — sort through the Vital goldmine by ear.

    uv run python tools/musicgen/preset_browser.py

Plays the scout's pre-rendered probe clips (no rendering in the UI).
Click a row = play once. Your picks are the point: press SPACE (or
right-click a row) to toggle a pick on the last-played preset — picks
save to tools/musicgen/director_picks.json immediately and outrank
everything downstream (slot assignments draw from picks first, scout
scores second).

Controls:
  left panel      filter by role (bass/lead/pad/all) + sort mode
  click row       play that probe clip once
  right-click     toggle pick directly
  SPACE           toggle pick on last-played
  mouse wheel     scroll
  S               cycle sort: score / name / picks-first
  ESC             quit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

S = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
         "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b"
         "/scratchpad/musicgen/preset_scout")
SCORES = Path(__file__).parent / "preset_scout_scores.json"
PICKS = Path(__file__).parent / "director_picks.json"


def main():
    import mgui
    from perihelion import fb2d, text, uievent
    W, H = 1100, 780
    disp = mgui.Display(W, H, "PERIHELION preset browser")
    screen = disp.fb
    font, big = 14, 17            # text.blit_text sizes (FSEX300)
    player = mgui.OneShot(mgui.audio())

    scores = json.loads(SCORES.read_text()) if SCORES.exists() else {}
    picks = set(json.loads(PICKS.read_text())) if PICKS.exists() else set()

    entries = []          # (stem, bank, preset, role, score)
    for w in sorted(S.glob("*.wav")):
        stem = w.stem
        bank_preset, role = stem.rsplit("__", 1)
        bank, preset = bank_preset.split("__", 1)
        sc = scores.get(stem, {}).get("p")
        entries.append([stem, bank, preset, role, sc, w])

    role_filter = "all"
    sort_mode = "score"
    scroll = 0
    last_played = None

    def visible():
        rows = [e for e in entries
                if role_filter == "all" or e[3] == role_filter]
        if sort_mode == "score":
            rows.sort(key=lambda e: -(e[4] if e[4] is not None else -1))
        elif sort_mode == "name":
            rows.sort(key=lambda e: e[2].lower())
        else:                                   # picks-first
            rows.sort(key=lambda e: (e[0] not in picks,
                                     -(e[4] or 0)))
        return rows

    def save_picks():
        PICKS.write_text(json.dumps(sorted(picks), indent=1))

    def toggle(stem):
        if stem in picks:
            picks.discard(stem)
        else:
            picks.add(stem)
        save_picks()

    rows_top = 76
    row_h = 20
    n_show = (H - rows_top - 20) // row_h
    clock = mgui.Clock()
    running = True
    while running:
        rows = visible()
        for ev in disp.events():
            if ev.type == uievent.QUIT:
                running = False
            elif ev.type == uievent.KEYDOWN:
                if ev.key == uievent.K_ESCAPE:
                    running = False
                elif ev.key == uievent.K_SPACE and last_played:
                    toggle(last_played)
                elif ev.key == uievent.K_s:
                    order = ["score", "name", "picks"]
                    sort_mode = order[(order.index(sort_mode) + 1)
                                      % len(order)]
            elif ev.type == uievent.MOUSEWHEEL:
                scroll = max(0, min(len(rows) - n_show,
                                    scroll - ev.y * 3))
            elif ev.type == uievent.MOUSEBUTTONDOWN and ev.button in (1, 3):
                x, y = ev.pos
                if y < rows_top and x < 500:
                    seg = x // 100
                    role_filter = ["all", "bass", "lead",
                                   "pad"][seg] if seg < 4 else role_filter
                    scroll = 0
                elif y >= rows_top:
                    i = scroll + (y - rows_top) // row_h
                    if 0 <= i < len(rows):
                        stem = rows[i][0]
                        if ev.button == 3:
                            toggle(stem)
                        else:
                            player.play(rows[i][5])
                            last_played = stem

        fb2d.fill(screen, (15, 15, 19))

        def txt(s, x, y, c=(200, 200, 200), f=font):
            text.blit_text(screen, s, x, y, c, f)

        for i, rf in enumerate(["all", "bass", "lead", "pad"]):
            sel = rf == role_filter
            fb2d.rect(screen, (85, 65, 35) if sel else (38, 38, 46),
                      (10 + i * 100, 12, 92, 26))
            txt(rf, 24 + i * 100, 18,
                (255, 240, 200) if sel else (180, 180, 180))
        txt(f"sort[S]: {sort_mode}   picks: {len(picks)}   "
            f"SPACE=pick last-played   right-click=pick row",
            430, 18, (240, 220, 160))
        txt(f"{len(rows)} clips  (scored {sum(1 for e in rows if e[4] is not None)})",
            10, 52, (150, 150, 160))
        for k in range(min(n_show, len(rows) - scroll)):
            stem, bank, preset, role, sc, _w = rows[scroll + k]
            y = rows_top + k * row_h
            picked = stem in picks
            col = (255, 220, 130) if picked else \
                  (140, 230, 140) if stem == last_played else \
                  (195, 195, 195)
            mark = "*" if picked else " "
            sc_s = f"{sc:.2f}" if sc is not None else "  — "
            txt(f"{mark} {sc_s}  {role:4s}  {preset:44.44s} {bank}",
                12, y, col)
        disp.flip()
        clock.tick(30)


if __name__ == "__main__":
    main()
