---
This specfile tells the work of the NETDS game runtime: the Python package `game/perihelion/`, without its `editor/` directory (see `spec/netds-editor.md`) and without its `testkit/` directory (a development harness). The files covered are `game/perihelion/__main__.py`, `app.py`, `sim.py`, `levels.py`, `render.py`, `menus.py`, `hud.py`, `audio.py`, and `stream.py`. The file also covers the level data contract that the game consumes: `levels/campaign.json`, `levels/l01.json` through `levels/l10.json`, and `levels/vigil.json` (`levels/smoke_4room.json` uses the same format and belongs to the test harness). The warm-start procedure wrote this file from the code at commit `bce6b56`. All sections tell the facts of the code as it is. The UX standard binds every player-facing surface in this file, per `spec/standards/manifest.md`.

---

# The NETDS game

NETDS is a top-down shooter. The world is a graph of convex polygons, and portals connect them edge to edge. Space therefore does not have to be Euclidean. Corridors can loop into themselves, a wall can mirror the room in front of it, and a portable hole can staple two distant walls together. The player descends through a ten-level campaign that streams into one seamless world. Six enemy kinds oppose seven weapons and a hole, and a separate endless mode, the Vigil, sends waves instead of levels.

The modules divide the work like this. `sim.py` is the deterministic core. One `GameSession` object holds the whole game state and advances it one 60 Hz tick at a time. It uses no I/O, no wall clock, and no pygame. `levels.py` reads the JSON level format and also contains the programmatic level builder. `stream.py` joins campaign levels into one live world and handles checkpoint respawn.

`render.py` paints a frame from the engine's visibility query. `hud.py` draws the status overlay. `audio.py` plays the sound bank with portal-graph attenuation. `menus.py` holds the scene-stack screens around the game. `app.py` owns the window, the fixed-timestep loop, the campaign progression, and the save file. `__main__.py` is the command line.

Two facts hold across the whole runtime:

- Same level, same seed, same input sequence give a bit-identical run. All randomness comes from one `random.Random(seed)` inside the session. The test `test_two_identical_aggro_runs_are_bit_identical` checks this.

- The package, the window caption, the save directory, and the final level title all still carry the name `PERIHELION`. Decision open (see `spec/open-questions.md` item NETDS-4).

## Entry point (`__main__.py`)

### Goal

`uv run python -m perihelion` starts the game. Options select a level, a seed, a window scale, hard mode, mute, and the fps overlay. Hidden options drive the development harness: autoplay bots, frame recording, and a starting chunk.

### Invariants

- `--record` without `--bot` selects the `aggro` bot. Any `--bot` turns autoplay on.

### Verification

- `uv run python tools/playtest/campaign_run.py --seed 1 --bot aggro` drives this entry path headless. Run on 2026-08-22: all ten campaign levels complete, one try each.

### Implementation

`main` parses the arguments and constructs `App(args)`:

- `--level PATH` — one level file instead of the campaign manifest. A relative path resolves against the repository root, not the working directory.

- `--seed N` — the session RNG seed. Default `None`, which the app treats as 0.

- `--scale N` — integer pixel scale for the window. Default: a fixed `1440x810` window.

- `--mute`, `--hard`, `--fps` — audio off, hard difficulty, fps overlay.

- Hidden (`argparse.SUPPRESS`): `--autoplay`, `--bot {aggro,explorer,pacifist}`, `--record DIR`, `--record-every N` (default 2), `--record-seconds S` (default 180), `--start-chunk N`.

After the flag coupling above, it imports `App` from `app.py` and calls `app.run()`.

### Caveats

- The `argparse` program name is `perihelion`. Decision open (see `spec/open-questions.md` item NETDS-4).

## Application shell: window, loop, and scene stack (`app.py`)

### Goal

`App` owns the pygame window and the main loop. The simulation ticks at a fixed 60 Hz that never depends on the display rate. The game renders at an internal `640x360` surface. It reaches the window through integer scaling with letterbox bars, so pixels stay square and crisp at any window size. A scene stack routes input, and only the top scene receives events, updates, and draws. Pausing therefore comes free: the game scene stops ticking the moment anything sits above it.

### Invariants

- Sim ticks are exactly `1/60` s of simulated time. A slow frame runs at most 4 catch-up ticks. A stall longer than 0.25 s loses the excess time instead of running a tick burst.

- Only the top of the scene stack receives events. Game ticks run only while a `GameScene` is on top.

- Mouse positions map into internal coordinates through the inverse of the letterbox layout and clamp to the internal surface.

### Verification

- `test_render_headless_smoke` exercises the internal-surface path under `SDL_VIDEODRIVER=dummy`.

- The manual keys and the resize path are unverified by tests. The streamed-app soak recorded in `litc/separation-plan.md` exercised the loop for 400 s.

### Implementation

Construction: `pygame.init()`, a resizable window, caption `PERIHELION`, an internal `640x360` surface, `Audio(mute)`, the save load, and the settings assembly. `--scale` sizes the window at `640*scale x 360*scale`, else it opens at `1440x810`. `--hard` overrides the saved difficulty for this launch. Saved master volume and mute apply to the audio. Construction ends with the optional bot from `testkit.bots`, the optional frame-recording state, and `_start_scene`. The app detects the SDL `dummy` video driver and stores the fact.

Layout: `_recompute_layout` picks `scale = max(1, min(window_w // 640, window_h // 360))` and centers the scaled surface. `window_to_internal` inverts that mapping and clamps into `[0, 640] x [0, 360]`. `_blit_scaled` scales the internal surface once per frame. It blits at the letterbox offset plus the screen-shake offset.

The loop (`run`), each iteration:

1. Read wall time. Recording mode instead forces exactly one tick per frame, decoupled from wall time.

2. Drain events: `QUIT`, `VIDEORESIZE` relayout, `F11` fullscreen toggle, everything else to the top scene.

3. Run the autoplay nudge, then up to 4 sim ticks through `_tick_game`, then the top scene's `update`.

4. Draw the frame, record it when recording, and cap at 60 fps (uncapped under the dummy driver).

On exit the loop closes the recording event file and persists the save.

Global keys inside `GameScene.handle_event`: `ESC` pushes the pause scene, `F3` toggles the debug overlay, and `F12` writes a screenshot. Screenshots of the internal surface go to `$PERIHELION_SCREENSHOT_DIR` or `<save_dir>/screenshots`. Keys `1`-`8` select a weapon slot, and the mouse wheel cycles through owned weapons. `F11` and `QUIT` work in every scene.

Scene stack: `push` and `pop` call `on_enter` and `on_exit`. `replace` empties the stack and pushes. `pop_to_title` empties the stack, drops the game reference, and pushes the title scene.

Autoplay nudge: with `--autoplay` on and a non-game scene on top, a counter presses `SPACE` after 90 frames. When the scene ignored `SPACE`, it presses `ESC` (the win scene answers only `ESC`). Soaks therefore test gameplay, not a press-any-key card.

Recording: `--record DIR` writes every Nth internal frame as a PNG plus an `events.jsonl` of audio taps. The taps are timestamped on the drawn-frame clock, and recording stops after `--record-seconds` of frames. `tools/playtest/mkvideo.py` rebuilds the soundtrack offline from that log.

### Caveats

- `_shake_offset` sums a uniform random jitter per live shake, clamps to `±9` internal pixels, and multiplies by the integer scale. The jitter uses the module-level `random`, not the session RNG. Shakes decay in `_tick_game` (magnitude times 0.82 per tick, 10 ticks maximum).

- The fps overlay draws in yellow at the top-left of the internal surface when the debug flag is on.

## Menu surfaces (`menus.py`)

### Goal

The screens around the game: title, difficulty question, level select, settings, level intro card, pause, death, and win. All render at the internal resolution in the game's typeface, Fixedsys Excelsior. That is a bitmap-grid font, so requested sizes snap to 16, 32, or 48 to keep every glyph on the pixel grid. Scenes that have a generated background image (`game/assets/art/`) use it. Every such scene falls back to its procedural background when the file does not exist, because the game must run with an empty art directory.

### Invariants

- `get_font` returns one cached `pygame.font.Font` per snapped size. Without the font file it falls back to the pygame default font.

- Menu navigation is keyboard only: arrows or `W`/`S` move, `RETURN`/`SPACE` activate, `ESC` goes back.

### Verification

- The de-narrativization soak recorded in `litc/separation-plan.md` drove the title, intro, and win scenes to New Game+. The individual scenes have no direct tests — unverified beyond that soak and the autoplay path.

### Implementation

- `TitleScene` — title `PERIHELION`, subtitle "a descent into non-Euclidean dark", menu `New Game`, `The Vigil (endless)`, `Level Select`, `Settings`, `Quit`. On entry it starts the `amb_drone_early` ambience. It inserts `New Game+` after `New Game` when the save records an earned NG+. It appends `- best N` to the Vigil item when a best wave exists. Background: `title_bg.png` with a dark text band, else a pulsing red-black gradient, with forty drifting dust pixels over either. `New Game` and `New Game+` push `DifficultyScene`, and the Vigil item calls `app.start_vigil()` directly.

- `DifficultyScene` — one question, "HOW FAR IN ARE YOU?", two answers: `NORMAL - the station is hostile` and `HARD - the station is hungry`. Selection writes `settings["difficulty"]` and starts the new game (carrying the NG+ flag). `ESC` backs out.

- `LevelSelectScene` — lists the campaign manifest by file stem, one line per level, `[locked]` past the save's `unlocked` count. Activating an unlocked entry calls `app.start_level_index(i)`. With no manifest it shows "(no campaign manifest -- debug level only)".

- `SettingsScene` — live keys, no selection cursor. Left and right arrows step master volume by 0.1. `m` toggles mute, `t` toggles screen shake, and `d` toggles the difficulty for the next new game. `ESC` persists the save and pops.

- `IntroCard` — the level-name card at the start of a sortie. Background `intro_t<tier>.png` (tier clamped 1-4) under a translucent black overlay, else near-black. Any key or mouse button pops it.

- `PauseScene` — draws the frozen game underneath, a 165-alpha black overlay, `PAUSED`, and the menu `Resume`, `Restart Level`, `Settings`, `Quit to Title`. `ESC` resumes.

- `DeathScene` — `death_bg.png` or the frozen game under a red overlay, and a pulsing `YOU DIED`. Below it: `deaths: N`, or in the Vigil `waves: N (best: M)`. `R`, `SPACE`, or `RETURN` pops and restarts the level. `ESC` returns to the title.

- `WinScene` — scrolls the campaign-complete text up the screen at 10 px/s over `win_bg.png` or black, then shows `ESC: title`. The text is the `WIN_TEXT` constant in `app.py`: "CAMPAIGN COMPLETE." and "New Game+ unlocked: the loop begins again, harder, with everything you carry."

### Caveats

- A comment beside the font path still says the internal resolution is `480x270`. The internal resolution is `640x360`. The snapping behavior itself is unaffected.

- Menu items match by string (`item == "New Game"`, `item.startswith("The Vigil")`). The best-wave suffix is why the Vigil match is a prefix test.

## Game scene: input capture and screen text (`app.py`, `GameScene`)

### Goal

`GameScene` binds one `GameSession` to the window. It samples the keyboard and mouse into the session's input frame and draws the world and the HUD. It also floats transient text. Pickup labels rise and fade, the location title shows on arrival, and two control-hint lines open a fresh campaign.

### Invariants

- One `InputFrame` per sim tick. `WASD` gives the move axes, the mouse position (in internal coordinates) is the aim, the left button fires, and the right button is alt-fire. The pending weapon selection is consumed exactly once.

- Float texts and the location title decay per drawn frame and never outlive their timers.

### Verification

- The input path runs end to end only under autoplay, and bots bypass `_input_frame`. Manual input mapping is confirmed by the soak, not by a test — unverified in the suite.

### Implementation

Construction takes the level, seed, optional carried player state, optional level path, and difficulty. It builds the `GameSession` at `640x360`, a `Renderer`, and a `HUD`. `on_enter` starts the level's ambience loop.

`_input_frame` reads pygame state directly. `d`/`a` and `s`/`w` give the move axes as -1, 0, or 1. The mouse maps through `window_to_internal`, and buttons 0 and 2 give fire and alt. `app.pending_weapon_select` (set by number keys and wheel cycling) transfers into the frame and resets to 0.

`draw` renders the world, then the HUD with the mouse position, then the screen text. Float texts rise 0.35 px per tick and fade over the last 24 of 66 ticks. Their color: green for `INTEGRITY`, tan for other `+` amounts, off-white otherwise. The location title draws at 26 px top center for 4 s, fading in the last second.

Hints show only when `show_hints` is set — a fresh campaign start that is not NG+. They last the first 14 s of the session and fade over the last 3. They draw on a dark plate, so busy floors do not eat the text. The two lines are "WASD move    mouse aim    LMB fire" and "1-8 weapons    ESC pause".

`_cycle_weapon` walks `WEAPON_ORDER` from the current weapon in wheel direction until it finds an owned weapon. It stores that slot in `pending_weapon_select`.

### Caveats

- Weapon selection set while a menu covers the game stays pending and applies on the first unpaused tick.

## The tick bridge (`app.py`, `_tick_game`)

### Goal

One call advances the game one tick and distributes the consequences. The input (bot or human) goes into the session, and the streamer advances. The effect list feeds the renderer and the audio, screen shake and floating text spawn, and death and completion push their scenes.

### Invariants

- The renderer and the audio see every tick's `fx` list exactly once.

- The death scene appears exactly on the tick where `dead` flips true. The completion transition fires exactly on the tick where `complete` flips true.

- Level completion carries the player forward with hp floored at 40, plus ammo, holes, the cloister flag, and the weapon list.

### Verification

- `test_stream_lazy_load_arrival_and_completion` and `test_stream_respawn_at_chunk_entry` cover the session and streamer half of this path. The scene transitions are covered by the soak and the autoplay campaign run (2026-08-22).

### Implementation

The order per tick: bot step or `_input_frame`, `session.tick(inp)`, `streamer.tick()` when streaming, `renderer.consume_fx(fx)`, `audio.handle_sounds(session, fx)`, `audio.update_heartbeat(session)`. Then the app-level fx apply:

- `shake` appends `[magnitude, 10]` when the shake setting is on. Shakes decay by the factor 0.82 per tick and drop below magnitude 0.05.

- `pickup_text` projects the world position through the session camera and spawns a 66-tick float text.

- `locname` sets the 4 s location title. `ambience` switches the ambience loop.

On a death edge in the Vigil, the reached wave persists to the save when it beats the best. The death scene then shows waves and best. Any other death shows the session's death count. On a completion edge, the carried state is assembled. A streamed run then marks NG+ (`ng_plus` count and `ng_state` in the save) and replaces everything with the win scene. A non-streamed run calls `advance_level`.

### Caveats

- `audio.handle_sounds` accepts the frame's visible-instance list for stereo panning. This call never passes it, so every sound plays center-panned (see the audio unit).

- Defect: `metrics["deaths"]` counts twice per streamed death. `_damage_player` counts the death, and streamed respawn counts it again, so the death scene shows 1, 3, 5, ... across successive deaths. A probe on 2026-08-22 (fatal hit, then `respawn()`) measured `deaths == 2` after one death.

## Campaign flow, New Game+, and the debug fallback (`app.py`)

### Goal

The campaign is a list of level files in a manifest. A new game streams them into one seamless world from the first chunk. Level select re-enters at any unlocked chunk with the state that chunk was first entered with. Finishing the last chunk unlocks New Game+: the loop begins again on hard, with everything the player carries. When nothing loads, a built-in three-room level starts instead, because the game must always start.

### Invariants

- The manifest order is the campaign order. `unlocked` in the save gates level select.

- New Game+ starts at chunk 0 on hard difficulty with the carried state from the completed run.

- Every load failure (manifest, level file, vigil file) logs to stderr and falls back — to an empty manifest, or to the debug level. It never crashes the app.

### Verification

- `test_campaign_exists_and_generator_runs` checks the manifest and files. The flow is verified by the campaign bot run of 2026-08-22 (ten completions) and the NG+ soak recorded in `litc/separation-plan.md`.

### Implementation

- `campaign_levels` — `--level` gives a one-entry list. Otherwise the manifest `levels/campaign.json` (`{"levels": [paths]}`) is read once and cached. Paths resolve against the repository root.

- `start_new_game(plus)` — for NG+ it sets difficulty hard and takes `ng_state` from the save, then `_start_streamed(0, state)`. A fresh non-NG+ start turns the control hints on.

- `_start_streamed(start_chunk, state)` — loads the chunk's level and builds the `GameScene` with seed `rng_seed + start_chunk`. It attaches a `WorldStreamer` and pushes the intro card. The streamer's arrival callback records `unlocked`, stores the chunk entry state under `states[str(idx)]`, and persists the save. With an empty manifest it falls back to `_load_and_play(0, state)`.

- `start_level_index(idx)` — `_start_streamed(idx, saved_states[str(idx)])`. Re-entry replays the state the chunk was first entered with.

- `_load_and_play(idx, state)` — the non-streamed path. It loads by index with the debug-level fallback, seed `rng_seed + idx`, and pushes the intro card only under a real video driver.

- `advance_level(carried)` — the non-streamed completion path. Past the end it marks NG+ and shows the win scene, otherwise it unlocks and starts the next index.

- `restart_level` — with a streamer it clears the float texts and calls `streamer.respawn()` (checkpoint reprint). Without one it reloads the current index with the state the level was started with.

- `build_debug_level` — three rectangular rooms in a corridor, a husk, a mite, ammo, a medkit, and an exit.

- `_start_scene` — under the dummy driver or autoplay the game starts immediately (at `--start-chunk` when given). Otherwise the title scene appears.

### Caveats

- Defect: dying in the Vigil and choosing "rise again" restarts into the debug level, not the Vigil. `start_vigil` sets `current_level_index = -1` and no streamer. `restart_level` therefore falls into `_load_and_play(-1)`, whose index check fails into the debug fallback. A probe on 2026-08-22 confirmed the reloaded level is `debug-corridor` with the Vigil loadout.

- Completing any streamed run marks NG+. That includes a `--level` one-off and a level-select entry into the final chunk. Proposed as a new open question in the warm-start report.

- `advance_level` is reachable only from the non-streamed path, which in practice is the debug fallback. Completing the debug level therefore also reaches the win scene.

## Save file (`app.py`)

### Goal

One JSON file persists progress and settings across launches. It holds the campaign unlocks, the per-chunk entry states, the New Game+ state, the Vigil best wave, and the audio and gameplay settings.

### Invariants

- The save path is `$XDG_DATA_HOME/perihelion/save.json`, or `~/.local/share/perihelion/save.json` without that variable.

- A missing or unreadable save yields the fresh state `{"unlocked": 1, "states": {}}` and a stderr log line. A write failure logs and does not crash.

### Verification

- Unverified by tests. The soak exercised write and re-read across the NG+ boundary.

### Implementation

Keys as written by the app:

- `unlocked` — count of selectable levels in level select.

- `states` — map of chunk index (as a string) to the entry state: `hp`, `ammo`, `weapons`, `weapon`, `holes`, `cloister` (a boolean).

- `settings` — `volume` (rounded to 2 decimals), `muted`, `shake`, `difficulty`.

- `ng_plus` — count of completed runs. Any nonzero value shows the `New Game+` menu item.

- `ng_state` — the carried state of the most recent completion.

- `best_wave` — the Vigil record.

Writes happen on quit, on settings exit, on chunk arrival, on Vigil death (best wave), and on completion. The file is written with `indent=1` after creating the directory.

### Caveats

- The directory name is `perihelion`. Decision open (see `spec/open-questions.md` item NETDS-4).

## Session core and the tick (`sim.py`, `GameSession`, `InputFrame`)

### Goal

`GameSession` is the whole game in one deterministic object. It ticks at 60 Hz from `InputFrame` values. Everything downstream reads data channels: `fx` (per-tick effect intents), `decals` (persistent per-room marks), `metrics` (run statistics), and `snapshot()` (the structured state for bots and tests). Hitstop freezes the world for a few ticks on heavy hits, so impacts land with weight.

### Invariants

- No I/O, no wall clock, no pygame inside the session. All randomness flows from `Random(seed)`.

- A dead or complete session ignores input and no longer simulates.

- During hitstop (`freeze > 0`) the tick consumes input without simulating.

- The camera matrix maps the player's current room to the internal screen. A portal transfer re-bases it with the inverse portal matrix, which changes nothing visibly by construction.

### Verification

- Determinism: `test_two_identical_aggro_runs_are_bit_identical`, `test_explorer_bot_run_is_deterministic`, `test_replay_record_play_roundtrip_identical_final_state`.

- Seamless camera re-base: `test_seamless_corridor_walk`, `test_seamless_infinite_loop_walk`, `test_seamless_doorway_wobble`, `test_seamless_mirror_approach`, `test_no_brightness_seam_across_transfers`.

- Containment: `test_normal_play_keeps_every_entity_inside`, `test_escaped_enemy_is_reclaimed_within_one_tick`.

### Implementation

`InputFrame` fields: `mx`, `my` (screen-space move, -1..1), `ax`, `ay` (aim in internal pixels), `fire`, `alt`, and `weapon`. A `weapon` of 0 keeps the current weapon, and 1..8 select `WEAPON_ORDER[i-1]`. `pack` rounds the axes (4 decimals for move, 2 for aim) into a list for replay files, and `unpack` reverses it.

Construction assembles, in order:

- The difficulty multipliers. `hard` gives enemy hp x1.35 and player damage taken x1.25.

- The RNG, the engine world (next unit), and the player body.

- The weapon and ammo state from `player_state` or the defaults: `knife` and `pistol`, 48 `9mm`, pistol in hand.

- The doors, the initial camera (`translate(screen/2) * scale(zoom) * translate(-player_pos)`, zoom 1.35), the authored entities, the exit, and the Vigil timer.

- The optional cloister rebuild, and the empty output channels.

`metrics` starts with `ticks`, `shots`, `hits`, `kills`, `dmg_dealt`, `dmg_taken`, `pickups`, `transfers`, `deaths`, `wave`, `rooms_visited` (a set), `hp_series`, and `completed`.

`tick(inp)` order:

1. Clear `fx`, count the tick, and append `hp` to `hp_series` once per 60 ticks.

2. Return early when dead or complete. Count down hitstop and return while frozen.

3. Activate the polygons within 5 hops of the player. Run player control, then enemy AI.

4. Apply friction to the player (factor 5.6) and each enemy (per-kind factor): velocity times `max(0, 1 - fric/60)` per tick.

5. Step the engine at `1/60` and consume the events. Sweep bullet lifetimes.

6. Tick turrets, scan pickups, scan the exit, and run the Vigil director when the level is a vigil.

7. Count down the fire cooldown and the hurt window. Regain one tick of lightning charge.

8. Move the camera toward centering the player, exponential factor `min(1, 7/60)` per tick.

`snapshot()` returns tick, hp, dead, complete, room, position, and the weapon state (weapon, weapons, ammo, keys, lightning readiness, hole count, tau charge). It adds the cloister link count and attachment, all enemies (id, kind, room, position, hp, state, hop distance), and all pickups. It ends with the exit data: exit room, next edge toward it, missing exit key, and the gate kind with count and room range. It also lists the sorted keys still needed for closed doors.

### Caveats

- The `screen` default in the constructor is `(480, 270)` and the `InputFrame` aim default is `(240, 135)` — both from an older internal resolution. The app always passes `640x360`. The defaults only affect tests that tick default frames, which then aim at a fixed point left of center.

- The comment on `InputFrame.weapon` says `1..6`. The code accepts 1..8, and slot 8 (the portable hole) is used by tests.

- `_outside_by` (signed clearance of a point against a convex polygon) has no callers in the runtime. `test_containment.py` uses it to assert the engine's containment invariant from the game side.

- `metrics["rooms_visited"]` is a set and would not survive JSON serialization. Nothing serializes metrics today.

## World construction and the collision policy (`sim.py`)

### Goal

The session builds the engine world from the level: polygons, portal connections, explicit-transform connections, and doors. A door is a pending connection — the rooms stay unconnected until it unlocks. A locked door is therefore genuinely a wall, and nothing sees through it. Entity collision follows the shared engine's law: all physical bodies collide. The only opt-out is the per-entity `physical` flag, which pickups and stationary guardians use.

### Invariants

- Doors register in two structures: `doors` (the unlock records) and `door_edges` (a map from `(room, edge)` to the key, both sides). The wall-hit handler and the renderer read `door_edges`.

- Pickups spawn with `physical=False` and `transfers=False`. Nothing collides with them, and they never drift through portals.

- Entity groups: 0 player, 1 enemies, 2 player bullets, 3 enemy bullets, 4 pickups.

### Verification

- `test_level_structure` builds every campaign level into a session. `test_transfer_preserves_speed_and_changes_room` and the seamless suite cover the connected world.

### Implementation

Construction adds each room polygon, then applies `connects` through `Sim.connect` (the engine derives the transform). `connects_x` rows go through `connect_with_xform` (an authored matrix). Doors record closed. The player spawns with radius 6.5, mass 1.2, wall restitution 0, entity restitution 0.05, and substep cap 6. Enemies spawn from their stat table with wall restitution 0, entity restitution 0.2, substep cap 8. Pickups spawn with mass 100 and the two opt-out flags.

A comment block at the collision policy (sim.py, near lines 162-172) records the engine divergence. The loop game configured collision pairs, and the shared engine hardwired "both bodies physical". Four pairs flipped from off to on:

- Enemy shots now hit enemies, so spitters can be body-blocked.

- Player pellets perturb each other.

- Player rounds deflect enemy shots.

- Radial bursts self-interact at spawn.

The preserved pairs include player-bullet against player: rounds that return through a fold still hit their shooter.

### Caveats

- Decision open (see `spec/open-questions.md` item NETDS-1) — the four flipped collision pairs are the engine's law, not a game choice. The game cannot represent the old matrix.

- The enemy stat table carries a `score` value per kind (1 to 25). Nothing reads it. There is no score system in the runtime.

## Player control (`sim.py`, `_player_control`)

### Goal

The player aims with the mouse in screen space and moves in screen space. Pressing right always accelerates toward the right of the screen, whatever rotation the camera picked up from portals. Weapon selection switches instantly among owned weapons. The right button is the modal alt-fire: tau charge when the tau is in hand, the lightning implant otherwise.

### Invariants

- Aim and movement both transform through the inverse camera, so control never depends on the room's orientation.

- A weapon slot selects only an owned weapon. Selection never blocks fire.

- Move input magnitude clamps to 1: a diagonal is not faster.

### Verification

- Bot runs and the cloister, hole, and tau tests all steer through this path (`nav_to_point` feeds `mx` and `my`). Aim math runs in every firing test that converts a world target through the camera, for example `test_portable_hole_links_two_walls`.

### Implementation

Selection: slot 1..8 into `WEAPON_ORDER = [knife, pistol, smg, shotgun, rail, lightning, tau, hole]`, accepted only when owned. Aim: the aim point maps through the inverse camera into room coordinates. The normalized player-to-point direction becomes the body direction and the stored aim. A degenerate aim (cursor on the player) keeps the previous direction. Movement: the screen vector maps through the inverse camera's linear part, normalizes, scales by the clamped input magnitude, and adds `820 * dt` to the velocity.

Fire: with the cooldown at 0, the left button fires the current weapon (next units). Alt with the tau in hand and cells available: holding charges the tau. The hum starts on the first tick, and holding past 160 ticks costs 12 hp and resets the charge. Releasing with charge fires the charged shot. With any other weapon in hand, alt fires the lightning implant when it is owned and fully charged.

### Caveats

- Player speed is set by acceleration against friction. The discrete 60 Hz terminal speed is about 133 u/s (a code comment records this). Enemy base speeds are tuned slightly below it, so spacing is a real skill.

## Guns: knife, pistol, SMG, shotgun (`sim.py`, `_fire`)

### Goal

The bread-and-butter arsenal. The knife is silent, free, and short: a melee arc for conserving ammo. The pistol is the accurate starter. The SMG trades accuracy for rate. The shotgun is the close-range spike: eight pellets and a long pump. Gunfire is loud — it wakes enemies across the portal graph — but the knife wakes no one beyond the room.

### Invariants

- A shot without ammo is a dry click with a short lockout (18 ticks) and no ammo change.

- Projectile weapons spawn their rounds at the muzzle (player radius + 5 along the aim). Rounds inherit 40% of the player's velocity, with per-pellet angle inside the spread and speed within ±5%.

- Every projectile shot appends a muzzle `flash` fx and a `shake`, plays its sound, and alerts enemies within the level's `alert_hops`.

- Knife hits only enemies in the player's room, inside its arc and reach.

### Verification

- The aggro-bot campaign run (2026-08-22) fires the guns throughout. Pellet and cooldown numbers below are transcribed from `WEAPONS` and are otherwise unverified individually.

### Implementation

Weapon table rows (damage, cooldown ticks, speed, spread, pellets, ammo, kick):

- `knife` — 9 damage, 22 ticks, reach 27 + target radius, arc ±55°, knockback 260. On any hit: a hit sound and a small shake. Counts one shot in metrics.

- `pistol` — 12, 20 ticks, speed 1500, spread ±1.6°, one `9mm`, kick 2.2.

- `smg` — 7, 6 ticks, speed 1350, spread ±5.5°, one `9mm`, kick 1.6.

- `shotgun` — 6 per pellet, 54 ticks, speed 1150, spread ±11°, 8 pellets for one `shell`, kick 7.

Bullets are group-2 bodies (radius 1.6, mass 0.002, substep cap 3.2). They record in `bullets` with kind `bullet`, their damage, and a 90-tick lifetime. The wall event turns them into a chip decal, a quiet wall sound, and a spark. Selecting `lightning` and pressing fire routes to the implant path with an 18-tick cooldown. Selecting `hole` routes to the hole path.

### Caveats

- The knife plays its swing but never calls `alert_enemies`. A knife kill wakes only the victims' neighbors through the kill alert (one hop). This is the stealth property of the weapon.

## Rail, lightning, and tau (`sim.py`)

### Goal

The three exotic weapons: the rail is a piercing hitscan lance — instant damage through up to three bodies, through portals, with a cosmetic tracer. The lightning implant is not a gun but an organ. It launches a slow dart that detonates into chain lightning, free to fire, recharging over nine seconds. The tau cannon is the technical weapon. Its cheap fast rounds ricochet twice, and a charged mode converts held time plus up to five cells into one massive bouncing slug. Holding too long bites the wielder.

### Invariants

- The rail's damage arrives on the trigger tick through a raycast chain, not through a projectile. The tracer deals no damage.

- The implant fires only at full charge (540 ticks), and the charge resets to zero on fire. The HUD reads readiness from the same counter.

- A tau round reflects off walls (engine restitution 1) and survives exactly its bounce budget: primary 2, charged 3.

- Tau overcharge (past 160 held ticks) costs 12 hp through the normal player-damage path and clears the charge.

### Verification

- `test_tau_primary_ricochets_and_charged_shot_fires`, `test_tau_overcharge_bites`.

- Rail and lightning have no dedicated tests. Their behavior is transcribed from code and exercised by the campaign bot run, which acquires all eight weapons.

### Implementation

Rail (`_fire_rail`): 42 damage, 84-tick cooldown, one `cell`, kick 5. Up to three raycasts (8 hops, 2000 length, enemy-group mask) walk from the muzzle. Each entity hit takes the damage with 420 knockback, and the next cast starts past that body. A wall hit leaves a scorch decal and stops the chain. A tracer body (speed 5200, lifetime 14, damage 0) flies the same line. Two ticks of hitstop.

Lightning (`_fire_lightning`): a dart body of radius 3 at speed 720 plus half the player's velocity, damage value 26, lifetime 240. `_detonate_dart` fires on wall contact, body contact, or lifetime end. The detonation:

- A `lightning` fx with radius 110, a shake of 9, five ticks of hitstop, and a scorch of 22.

- Every enemy in the detonation room within 110 units takes a radial velocity push of `1500 * falloff`.

- The same enemies take damage `26 * (0.4 + 0.6 * falloff)`.

Firing the implant alerts enemies at `alert_hops + 1`. A dart that contacts the player detonates and deals 60% of the damage value.

Tau primary: 9 damage, 7-tick cooldown, one `cell`, speed 1900, spread ±2°, bounce budget 2. Each wall contact while budget remains spends one bounce with a ricochet sound and a spark (the engine already reflected the body). With the budget spent, the next wall removes the round.

Tau charged (`_fire_tau_charged`): on release, cost `min(cells, 5)`. Power is `min(1, held/80) * (0.4 + 0.6 * cost/5)`. Damage is `18 + 46 * power`, speed 2600, radius 2.2, lifetime 160, bounce budget 3. It shakes `4 + 5 * power` with two ticks of hitstop.

### Caveats

- The dart's radial push adds velocity directly, without dividing by mass. A brute and a mite receive the same velocity change from a detonation.

- Releasing alt after the cells ran out during the hold fires `_fire_tau_charged` with zero cells. That is a dry click, and it discards the charge.

## The portable hole (`sim.py`, `_hole_shot`)

### Goal

The signature tool: the player carves the level. Mark one wall, then mark a second wall anywhere in the world. A corridor 15 units wide staples them together — wide enough for the player (diameter 13) and the small enemies, too narrow for a brute (diameter 27). With the cloister built, the hole changes meaning: each shot cuts one doorway that links the safe room's corridor to that wall.

### Invariants

- A hole shot costs one charge only when it completes a passage (or a cloister link). Marks and misses cost nothing.

- The cut spans exactly 15 units of the wall. Both cut points keep at least `half + 2` units of clearance from the edge ends. A shot too near a corner is refused with a dry click.

- Both marks on the same edge are refused. The first mark stays.

- Every Python-side `(room, edge)` reference — doors, door keys, cloister links — survives the edge renumbering that a split causes.

### Verification

- `test_portable_hole_links_two_walls` (marks two walls, crosses through the new corridor both ways), `test_hole_corridor_excludes_brutes_admits_mites` (the fit rule against the width).

### Implementation

The shot raycasts 160 units along the aim with an empty entity mask, so only walls answer. A wall hit projects the impact along the edge, checks the clearance, and derives the split parameters.

Without a cloister, the first accepted hit stores the mark (scorch, quiet impact, `holemark` fx). The second accepted hit on a different edge completes the passage:

1. Split the first marked wall, then the second. When both marks share a room and the second edge index is beyond the first, the index shifts by 2 for the insertion. The reverse correction applies to the first doorway.

2. Add a `36 x 15` corridor polygon and connect both doorways to its two ends.

3. Append a detail seed for the new room, spend the charge, and clear the mark.

4. Announce with the unlock sound, a `holeopen` fx, and a shake.

With a cloister: a shot at a wall of the sanctum or its corridor is refused. Any other accepted hit splits the wall, appends the doorway to the cloister's link list, attaches the cloister there, and spends the charge.

`_shift_edge_maps(room, edge)` remaps `door_edges`, door records, and cloister links. Every edge index beyond the split edge in that room moves up by 2 (the engine inserted two edges).

`carve_door(room, near, width=70)` is the streaming-side cousin. It finds the solid edge nearest a point with span for the width plus margins. It splits a door-width sub-edge there, shifts the maps, and returns the new edge index, or `None` when no wall qualifies.

### Caveats

- The hole corridor gets a detail seed but no entry in `room_kinds`, `room_verts`, or `room_centroids`. The renderer therefore draws its floor and walls without props. The same holds for the cloister rooms.

- Building the cloister discards a pending first mark, because paired mode cannot complete once the hole re-purposes.

## The Cloister (`sim.py`)

### Goal

The safe room: picking up the `safe_room_core` builds an isolated octagonal sanctum with no address in the world. It is reachable only through the doorways the player cuts with the portable hole. Two invincible guardian turrets defend it, and a small pantry keeps it stocked. Each time the player steps into the sanctum, the corridor re-attaches to the next cut doorway in rotation. The cloister is therefore a hub: enter from one place, leave into another. It persists across levels.

### Invariants

- The sanctum is disconnected from the rest of the graph until the first link is cut (`hop_distance` from room 0 is -1).

- The guardians never move, never transfer, collide with nothing, and resist pickup and harm. They fire at the nearest enemy in their room.

- Attachment rotates on the player's transfer into the sanctum, cycling through the links in cut order.

- The carried flag `cloister=True` rebuilds the pocket (with empty links) in the next session.

### Verification

- `test_core_pickup_builds_pocket_with_guardians`, `test_link_enter_exit_and_rotation`, `test_guardians_kill_pursuers`, `test_cloister_carries_between_levels`.

### Implementation

`_build_cloister` assembles:

- A regular octagon of radius 85 (vertices in the engine's canonical winding), with a 15-unit door split from edge 4.

- A `36 x 15` corridor connected to that door, and the record `{sanctum, corridor, links: [], attached: None}`.

- Two turret bodies at `(-30, ±34)`: radius 6, mass 50, pickup group, non-physical, non-transferring, registered in `turrets`.

- A medkit and a `9mm` box at `(30, ±20)`, plus detail seeds for both rooms.

`_attach_cloister(idx)` disconnects the corridor's outer edge from the previous link and connects it to link `idx`. `_rotate_cloister` advances to the next link when more than one exists. It runs from the transfer event when the player enters the sanctum.

`_turret_tick`: each guardian with its 16-tick cooldown elapsed targets the nearest enemy in its room. It fires a `turret` round (damage 6, speed 1200, lifetime 40) with a quiet SMG report and a muzzle flash. Turret rounds hurt enemies with the normal knockback and pass through the player without damage.

The `safe_room_core` pickup grants the hole weapon and two charges along with the build.

### Caveats

- Defect: the guardians are invisible. The renderer resolves an entity's appearance by membership in `pickups`, `enemies`, `bullets`, or the player id. The guardians live only in `turrets`, so `_role_kind` returns nothing and the draw skips them. The `turret` pickup kind has a tripod drawing, but nothing spawns a firing guardian as a pickup. A probe on 2026-08-22 confirmed the membership gap. The player sees SMG fire from empty floor.

- A level-authored `turret` entity is the inverse: it renders as furniture and never fires. `_pickup_scan` skips it, and `_turret_tick` only reads `turrets`.

## Enemies and their AI (`sim.py`, `_enemy_ai`)

### Goal

Six enemy kinds with one shared doctrine (a code comment attributes it to Teleglitch). Base walk speeds sit slightly below the player's, so spacing is a skill, and the lunge is the burst that punishes carelessness. Enemies sleep until noise or sight wakes them, and the wake has a beat — a growl first, the charge after. The player always gets the first move. Sound is the dread channel: hunters groan, and their footfalls carry through walls before anything is visible.

### Invariants

- States move one way: `idle` to `waking` (a fixed per-kind delay) to `hunt`. Damage promotes straight to `hunt`.

- An enemy more than 5 hops from the player neither thinks nor moves (the active-set gate).

- Seeing the player (same room, idle) wakes with a growl and an `alerted` fx. The enemy faces the player during the delay.

- A hunting enemy in another room steers to the next portal edge on the hop-shortest route to the player. A `tether` enemy holds its room instead.

### Verification

- `test_waves_spawn_and_escalate` (hunt state en masse), `test_guardians_kill_pursuers` (mite pursuit through a portal), the campaign bot run for the full bestiary. Individual stat numbers are transcribed from `ENEMIES` and unverified per kind.

### Implementation

The stat table (hp, radius, accel, touch damage and cooldown):

- `husk` — 15 hp, r 8, accel 430, touch 12 every 38. Lunges: within 95 units, every 120 ticks, a 300 u/s burst with a growl.

- `mite` — 4 hp, r 4, accel 690, touch 4 every 24. Nearly player speed, wins by numbers. No footfalls.

- `spitter` — 18 hp, r 9, accel 340, touch 8 every 45. Holds a 110-190 range band. It spits every 95 ticks: a group-3 round, speed 380, damage 9, lifetime 180, ±0.06 rad jitter.

- `brute` — 65 hp, r 13.5, accel 260, touch 24 every 55. Lunges every 150 ticks at 240 u/s. Too wide for hole corridors.

- `shrieker` — 10 hp, r 7, accel 520, touch 0. Every 5 s it screams: an fx ring, and every other enemy within 2 hops goes to `hunt` with a 5 s speed buff (accel x1.25). In the player's room it flees instead of approaching. No footfalls.

- `warden` — 300 hp, r 16, accel 330, touch 30 every 48. It spits at speed 460 for 13 damage every 70 ticks while closing (band 0-100). Below half health it enrages once: a scream, a permanent buff, spit cooldown halved, and each spit adds a rotating six-way radial burst.

Wake delays (`WAKE_TICKS`): husk 32, mite 18, spitter 26, brute 45, shrieker 12, warden 20. `alert_enemies(room, hops)` wakes idle enemies within the hop budget, with the growl and fx only at distance 0. Gunfire calls it with the level's `alert_hops`, the lightning with one more, and every kill with 1.

Idle enemies wander: a new random direction every 90-240 ticks at quarter acceleration. Hunters groan on a 140-260 tick cycle at low volume. Footfalls: kinds other than mite and shrieker accumulate distance walked within a room, and a transfer resets the stride. They emit `step_heavy` (brute, warden — every 44 units) or `step_soft` (every 30 units), louder while hunting.

### Caveats

- Enemy body-to-body damage does not exist. Touch damage applies only against the player.

- The spit-band logic keys on the presence of `keep_min` and `spit_cd` in the stat row. The spitter and the warden therefore share the code path, and the warden's `keep_max` of 100 makes it advance except at point-blank range.

## Physics events: transfers, walls, contacts (`sim.py`, `_consume_events`, `_contact`, `sweep_bullets`)

### Goal

The engine reports what happened during the step, and the session gives the events their game meaning. A player transfer re-bases the camera and rotates the cloister. A bullet's wall hit resolves by kind — ricochet, splat, detonation, chip — or a secret wall gives way. A contact resolves by the pair's roles: bullet against enemy, bullet against player, enemy touching player.

### Invariants

- The camera re-base happens on the same tick as the player's transfer, so the world never jumps.

- Any player-owned round that strikes a `shoot` door edge opens that door permanently. Enemy spit never does.

- A round that returns to its shooter through a fold hurts the shooter at 75% damage.

- A bullet's lifetime ends it exactly once, and a dart that times out still detonates.

### Verification

- `test_transfer_preserves_speed_and_changes_room` (engine side), the seamless suite (camera re-base), `test_tau_primary_ricochets_and_charged_shot_fires` (wall resolution by kind). Returned-round damage is preserved-pair behavior recorded in `litc/separation-plan.md` — unverified by a dedicated test.

### Implementation

`transfer` of the player: rotate the cloister when the destination is the sanctum, then multiply the camera by the inverse portal matrix. Count the transfer and record the room as visited. Transfers of other bodies pass silently (the engine already moved them).

`wall`, when the striker is a player-owned round on a `shoot` door edge: the door record opens, the rooms connect, and both `door_edges` entries clear. The unlock sound, a scorch, a shake, and a `holeopen` fx announce it. Then by round kind:

- `tau` and `taucharged` with bounce budget left spend one bounce (ricochet sound, spark) and live on.

- `spit` leaves a splat decal. `dart` detonates. `bullet` leaves a chip with a spark and a quiet impact.

- Every non-bouncing case removes the round.

`contact` normalizes the pair by role. A round against an enemy: darts detonate, and `bullet`, `tau`, `taucharged`, and `turret` deal their damage with 90 knockback. Spit is absorbed without effect. The round is removed.

A round against the player: spit deals its damage, and a dart detonates plus 60% of its damage value. A turret round passes free. Anything else is the player's own returned round and deals 75%. An enemy touching the player deals its touch damage when its touch cooldown allows and the damage is nonzero.

`sweep_bullets`: each round's lifetime counts down every tick. At zero, a dart detonates in place, and the body and record are removed.

### Caveats

- Spit absorbed by an enemy body is a consequence of the flipped `EBULLET`-`ENEMY` collision pair: spitters can be body-blocked. Decision open (see `spec/open-questions.md` item NETDS-1).

- The `tracer` kind also opens `shoot` doors and also returns at 75% in principle. Both checks test only "a player-owned round that is not spit".

## Damage, death, and drops (`sim.py`)

### Goal

Hits register with feedback stacked deep: sound, blood decals, and a white flash on the victim. Hitstop and screen shake scale to the kill, a gib burst flies, and a corpse stays. Kills roll a per-kind drop table, so the economy flows from the fighting. The player's own damage has a half-second mercy window, and death is loud and final for the session.

### Invariants

- Damaging an enemy always promotes it to `hunt` and counts a hit in metrics.

- A kill removes the enemy body on the same tick, leaves a permanent corpse decal plus a blood spray, and rolls at most one drop.

- The player takes damage at most once per 30-tick window. Hard mode multiplies incoming damage by 1.25.

- Player death flips `dead`, counts in metrics, and leaves a corpse decal. The session then stops simulating.

### Verification

- `test_guardians_kill_pursuers` (kill path), `test_tau_overcharge_bites` (player damage path), the campaign run for the drop economy. Drop probabilities are transcribed and unverified individually.

### Implementation

`_damage_enemy(eid, dmg, dir, knock)`: subtract hp, promote to `hunt`, and add metrics. Knockback applies as a velocity change of `knock / mass` along the hit direction. It plays `hit_flesh`, drops a randomized blood decal, and flags the hit flash. At zero hp it calls `_kill_enemy`, which:

1. Pops the record, counts the kill, and plays the kind's death sound.

2. Stamps a `corpse_<kind>` decal oriented along the killing direction, plus radius-many blood decals in a spray.

3. Emits a `gib` fx, freezes 4 ticks (husk, mite) or 7 (larger), and shakes.

4. Removes the body, rolls the drop table in order, and spawns the first success near the corpse.

5. Alerts neighbors within 1 hop.

Drop tables: husk 35% `ammo_9mm` else 8% `medkit`. Mite 4% `ammo_9mm`. Spitter 30% `ammo_shell` else 8% `medkit`. Brute 55% `ammo_cell` else 25% `medkit`. Shrieker 50% `ammo_9mm`. Warden nothing.

`_damage_player(dmg, room)`: refuse inside the hurt window or when dead, then arm the 30-tick window. The damage multiplies by the difficulty factor and subtracts. It plays `player_hurt`, shakes `min(8, 2 + dmg/4)`, emits `playerhurt` (the renderer's red flash), and drops a blood decal. At zero hp: set `dead`, count the death, play `player_die`, emit `playerdie` (the death fade), and stamp the player corpse.

### Caveats

- Decals per room cap at 250, oldest dropped first, so long fights shed their oldest blood.

## Pickups, keys, and doors (`sim.py`, `_pickup_scan`, `_unlock_doors`)

### Goal

Walking over a pickup collects it: ammo by type, health, weapons, hole charges, the cloister core, the lightning implant, and colored key seals. A new weapon arms itself with a starter ammo bonus. Health respects foresight — a medkit refuses a player above 70 hp, so it stays on the floor for later. A key opens every door of its color across the world the moment the player takes it. A door is a promise, not a lock to walk to.

### Invariants

- Collection needs the player and pickup in the same room within touching distance (radii plus 2).

- A medkit never collects above 70 hp. It heals 35, capped at 100.

- A weapon pickup arms the new weapon immediately and re-collects as pure ammo when already owned.

- Key doors connect their rooms permanently on unlock. Nothing re-locks a door.

### Verification

- `test_keys_reachable_before_their_doors` (the campaign data honors the key-before-door ordering), `test_core_pickup_builds_pocket_with_guardians`, the campaign run (all weapons acquired, all doors passed).

### Implementation

Per collected kind:

- `ammo_9mm` +30, `ammo_shell` +7, `ammo_cell` +8, with the float text `+N <TYPE>`.

- `medkit` +35, float text `+35 INTEGRITY`.

- `weapon_<w>` adds and selects the weapon plus its bonus: `smg` +30 `9mm`, `shotgun` +8 `shell`, `rail` +6 `cell`, `tau` +10 `cell`.

- `portable_hole` +1 charge and grants the hole weapon (`PORTABLE HOLE`).

- `safe_room_core` builds the cloister, grants the hole weapon, +2 charges (`THE CLOISTER`).

- `implant_lightning` grants the implant (`LIGHTNING IMPLANT`).

- `key_<k>` adds the key, floats `<K> SEAL`, and unlocks every closed door with that key. Each door plays the unlock sound at its own edge midpoint.

- `turret` is skipped: the guardians are furniture.

Every collection counts in metrics and removes the pickup. Ammo pickups play `pickup_ammo`, medkits `pickup_medkit`, keys and the special items `pickup_key`.

### Caveats

- Key ids are open strings. The campaign uses `red`, `blue`, `gold`, `void`, plus the special door key `shoot`. A door whose key string is empty can never open, because no pickup produces an empty key, and the level loader accepts it. The format comment calls the empty string reserved and unimplemented.

## Exit and completion (`sim.py`, `_exit_scan`)

### Goal

Each level has one exit pad, and standing on it completes the level. A level can demand more: an exit key the player must hold, or a gate kind — a named enemy type that must be extinct first. The two warden levels gate this way. In the streamed campaign only the final chunk's exit is armed, and its gate counts only that chunk's guardians.

### Invariants

- Completion requires the player within 18 units of the pad in the exit room. The exit key (when set) must be held, and zero gate-kind enemies may live (within the gate's room range when one is set).

- `complete` flips once, and the session then stops simulating.

### Verification

- `test_stream_lazy_load_arrival_and_completion` (armed exit on the final chunk), `test_aggro_bot_completes_smoke_level`, `test_pacifist_bot_does_not_complete_level_with_mandatory_combat` (the gate holds), the campaign run.

### Implementation

`_exit_scan` runs every tick. The `exit_enabled` attribute gates everything (absent means true, and only the streamer sets it). The room, distance, key, and gate checks run in that order. The gate check filters `enemies` by kind, and by room range when `exit_gate_rooms` is set. `snapshot` exposes the same data to bots: the remaining gate count, the missing key, and the next edge toward the exit.

### Caveats

- The exit pad renders in every mode, armed or not. The streamer keeps the disabled marker pointing at the way forward, so route queries and bots always have a heading.

## The Vigil (`sim.py`, `_vigil_tick`, and `app.start_vigil`)

### Goal

The endless holdout mode: things still come through, and they are met. A wave director spends a growing budget on enemy prints, spawning them away from the player. Every fifth wave the budget buys a single fresh warden at the door. The seed keeps the pantry stocked between pushes. The mode tracks the reached wave, and the best persists on the save and shows on the title screen. There is no exit — it ends when the player falls.

### Invariants

- The first wave arrives 6 s in. After each wave the next timer is 8 s, and the next wave waits for the field to clear — but stragglers stall it at most 60 s.

- Wave budget is `3 + 2 * wave`, spent on mites (1), husks (2), spitters (4), brutes (7), at most 22 prints per wave. No shriekers: a thing that flees forever stalls a holdout.

- Spawns land in rooms other than the player's (and never in the cloister), 55 units from the room center, already hunting.

- Every even wave restocks the pantry in room 0: a medkit on multiples of 4, shells on multiples of 3, else `9mm`.

### Verification

- `test_waves_spawn_and_escalate`, `test_no_exit_and_no_waves_in_campaign_levels`. The best-wave persistence runs only manually — unverified.

### Implementation

`start_vigil` (app side) loads `levels/vigil.json` (debug fallback on failure) and sets the level index to -1. The loadout is fixed: 100 hp, 90/12/12 ammo, every weapon except the hole, SMG in hand. The scene starts with seed `rng_seed or 1` plus the intro card. `vigil.json` has 7 rooms (chapel and generic kinds), no exit, and a small pantry.

`_vigil_tick` implements the director as specified above. It plays the `stinger_wrongness` sting on each wave start at the player and records the wave in metrics. Warden waves (5, 10, ...) spend the whole budget on the one warden. The wave counter feeds the HUD and the death scene.

### Caveats

- Defect: the restart path after a Vigil death loads the debug level (see the campaign-flow unit). The Vigil is re-enterable only from the title screen.

- The stall counter initializes through `hasattr` on first use.

## Session outputs: fx, decals, metrics (`sim.py`)

### Goal

The session communicates outward only through data. The renderer, the audio system, the app, bots, and tests all read the same channels without touching game logic.

### Invariants

- `fx` holds exactly the current tick's events. Sounds carry their room and position, so the audio can attenuate by graph distance.

- `decals` persist per room, capped at 250 each.

### Verification

- Every renderer, audio, and bot test consumes these channels. The fx vocabulary below is transcribed from the emit sites.

### Implementation

The fx vocabulary: `("sound", name, room, x, y, vol)`, `("shake", mag)`, `("flash", room, x, y, radius)`, `("hitflash", eid)`, `("gib", room, x, y, n, dir)`, `("spark", room, x, y, nx, ny)`, `("lightning", room, x, y, radius)`, `("scream", room, x, y)`, `("alerted", room, x, y)`, `("holemark", room, x, y)`, `("holeopen", room, x, y)`, `("playerhurt", dmg)`, `("playerdie",)`, and `("pickup_text", room, (x, y), label)`. The streamer appends two more: `("locname", name)` and `("ambience", name)`.

Decal kinds: `blood`, `splat`, `chip`, `scorch`, `corpse_<kind>` with position, size, and angle.

### Caveats

- None.

## Level format v2 and loading (`levels.py`, `levels/*.json`)

### Goal

Levels are JSON. Rooms carry absolute vertex lists from an editor canvas. The loader re-centers each room on its area centroid — matching the engine's own re-centering — so every position in the file converts to room-local coordinates. Doors load as pending connections. A wrong winding fails loudly at load, because the engine would otherwise silently rewind the vertices and renumber every authored edge index.

### Invariants

- A `version` other than 2 is rejected. A missing `version` passes.

- Room vertices must wind negative-shoelace (visual counterclockwise with y down). A positive shoelace raises with the room index in the message.

- Entity, player, and exit positions in the file are canvas-absolute and load as room-local.

- An unknown entity type raises at spawn (`_spawn_from_spec`), not at load.

### Verification

- `test_level_structure` (loads and boots every campaign level), `test_campaign_exists_and_generator_runs`, `test_wrong_winding_blocks_save` (editor side of the same rule).

### Implementation

Top-level keys:

- `version`, `name` (default `?`), `tier` (default 1), `ambience` (default `amb_drone_early`).

- `rooms`, `connects` (`[a, ea, b, eb]` lists), `connects_x` (`[a, ea, b, eb, m9]` with a row-major 9-tuple transform).

- `doors` (`{a, ea, b, eb, key}`), `player` (`{room, pos}`, required).

- `exit` (`{room, pos, key?, gate_kind?}`, optional — absent means no exit, stored as room -1).

- `alert_hops` (default 2) and `vigil` (default false).

Each room: `verts`, optional `detail_seed` (default `index * 7919 + 13`), optional `kind` (default `generic`), optional `entities`. An entity is `{type, pos, props?}` where the type is an enemy kind, a pickup kind, or `player` (ignored). Recognized props: `hp` (an override, scaled by difficulty) and `tether` (the enemy holds its room).

The `Level` dataclass carries the loaded form: local room vertices, authoring centroids, seeds, kinds, connections, doors, and entities as `(room, spec)` pairs. It also carries the player and exit placements, `exit_key`, `exit_gate_kind`, `alert_hops`, `vigil`, and `ambience`. `save_level` stamps `version` 2 and writes with `indent=1`.

The shipped campaign (`levels/campaign.json` lists `l01` through `l10`): tiers run 1 to 4 with matching ambience tracks (`amb_drone_early`, `_mid`, `_late`, `_finale`). Door keys used: `red` (l02), `blue` (l03, l04), `shoot` (l05, l07, l10), `void` (l10). Exit keys: `gold` (l05, l07), `red` (l06), `void` (l09). Warden gates: l08 (`THE FOLD`) and l10 (`PERIHELION CORE`). No shipped level uses `connects_x` — mirrors are authored as a same-room connection between one edge and itself.

Room kinds across the campaign: `dock`, `corridor`, `transit`, `storage`, `pump`, `lab`, `quarters`, `chapel`, `records`, `medbay`, `core`, `generic`.

### Caveats

- The final level's title is `PERIHELION CORE`. Decision open (see `spec/open-questions.md` item NETDS-4).

- A door with an empty key string loads but can never open (see the pickups unit).

## LevelBuilder and the resolve pipeline (`levels.py`)

### Goal

The programmatic authoring path, used by the debug level, the tests, and the external campaign generator. The author places rooms anywhere on the canvas — only connections define adjacency. The author can also give connections and doors as points instead of edge indices, which survives the doorway-splitting pass that renumbers edges.

### Invariants

- `resolve` runs three passes in order: the doorway splitter, then point-authored door and connect resolution (doors first, so autoconnect cannot steal their edges), then autoconnect over exactly-coincident free edge pairs.

- `ngon` emits vertices in the engine-canonical winding, so authored edge indices survive `add_polygon` unchanged. `poly` rewinds when needed, and edge indices then follow the rewound order.

- `no_connect` forbids autoconnect between two rooms: their shared wall stays a wall.

- A point-authored connection that resolves onto an already-used edge raises.

### Verification

- `test_doorway_splitter_makes_doorways`, `test_no_connect_keeps_walls_solid`, `test_seamless_mirror_approach` (a self-edge `connect_pts` mirror), the smoke levels throughout the suite.

### Implementation

Authoring methods: `room`, `rect`, `ngon`, `poly`, `set_kind`, `connect`, `connect_x`, `door`, `connect_pts`, `door_pts`, `no_connect`, `entity`, `player`, `exit`. `build` requires a player spawn and returns a loaded `Level`. `to_dict` returns the resolved dict (what `save_level` writes).

The splitter finds a shorter opposite-facing edge collinear inside a longer wall (within tolerance 0.5). It inserts the matching vertices into the wall, so an exactly-matching sub-edge exists, and repeats to a fixed point (guard: 200 iterations). Point-authored doors and connects then resolve to the nearest edge midpoint. Autoconnect pairs remaining free edges whose endpoints coincide reversed within tolerance.

### Caveats

- `autoconnect()` is a deprecated no-op shim kept for old call sites. `resolve()` does the work.

## Seamless world streaming (`stream.py`, `WorldStreamer`, and `sim.append_chunk`)

### Goal

The campaign is one seamless world, and levels are chunks that lazy-load as the player approaches. Chunk k's exit pad becomes a carved doorway into a transit spine — two long corridor rooms. Entering the spine loads chunk k+1, carves its entry doorway near the authored player spawn, and joins the worlds. The far side of every spine is a fresh security zone: held keys clear on arrival. The final chunk keeps its real exit pad, which ends the campaign.

### Invariants

- Only the final chunk's exit is armed. The disabled exit marker always points at the way forward, so route queries and bots always have a heading. That target is the spine while the next chunk is unloaded, and its entry room once it exists.

- Arrival in a new chunk clears the held keys and snapshots the entry state as the chunk's checkpoint. It also fires the location title, the ambience switch, and the save callback.

- Chunk indices offset uniformly. `append_chunk` re-indexes every room, connection, door, and entity by the polygon-count offset and extends the level's per-room arrays.

- A chunk whose target room has no carvable wall gets its doorway in the nearest room (breadth-first within the chunk) that has one. No carvable wall anywhere raises.

### Verification

- `test_stream_lazy_load_arrival_and_completion` (lazy load on spine entry, key clearing, armed final exit, completion), `test_radial_hub_world_is_well_formed`, the campaign bot run.

### Implementation

Construction wraps the session's already-loaded first chunk as chunk 0 and snapshots its entry state. A single-chunk run arms the exit, and any other run builds the first spine. The spine: a doorway of width 70 carved near the exit pad, with two `260 x 70` rooms chained onto it, far end sealed. Spine rooms append `transit` kinds, detail seeds, and centered vertices to the level arrays.

`tick` watches the player's room and reacts only to room changes. Entering the current chunk's spine triggers `_load_next`:

1. Load the next level file and `append_chunk` it into the live sim.

2. Carve its entry doorway near the authored spawn. The entry position falls back to the room center when the carve landed elsewhere.

3. Connect the spine's far end, and pre-build the next spine unless the new chunk is final.

Crossing into the next chunk's own rooms is arrival. The streamer advances `current`, snapshots the entry state, clears keys, arms or re-points the exit, and fires the fx and callback.

### Caveats

- `room_chunk` attributes spine rooms to their owning chunk. Rooms of no chunk (cloister, hole corridors) attribute to the current chunk.

- Spine and chunk geometry appended at runtime shares all level arrays, so the renderer props and seeds extend seamlessly. But see the renderer props defect for the portal-edge map.

## Checkpoint respawn (`stream.py`, `respawn`, `_snapshot_state`)

### Goal

Death in the streamed campaign reprints the frame at the current chunk's entry with the state it was first entered with. The chunk's dead rise again, and its supplies are restocked. The checkpoint state applies floors, so a doomed loadout cannot replay forever. A hurt or dry arrival lifts to a battle-ready minimum, while normal entries carry far more and stay untouched.

### Invariants

- The checkpoint floors: hp at least 70 (85 on hard), `9mm` at least 45 (90 on hard), and on hard `shell` at least 8. Weapons, the held weapon, hole charges, and the cloister flag copy as-is.

- Respawn removes every bullet in the world and every enemy and pickup within the chunk's rooms. It respawns the chunk's authored entities and restores the checkpoint state. It clears keys, the tau charge, and any hole mark, and places the player at the chunk entry with zero velocity.

- Opened doors stay open across respawns.

### Verification

- `test_stream_respawn_at_chunk_entry`. A code comment records the floor rationale with soak evidence: seed 2175, and 75 of 983 hard-mode soak campaigns grinding out on normal floors.

### Implementation

`respawn` performs the removal and respawn as specified, then resets `dead` and the hitstop. It counts a death in metrics, rebuilds the camera from the entry position, and fires the location title again. Placement calls `set_pos` within the player's current room. When the player died in a different room, `_reseat_player` removes the body and spawns a fresh one in the entry room with the player's constants. It updates `pid` and preserves the facing.

### Caveats

- The comment above the reseat call rejects a remove-and-spawn and claims "the sim's own transfer". `_reseat_player` is exactly a remove-and-spawn, with `pid` reassigned to the new id. The comment is stale. The mechanism works because nothing else holds the old id across the call.

- Defect: the respawn's death increment double-counts with `_damage_player` (recorded at the tick bridge).

- Enemies that chased the player out of the chunk (into a spine or the cloister) survive the reprint.

## Renderer: frame composition (`render.py`, `Renderer.draw`)

### Goal

An immediate-mode renderer paints each frame from the engine's visibility query. Each visible room image — a polygon seen through a portal chain, with its screen transform and clip — draws in a fixed layer order. A player-centered darkness field then multiplies over the whole world in screen space, so light falls off smoothly and identically across portals. Light sources punch back through the dark: muzzle glows, lightning, and the lit lab screens. Seamlessness is sacred: a portal edge is never drawn.

### Invariants

- Per instance, in order: floor, room detail, decals, exit pad, walls, doors, entities, effects. After all instances: the darkness multiply, the deferred glows and bolts, the post overlays, and the debug labels last.

- Wall segments flagged as portals are skipped. Solid walls draw at a color that never dims below `WALL_MIN` — walls are the readability skeleton.

- `draw` allocates no `pygame.Surface`. All effect and overlay surfaces bake once in the constructor.

- The renderer requests up to depth 14 and 96 instances from `visible_set`, with the camera apex at the player, so sightlines are the player's own.

### Verification

- `test_render_headless_smoke`, `test_visible_set_returns_sane_instances`, `test_no_brightness_seam_across_transfers` (the darkness field's smoothness across portals).

### Implementation

The darkness field bakes on first use: a smoothstepped radial falloff from the screen center, multiplied over the frame with `BLEND_RGB_MULT`. The falloff is warm-biased — red survives longest, and a comment ties that to the ever-present sun. Glows that must survive the dark defer during instance drawing and blit after it in additive mode:

- Warm muzzle and lightning glows from a six-size baked cache.

- Green phosphor screen glows from a separate three-size cache, so a lit instrument reads as its own light source, not a gunshot afterimage.

- Lightning bolt polylines with their glow.

Post overlays: below 35 hp a red vignette pulses while the session is alive. A hit flashes the red vignette plus a faint full-screen cast for 2 ticks. Pain reads at the edges, and the center of the world stays readable. Death fades to black over 40 ticks. The debug overlay labels each instance with its room index and depth in magenta.

Helper facts: clip polygons can arrive with either winding, because a chirality-flipping portal mirrors them, so point-in-polygon uses ray casting. Screen scale per instance derives from the transform's effect on a unit vector.

### Caveats

- `_dim` and `_floor_dim` return constants 1.0, and `_room_tint` returns black. Depth dimming and per-room tints are retired — comments record that dimming snapped at portal crossings and tints made a visible floor seam. The darkness field replaced them, and the functions remain as vestigial call sites.

## Room props and the detail cache (`render.py`, `_get_detail` and the generators)

### Goal

Rooms tell their function through furniture, drawn procedurally from each room's stable detail seed. Per kind:

- `dock` — cargo crates in corner stacks, a hazard-striped strip, mooring rings.

- `corridor` and `transit` — wall pipe runs with elbows, vent grates, floor lane chevrons.

- `storage` — dense crate rows with a walkable aisle and wall shelf lines.

- `lab` — console slabs with lit phosphor screens and a specimen table.

- `quarters` — cot bays with pillows and footlockers. `chapel` — pew rows facing a dais arc.

- `records` — long shelf stacks. `medbay` — curtained cots and a cross-marked cabinet.

- `pump` — tank rings with an inflow pipe and floor puddles. `core` — concentric inlays, radial spokes, an amber warning ring.

- `generic` — subtle plates, rivets, and grime.

The prop palette is deliberately desaturated and dark, so furniture never competes with a live threat for the eye. Hazard stripes and lit screens are the intended exceptions. Props hang only on true walls, never across a passage that is open or will open.

### Invariants

- Detail generates once per room from `room_seeds[room]` and caches. The same room always draws the same furniture.

- Prop generators receive the room's non-portal edges only. Open connections, mirror connections, and pending doors are excluded, so furniture never blocks a passage.

- A room beyond the level's vertex arrays (a hole corridor, the cloister) has no detail.

### Verification

- `test_render_headless_smoke` draws the prop path. The per-kind generator outputs are unverified individually (pure geometry, checked by eye in soak footage).

### Implementation

`_get_detail` seeds a private `random.Random` per room and computes the bounding box and the wall list. Walls are non-portal edges longer than 16, sorted longest first, each with tangent and inward normal. The kind's generator emits primitive tuples — `line`, `dot`, `stain`, `poly` (fill and outline), `polyline`, and `screenglow` — in room-local coordinates. `_draw_detail` transforms them per instance, clips lines and polygons against the instance clip, and registers screen glows for the post-darkness pass.

`_portal_edges_for` builds the room-to-portal-edge map once from the level's `connects`, `connects_x`, and `doors`. It caches the map for the renderer's lifetime.

### Caveats

- Defect: the portal-edge map covers only the first chunk. Streamed chunks connect through the live sim and through session-side door records, and neither feeds `level.connects` or `level.doors`. Every room of a streamed chunk therefore resolves to an empty portal set, and its props can straddle open doorways and pending doors. A probe on 2026-08-22 streamed a second chunk: its entry room reported portals at two edges in the sim and none in the renderer's map. The first chunk is unaffected.

- The cache never regenerates, so a door carved into an already-visited room can sit behind previously generated props. Furniture is cosmetic: nothing collides with it.

## Entities, decals, doors, and the exit pad on screen (`render.py`)

### Goal

Everything alive reads at a glance. The player is a pale kite pointing where it aims. Each enemy kind has its own lumpy silhouette, color, and a value-contrast rim. A two-tone body — a shadow core trailing the facing and a lit brow toward it — gives the flat cutout volume. Hits flash the victim white. Bullets are streaks, spit is a green bead, the dart is a cyan spider, and pickups draw as compact icons.

Locked doors draw in their key color with a lozenge at the midpoint. A secret `shoot` wall keeps its secret: ordinary wall color with one hairline fissure off-center. The exit pad pulses green with an arrow.

### Invariants

- An entity partially outside its clip region clips against it, so no body pops at a portal line. Decals, bullets, and pickups instead test their center point and skip when outside.

- Blood and corpse decals stay below every live-enemy color (residue never outranks threats). Blood draws undersized against its simulated size, so heavy fights stay readable.

- The hit flash overrides fill and rim to pure white for its 3 ticks.

### Verification

- `test_render_headless_smoke` covers the code path. Shape and color choices are transcribed from the tables at the top of `render.py` — verified by soak footage, not by pixel tests.

### Implementation

`_role_kind` resolves an entity id against the session (player, enemy, bullet, pickup), and unresolved ids are skipped. Enemies: `mite` is a plain circle, and the other kinds use per-kind polygon shapes. Kind dressing: spitters get a green mouth dot, and brutes get two tusk lines and a heavier rim. Wardens get a violet inner ring and a pale rim, and husks a dark core dot. Corpse decals reuse the enemy silhouette squashed flat at 45% brightness with two limb strokes.

Doors draw from `door_edges` through live edge endpoints, clipped to the instance. The exit pad draws in its room at a 90-tick pulse.

### Caveats

- Unknown key colors fall back to the orange door color. `KEY_COLORS` names `red`, `blue`, `gold`, `void`.

- The `turret` pickup icon (a squat tripod with a bright rim) draws only for the level-authored decorative kind. The firing guardians never reach the draw path (defect recorded at the Cloister unit).

## Effect pools and their decay (`render.py`, `consume_fx`)

### Goal

Transient presentation state lives in renderer-side pools. The pools hold gibs, sparks, muzzle flashes, lightning bolts, scream rings, per-enemy hit flashes, the hurt flash, and the death fade. The pools decay once per sim tick, not per display frame, so every duration is exact ticks and presentation stays frame-rate independent like everything else.

### Invariants

- `consume_fx` runs exactly once per sim tick, from the tick bridge, and drives all pool aging.

- Pools are bounded: 400 gibs, 200 sparks, 30 flashes, 30 bolts, 20 screams. Overflow drops the oldest.

- Gibs integrate their own motion (friction factor 0.90 per tick) in room-local space and draw only in their room's instances.

### Verification

- `test_render_headless_smoke` exercises ingestion and drawing. Pool numbers are transcribed.

### Implementation

Ingestion maps fx tags to pool entries:

- `gib` spawns radius-many particles in a cone around the kill direction, random speed, 18-34 tick lives.

- `spark` — a 4-tick normal-aligned streak. `flash`, `holemark`, `holeopen` — glow entries of 3, 6, and 8 ticks.

- `lightning` — a bolt entry with 4-8 random segments, redrawn every other tick for 6 ticks.

- `alerted` and `scream` — expanding double rings of 10 and 16 ticks.

- `hitflash` — 3 ticks on the entity id. `playerhurt` — 2 ticks of hurt overlay. `playerdie` starts the 40-tick death fade.

Bolts and flashes defer their glows to the post-darkness pass.

### Caveats

- Gib and bolt shapes use the module-level `random`, not the session RNG. Presentation is non-deterministic by design while the simulation stays deterministic.

## HUD (`hud.py`)

### Goal

A minimalist status overlay in the corners. Integrity sits bottom-left as a bar plus a digit on a backing plate — combat debris otherwise renders through the numbers. The weapon and its ammo sit bottom-right, key seals top-right as colored dots, and the wave counter top-left in the Vigil. A crosshair at the mouse expands with the fire cooldown, so readiness is visible at the point of aim.

### Invariants

- Below 35 hp the integrity color pulses red, with a floor bright enough to stay readable mid-pulse.

- The weapon line always shows a count: ammo for gun weapons, a charge readout for the implant, and an infinity sign for the knife. For the hole it shows the charge count, with a `*` when one wall is marked.

- The crosshair expansion is `cooldown / weapon cooldown * 4`. For the implant it is the inverse of the charge fraction.

### Verification

- Drawn in every soak and recording. No dedicated tests — unverified in the suite.

### Implementation

The hp bar is 70x5 at the top of a dark plate sized to the bar plus the digit. The weapon line renders `NAME COUNT` in 11 px at the bottom right, and the tau appends ` [N%]` while a charge is held. The implant draws a circular gauge with a `LIGHTNING` label. An outlined circle fills as a pie from the top, dim cyan while charging and bright at full. Keys draw right-to-left as 4 px dots in their key color. The crosshair is four gapped lines.

### Caveats

- `_draw_weapon` contains an unreachable branch: inside the non-implant path, an `elif name == "lightning"` can never be true, because the implant took the other branch. Dead code, no behavioral effect.

- The HUD reads `WEAPONS`, `LIGHTNING_RECHARGE_TICKS`, and `PLAYER_HP` from `sim.py` and `KEY_COLORS` from `render.py`. The readouts therefore cannot drift from the simulation constants.

## Audio (`audio.py`)

### Goal

A lazy-loaded WAV bank with portal-graph positional attenuation. A sound one hop away arrives at 55% volume, two hops at 30%. Sound carries through walls before anything is visible, which is the horror pacing of the level design. An ambience track loops per level tier, and a heartbeat loop starts below 30 hp. A parallel tool generates the bank, and the bank can be partial. A missing file logs once to stderr, and the game runs silently for whatever has not landed yet.

### Invariants

- A sound in a room unreachable from the player (`hop_distance < 0`) is silent.

- Attenuation is `vol * 0.55 ** hops` before the sfx and master volume factors.

- Mixer failure at startup degrades to fully silent operation without a crash. Mute stops all channels.

- The recorder tap fires for every sound decision — even muted or with a failed mixer — so headless captures still log the soundtrack.

### Verification

- `test_wav_file_exists`, `test_wav_loads_and_is_44100_mono_16bit`, `test_wav_non_silent`, `test_wav_no_clipping`, `test_wav_duration_within_2x_of_spec_range`, `test_manifest_covers_expected_sound_count` (the bank against its manifest). The attenuation constant is transcribed — unverified by a listening test.

### Implementation

`handle_sounds` consumes the tick's `sound` fx: hop distance from the player's room, attenuation, and stereo pan. Pan derives from the sound's on-screen x position when the caller passes the frame's visible instances, else center. Center is the documented correct choice for a source heard before it is seen.

`ambience(name)` switches the loop only on a name change, at volume 0.35 times master. `update_heartbeat` starts or stops the heartbeat loop on the threshold crossing (hp below 30 and alive). `set_master` clamps 0..1. Sounds load from `game/assets/sfx/<name>.wav` on first use and cache, including the failure.

### Caveats

- The app's only `handle_sounds` call passes no visible instances. In the shipped game every sound therefore pans center, and the pan path is dormant. Proposed as a new open question in the warm-start report.

- There is no music runtime in NETDS — ambience loops are the only continuous audio. Decision open (see `spec/open-questions.md` item NETDS-2).

- Ambience names arrive from level data. An unknown name logs a missing-file line once and plays nothing.
