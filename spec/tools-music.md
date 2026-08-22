---
This warm-start specfile covers all music-tool Python modules in `tools/musicgen/` and `tools/musiccal/`. These internal tools make and calibrate music assets. They do not ship with the game.
---

# Music tools

The music tools are in 2 directories. Tools in `tools/musiccal/` calibrate the game's music-control values. They make calibration levels, run headless bot batches, and fit models to run data. Tools in `tools/musicgen/` make music assets. They run synthesizers, render stems, make banks and tracks, and use models that can examine audio. Engine code in `game/perihelion/` uses these outputs: `music.py` plays the banks, and the engine `battery` calculates 3 music values.

`tools/musiccal/` uses 2 data formats. `run_farm.py` writes 60 Hz run files read by `fit_factors.py` and `saturation_stream.py`. `collect_corpus.py` writes 10 Hz rows read by `analyze_corpus.py`, `fit_battery.py`, and `tune_battery2.py`. The reference target `mowing` does not have one consistent definition across these tools. See the Caveats for `tune_battery2`.

References to the user identify dated creative instructions. Many tool docstrings keep the exact text of those instructions.

## `build_gauntlet` — calibration `gauntlet` 1 (`tools/musiccal/build_gauntlet.py`)

### Goal

This tool makes `levels/gauntlet_cal.json`, the first calibration `gauntlet`. It copies 6 combat segments from the middle of levels `l04` through `l07`. It connects them with 7 safe passages that have the same structure. Each passage contains 2 medkits, 3 ammunition pickups, and one `sentry`. The `--density` flag scales enemy count but does not change enemy statistics. The tool also writes `gauntlet_meta.json` for downstream analysis.

### Invariants

- The output level contains only the specified connections. The tool counts them and raises `RuntimeError` on a mismatch because `LevelBuilder.resolve()` connects each pair of aligned edges without a report.

- The target enemy count stays in the range 0 to 43. The tool does not add more enemies than the full enemy list contains.

- Each supply polygon in a passage contains one `sentry` at each density. Thus, density does not change the turret count.

- The level obeys the engine check in `LevelBuilder.build()`.

### Verification

The tool prints the enemy count for each segment and a report line. A reader compares these counts with the enemy table in the docstring. Segments `B`, `A`, `C`, `D`, `E`, and `F` hold `3`, `7`, `4`, `7`, `15`, and `7` enemies at `density` 1. The connection count check runs on each build.

### Implementation

The `SEGMENTS` table identifies 6 polygon groups from levels `l04` through `l07` in the sequence `B`, `A`, `C`, `D`, `E`, `F`. A person checked each entry and exit edge. `add_segment` copies each polygon with an offset of 20,000 units for each segment.

It keeps the selected enemies, copies the internal lights, and replays only the internal `connects`. It does not replay `connects_x` edges or keyed doors. The module-global `TEXTURE_MAP` records the source of each copy, and the copy uses the source floor texture.

The segment data has these values:

```python
[
    {"tag": "B", "src": "l06", "polygons": [18, 19, 20],
     "entry": (18, 0), "exit": (20, 1)},
    {"tag": "A", "src": "l04", "polygons": [4, 55, 56],
     "entry": (4, 5), "exit": (56, 1)},
    {"tag": "C", "src": "l07", "polygons": [2, 214],
     "entry": (2, 2), "exit": (214, 7)},
    {"tag": "D", "src": "l07", "polygons": [13, 16, 17, 18, 20, 21, 22],
     "entry": (22, 2), "exit": (20, 0)},
    {"tag": "E", "src": "l05", "polygons": [1, 2, 3, 4, 5, 6, 7],
     "entry": (1, 2), "exit": (4, 2)},
    {"tag": "F", "src": "l06", "polygons": [170, 171, 172],
     "entry": (170, 1), "exit": (172, 3)},
]
```

The `density` mechanism uses a sequence with equal distribution. `_collect_enemy_pool` puts all 43 enemies into one flat list. `_fair_order` sorts them by the key `(polygon_pos + 0.5) / polygon_size`. Each prefix therefore samples polygons and segments equally. The target count is `round(43 * density)`, in the range 0 to 43.

One `density` step adds approximately one enemy. The previous method rounded each polygon independently. A `density` change of 0.7 percent then moved the total from 5 to 15 enemies.

`add_corridor` makes 3 rectangles in the band `y = 60000 + idx * 2000`: a 320-by-90 stub, a 220-by-220 supply polygon, and a second stub. The supply polygon receives 2 medkits, 3 ammunition pickups (`9mm`, `shell`, and `cell`), a light, and a `sentry` at its center. A report found that enemies in `hunt` state follow a player with an injury to medkits. The `sentry` protects that destination. The enemy AI has no path that ends a `hunt`.

`main` builds the level with `LevelBuilder` (`tier=3`, `alert_hops=2`, seed `20260713`), does the connection count check, and writes the level. A display stage then reads the written `JSON` again and writes it again with the texture map. It adds a dim fill light to each polygon that has no light. The region file maps each polygon to `combat`, `loot`, or `corridor`, with the segment tag. It also adds an `is_heavy` flag for the types `brute`, `shrieker`, and `warden`.

### Caveats

- `TEXTURE_MAP` is module-global and is not cleared. A second build in the same process keeps entries from the first build. `build_gauntlet3` clears it before each use.

- The display stage changes the level JSON after `build()` checks it, and the check does not run again. This stage adds only lights and texture data. These changes have no effect on AI operation.

- `polygon_center` is a vertex average, not an area center. This is only for rectangles.

- An absolute `--out` path external to the repository raises `ValueError` during the `meta` write.

## `build_gauntlet2` — the dense `population` (`tools/musiccal/build_gauntlet2.py`)

### Goal

This tool puts a new enemy set on the geometry from `gauntlet_cal.json` and writes the result as `levels/gauntlet_cal2.json`. `Gauntlet` 1 contained only 10 enemies of 2 types, so its calibration did not include 5 types.

This tool puts all 7 types across the polygons. Position selection uses polygon area, minimum separation, wall margin, depth gates for heavy types, and more separation between enemies of the same type. The user requested movement, spread across space, and a stronger player instead of a smaller enemy set.

### Invariants

- The geometry, connections, doors, and exit of `gauntlet_cal.json` stay the same. The tool changes only entities.

- Type counts always sum to `--n` through the largest-remainder rounding method.

- When separation prevents position selection, the tool decreases the separation scale. It does not omit an enemy without a report. It reports each enemy for which it cannot select a position after 600 tries.

- No enemy starts in the player's polygon or at a distance of 260 units or less from the player position. Each enemy stays a minimum of 22 units from walls.

### Verification

The tool prints `placed X/N (fails F)` and the type `mix` with counts. A zero `fails` value shows that all enemies received positions.

### Implementation

The type `mix` is `husk .30, mite .20, spitter .15, shrieker .10, brute .10, warden .05, flicker .10`. Depth gates keep heavy types out of the start of the run: `warden .55, brute .40, shrieker .30` as a fraction of the polygon index sequence. The separation multipliers for the same type are `warden 3.0, brute 2.0, shrieker 1.5`, and the polygon caps are `warden 1, brute 1`.

For each enemy, the tool selects a polygon with a probability based on area after the depth gate and samples a point in it. It rejects a point when the polygon is at its cap. It also rejects a point that is not in the polygon or is in the player area. It rejects points less than 22 units from a wall or below `min_sep` in the polygon. A point below the separation for enemies of the same type across the level is also rejected. After each 150 rejected points, it multiplies the separation scale by 0.75.

After 600 tries, it counts a failure to select a position. It then sets `alert_hops = 1`. A large enemy set with `alert_hops = 2` connects the full level into a `hunt` with no end.

### Caveats

- Depth is the polygon-index fraction and not path distance, and corridors have the highest indices. Wardens and brutes can thus spawn in safe corridors and late-run loot polygons because placement rules let enemies use those polygons.

- A position failure (`failed > 0`) makes a smaller number of enemies than `--n`, but the process continues to exit with code 0. Only the printed report shows the missing number.

- The tool writes the `JSON` directly, without `save_level` or a `schema` check. The geometry stays the same, but no check examines the new entity positions.

- `Sentries` from `gauntlet` 1 stay because entity removal applies only to the 7 enemy types.

## `build_gauntlet3` — tactical geometry (`tools/musiccal/build_gauntlet3.py`)

### Goal

This tool builds `levels/gauntlet_cal3.json`. It makes the player stronger with geometry, not hit points, as the user instructed on 2026-07-16. The target is a 50 percent bot completion rate at 100 hp with no armor. Each segment connects a kite lane with a `sentry` alcove and fold, an hourglass choke, a source arena polygon, and an adapter.

The build connects 4 different boss compounds after segments 1 to 4, and each compound holds 2 or more `wardens`. The boss music value must clear 0.9 only in boss polygons. Thus, `wardens` live only there.

### Invariants

- Each portal is rigid: the 2 connected edges agree in length in 0.5 percent. `_rigidify` repairs each seam and raises `ValueError` when repair is not possible or the seam stays beyond the tolerance.

- Each polygon stays convex after each repair.

- The spread `population` does not enter polygons that spread placement must not use. It also does not enter boss compounds. The boss compounds keep only their hand-specified rosters.

- Each polygon contains a maximum of 6 enemies from spread placement. The position-selection rules keep `wardens` and `brutes` a minimum of 500 units apart.

- The spread `mix` contains no `wardens`. The initial `warden` fraction of the `mix` is added to the `brute` fraction.

### Verification

The tool prints the forward supply count, repaired seam count, `placed X/N (fails F)`, and type mix. After repair, `_rigidify` checks each seam and raises if one stays beyond tolerance. Comments record measured calibration results. A limit that put `wardens` only in the last third moved completed runs from 6 of 20 to 0 of 20. A build before the supply change completed 0 of 80 runs.

### Implementation

`lane_with_alcove` builds 5 chained rectangles with a total length of 1,050 and width of 150. The middle third divides into widths `90 | 170 | 90`, with a 170-by-170 alcove that extends north from the center piece. The alcove contains 3 `sentries`, one medkit, and 3 ammunition stacks. Lane pieces contain medkits and ammunition but no weapons. A fold connects the south edge of the last piece to the south edge of the first. The player can then move forward and get behind enemies in `hunt` state.

`hourglass` builds 2 mirrored quadrilaterals that use the same 64-unit portal at the center because engine polygons must stay convex. `choke` puts an hourglass with 3 `sentries` and one medkit between the lane and arena. The arena is built first. Thus, the choke exit uses the length of the arena entry edge. A quadrilateral adapter returns the arena exit to width 150.

The 4 boss compounds follow. `boss_donut` is a 3 by 3 grid of 220-unit cells without its center and has 4 `wardens`. `boss_cross` is a vault with 4 arms of length 700 and has 3 `wardens`. `boss_ring` has 5 `corridor` segments connected as a closed 5-cycle. Euclidean space cannot show this topology.

`boss_dark` has 2 unlit halls, a fold, and 4 `wardens`. Each compound connects through a hall with 2 turns that ends in an hourglass pinch of `150 -> 64 -> 150`.

`build` puts a medkit in each third polygon unless spread placement must not use that polygon or the polygon is part of a lane. It then runs `_rigidify` and `populate`. `populate` extends the `gauntlet` 2 algorithm with a 6-enemy polygon cap, a lane-area weight factor of 0.25, and the `warden`-to-`brute` distance condition. Boss-polygon ranges are written in `boss_polygons` in the level JSON.

### Caveats

- The docstring states the alcove contains 2 sentries, while the code puts 3.

- The `populate` docstring states lane polygons receive more weight, but the code multiplies their areas by 0.25. The parameter named `boost` thus decreases their weight. The code comment gives the correct operation.

- The `warden`-to-`brute` distance condition has no effect in this builder. The `mix` has no `wardens`, and boss `wardens` put in specified positions do not go into the spread point table. The condition runs but cannot reject a point.

- The tool changes the level after the `build()` check and writes it with `json.dumps` directly. Only `_rigidify` checks its repairs.

- `BOSS_CORRIDOR = 1150.0` is not used. The comment marks it as a legacy scale reference.

## `build_heavy_probe` — the heavy-data probe level (`tools/musiccal/aux/build_heavy_probe.py`)

### Goal

This tool builds a small auxiliary level for one comparison of contempt during kills of weak enemies and heavy enemies. An 80-run batch at full density made only 34 ticks of data in heavy segments `E` and `F`. This occurred because the bot usually died before it got there. This probe connects only `E` and `F` at full density with a complete passage between them. Thus, each run faces heavy enemies immediately. The primary fit does not use this level.

### Invariants

- The level holds 2 segments only, `E` and `F`, at `density` 1 by construction.

- The same connection count check and `build()` check as `gauntlet` 1.

### Verification

The tool prints the polygon and enemy totals for each segment. A reader compares them with the `gauntlet` 1 enemy list: `E` holds 15 enemies, and `F` holds 7.

### Implementation

The tool imports `SEGMENTS`, `add_corridor`, `add_segment`, `HEAVY_KINDS`, and `LEVEL_SEED` from `build_gauntlet`. For `E` and `F`, it reads the source level `JSON` and selects each enemy. It puts the segments 20000 units apart and adds start, middle, and end `corridors`. It writes `tools/musiccal/aux/gauntlet_heavy_probe.json` and a region data file. The builder uses `alert_hops=2` and the ambience `amb_drone_late`. Each supply polygon in a `corridor` receives the standard cache and 1 `sentry` because the tool calls `add_corridor` without a change.

### Caveats

- The tool duplicates the 7-type enemy set and does not import `build_gauntlet.ENEMY_KINDS`. A source change can leave this copy with the previous values without an error.

- The import sequence works only because `perihelion` is an installed package. The inserted `sys.path` includes only `tools/musiccal`, and the engine import runs before the `build_gauntlet` import that can add `game/`.

- `from random import Random` is not used.

- The tool does not write a `texture_map`, so the probe level lacks the parent level's floor-texture provenance. No display stage runs.

## `tune_density` — the 50 percent binary search (`tools/musiccal/tune_density.py`)

### Goal

This tool finds the gauntlet 1 density that makes a bot clear rate between 45 and 55 percent, as specified by the director. It assumes that more enemies cannot make the level easier, so clear rate decreases monotonically as density increases. This assumption allows binary search. The tool rebuilds `levels/gauntlet_cal.json` at the selected density and records the method in the target table.

### Invariants

- The probe seeds, confirmation seeds, and calibration-farm seeds are separate blocks with no overlap. The adjustment data does not leak into the fitted data.

- The tool rebuilds the level at the selected density, ensuring that the file on disk matches the reported result.

- The `subprocess` calls run with `check=True`. A build failure or a farm failure stops the tool with a clear error.

- The exit code is 0 only when the confirmation run falls in the band.

### Verification

The confirmation run uses 150 seeds, 2.5 times the probe seed count, and the exit code reports the band result. The file `tools/musiccal/tuning_log.json` holds each iteration with `density`, clear rate, and limits.

### Implementation

The lower and upper bounds start at `0.08` and `1.0`, with at most 10 iterations and 60 probe runs each. Each iteration builds the level at the midpoint `density` through a `subprocess` call to `build_gauntlet.py`, then runs `run_farm.py` with `seed0 = 500000 + iteration * 10000`. A clear rate below 0.45 moves the upper bound down. After the 10 iterations end, the tool selects the logged iteration nearest to 0.5 and builds at that `density` again. The confirmation run uses `seed0 = 1499000` and 150 runs.

The tool reads the farm report from the first `{`-prefixed stdout line. If no such line is present, it raises `RuntimeError` with the full output.

### Caveats

- `build()` is marked `-> dict` but returns the `subprocess` stdout text, which no caller uses.

- The binary search treats each probe result as exact. With 60 runs, the band boundaries contain sample noise that the loop does not model. The confirmation run decreases this uncertainty.

## `tune_pass_rate` — bot completion measurement (`tools/musiccal/tune_pass_rate.py`)

### Goal

This tool measures bot completion on a gauntlet level with the full loadout. It prints calibration diagnostics: death polygons, enemy types active at death, weapon usage, and death times. The director's target is a 50 percent clear rate achieved through enemy movement and player buffs and not population reduction.

### Invariants

- The session uses the product camera: `screen=(640, 360)`, `zoom=0.45`. The bot perception reads the camera view, and a different camera measures a different bot. A measured example: seed 1011 completes with 176 kills at the small camera and times out with 103 kills at the product camera.

- Seeds span `1000` through `1000 + k - 1`, enabling direct comparisons across configurations.

- The player state is the full `loadout`, with optional `--hp-buff` and `--resist` changes.

### Verification

The printed completion rate over a fixed seed block is the measurement. Worker `one()` also defines the canonical session construction: `hunt_winner` imports it and `boss_probe` mirrors it, so seed results replay across those tools.

### Implementation

`one()` builds a `GameSession` with the full `loadout`, steps the bot each tick, and stops on death, end, or `--max-ticks` (default 28800 ticks, 8 minutes). It returns the seed, `outcome`, hp, ticks, kills, damage received, last polygon, nearby enemy types, `ammo`, and weapons used. `main` runs the seeds in a pool with `--workers` (default 10) and prints report lines.

### Caveats

- Defect: 3 printed labels describe the wrong population. `kinds active at deaths` aggregates all runs and not only deaths, `death ticks` also includes all runs, and `ammo at death (first 3)` uses the first 3 completed results regardless of outcome. Only `death polygons` filters correctly.

- Weapon usage is sampled before each tick, so a switch is reflected one tick late.

## `hunt_winner` — the winner search (`tools/musiccal/hunt_winner.py`)

### Goal

This tool finds seeds where the bot completes the `gauntlet`, for the video of a full-session win (`director` instruction, 2026-07-17). It streams each seed result as it completes, and it stops after `--want` winners (default 3).

### Invariants

- Session construction calls `tune_pass_rate.one` unchanged with an unbuffed player. A winning seed thus replays identically in the farm and recorder.

- The seeds are the adjacent block `--start` to `--start + k - 1`.

### Verification

Each result prints as one line with seed, `outcome`, ticks, kills, polygon, and hp. Other tools can directly use a printed seed whose `outcome` is `complete`.

### Implementation

The tool submits each seed to a pool, with defaults of 24 workers and 43,200 maximum ticks, and prints results in completion order. When a run completes the level, it records the seed and prints a winner line. After reaching the requested winner count, it cancels tasks that have not started.

### Caveats

- `Future.cancel()` stops only tasks that have not started. Active tasks run to completion, and pool shutdown waits for them. Exit can thus take as long as one full run for each active worker.

- The last `done=` count drops the results after the stop point.

## `boss_probe` — boss music measurement (`tools/musiccal/boss_probe.py`)

### Goal

This tool runs the bot headless with a tick-clock `MusicSystem` attached and measures how the boss music engages. It defines a full boss trigger from the engine thresholds. The trigger must have 4 or more adjacent `bars` with the `overlay_boss` lane at `gain` 0.20 or more. It must also have a `peak` of 0.45 or more and use the `drums_boss` kit. The tool also reports death diagnostics and `warden` encounter records. `--godmode` prevents the bot from dying, so a person can measure the data without survival `skill` as a factor.

### Invariants

- The session construction mirrors `tune_pass_rate.one`, with the product camera.

- Music uses the tick clock. This makes the measurement deterministic.

- Environment variables select dummy SDL video and audio drivers, allowing the tool to run without a display.

### Verification

The output prints each seed with its boss music runs as `t0-t1(Nb,peak)`. A reader can compare the trigger class with the raw `bar` data. For complete runs, the tool prints the minimum and mean full-trigger counts. The stated goal is 3 or more full triggers in a complete run.

### Implementation

The tool scans `MUSIC_ROOT/album_*/bank.json` for `banks` and gives them to `MusicSystem` with `tick_clock=True`. A muted `Audio` collects `(t, kind, name)` events in memory through `tap`. Every 6 ticks, the tool samples the player polygon, hp, the top `warden` hp in the same polygon, and the hunter count. A contiguous span of `warden` samples in the same polygon forms one encounter record. A polygon change or a gap longer than 360 ticks starts a new record, and spans shorter than 60 ticks are discarded as short encounters.

The `bar` `taps` parse as `head|lane:kit:gain` parts, and a lane with the kit `silence` counts as `gain` 0. Death records include the polygon type, types in the same polygon, weapon, and `ammo`.

### Caveats

- The `won` field is calculated from warden HP at or below 0 but never returned, so encounter records do not state whether the warden died.

- Death-time ammunition and weapon values come from `locals().get(...)`, which returns `None` on non-death paths. A future control-flow change could silently break this pattern.

- The polygon type lookup handles each error and reports `?`.

- The default level is `levels/gauntlet4.json`, and no tool in these 2 directories builds that level.

## `run_farm` — the headless run farm (`tools/musiccal/run_farm.py`)

### Goal

This tool runs `GameSession` directly without a renderer across many seeds in parallel and writes one raw telemetry file for each run. Under a director correction dated 2026-07-13, it calculates no derived features. Instead, it logs pre-tick state, action, and metric deltas for downstream analysis tools.

### Invariants

- An unknown bot name raises `ValueError`.

- Each run file starts with a header object. On the good path it ends with a footer object with the `outcome`.

- The seeds are the block `seed0` to `seed0 + n - 1`.

- An error in the telemetry write block does not stop the farm. The run reports the `outcome` `error`. Errors before that block, or an exception from a worker `Future`, stop the farm.

- The player state is `MID_GAME_STATE`, a `loadout` for a player immediately after level `l03`: 100 hp, 60 `9mm`, 16 `shell`, 4 weapons. The `density` adjustment does not change this state.

### Verification

At completion, the tool prints outcome counts and clear rate. The tuned gauntlet targets approximately 50 percent. Its docstring cites the `test_human_bot.py` bot suite and smoke runs of this tool as stability evidence.

### Implementation

Each run repeats snapshot, `bot.step`, and `session.tick` until death, level completion, or `--max-ticks`, whose default is 72,000. Each tick writes one JSON array with 24 fields in a fixed order. The fields cover time, HP, polygon, position, movement, fire, ammunition, weapon, death, completion, metric deltas, enemies, and pickups.

The record schemas are fixed:

```python
TICK_FIELDS = [
    "t", "hp", "polygon", "x", "y", "mx", "my", "fire", "alt",
    "ammo_9mm", "ammo_shell", "ammo_cell", "weapon", "n_weapons",
    "dead", "complete", "kills_d", "dmgtaken_d", "dmgdealt_d",
    "shots_d", "hits_d", "pickups_d", "enemies", "pickups",
]
ENEMY_FIELDS = ["id", "kind", "hp", "state", "hops", "x", "y"]
PICKUP_FIELDS = ["id", "kind", "hops", "x", "y"]
```

Arrays replace objects to avoid repeated keys on each tick. Files use gzip compression and the name `<out-dir>/<bot>_<seed>.jsonl.gz`. The header contains schema number, seed, bot, level hash, git commit, and field lists. For `gauntlet_cal2.json`, `gauntlet2_meta.json` supplies a loadout with all 10 weapons. A worker pool runs the seeds, and the tool prints progress in 5-percent increments.

### Caveats

- Defect: the comment on `DEFAULT_MAX_TICKS` states `20000 ticks ~= 333 sim-seconds`, but the value is `60 * 1200 = 72000` ticks, or 1,200 seconds.

- On a run error, the file has no footer. `fit_factors` treats it as outcome `error` and does not include its label rows, while `saturation_stream` does not include the entire file. The 2 readers disagree.

- The loadout override is keyed to the exact file name `gauntlet_cal2.json`. Any other name silently falls back to `MID_GAME_STATE`.

- `--skill` has no effect for the `aggro` bot, and the header then records `skill=None`.

## `collect_corpus` — the 10 `Hz` refit corpus (`tools/musiccal/collect_corpus.py`)

### Goal

Under the director's 2026-07-16 instruction to capture all available data, this tool records a data set for a new factor fit. It writes one row each 6 ticks with raw observables, the product camera, and the full loadout. Active battery outputs are included only for comparison.

### Invariants

- Rows are recorded each 6 ticks.

- The sparse enemy counts do not include the zero values.

- Features include only enemies at hop distance 0 or 1.

### Verification

The first output line holds the `outcome`, the ticks, the kills, and the damage received for the run. The tool prints the same line to the console.

### Implementation

The session runs `levels/gauntlet_cal3.json` with the full `loadout`, `screen=(640, 360)`, and `zoom=0.45`, for at most 54000 ticks. Each row holds hp, the damage rate over 0.1 seconds, the kill delta, fire duty in the last second, and the weapon. It also holds enemy counts by type and state in the same and adjacent polygons, the new aggro count, and the minimum hunter distance. Other fields are crowd `pressure` as `sum(1 / max(d, 10))`, speed of approach, seconds since a scream capped at 600, the nearby `sentry` count, and 4 bot-internal values. `cur_vals` holds the active `battery` outputs from `values(read_inputs(s))` after the tick. The output is one gzip `JSONL` file with a `meta` line followed by the rows.

### Caveats

- Defect: the scream scan reads the last 8 entries of `s.fx`, but nothing drains `s.fx` in this harness. A scream stays in that tail until 8 newer entries displace it, and each scan resets `scream_tick` to the current tick. Thus, `since_scream` stays 0 long after the actual scream during quiet stretches.

- `prev_hp` starts at the fixed value 100.0 and not the loadout HP. The first damage-rate value is wrong when spawn HP differs from 100.

- `n_visible` is calculated but not written to the row.

- The outcome string is `death` here and `died` in `run_farm`. Readers of this data set compare only against `complete`, so the inconsistency currently causes no failure.

- `new_aggro` counts hunters at hop distance 0 to 1, but `min_hunt_dist` and `crowd_pressure` count only hop distance 0.

## `analyze_corpus` — the factor `analysis` (`tools/musiccal/analyze_corpus.py`)

### Goal

This tool does factor analysis on the 10 Hz data set with 3 ground-truth targets. `future_damage` is damage during the next 5 seconds. `mowing` is kills during the next 3 seconds while damage stays below 8. `calm` requires both no future damage and no active hunters. The tool fits a factor model, screens features by Spearman correlation, and fits a ridge model against the active battery baseline.

### Invariants

- Only rows with a complete 5-second future window enter the matrix.

- The train/test split groups by run and assigns one run in 5 to the test set, with no leakage across the split.

- The output keeps the `feature` names, means, and standard deviations.

### Verification

For each target, the tool prints held-out Spearman correlations for the ridge model and active battery channel. Acceptance requires the ridge correlation to exceed the battery correlation.

### Implementation

The tool reads `run_*.jsonl.gz` files and keeps runs longer than 40 rows. It derives feature keys from a row sample, adds 1- and 3-second trailing means for 5 fast channels, and scales all values. `FactorAnalysis` uses 6 components on approximately 60,000 sampled rows, and output records the 8 largest loadings for each factor. Spearman screening keeps the top 20 features for each target. The ridge model uses `alpha=10.0`. Battery channels map index 2 to `future_damage`, 1 to `mowing`, and 0 to `calm`.

### Caveats

- Defect: the run filter accepts more than 40 rows, but the cut point is `n - 50`. For runs of 41 through 50 rows, `X[:cut]` uses a negative limit and keeps rows without complete future windows, producing invalid targets. `fit_battery` requires a minimum of 60 rows. This tool does not.

- A sparse count key absent from the sampled rows silently drops out of the feature set.

- The `calm` target combines a future-damage condition with a current active-hunter count.

- An empty data set raises `NameError` on `extra_names`.

## `fit_factors` — the 60 `Hz` hazard model (`tools/musiccal/fit_factors.py`)

### Goal

This tool analyzes run-farm files with the method ratified on 2026-07-13. It builds a wide feature matrix from the raw stream and labels whether death occurs in a horizon. It fits a sparse hazard model and defines stalwart as the percentile rank of `P(death in 3 seconds)`. It also derives contempt and prayer directly from observations, measures saturation, runs 3 result checks, and writes `factor_model.json` plus the hazard graph.

### Invariants

- Each split groups by run. This prevents leakage between the train and test sets or across inner folds.

- The labels cut off timeout tails: a row is included only when the run has a full horizon after it.

- `fit_logistic` returns an error record when a model's training or test split has fewer than 2 positive labels. The command does not convert that record into a nonzero exit status.

- Subsampling is capped at 200,000 rows and deterministic under seed `20260713`.

### Verification

Output compares held-out AUC for the full model with a one-feature baseline. It also includes the quantile-calibration curve and AUC values for 5- and 10-second horizons. 3 result checks use separate criteria. Combat hazard must exceed corridor hazard with a permutation p-value below 0.05.

Weak-enemy kill rate must exceed heavy-enemy kill rate. Mean prayer in loot polygons must fall in 0.1 of 1.0. The command records these results but does not use them to set its exit status. `game/tests/test_gauntlet_calibration.py` fixes the expected values.

### Implementation

The 34 features include HP, ammunition, accuracy, aggression counts, and score-weighted threat `sum(score / (1 + hops))`. They also include 1-, 3-, and 10-second damage and kill windows. Remaining features cover capped minimum enemy distance, speed, time in polygon, and 4 weapon flags. They also cover static polygon data for example area, portals, lights, and region flags.

Labels use horizons of 3, 5, and 10 seconds at 60 ticks for each second. `LogisticRegressionCV` uses an L1 penalty across 5 `C` values and 3 grouped folds. PCA makes an auxiliary 8-component output. The percentile table contains 101 points derived from sorted model predictions.

The `feature` sequence is:

```python
[
    "hp", "total_ammo", "ammo_9mm", "ammo_shell", "ammo_cell", "n_weapons",
    "dmgtaken_1s", "dmgtaken_3s", "dmgtaken_10s",
    "kills_1s", "kills_3s", "kills_10s",
    "shots_3s", "hits_3s", "accuracy_3s", "fire_1s",
    "n_aggro", "n_aggro_same_polygon", "weak_aggro_same_polygon",
    "weighted_threat_active", "min_enemy_dist_capped",
    "has_same_polygon_threat", "n_pickups_polygon", "speed",
    "time_in_polygon", "area", "n_portals", "n_lights",
    "is_combat_zone", "is_loot_zone", "weapon_is_knife",
    "weapon_is_pistol", "weapon_is_smg", "weapon_is_shotgun",
]
```

Contempt groups kill rate by the number of weak, aggressive enemies in the same polygon. `Prayer` is `1 / (1 + n_aggro)`, and a long comment explains its nonzero floor. The enemy AI has no path that ends a `hunt`, so the count never returns to 0.

The saturation table calculates hazard for each polygon at run-prefix fractions from 1/16 through 1. Its criterion covers the polygons that account for 95 percent of bot time. Standard error must stay below 15 percent for those polygons. Change between the last 2 sample counts must not exceed 15 percent.

### Caveats

- Defect: the docstring points to `report.py` and `write_report` for the report and graph. Neither file is in the repository. This file writes the graph itself.

- `percentile_rank` has no callers. The percentile table ships to the engine, and the reference function is dead code.

- The saturation prefixes order runs lexicographically by file name, whereas `saturation_stream` orders them by seed number. The 2 tools thus use different prefix batches.

- The percentile table builds from model outputs on the train and test rows together.

- `load_polygon_features` is annotated as returning `dict[int, dict]` but returns a tuple. A comment states `~29 features`, while the list contains 34.

## `fit_battery` — `ridge` fit on observable signals (`tools/musiccal/fit_battery.py`)

### Goal

This tool derives `battery` constants from the 10 Hz data set. The deployed `battery` can use only signals observable by a player, so the model does not include bot-internal values. It fits one ridge model for each ground-truth target and compares its held-out Spearman correlation with that of the deployed `battery`.

### Invariants

- The feature set contains only observable values. Bot-internal fields from the data set stay out.

- The feature names have a fixed, sorted order.

- Only runs with more than 60 rows are included, ensuring that retained rows have a full future window.

### Verification

For each ground-truth target, the tool prints the new and deployed Spearman correlations and the 6 largest model weights. An improvement over the deployed correlation is the acceptance criterion.

### Implementation

For each enemy type, the features include `hunt` and `ambush` counts in the current and adjacent polygons, plus counts of nearby idle enemies. Other features include minimum hunter distance (with the -1 sentinel replaced by 600), crowd pressure, new aggression, damage rate, kill delta, and firing duty. The model also receives `hp_deficit = (100 - hp) / 100`, `scream_recent = max(0, 1 - since_scream / 300)`, and 1- and 3-second trailing means for 4 channels. Its targets use the same formulas as `analyze_corpus`. The model is `Ridge(alpha=10.0)` with the same run-grouped split. The output JSON contains feature names, means, standard deviations, and model weights sorted by magnitude.

### Caveats

- Defect: the docstring states that the tool fits ridge models with nonnegative weights and maps those weights onto the `music.py` battery formula. The code does not pass `positive=True` to `Ridge`, so model weights can be negative. It also contains no mapping step. The weights were transferred manually into `tune_battery2.W_CO` and `W_ADJ`.

- `hp_deficit` sets the maximum hp at 100 and does not read the `loadout` value.

## `tune_battery2` — the structured `battery` tuner (`tools/musiccal/tune_battery2.py`)

### Goal

This tool replays the data set through a structured `battery` that the engine can calculate from observable values. It tunes scalar constants by coordinate descent to approach the `ridge`-model `Spearman` limit. It prints the tuned constants for manual transfer into the engine and writes no files.

### Invariants

- The type-weight tables `W_CO` and `W_ADJ` do not change during calibration. They come from ridge-model ratios, with `husk_co = 1`.

- Each channel tunes only its knobs against its target. No channel changes a different channel.

- Model outputs and targets are subsampled at the same stride of 7.

### Verification

For each channel, the tool compares 3 versions on the same data. They are the deployed `battery`, the initial structured `battery`, and the tuned structured `battery`. The ridge fits from `fit_battery` supply the stated upper bound.

### Implementation

The battery formula includes the 10 Hz rate-conversion factors needed to reproduce the deployed calculation. `danger` sums type weights over `hunt` and `ambush` counts, then adds `CROWD_W * crowd`, `INFLUX_W * ema(new_aggro) * 10`, `DMG_W * ema(dmg_rate) * 10`, and `FIRED_W * fire_duty`. The scream term is `0.0 * scream_recent`. Finally, `stalwart = 1 - exp(-danger / KNEE)`.

`mow = KILL_W * ema(kills) * 10 + FIRE_W * fire_duty + TRASH_W * trash`. Here, `trash` is the count of mites and husks in the same polygon that hunt, ambush, or stay idle. `contempt = 1 - exp(-mow / MOW_KNEE)`. Contempt is an independent axis with no gates because boss combat can produce stalwart and contempt simultaneously.

The initial tables have these values:

```python
W_CO = {"warden": 12.0, "brute": 1.0, "flicker": 1.9,
        "husk": 1.0, "mite": 0.8, "spitter": 0.6, "shrieker": 0.15}
W_ADJ = {"warden": 8.5, "brute": 0.3, "flicker": 0.2,
         "husk": 0.8, "mite": 0.3, "spitter": 0.3, "shrieker": 0.1}
P = {"CROWD_W": 11.0, "INFLUX_W": 6.0, "SCREAM_W": 2.2,
     "DMG_W": 1.5, "FIRED_W": 1.5, "KNEE": 14.0,
     "KILL_W": 1.0, "FIRE_W": 0.5, "TRASH_W": 0.15,
     "MOW_KNEE": 1.5, "WAVE_CUT": 1.5, "ENGAGE_KNEE": 3.5,
     "FIRE_PRAY": 0.4, "FLOOR": 0.12}
```

`prayer = max(FLOOR, 1 - min(1, danger / ENGAGE_KNEE + FIRE_PRAY * fire_duty))`. The `ema` uses `alpha = 1 / 30` for the 10 `Hz` rows. Its accumulator starts at 0 for each run. The descent runs 3 rounds for each channel. It tries the multipliers `(0.4, 0.6, 0.8, 1.25, 1.7, 2.5)` in that sequence and accepts an increase above `1e-4`.

### Caveats

- Defect: the code's scream contribution is `+ 0.0 * scream`. Although `SCREAM_W` equals 2.2 and appears in the stalwart calibration list, it never affects the formula, so coordinate descent evaluates an inert parameter. The docstring instead shows `SCREAM_W * scream_recent`.

- Defect: the docstring gives contempt 3 gates: `(1 - stalwart)`, a wave guard on `WAVE_CUT`, and an HP scale. The code dropped all 3 under a director instruction dated 2026-07-16, and the code comment is the authoritative record. `WAVE_CUT` is thus another dead calibration parameter, and `hp` is an unused variable.

- The target here is `mowing = fut_kill` with no damage gate. The same name has a gated meaning in `analyze_corpus` and `fit_battery`.

- The tool prints the constants of record and writes no file. The transfer to the engine is manual.

## `saturation_stream` — memory-limited saturation (`tools/musiccal/saturation_stream.py`)

### Goal

This tool measures for each-polygon hazard saturation with bounded memory. `fit_factors` keeps each run in memory and consumes nearly 5 GB at 2,400 runs. That amount exceeds the free memory on this system. This tool keeps one run's `(polygon, tick)` rows at a time plus aggregate storage proportional to the polygon count. It also reports an unlabeled uncertainty measure.

One death labels up to a full horizon of ticks as positive. Tick-level standard errors thus make the sample appear more precise than it is. The tool estimates death counts as `positive_ticks / 180`.

### Invariants

- Each run file is read once, in seed-number order.

- Each batch snapshots the accumulated prefix, so tick counts can only increase.

- For runs with a footer, the labeling rule matches `fit_factors`.

### Verification

The tool is a diagnostic instrument. For each sample-count double, it reports whether the literal criterion holds. Standard error must stay below 15 percent on the covered polygons, and change must not exceed 15 percent. Beside the measured change, it reports the change predicted by a Poisson death-count model: `sqrt(1/d_cur + 1/d_prev)`. A measured-to-predicted ratio near 1 supports the interpretation that the changes come from death-count noise.

### Implementation

The tool uses only the standard library. `stream_run` reads a run file into a
list of polygon and tick pairs, then labels them with the 3-second horizon
criterion. It returns total and positive tick counts for each polygon. `main`
snapshots those totals at run-count fractions from 1/32 through 1. The coverage
set ranks polygons by tick count until it covers 95 percent of all ticks. The
output JSON contains the batches, the checks, and a last table of estimated
deaths for each polygon.

### Caveats

- This tool skips a run file without a footer. `fit_factors` instead keeps it as an error run but does not include its rows from the labels. The docstring's claim that the 2 tools use the same labeling rule is thus inaccurate.

- `worst_se` records the last polygon that fails the criterion and not the polygon with the largest relative standard error.

- With few runs, 2 fractions can round to the same count. The tool then records fewer batch snapshots than the fraction list implies.

- The noise model treats the 2 batches as independent even though the larger batch contains the smaller one. The result is only a rough check.

## `vst2_host` — the ctypes VST2 `host` (`tools/musicgen/vst2_host.py`)

### Goal

This module is a small VST2 host written entirely with Python `ctypes`. It renders native Linux `.so` synthesizers that `pedalboard` cannot load because `pedalboard` supports only VST3. It opens a plugin, supplies MIDI events, and pulls audio blocks. It operates offline with one instance for each process and is not part of the game.

### Invariants

- The `host` checks the VST2 format mark `0x56737450` on load.

- `MIDI` events always arrive in their block, with the frame delta at 0 or more.

- The output is always mono `float64`, computed as the mean of all plugin output channels.

### Verification

The self-test command, `python vst2_host.py <plugin.so>`, loads the plugin, prints its ID and counts, and renders a 2-note chord. It prints `SOUND` when the peak exceeds `1e-4` and writes `out/vst2_host_test.wav` when the rendered signal has sound.

### Implementation

The constants are `SR = 44100` and `BLOCK = 512`. The `AEffect` and event structures come from `aeffect.h`. The host callback returns version 2400, sample rate 44100, block length 512, or 0 for any other request. Construction tries the entry symbols `VSTPluginMain` and `main`, then dispatches open, sample-rate, block-length, and mains-on operations. `set_program` uses opcode 2, `program_names` uses opcode 29, and `set_chunk` uses opcode 24. `render(seq, total_s, tail_s)` expands each `(note, start, dur, velocity)` tuple into note-on and note-off events, sends each block's events through opcode 25, and calls `processReplacing` for each 512-sample block.

### Caveats

- With no entry symbol, the load fails with an opaque `AttributeError` on `None`, not a clear message.

- The `host` does not examine the `canReplacing` flag before it calls `processReplacing`.

- `close()` catches all errors.

- The self-test writes to the relative directory `out/`, which must already exist.

## `juce_valuetree` — binary state `decoder` (`tools/musicgen/juce_valuetree.py`)

### Goal

This module decodes the JUCE binary `ValueTree` format into XML. Its format rules were transcribed from the JUCE 7.0.12 source and not reconstructed from memory. The `.odin` patch files use the binary format, while the `Odin2` state must show the same data as XML.

### Invariants

- An unknown value marker raises `ValueError` with the byte offset.

- A zero or negative length value decodes to `None` and does not damage the read position.

### Verification

The file contains no test of its own. The `Odin2` self-test exercises the decoder end to end. Invalid XML leaves the plugin in its initial state, producing an A/B difference of 0.

### Implementation

The grammar consists of a type string, a packed property count, `(name, value)` pairs, a packed child count, and the child trees. Strings are UTF-8 with a NUL terminator. A packed integer starts with a one-byte length. Bit `0x80` records a negative sign, and the stated number of little-endian value bytes follows.

Value markers are 1 for `int32`, 2 for `true`, 3 for `false`, 4 for `float64`, 5 for text, 6 for `int64`, 7 for an array, and 8 for raw bytes. `to_xml` writes properties as attributes. It encodes byte properties as `base64:<name>` with JUCE's `MemoryBlock` encoding and escapes attribute values with `quoteattr`. `binary_to_xml` adds the XML declaration.

### Caveats

- For an array marker, the decoder ignores the stated byte length and reads by element count. This matches JUCE's behavior, so a corrupt length is accepted without an error.

- Trailing data after the tree is accepted without an error. Truncated data surfaces as `IndexError`.

## `odin2_host` — `Odin2` preset `host` (`tools/musicgen/odin2_host.py`)

### Goal

This module loads genuine `Odin2` factory presets headlessly through `pedalboard`, satisfying the presets-first requirement. The VST3 state chunk consists of `VC2!`, a length, and XML. Its `<IComponent>` element contains a JUCE base64 encoding of the same bytes stored in an `.odin` patch file. Loading a patch thus changes the patch to XML, wraps and encodes it, splices it into the state, and assigns the result to `raw_state`.

### Invariants

- Each splice starts from the plugin's cached initial state, not from a previously modified state.

- The outer state length field always agrees with the payload after the splice.

### Verification

The self-test renders MIDI note 38 with both the initial state and the first factory bass patch. It prints `LOADED` when the difference exceeds `1e-3` and writes `out/odin2_factory_bass_test.wav`.

### Implementation

`juce_b64encode` implements JUCE's `MemoryBlock` encoding. A decimal byte count and a period precede the 6-bit groups. The function reads each group least-significant bit first and maps it through `.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+`. `_state_template` caches the unchanged `raw_state` and the `<IComponent>` span once.

`load_patch` builds `VC2!` plus a length and the XML from `binary_to_xml`. It encodes and splices the result, updates the outer length at bytes 4 through 7, and returns the plugin. `factory_patches` finds the `Factory Presets` directory in the temporary work directory. `render_sequence` sends a complete phrase through one plugin invocation. Overlapping notes thus produce real legato, and envelopes continue across the line.

### Caveats

- The import `from juce_valuetree import binary_to_xml` has no `sys.path` put in. The module imports only when the script directory is on the path before this import runs.

- A missing preset directory raises a bare `StopIteration` from `next()`.

- The plugin path is hard-coded to a temporary work directory under `/tmp` with a session ID. A different session breaks it.

- A dead line calculates `base` from `render_notes.__wrapped__` and never uses it.

## `dexed_host` — `DX7` voice `host` (`tools/musicgen/dexed_host.py`)

### Goal

This module hosts `Dexed` and selects genuine DX7 factory voices headlessly. The `program` parameter has no effect in headless operation, so the module edits the state XML. It moves the selected voice to slot 0 of the SysEx cartridge and recomputes the checksum. It then writes the unpacked voice into the `base64:program` attribute from which the engine renders.

### Invariants

- The inner chunk marker must be `VC2!`, and the SysEx header must be `F0 43 00 09 20 00` with a total length of 4,104 bytes. The two conditions are asserted.

- The cartridge checksum is recomputed after each change as `(-sum) & 0x7F`.

- The 6 trailing bytes of the program blob after byte 155 stay unchanged.

### Verification

The self-test renders MIDI note 50 with programs 0 and 4, then prints `PRESETS SWITCH HEADLESS` when their difference exceeds `1e-3`. As recorded in the docstring, the unpacked factory voice 0 matched the plugin's program blob byte for byte.

### Implementation

`unpack_voice` changes a 128-byte packed DX7 voice into its 155-byte unpacked representation: 6 operators followed by the global block. Each operator expands from 17 packed bytes to 21 bytes, with bit fields separated according to the DX7 format. `program_names` reads bytes 118 through 127 of each voice. `set_program(n)` decodes the layered state: outer XML, JUCE base64, inner `VC2!` chunk, `dexedState` XML, and its SysEx attribute. It reorders the cartridge and updates the program blob, re-encodes the state, patches the outer length, assigns `raw_state`, and returns the plugin. `render_notes` and `render_sequence` mirror the `Odin2` functions.

### Caveats

- Defect: the program index drifts. `set_program` writes the reordered cartridge back, and the next call reads that modified state. After `set_program(4)`, a call with index 2 selects initial factory voice 1. An index means "factory voice `n`" only on the first call. The self-test sequence 0 then 4 is safe by chance.

- The `_cartridge` docstring lists 4 return values, but the function returns 5.

- The plugin path is hard-coded to a temporary work directory with a session ID.

- JUCE base64 logic has 4 implementations across this directory: encoding and decoding here, encoding in `odin2_host`, and decoding in `juce_valuetree`.

## `surge_bank` — `Surge XT` patches (`tools/musicgen/surge_bank.py`)

### Goal

This module defines 4 hand-built `Surge XT` patches: a detuned saw lead, FM bass, gated buzzsaw wall, and dark drone. Each patch starts from `Init` and sets parameters explicitly. Earlier versions synthesized these voices with bare `numpy` oscillators. An audit showed that `pedalboard` can load `Surge XT` without a window. The GPL-licensed tool renders assets offline and does not ship with the game.

### Invariants

- Failure to set a parameter raises `RuntimeError` with its name and value. An invalid name is never accepted silently.

- Each patch has a dedicated plugin instance whose parameters are set once. Sharing an instance corrupted the first render after an oscillator-type change, as documented by the measurement in the docstring.

- Velocity stays between 1 and 127, and each note lasts a minimum of 10 ms.

### Verification

`main()` renders 4 fixed tests and prints each signal's peak and strongest spectral frequency between 30 and 2,000 Hz. The reader can compare that frequency with the target note, for example D2 at approximately 73.4 Hz.

### Implementation

The patch table has these values:

```python
{
    "lead_saw": {
        "a_osc_1_type": "Classic", "a_osc_1_shape": 0.0,
        "a_osc_1_unison_voices": "7 voices",
        "a_osc_1_unison_detune": "32.00 cents",
        "a_filter_1_type": "LP 24 dB", "a_filter_1_cutoff": 52.0,
        "a_filter_1_resonance": 0.16,
        "a_filter_1_feg_mod_amount": "33.98 semitones",
        "a_lfo_1_rate": "5.436 Hz", "a_lfo_1_amplitude": 0.06,
        "a_portamento": "24.3 ms", "a_waveshaper_type": "Hard",
        "a_waveshaper_drive": 11.0, "a_amp_eg_attack": "12.0 ms",
        "a_amp_eg_release": "251.0 ms",
    },
    "fm_bass": {
        "a_osc_1_type": "FM2", "a_osc_1_shape": 0.35,
        "a_filter_1_type": "LP 24 dB", "a_filter_1_cutoff": 52.0,
        "a_filter_1_resonance": 0.18, "a_waveshaper_type": "Hard",
        "a_waveshaper_drive": 9.0, "a_amp_eg_attack": "4.0 ms",
        "a_amp_eg_release": "179.9 ms",
    },
    "buzzsaw_wall": {
        "a_osc_1_type": "Classic", "a_osc_1_shape": 0.0,
        "a_osc_1_unison_voices": "9 voices",
        "a_osc_1_unison_detune": "55.00 cents",
        "a_filter_1_type": "LP 24 dB", "a_filter_1_cutoff": 60.0,
        "a_filter_1_resonance": 0.08, "a_waveshaper_type": "Hard",
        "a_waveshaper_drive": 8.0, "a_amp_eg_attack": "6.0 ms",
        "a_amp_eg_release": "119.9 ms",
    },
    "drone": {
        "a_osc_1_type": "Classic", "a_osc_1_shape": 0.15,
        "a_osc_1_unison_voices": "5 voices",
        "a_osc_1_unison_detune": "18.00 cents",
        "a_filter_1_type": "LP 24 dB", "a_filter_1_cutoff": 44.0,
        "a_filter_1_resonance": 0.22, "a_amp_eg_attack": "902.5 ms",
        "a_amp_eg_release": "1.40 s",
    },
}
```

`render_phrase` renders one continuous MIDI performance with random timing changes that have a standard deviation of 8 ms. It applies a velocity contour from 84 to 118 across the pitch range and a 94 percent note gate. The default random generator uses seed 0. Thus, phrases are deterministic across runs.

### Caveats

- No caller uses `_plugin()`. The live path is `_plugin_for(patch)`.

- The plugin path is hard-coded to a temporary work directory with a session ID.

## `vital_bank` — the `Vital` slot map (`tools/musicgen/vital_bank.py`)

### Goal

This module maps each album slot to a preset in one of 2 `Vital` preset banks. The slots include the wall, core basses, a bass cell for each enemy, a lead for each weapon, holy voices, and stage beds. It renders through the installed `Vital` synthesizer in the VST2 host. On 2026-07-15, the director stated that all voices made by a synthesizer must come from the `Vital` banks. `Delay Lama`, the `TR-909` kit, and the chug wall stay because they are the vocal or recorded samples, not voices made by a synthesizer.

### Invariants

- A missing preset file raises `FileNotFoundError` with the path.

- The preset chunk gets a `NUL` end byte before `effSetChunk`.

- The module keeps one synthesizer instance and reloads a preset only when the slot key changes.

### Verification

The file contains no test. Comments adjacent to the slots record external test results. The measured sustain for the `Machine Drone` bed is 0.84. The director's listening test found that `Vitalium` changes `Vital` 1.5 presets into a fallback sound. This result caused the change to the installed `Vital` plugin.

### Implementation

`SLOTS` contains 27 entries of the form `slot -> (bank, preset stem)`. Each entry comes from `director_picks.json` and obeys the requirement to use selections first. For example, the wall uses `Supersync`, while enemy cells use different timbres for different types. The `mite` uses `Short Pulse Bass`, and the `warden` uses `Sub Fall`.

10 weapon leads map to 10 weapons, and the sound of the 4 stage beds changes from light to dark. `render_seq` loads preset bytes into the same `Vst2Synth` through `set_chunk` and renders the sequence.

The slot table is:

```python
{
    "wall": ("5years", "Supersync"),
    "bass_deep": ("5years", "Heavy"),
    "bass_fm": ("5years", "FM Bass 1"),
    "cell_mite": ("5years", "Short Pulse Bass"),
    "cell_husk": ("5years", "Rubber Bass"),
    "cell_spitter": ("5years", "Acid Bass 3"),
    "cell_shrieker": ("5years", "Rave Alarm"),
    "cell_brute": ("tngkaos", "Fat Bass"),
    "cell_warden": ("5years", "Sub Fall"),
    "cell_flicker": ("5years", "Malfunction"),
    "lead_knife": ("5years", "Elastic"),
    "lead_pistol": ("5years", "Hypercube PLUCK"),
    "lead_smg": ("5years", "Techtonics"),
    "lead_shotgun": ("5years", "Splatter"),
    "lead_rail": ("5years", "Magnetic Separation"),
    "lead_lightning": ("5years", "Tesla Coil"),
    "lead_tau": ("5years", "Exabyte"),
    "lead_hole": ("5years", "Fifth Revival"),
    "lead_scrap": ("tngkaos", "Dirty  Fonk"),
    "lead_gland": ("5years", "Tuvan"),
    "choir": ("5years", "Choir Pad"),
    "organ_holy": ("5years", "Heaven's Gate"),
    "organ_defiant": ("5years", "Hoover"),
    "bed_t1": ("5years", "Machine Drone"),
    "bed_t2": ("tngkaos", "Dark mood 1"),
    "bed_t3": ("5years", "Distress Signal"),
    "bed_t4": ("5years", "Evil"),
}
```

### Caveats

- The first docstring line names `Vitalium`, but the code loads `Vital` as specified. That line is incorrect.

- The preset-bank and synthesizer paths are hard-coded to temporary work directories with a session ID.

- Import does not check that each preset named in `SLOTS` is available. The code finds a missing file only on the first render that uses it.

## `tr909_kit` — the `TR-909` sample kit (`tools/musicgen/tr909_kit.py`)

### Goal

This module supplies the drum instrument: a recorded `TR-909` set with 853 samples from one output. It includes 11 accent levels for each instrument and a kick-parameter grid. The samples are the preset. Each hit selects a recorded accent layer and gives the `TR-909` velocity response, not only a scaled gain. The terms for use let these samples occur in music but do not let the repository contain them. Thus, the samples stay in the temporary work directory, and only rendered audio is in the repository.

### Invariants

- Each sample checks a 44100 sample rate on load.

- A missing instrument directory or control file raises `FileNotFoundError`.

### Verification

The file contains no test. Listening probes and the director examine renders that use the kit.

### Implementation

`_accent_files` examines an instrument directory for names with `accent<N>` and keeps variants with neutral calibration. If no accent set is available, it uses the middle file as a synthetic accent level of 100. `hit(inst, vel, rng)` maps velocity to the nearest recorded accent. When given a random generator, it selects an adjacent accent with probability 0.3 and uses the drum machine's layer differences. `kick_knob(tune, attack, decay)` loads the grid file for parameter values 0, 25, 50, 75, or 100. `place` mixes a sample into a buffer at the requested time and truncates it at the buffer boundary.

### Caveats

- No code reads the second element of each `INSTS` entry, the file name `pattern`.

- `place` gives no error when it drops a hit that starts after the buffer boundary.

- The sample-set path is hard-coded to a temporary work directory with a session ID.

## `specimen_kit` — the `Specimen` sample pack (`tools/musicgen/specimen_kit.py`)

### Goal

This module makes a list of the free `Specimen` sample set and loads its files. The terms for use let these samples occur in music but do not let the repository contain them. Because of this limit, they stay in the temporary work directory. File names follow the grammar `SPEK_PACK_CATEGORY[_Loop_BPM][_KEY]_Name.wav`. The code changes the pitch of keyed entries with the procedure that a sampler uses, and loop names include a BPM value.

### Invariants

- A file name that does not agree with the grammar does not go into the list.

- Each load gives mono `float64` at 44100.

### Verification

The test in the module prints total and keyed item counts for each group. It checks the grammar against the structure of the installed sample set.

### Implementation

`catalog` parses each file name into group, name, path, MIDI note, and BPM, with `C4` equal to 60. `load` caches 64 files, folds stereo to mono, and changes the sample rate to 44,100 Hz with linear interpolation when necessary. `keyed(path, src_midi, target_midi)` moves pitch through a sample-rate change at the ratio `2^((target - src) / 12)`. Duration changes with pitch, as specified for playback that changes `tape` speed.

### Caveats

- The key grammar accepts a negative octave, but the parser reads only the last character as the octave. For example, `C-1` raises `KeyError`. The active sample set contains no such names.

- `load` uses the same linear interpolation as `keyed`, but it uses it to make a standard sample rate. It does not use it to move pitch through a change in `tape` speed.

## `delay_lama` — the vocal instrument (`tools/musicgen/delay_lama.py`)

### Goal

This module renders the album's vocal instrument, the 2002 `Delay Lama` plugin. It is a 32-bit Windows VST2 hosted through the `MrsWatson` command-line host in `Wine`. Tests found some limits that the wrapper records. The host reads only MIDI type 0. The plugin sounds one octave below the written note. Thus, the wrapper moves notes up by 12 semitones.

The voice is monophonic, and the pitch wheel selects the vowel as recorded in the plugin's MIDI document.

### Invariants

- A missing plugin or host executable raises `FileNotFoundError` before the render starts.

- A host failure always raises `RuntimeError` with the return code and the tails of standard output and standard error. The caller receives the instrument audio or a clear error. A failure cannot give no indication.

- Each MIDI file made by the wrapper contains one `control-change` event. A measured host defect causes files with 2 or more control changes to render with no sound. The distance between events has no effect on this defect.

- The output is always mono `float64` at 44100.

### Verification

A check recorded on 2026-07-13 found that MIDI note 50 renders at 73.6 Hz, the note `D`, with 100 percent voiced audio. A short listening test found a low, stable vocal drone with a male timbre. The test in the module renders a 4-event phrase and writes `selftest.wav`.

### Implementation

`_write_midi` changes `(semitone, steps)` events, with `None` as rests, into a type 0 MIDI file at 480 ticks for each quarter note. At time 0 it writes the one permitted control change, `CC5` portamento, which turns glide between notes on or off. When the caller supplies vowels, the pitch-wheel vowel value comes before each note. The note then sounds at `base + 12 + semitone`, velocity 100, with a 93 percent gate. `render_vocal` runs `wine mrswatson.exe --plugin DelayLama.dll --midi-file ... --output ...` with paths relative to the plugin directory because absolute paths break the host in `Wine`. When necessary, it changes the output sample rate with `resample_poly`.

### Caveats

- `render_vocal` keeps its `delay`, `voice`, and `vibrato` parameters as attributes on `_write_midi`, but no code reads them. Only `port_time` has an effect. The measured defect above lets the file contain a maximum of one control change. An additional control change causes the output to have no sound.

- Parameter transfer through function attributes raises `AttributeError` when `_write_midi` runs before the first `render_vocal` call.

- The vowel list is indexed by event position, with rests in the position count. If a caller supplies vowels only for notes that sound, the vowels do not align with those notes. The function gives no error.

## `preset_scout` — the `Vital` preset screen (`tools/musicgen/preset_scout.py`)

### Goal

This tool examines 2 `Vital` preset banks for album-slot candidates in 3 phases. During `render`, each preset renders short standard phrases for each use suggested by its name. The tool tries a preset with an unknown name in each use. During `probe`, the fast judge scores each render against a short description of that use. This obeys the director's instruction that the fast judge examines only calls with one instrument, not comparisons. During `top`, the tool prints the best candidates for each use.

### Invariants

- The two work phases can continue after a stop. A render that is present and contains sound marks a preset as rendered. A score that is present marks a stem as probed.

- The scores file is written after each 25 probes. Thus, an unexpected stop can lose a maximum of 24 scores.

### Verification

The `scores` file `tools/musicgen/preset_scout_scores.json` is in the repository. `preset_browser` and the slot map read it. The `vital_bank` docstring names it the decision log of the alternatives.

### Implementation

Word tables map parts of preset names to bass, lead, and pad uses. The 3 test phrases are a bass riff near `D1`, a lead line near `D4`, and a sustained `D3` chord. For example, the short description for bass requests a heavy, rough low end below the wall. The tool does not keep a render with a maximum level below `1e-4`. `probe` calls the playtest judge with `n_passes=1` and keeps `p`, `match`, and a short report for each stem. `top` prints the best 8 candidates for each use.

### Caveats

- The tool does not keep a render with no sound, and it makes no record of that result. Thus, each subsequent run renders it again. There is no cache for negative results.

- Each item failure is printed and the loop continues. If the judge does not operate, the tool continues through the full list and makes no scores.

## `preset_browser` — the selection browser (`tools/musicgen/preset_browser.py`)

### Goal

This windowed tool lets the director sort `Vital` presets after listening to clips rendered by the probe. The UI does not run the synthesizer. Each selection is written immediately to `tools/musicgen/director_picks.json`. Downstream slot selection gives director selections priority over `scout` scores.

### Invariants

- Each change to a selection writes the selections file immediately. Thus, the file contains the state before the tool exits.

- The playback source is only the probe's rendered clip set.

- A missing `score` shows as a placeholder mark, not a false number.

### Verification

The selections file is the output. Comments in `vital_bank.SLOTS` record that the slot map draws from it. This tool supplies the verification step that a person does.

### Implementation

The window is 1,100 by 780 and updates at 30 frames for each second. It uses `mgui` and the engine's `fb2d` and `text` surfaces. Row names follow `bank__preset__role`. 4 use buttons filter the rows, and a click on a row plays it once.

A click with the right mouse button or `SPACE` changes selection, and the mouse wheel moves 3 rows. `S` cycles through sort by score, name, and selections first. `ESC` exits. Selected rows show a `*` in gold, and the last row played is green.

### Caveats

- `SPACE` changes the selection of the last `stem` played even when the active `filter` does not show that row. The screen gives no indication.

- Sort modes use a missing score in different ways. Sort by score puts it below 0, while sort with selections first uses it as 0.

- The row position does not return to its start after a sort change. It returns to its start only after a `filter` change.

- No code reads `big = 17`.

## `chants` — chant transcriptions (`tools/musicgen/chants.py`)

### Goal

This data module contains chant transcriptions checked by a person and 4 motif transformations from the initial `melodies.py`. The complete `Dies Irae` strophe is the specified seed phrase. An external consultation estimated a 65-to-80-percent chance of acceptance with an authored seed, compared with 15 to 25 percent without one. The module contains only data and must not contain rendering code.

### Invariants

- A module-level assertion checks that the strophe durations total 8 bars of 16 steps.

- The module imports only `annotations` from `__future__`. It has no runtime
  dependencies.

- This module defines the event convention used in the full tool set. An event is `(semitones_from_final, duration_in_16th_steps)`, and `(None, steps)` shows a rest.

### Verification

The strophe is the fixture for the `gabc` parser test, checked pitch for pitch against `GregoBase` 1198. `vocal_check` aligns rendered audio with it.

### Implementation

`DIES_IRAE_STROPHE` contains the complete first strophe of 3 lines transcribed from `GregoBase` GABC source 1198. Comments identify the source book and transcriber. A syllable is represented as a 4-step quarter note, and a 2-note group divides into 2 eighth notes. A dotted note at the end of a line lasts 8 or 12 steps, while breath marks become rests of 4 or 8 steps. `DIES_IRAE_MOTIF` and `VICTIMAE_MOTIF` contain 8-note incipits. The transformations `sequence`, `invert`, `fragment`, and `retrograde` operate on semitone lists.

The literal `melody` data is:

```python
DIES_IRAE_MOTIF = [3, 2, 3, 0, 2, -2, 0, 0]
VICTIMAE_MOTIF = [0, -2, 0, 3, 5, 3, 2, 0]
MOTIF_DUR_STEPS = 2
DIES_IRAE_STROPHE = [
    (3, 4), (2, 4), (3, 4), (0, 4),
    (2, 4), (-2, 4), (0, 4), (0, 8), (None, 4),
    (3, 4), (3, 2), (5, 2), (3, 2), (2, 2), (0, 2), (-2, 2),
    (2, 4), (3, 4), (2, 4), (0, 8), (None, 4),
    (-5, 4), (-2, 2), (0, 2), (0, 4), (0, 2), (-2, 2),
    (2, 4), (3, 4), (2, 4), (0, 12), (None, 8),
]
```

### Caveats

- The 4 transforms occur twice in duplicate blocks. The second definitions replace the first definitions.

- A section header promises `harmony-aware snapping` from `MELODY_CRAFT.md`, but the module contains no such function.

- Only `DIES_IRAE_STROPHE` has importers. The motifs and transformations have no importers. `riffs.py` contains the live transformations.

## `chants_data` — the `melody` menu data (`tools/musicgen/chants_data.py`)

### Goal

This generated data module contains 7 `GregoBase` chant excerpts and 6 historical tunes in the strophe event format. Each block records its source: `GregoBase` ID, book, mode, and counts. `build_chant_data.py` makes the file, which must not be edited by hand.

### Invariants

- The module contains data only, with no executable functions.

- Each entry has a provenance comment.

### Verification

The tune tables come from the parsers in `tunes.py`, which fixture tests check. The chant source record connects each entry to its `GregoBase` ID.

### Implementation

The chant tables are `MEDIA_VITA`, `LIBERA_ME`, `REQUIEM_INTROIT`, `VEXILLA_REGIS`, `VENI_CREATOR`, `PANGE_LINGUA`, and `VIDERUNT_OMNES`. The tune tables are `LHOMME_ARME`, `OLD_100TH`, `CHRIST_LAG`, `EIN_FESTE_BURG`, `IDUMEA`, and `AD_MORTEM`. The `CHANT_MENU`, `TUNE_MENU`, and `MELODY_MENU` dictionaries map lowercase names to those tables.

The complete generated tables, with source comments, are:

```python
# Media vita — 'In the midst of life we are in death' — battle antiphon, mode 4 (Phrygian)
# GregoBase id 3973; book: Cantus selecti, 1957, p. 41*; mode 4; 119 events, 16.4 bars
MEDIA_VITA = [
    (0, 4), (2, 4), (3, 4), (5, 4), (3, 2), (2, 4), (0, 2), (7, 2), (7, 4),
    (5, 2), (3, 2), (5, 1), (7, 1), (5, 1), (5, 1), (2, 0), (2, 8),
    (None, 4), (0, 2), (7, 2), (7, 4), (5, 4), (5, 1), (7, 1), (5, 2),
    (3, 2), (2, 2), (3, 1), (5, 1), (3, 2), (5, 8), (5, 8), (None, 4),
    (5, 1), (3, 1), (0, 2), (3, 1), (5, 1), (7, 2), (5, 2), (7, 2), (5, 2),
    (3, 2), (2, 1), (5, 1), (3, 1), (3, 1), (2, 1), (2, 1), (3, 4),
    (None, 4), (0, 4), (2, 4), (3, 4), (5, 4), (3, 4), (3, 1), (3, 1),
    (2, 1), (0, 1), (2, 2), (0, 4), (None, 4), (0, 1), (3, 1), (7, 2),
    (5, 8), (5, 4), (5, 1), (3, 1), (5, 1), (7, 1), (2, 1), (5, 1), (3, 1),
    (3, 1), (3, 2), (2, 4), (None, 4), (7, 4), (5, 1), (7, 1), (8, 1),
    (7, 1), (5, 1), (5, 1), (3, 1), (0, -1), (2, 1), (3, 1), (5, 2),
    (3, 2), (2, 4), (None, 4), (7, 4), (5, 1), (7, 1), (8, 1), (7, 1),
    (5, 1), (5, 1), (3, 1), (0, -1), (2, 1), (3, 1), (5, 2), (3, 2),
    (2, 4), (None, 4), (7, 4), (5, 1), (7, 1), (8, 1), (7, 1), (5, 1),
    (5, 1), (0, 4), (2, 4), (None, 4),
]

# Libera me Domine de morte — Office of the Dead responsory, mode 1
# GregoBase id 14065; book: The plainchant gradual - Parts III & IV, 1962, p. 233*; mode 1; 125 events, 11.2 bars
LIBERA_ME = [
    (0, 4), (0, 2), (-2, 2), (0, 4), (3, 2), (3, 2), (2, 1), (0, 1),
    (2, 1), (3, 1), (0, 1), (-2, 1), (0, -2), (0, 4), (2, 1), (3, 1),
    (5, 2), (5, 2), (3, 2), (0, 2), (3, 2), (2, 1), (0, 1), (3, 1), (3, 1),
    (0, 0), (0, 4), (None, 4), (0, 2), (5, 2), (5, 4), (5, 1), (3, 1),
    (3, 1), (2, 1), (0, 1), (-2, -1), (0, 1), (2, 1), (3, 1), (2, 1),
    (-2, 0), (0, 2), (-2, 2), (None, 4), (-2, 2), (0, 2), (0, 4), (2, 1),
    (3, 1), (5, 2), (5, 1), (3, 1), (2, 1), (2, 1), (2, 1), (5, 1), (7, 1),
    (8, 1), (5, 0), (3, 4), (2, 2), (3, 2), (0, 4), (0, 1), (2, 1), (0, 1),
    (-2, 1), (0, 1), (2, 1), (3, 2), (2, 2), (0, 2), (None, 4), (7, 4),
    (7, 1), (5, 1), (7, 1), (3, 1), (5, 1), (7, 1), (8, 1), (5, 1), (3, 1),
    (2, 1), (0, -6), (2, 2), (0, 2), (0, 4), (7, 4), (7, 2), (5, 2),
    (7, 1), (10, 1), (9, 1), (5, 1), (5, 1), (7, 1), (5, 1), (3, 1),
    (2, 1), (0, 1), (0, -2), (2, 1), (3, 1), (5, 1), (2, 1), (3, 1),
    (2, -1), (-2, 2), (0, 2), (0, 4), (-2, 1), (3, 1), (2, 1), (3, 1),
    (5, 0), (5, 1), (-2, 1), (0, 1), (2, 1), (3, 1), (2, 1), (0, -2),
    (None, 8),
]

# Requiem — Requiem aeternam introit, mode 6 (Graduale Romanum 1974)
# GregoBase id 7978; book: Graduale Romanum, 1974, p. 669; mode 6; 101 events, 14.6 bars
REQUIEM_INTROIT = [
    (0, 1), (0, 1), (2, 2), (0, 4), (0, 4), (0, 1), (2, 1), (4, 2), (4, 1),
    (2, 1), (2, 1), (0, 1), (2, 0), (2, 2), (0, 4), (None, 4), (0, 1),
    (2, 1), (4, 2), (4, 2), (2, 2), (4, 4), (4, 1), (7, 1), (4, 1), (2, 1),
    (4, 1), (5, 1), (4, 1), (2, -3), (0, 4), (0, 1), (2, 1), (4, 1),
    (2, 1), (0, 1), (2, -1), (2, 2), (0, 4), (None, 4), (4, 2), (2, 2),
    (4, 1), (2, 1), (0, 2), (4, 4), (2, 2), (4, 2), (2, 2), (0, 2), (0, 8),
    (None, 4), (4, 2), (2, 2), (4, 4), (4, 1), (7, 1), (4, 1), (2, 1),
    (4, 1), (5, 1), (4, 1), (2, -3), (0, 1), (2, 1), (4, 1), (2, 1),
    (0, 1), (2, -1), (2, 2), (0, 4), (None, 8), (0, 2), (2, 2), (2, 2),
    (0, 2), (2, 2), (4, 2), (4, 4), (2, 4), (5, 4), (4, 4), (4, 4), (2, 4),
    (0, 8), (4, 4), (4, 2), (7, 2), (2, 4), (0, 4), (0, 4), (0, 4), (0, 4),
    (2, 4), (0, 2), (-3, 2), (0, 4), (2, 4), (0, 4), (0, 8), (None, 8),
]

# Vexilla Regis — 'The banners of the King advance' — processional battle hymn, mode 1
# GregoBase id 19728; book: Antiphonale Romanum, 1912, p. sup16; mode 1; 56 events, 9.2 bars
VEXILLA_REGIS = [
    (3, 4), (5, 2), (7, 2), (8, 4), (7, 1), (5, 1), (3, 2), (5, 4), (5, 1),
    (7, 1), (5, 2), (3, 4), (2, 2), (0, 2), (None, 4), (5, 4), (5, 4),
    (7, 4), (3, 2), (0, 2), (3, 4), (2, 2), (3, 2), (0, 4), (-2, 2),
    (0, 2), (None, 4), (0, 4), (0, 4), (3, 4), (0, 2), (-2, 2), (3, 4),
    (3, 1), (5, 1), (7, 2), (5, 4), (5, 2), (3, 2), (None, 4), (3, 4),
    (3, 1), (7, 1), (8, 1), (7, 1), (5, 0), (7, 4), (3, 2), (0, 2), (3, 4),
    (2, 2), (3, 2), (0, 4), (-2, 2), (0, 2), (None, 8),
]

# Veni Creator Spiritus — Invocation of the spirit — boot-up litany register, mode 8
# GregoBase id 8686; book: ?; mode 8; 47 events, 10.2 bars
VENI_CREATOR = [
    (0, 4), (2, 4), (0, 2), (-2, 2), (0, 4), (2, 2), (0, 2), (5, 4),
    (7, 4), (5, 8), (None, 4), (5, 4), (0, 4), (2, 4), (5, 4), (7, 2),
    (5, 2), (7, 4), (9, 4), (7, 8), (None, 4), (5, 4), (7, 2), (9, 2),
    (5, 2), (4, 2), (2, 2), (0, 2), (5, 2), (7, 2), (0, 4), (2, 4), (5, 8),
    (None, 4), (4, 2), (5, 2), (2, 4), (0, 2), (-2, 2), (2, 4), (2, 1),
    (4, 1), (2, 2), (0, 4), (-2, 4), (0, 8), (None, 8),
]

# Pange lingua... Corporis — Aquinas corpus hymn, mode 3 (Phrygian family)
# GregoBase id 8670; book: Antiphonale Monasticum, 1934, p. 547; mode ?; 56 events, 13.5 bars
PANGE_LINGUA = [
    (0, 4), (0, 4), (0, 4), (-2, 4), (3, 4), (3, 4), (5, 2), (7, 2),
    (7, 8), (7, 1), (8, 1), (10, 2), (8, 4), (8, 4), (7, 4), (5, 4),
    (8, 4), (7, 1), (5, 1), (3, 4), (None, 4), (3, 4), (5, 4), (8, 4),
    (7, 4), (5, 4), (3, 4), (5, 4), (5, 8), (5, 4), (7, 4), (3, 4), (2, 4),
    (0, 4), (5, 4), (5, 2), (-2, 4), (None, 4), (-2, 4), (0, 4), (3, 4),
    (0, 4), (3, 4), (5, 4), (5, 4), (3, 8), (5, 4), (7, 4), (3, 4), (5, 2),
    (3, 2), (0, 4), (-2, 2), (0, 2), (0, 8), (None, 8),
]

# Viderunt omnes — Gradual, mode 5 — the Perotin organum tenor; stretch for machine-organum treatment
# GregoBase id 1745; book: Graduale Romanum, 1908, p. 31; mode 5; 118 events, 8.0 bars
VIDERUNT_OMNES = [
    (0, 4), (0, 4), (4, 2), (7, 2), (7, 1), (9, 1), (7, 1), (4, 1), (7, 1),
    (7, 1), (7, 1), (11, 1), (9, 1), (7, -5), (7, 4), (7, 2), (9, 2),
    (7, 2), (4, 2), (7, 1), (4, 1), (7, 1), (7, 1), (4, 0), (4, 1), (7, 1),
    (7, 1), (4, 1), (7, 1), (6, 1), (7, 1), (4, -3), (None, 4), (4, 4),
    (7, 2), (6, 2), (7, 1), (6, 1), (9, 2), (9, 1), (7, 1), (6, 1), (7, 1),
    (4, 0), (4, 1), (2, 1), (4, 1), (6, 1), (7, 1), (9, 1), (7, -2),
    (7, 1), (6, 1), (9, 1), (11, 1), (12, 0), (9, 2), (7, 2), (7, 1),
    (6, 1), (7, 1), (4, 1), (None, 4), (4, 4), (7, 2), (6, 2), (7, 4),
    (7, 1), (7, 1), (7, 2), (4, 1), (7, 1), (2, 1), (2, 1), (0, 0), (0, 1),
    (2, 1), (4, 1), (7, 1), (4, 1), (0, -1), (None, 4), (0, 1), (4, 1),
    (6, 1), (9, 1), (11, 1), (7, -1), (7, 1), (4, 1), (5, 1), (7, 1),
    (5, 1), (2, 1), (4, 1), (5, 1), (4, 1), (2, -5), (0, 1), (2, 1),
    (0, 2), (0, 1), (4, 1), (7, 1), (0, 1), (4, 1), (7, 1), (7, 1), (6, 1),
    (2, 1), (0, 1), (4, 1), (2, 1), (4, 1), (2, 1), (2, 1), (0, -11),
    (None, 8),
]

# L'homme armé (15th c.) — en.wikipedia score
# 60 events, 23.2 bars
LHOMME_ARME = [
    (0, 8), (0, 4), (5, 8), (5, 4), (3, 4), (2, 8), (0, 12), (7, 4),
    (7, 4), (0, 4), (None, 4), (7, 4), (7, 4), (7, 4), (5, 8), (3, 4),
    (2, 8), (0, 12), (7, 4), (7, 4), (7, 4), (0, 12), (12, 8), (12, 4),
    (10, 8), (10, 4), (12, 8), (12, 4), (7, 12), (12, 8), (12, 4), (10, 8),
    (10, 4), (12, 8), (12, 4), (7, 8), (12, 4), (14, 8), (12, 4), (10, 4),
    (9, 8), (7, 12), (0, 8), (0, 4), (5, 8), (5, 4), (3, 4), (2, 8),
    (0, 12), (7, 4), (7, 4), (0, 4), (None, 4), (7, 4), (7, 4), (7, 4),
    (5, 8), (3, 4), (2, 8), (0, 12),
]

# Old 100th, 1551 Genevan rhythm — en.wikipedia score 0
# 32 events, 13.0 bars
OLD_100TH = [
    (0, 8), (0, 4), (-1, 4), (-3, 4), (-5, 4), (0, 8), (2, 8), (4, 8),
    (4, 8), (4, 4), (4, 4), (2, 4), (0, 4), (5, 8), (4, 8), (2, 8), (0, 8),
    (2, 4), (4, 4), (2, 4), (0, 4), (-3, 8), (-1, 8), (0, 8), (7, 8),
    (4, 8), (0, 8), (2, 4), (5, 4), (4, 8), (2, 8), (0, 16),
]

# Christ lag in Todesbanden, Bach BWV 4 soprano — en.wikipedia
# 71 events, 16.2 bars
CHRIST_LAG = [
    (7, 4), (6, 4), (7, 2), (9, 2), (10, 4), (12, 4), (10, 4), (9, 4),
    (7, 4), (7, 4), (3, 4), (5, 4), (7, 4), (5, 2), (3, 2), (2, 2), (0, 2),
    (2, 4), (0, 4), (-5, 4), (-6, 4), (-5, 2), (-3, 2), (-2, 4), (0, 4),
    (-2, 4), (-3, 4), (-5, 4), (-5, 4), (-9, 4), (-7, 4), (-5, 4), (-7, 2),
    (-9, 2), (-10, 2), (-12, 2), (-10, 4), (-12, 4), (None, 4), (0, 2),
    (2, 2), (3, 4), (5, 4), (0, 2), (2, 2), (3, 4), (5, 4), (7, 4), (7, 4),
    (12, 4), (11, 4), (12, 4), (14, 2), (12, 2), (10, 4), (9, 4), (7, 4),
    (9, 4), (10, 4), (7, 2), (9, 2), (10, 4), (5, 4), (3, 4), (2, 4),
    (0, 8), (7, 4), (5, 4), (3, 8), (2, 8), (0, 8),
]

# Ein feste Burg, Bach chorale 20 soprano — kern2abc
# 52 events, 12.0 bars
EIN_FESTE_BURG = [
    (12, 4), (12, 4), (12, 4), (7, 2), (9, 2), (11, 4), (12, 2), (11, 2),
    (9, 4), (7, 4), (12, 4), (11, 4), (9, 4), (7, 4), (9, 4), (5, 2),
    (4, 2), (2, 4), (0, 4), (0, 4), (7, 4), (9, 4), (7, 4), (6, 4), (7, 8),
    (0, 4), (7, 4), (9, 4), (11, 4), (12, 4), (11, 4), (12, 2), (11, 2),
    (9, 4), (7, 4), (9, 4), (9, 4), (7, 4), (9, 2), (7, 2), (5, 4), (4, 4),
    (12, 4), (11, 4), (9, 4), (7, 4), (9, 2), (7, 2), (5, 4), (4, 4),
    (2, 8), (0, 4),
]

# Idumea, Sacred Harp (Denson 1971) TENOR = melody
# 53 events, 30.5 bars
IDUMEA = [
    (0, 8), (0, 16), (-2, 4), (0, 4), (3, 16), (5, 4), (3, 4), (0, 16),
    (7, 8), (10, 16), (7, 4), (5, 4), (3, 16), (5, 8), (7, 16), (7, 8),
    (10, 16), (7, 4), (5, 4), (7, 16), (5, 4), (3, 4), (0, 16), (-2, 4),
    (-5, 4), (-2, 16), (-2, 8), (0, 16), (-2, 4), (0, 4), (3, 16), (5, 4),
    (3, 4), (0, 16), (7, 8), (10, 16), (7, 4), (5, 4), (7, 16), (5, 4),
    (3, 4), (0, 16), (-2, 4), (-5, 4), (-2, 16), (-2, 8), (0, 16), (-2, 4),
    (0, 4), (3, 16), (5, 4), (3, 4), (0, 24),
]

# Ad mortem festinamus, Llibre Vermell — alijc abc
# 86 events, 15.0 bars
AD_MORTEM = [
    (5, 4), (7, 2), (9, 4), (5, 2), (7, 4), (7, 2), (0, 4), (2, 2), (5, 4),
    (2, 2), (4, 4), (0, 2), (2, 4), (4, 1), (2, 1), (0, 4), (2, 2), (5, 4),
    (2, 2), (4, 4), (0, 2), (2, 4), (4, 1), (2, 1), (0, 6), (12, 4),
    (9, 2), (12, 4), (16, 1), (14, 1), (12, 1), (11, 1), (9, 4), (7, 4),
    (5, 2), (9, 4), (5, 2), (7, 4), (4, 2), (5, 4), (9, 1), (7, 1), (5, 6),
    (12, 4), (9, 2), (12, 4), (16, 1), (14, 1), (12, 1), (11, 1), (9, 4),
    (7, 4), (5, 2), (9, 4), (5, 2), (7, 4), (4, 2), (5, 4), (9, 1), (7, 1),
    (5, 6), (5, 4), (7, 2), (9, 4), (5, 2), (7, 4), (7, 2), (0, 4), (2, 2),
    (5, 4), (2, 2), (4, 4), (0, 2), (2, 4), (4, 1), (2, 1), (0, 4), (2, 2),
    (5, 4), (2, 2), (4, 4), (0, 2), (2, 4), (4, 1), (2, 1), (0, 6),
]

CHANT_MENU = {
    "media_vita": MEDIA_VITA,
    "libera_me": LIBERA_ME,
    "requiem_introit": REQUIEM_INTROIT,
    "vexilla_regis": VEXILLA_REGIS,
    "veni_creator": VENI_CREATOR,
    "pange_lingua": PANGE_LINGUA,
    "viderunt_omnes": VIDERUNT_OMNES,
}

TUNE_MENU = {
    "lhomme_arme": LHOMME_ARME,
    "old_100th": OLD_100TH,
    "christ_lag": CHRIST_LAG,
    "ein_feste_burg": EIN_FESTE_BURG,
    "idumea": IDUMEA,
    "ad_mortem": AD_MORTEM,
}

MELODY_MENU = {**CHANT_MENU, **TUNE_MENU}
```

### Caveats

- Defect: the chant entries contain zero and negative durations, for example `(2, 0)` and `(0, -11)`. The formula that divides a group in `gabc.py` causes them, as described in that unit. The tunes do not have this defect because their parser drops durations at or below 0. A reader that advances time through the chant entries will drift, and the bar counts in the comments include the invalid values.

- `VENI_CREATOR` has `?` for its book, and `PANGE_LINGUA` has `?` for its mode. Their source headers do not supply those fields.

## `build_chant_data` — the menu generator (`tools/musicgen/build_chant_data.py`)

### Goal

This tool makes `chants_data.py` from downloaded `GregoBase` GABC files and the parsed tune menu. The GABC sources stay in the temporary work directory. Only the extracted public-domain event data and its source record are in the repository.

### Invariants

- Each entry in the repository includes a source record.

- Each excerpt ends on a rest. The cut point is the first long rest at or after 8 bars, with a hard cap at 16 bars. If the cap falls in the middle of a phrase, the tool appends a rest.

### Verification

The output is `chants_data.py` in the repository. Fixture tests in `tunes.py` check its tune tables.

### Implementation

`MENU` maps 7 `GregoBase` IDs to names and one-line reasons that become comments in the repository. `excerpt` accumulates events and stops at the first rest of a minimum of 8 steps after the total reaches 8 bars. `main` writes the module docstring, chant blocks, tune blocks from `tunes.load_menu()`, and 3 menu dictionaries.

### Caveats

- The GABC path is hard-coded to a temporary work directory with a session ID. The tool can make the file again only in that session. Thus, the output in the repository keeps the extracted data.

- The tool does not filter zero and negative durations returned by `gabc.parse`. The excerpt step counter includes them, slightly distorting the 8- and 16-bar limits.

## `gabc` — the `GABC` parser (`tools/musicgen/gabc.py`)

### Goal

This module parses GABC chant notation into event lists with the strophe convention. Tests check its pitch rules against the `Dies Irae` fixture transcribed by a person. Pitch characters show staff positions, and the clef determines the position of DO. Output pitches are semitone offsets from the piece's last note.

### Invariants

- The output follows `DIES_IRAE_STROPHE`: semitone offsets from the last note and durations in sixteenth-note steps.

- The parser merges consecutive rests.

### Verification

The test in the module parses the downloaded `GregoBase` 1198 file and compares its sung pitches with the transcription checked by a person. It prints `fixture pitches match: True` when they agree. The fixture checks pitches only, not durations.

### Implementation

The clef `cN` places DO at position `2N + 1`, while `fN` places FA there. The scale-degree table is `do 0, re 2, mi 4, fa 5, sol 7, la 9, ti 11`. An `x` after a pitch flattens it, and `y` restores its natural pitch. A syllable lasts 4 steps.

In a group of `n` notes, each note receives `max(1, 4 // n)` steps. The last note receives the remaining steps plus 2 when dotted. Breath marks `;` and `::` become rests of 4 and 8 steps. The quarter-bar mark `,` contributes 0 steps.

### Caveats

- Defect: for a group of 5 or more notes, the duration formula gives the last note `4 - (n - 1)` steps. This value is 0 for 5 notes and negative for larger groups. Long melismas frequently cause the defect, and the invalid durations stay in `chants_data.py` in the repository. The fixture that checks only pitch cannot detect them.

- The note pattern accepts the sharp marker `#`, but no code path applies it. The parser ignores sharps without an error. Thus, the applicable notes render at their natural pitch.

- Flat state lasts only in one parenthesized group. In GABC, flats continue to the end of a word or line. Thus, subsequent syllables in the same word can lose the accidental.

- The fixture path is hard-coded to a temporary work directory with a session ID.

## `tunes` — historical tune parsers (`tools/musicgen/tunes.py`)

### Goal

This module parses 2 notation subsets: the LilyPond `\relative` notation used in Wikipedia score blocks and a subset of ABC notation. It changes 6 historical tunes to the strophe event format. Downloaded sources stay in the temporary work directory, and the docstring records the source of each tune.

### Invariants

- Output durations are positive integers. The last stage drops durations at or below 0.

- Melody pitches are relative to the last note.

### Verification

The test in the module contains incipit targets for all 6 tunes that a person checked, with note names in comments. It compares the opening sung pitches of each tune and then prints `ALL FIXTURES PASS`.

### Implementation

The LilyPond path removes comments and lyrics, keeps only the first voice of each `<< >>` block, and expands `\repeat unfold N { ... }`. It keeps `\relative` anchors as markers that set the state again. A scale-degree distance more than 3 changes the octave, after which apostrophe and comma modifiers apply. The duration state changes denominators to sixteenth-note steps and applies dotted-note factors of 1.5 and 1.75. Ties merge adjacent equal pitches.

The ABC path reads key, unit length, and voice from the header. It expands one volta pattern and applies key-signature and measure accidentals. For `IDUMEA`, it selects the tenor melody in voice `V:3`. `load_menu` returns all 6 tunes with provenance lines.

### Caveats

- No code reads the compiled `_LY_NOTE` pattern. The live parser duplicates that pattern inline.

- The parser does not expand a repeat without a mark and without a volta. Thus, the section plays one time. It expands only the first volta pattern.

- A chord in `[]` keeps its first note even though the docstring states that it keeps the top note. The fixtures continue to succeed. Thus, their parsed voices contain no chord for which this difference matters.

- Grace-note groups stay in the input, and the parser can treat them as full notes.

- The source path is hard-coded to a temporary work directory with a session ID.

## `riffs` — delivery transforms (`tools/musicgen/riffs.py`)

### Goal

This module turns a historical melody into a performance in the album's idiom. A director instruction dated 2026-07-14 treats the chant as source material, not the finished performance. Playback without changes sounds similar to MIDI renditions of historical melodies. `diminish` doubles the speed, and `riff_16` builds a continuous sixteenth-note motor from palm-muted chugs and open accents. `lead_phrase` adds anticipations and holds the highest note.

### Invariants

- The module imports only `annotations` from `__future__`. It has no runtime
  dependencies.

- Each sixteenth-note slot in `riff_16` sounds. This makes a continuous motor, not a line with large spaces.

### Verification

The bank builders and listening-check tools use these transformations and supply material for director review. The module has no test.

### Implementation

The album's push patterns are `ACCENTS_A (0,3,6,10,12)`, `ACCENTS_B (0,4,7,10,14)`, and `ACCENTS_C (0,2,6,8,11,14)`. With chord roots from `harmony.roots_16`, `riff_16` plays the active root openly in accent slots and as a muted chug in all remaining slots. The wall carries harmonic rhythm while lead voices retain the melody. Without chord roots, accents cycle through melody pitches. Output events are `(semitone, steps, art)`, where `art` is `open` or `mute`. `lead_phrase` halves durations, anticipates every third note by one sixteenth note, and doubles the duration of the highest note.

### Caveats

- `lead_phrase` drops all rests without an error. This shortens the output and removes breath time. Its docstring does not state this.

- Most transformations return 2-field events, while `riff_16` returns 3-field events. The distinction is documented but easy to miss.

## `harmony` — progressions as forces (`tools/musicgen/harmony.py`)

### Goal

This data module defines the harmonic identity ratified on 2026-07-14. Progressions carry meaning, and chords apply forces relative to home. Harmonic rhythm shows the tempo of combat, and cadences show kills. Mode identifies good and evil as different: faith uses the Dorian and Phrygian family, while the tritone shows the `Adversary`. Each chord contains only a root, fifth, and octave, with no third.

### Invariants

- Each chord progression bar totals 4 beats. The tables obey this invariant, but no code enforces it.

- The module imports only `annotations` from `__future__`. It has no runtime
  dependencies.

### Verification

Bank builders and listening-check tools use these tables. Each entry includes a comment that explains its narrative and musical function for director review.

### Implementation

`PROGRESSIONS` contains 6 entries that specify chord roots and beat counts for each bar. `vigil` is a home pedal that shows prayer. `swagger` moves from `i` to `bVII` for contempt. `pressure` pushes `bII` against home with a drop each bar for the stalwart verse.

`ratchet` follows `i`, `bVI`, `bVII`, `i` and returns home. `grind` descends as the walls close. `lunge` visits the tritone for one beat before it drops.

`recast(events, target)` moves a melody between parallel modes by scale degree and adapts major-mode tunes that clash with the minor modal register. `bar_cells` repeats a named chord progression to the requested bar count, and `roots_16` expands those cells to one root for each sixteenth-note slot.

The chord progression cells are:

```python
{
    "vigil":    [[(0, 4)]],
    "swagger":  [[(0, 2), (-2, 2)], [(0, 4)]],
    "pressure": [[(0, 4)], [(1, 2), (0, 2)], [(0, 4)],
                 [(1, 1), (1, 1), (0, 2)]],
    "ratchet":  [[(0, 4)], [(-4, 4)], [(-2, 4)], [(0, 4)]],
    "grind":    [[(0, 4)], [(3, 4)], [(1, 4)], [(0, 4)]],
    "lunge":    [[(0, 3), (6, 1)], [(0, 4)]],
}
POWER = (0, 7, 12)
MAJOR = (0, 2, 4, 5, 7, 9, 11)
TARGETS = {
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
}
```

### Caveats

- `roots_16` assumes 4 beats for each bar and does not check the input.

## `parts` — shared part renderers (`tools/musicgen/parts.py`)

### Goal

This module contains parameterized part renderers moved from the voices that tests checked in the first hymn build. The parts are riff, kick, hats, bass, wall, chant, organum, lead, a bell hit, a Shepard riser, and a mechanical hum bed. Each renderer receives its pattern, kit, and patch as data.

### Invariants

- Renderers contain no section-specific values. All patterns are parameters.

- `place` does not write out of its buffer.

### Verification

The docstring records the move from the voices that tests checked, and `bell_hit` supplies the audited bank builds. The module has no test.

### Implementation

`render_riff` puts chug notes with random timing changes of 6 ms and random velocity changes of 5 percent. It then runs the bus through `tempo_punch`. `render_kick` puts the supplied kick pattern with random velocity changes and applies a 34 Hz high-pass filter to the bus. `render_hats` makes a metallic hi-hat from 4 square waves with ring modulation.

`render_bass` plays root eighth notes through the selected Surge patch. For each half-bar, `render_wall` sustains root, fifth, and octave chugs and pumps the result. It applies a high-pass filter and can add a tiled `buzzsaw_wall` layer. `render_chant` uses `machine_voice`.

Its optional phrase gain follows each note's height between the phrase minimum and highest point. `render_organum` adds chant voices a fifth below and an octave above in the Pérotin style. `render_lead` sends the event phrase to the selected `Surge` patch and applies a 150 Hz high-pass filter.

`bell_hit` loads the temporary bell sample and lowers it by 1.7 semitones with `resample_poly`. `shepard_riser` sums 6 octave layers under a raised-cosine window. `hum_bed` sends `machine_voice` through a feedback loop. The loop period is tuned to `D2`, and the howl is tuned to `D3`.

### Caveats

- The docstring points to `album_build.py`, which is absent from the repository.

- Only `bell_hit` has importers. The other renderers, the riser, and the hum bed have no callers. They were written for the missing `album_build.py`.

- `bell_hit` reads the sample file and imports `scipy` on each call without caching. The 1.7-semitone shift is unexplained.

- The module uses `gc._tube`, an internal symbol of `gordon_chain`.

## `voices` — the recorded instruments (`tools/musicgen/voices.py`)

### Goal

This module contains the second-generation voices built from the audited toolchain after the director rejected the first-generation stems as random General MIDI clips. The guitar uses sliced recorded hits passed through an amplifier chain that ends in convolution with a recorded 4-by-12 speaker-cabinet impulse response. The machine choir uses WORLD-vocoder resynthesis of factory-recorded audio at a forced, constant pitch. A synthesized dark plate provides reverberation only for the holy lane. GPL-licensed libraries render assets offline and do not ship with the game.

### Invariants

- The chug kit must retain at least 3 tuned slices or raise `RuntimeError`.

- Each kit slice must fall within 3.5 semitones of the D pitch class or be discarded.

- The plate impulse is deterministic under a fixed seed.

- Each expensive analysis is cached and runs once per process.

### Verification

The docstring records the audit measurements. WORLD resynthesis with forced pitch and reduced aperiodicity produces 25.6 dB of comb contrast. The result is 2.8 dB when only pitch is forced. Comments cite probe measurements for the palm-muting and repitching choices.

### Implementation

`_chug_kit` slices the temporary riff recording at detected onsets, measures each slice's pitch with `parselmouth`, and folds its offset to the nearest octave. It repitches by resampling. A comment records that phase-vocoder processing smears the pick transient into a square-wave synthesizer sound.

`_amp_chain` uses `pedalboard` for a 70 Hz high-pass filter, compression, 18 dB of distortion, a low shelf, and speaker-cabinet convolution. `chug_note` selects and repitches a slice, then applies a palm mute with a mild spectral tilt and a hard duration cut. `machine_voice` resynthesizes with pitch forced to the D3 pitch class and aperiodicity reduced to 5 percent. `lufs` and `to_lufs` measure and normalize loudness with `pyloudnorm`.

### Caveats

- Defect: the kit applies its repitch ratio in the wrong direction. It calculates `ratio = 2^(-off/12)` and orders the resampling factors so that pitch is multiplied by this ratio, although the target requires `2^(+off/12)`. A slice near D lands equally far beyond D on the opposite side and doubles its distance from the target. The 3.5-semitone admission gate limits the error. Contrary to the docstring, the code does not tune each slice to D2. `parts.bell_hit` supplies its resampling factors in the opposite order.

- `chug_note` pitch-shifts each note with the `librosa` phase vocoder. This directly contradicts the preceding comment, which cites phase-vocoder smearing as the reason to use resampling.

- Sample and impulse-response paths are hard-coded to temporary work directories with a session ID.

- `machine_voice` selects its source window with `hash()` of a number pair, which is stable in CPython only as an implementation fact.

## `m3_verse` — the M3 assembled verse (`tools/musicgen/m3_verse.py`)

### Goal

This tool renders one assembled verse in the style of album track 1. It opens with a wide, deep, fully wet choir and drone. The band enters abruptly as the mix contracts around half-time drums and a palm-muted wall, while the chant continues above it. Only instruments accepted by the director are used. The docstring records 2 open issues: there is currently no synthesizer bass, and the wall occupies the low-mid frequencies.

### Invariants

- Only accepted instruments render: the M1 monk, M2 TR-909 kit, probe-approved chug kit, and Dragonfly hall.

- Random generators use seeds 3, 11, and 22. This makes the render reproducible.

### Verification

The director reviews the output `out/m3_verse.wav` by ear. The tool prints its duration and band-entry time, while `vocal_check` verifies the rendered chant against the strophe.

### Implementation

The piece uses a 110 BPM, 26-bar grid, with the band entering at bar 8. The monk follows its own grid of quarter notes at 72 BPM and uses closed vowels at phrase endings. The hall wet-level scale changes from 1.6 before the entry to 0.55 afterward. The wall consists of 2 performances with seeds 11 and 22, panned hard left and right and ducked beneath the drums. The mix also ducks the bed beneath the drums, sums a center bus, and soft-clips. It normalizes the mono mean to -15 LUFS and caps the peak at -1 dBFS.

### Caveats

- The `Dragonfly` `plugin` finds with `next(rglob(...))` at import time. Without the `scratchpad`, the import raises `StopIteration`.

- The bell tolls at bars 3.2 and 6.6 were placed by ear rather than derived from strophe rests.

- `hall()` loads the `plugin` from disk on each call.

- The LUFS measurement folds stereo to mono, reducing the contribution of the wide wall through channel cancellation.

## `gordon_chain` — the `Gordon` signal chains (`tools/musicgen/gordon_chain.py`)

### Goal

This module implements the Gordon method's parallel signal chains. Recorded sources pass through 4 parallel paths with cross-path ducking and a genuinely recursive nonlinear feedback loop. A tempo-tuned stage adds makeup gain and punch. The first attempt failed because it used a single linear chain that ended in one distortion call. The docstring maps each processing stage to the named hardware it models. It also records that VST hosting was tried and ruled out on this system.

### Invariants

- Each stage maps to a named hardware unit and reproduces its relevant audible effect. The mapping table is the module contract.

- Chain 1 drives the compressors on chains 2 and 3, creating cross-path routing rather than 4 equal paths.

- The feedback howl frequency is reinforced by a comb resonance at a multiple of the loop rate.

### Verification

Measurements stay in the comments. With the howl filter, the feedback loop swells by 8.9 dB over 0.4 seconds after each note. Without that filter, the change stays below 1 dB. A measured 3-hit chug test found that feedback was choked to -15.9 dBFS after each hit. It swelled in each gap, which matched the behavior in the hardware demonstration.

### Implementation

The component models include asymmetric fuzz clipping with bias and a `tanh` tube stage with an even-harmonic term. They also include envelope-keyed gated fuzz and a swept-allpass phaser. Additional models cover tape echo and reel-to-reel saturation. The tape echo has low-pass filtering and `tanh` saturation inside the feedback path. The reel-to-reel model has pre-emphasis. Spring reverb uses an impulse response with 6 descending chirps.

`feedback_loop` calculates `y[n] = tanh(drive * (input * x[n] + fb * y[n - delay]))` for each sample, with optional low-pass and howl-band-pass filters inside the loop. The `tanh` nonlinearity creates the choke and subsequent swell because it compresses the loop while the input is strong. The docstring records the frequency bands used during calibration. `doom_array` connects the 4 chains at specified gains, then applies a smile-shaped EQ and `tempo_punch`. `tempo_punch` follows the envelope for compression and applies makeup gain to the complete signal. This exposes quiet parallel tails as notes decay under a director instruction.

### Caveats

- A repository-wide rename from `room` to `polygon` corrupted prose in active docstrings. It changed `headroom` to `headpolygon` and `a real room` to `a real polygon`. The implementation stays functional because the `synth.py` reverb parameter is intentionally named `polygon_size`.

- The `drone` parameter of `organ_choir_chain` is not used.

- `feedback_loop` returns `float32`, and each other function returns `float64`.

- `argent_bass_chain` tunes its ring modulation and feedback delay to 55 Hz, an A, while the rest of the module uses the D pitch class.

- 4 functions iterate over individual samples in Python. Recursion requires this in the feedback loop, but the envelope follower and phaser could use array operations.

- The module uses `sy._biquad_coeffs`, an internal symbol.

## `tutti` — the complete `tracks` (`tools/musicgen/tutti.py`)

### Goal

This tool composes 7 complete album tracks from separate recipes. The director established their variation requirements on 2026-07-15.

Each track specifies its own value for each element axis, and each recipe has a distinct structure. No pair of tracks shares more than 2 elements. The monk always enters on a ramp, transitions use pullbacks and riser cues rather than master-bus cuts, and the drone spine continues throughout.

A lane-collection mode lets `tutti_bank` obtain stems from the same composition run.

### Invariants

- `check_uniqueness()` runs before each batch. It projects each recipe onto a 14-axis element grid and raises `AssertionError` if any pair shares more than 2 values.

- The close monk always enters on a gain ramp: `(t / 6 s)^1.5` in ordinary sections and 4 seconds long in peak sections.

- The drone spine plays in each section.

- The master soft-clips, `normalizes` to -15 `LUFS`, and caps the `peak` at -1 `dBFS`.

- The `monksig` lane contains only close-monk placement markers and contributes no audio, providing ground truth for where the voice sounds. Raw audio level is unreliable for this purpose because pads and hall tails keep bar levels high during composed rests.

### Verification

Before rendering, the tool prints `uniqueness ok (worst pair shares N elements)`. It then prints each track's title, path, and duration. Listening probes and bank checks examine the downstream output.

### Implementation

Each of the 7 recipes defines a 5-section form as `(type, bars, progression)`. It also selects 3 accent patterns, a lead slot, and presets for wall, bass, FM, choir, and flourish parts. A bell variant includes a pitch shift, while a kit specifies style, kick settings, snare, and hats. Finally, each recipe supplies 5 drone-spine patches and 5 seeds.

The complete recipe data is required for reproducible rebuilding:

```python
RECIPES = {
    "dies_irae": {
        "title": "tutti_dies_irae",
        "form": [("vigil", 8, "vigil"), ("entry", 8, "pressure"),
                 ("develop", 8, "swagger"), ("peak", 8, "ratchet"),
                 ("outro", 4, "vigil")],
        "accents": ("A", "B", "C"), "lead": "lead_rail",
        "wall": ("5years", "Supersync"), "bass": ("5years", "Heavy"),
        "fm": ("5years", "FM Bass 1"), "choir": ("5years", "Choir Pad"),
        "flour": ("5years", "Hoover"), "bell": ("authored", 0),
        "kit": {"style": "half", "kick": (25, 25, 50),
                "snare": "snare", "hats": "eighth"},
        "spine": ("Daphne Oram 2", "Faulty Connection", "Taiga",
                  "St. George", "Ether"), "seeds": (11, 22, 33, 44, 7),
    },
    "media_vita": {
        "title": "tutti_media_vita",
        "form": [("vigil", 8, "vigil"), ("ritual", 8, "pressure"),
                 ("entry", 8, "grind"), ("peak", 8, "pressure"),
                 ("vigil", 4, "vigil")],
        "accents": ("B", "A", "C"), "lead": "lead_hole",
        "wall": ("5years", "Reso Poly"), "bass": ("5years", "Sub Fall"),
        "fm": ("5years", "Nicotine"), "choir": ("5years", "Laika"),
        "flour": ("5years", "Injustice"), "bell": ("authored", -5),
        "kit": {"style": "doom", "kick": (50, 0, 75),
                "snare": "rim", "hats": "quarter"},
        "spine": ("Ether", "Machine Drone", "Lysergic", "St. George",
                  "Daphne Oram 2"), "seeds": (13, 24, 35, 46, 9),
    },
    "vexilla_regis": {
        "title": "tutti_vexilla_regis",
        "form": [("entry", 8, "ratchet"), ("develop", 8, "swagger"),
                 ("ritual", 6, "vigil"), ("peak", 8, "ratchet"),
                 ("outro", 4, "vigil")],
        "accents": ("A", "C", "A"), "lead": "lead_smg",
        "wall": ("5years", "Knowledge"), "bass": ("5years", "Galatheae"),
        "fm": ("5years", "Core Robot"), "choir": ("5years", "Monument"),
        "flour": ("5years", "Splatter"), "bell": ("tubular", 0),
        "kit": {"style": "march", "kick": (0, 50, 50),
                "snare": "snare", "hats": "sixteenth"},
        "spine": ("Taiga", "Faulty Connection", "MissingNo", "Lysergic",
                  "Ether"), "seeds": (15, 26, 37, 48, 11),
    },
    "idumea": {
        "title": "tutti_idumea",
        "form": [("develop", 8, "swagger"), ("ritual", 6, "vigil"),
                 ("peak", 8, "grind"), ("develop", 6, "swagger"),
                 ("outro", 4, "vigil")],
        "accents": ("C", "B", "C"), "lead": "lead_pistol",
        "wall": ("5years", "Tesla Coil"), "bass": ("5years", "Aqualung"),
        "fm": ("5years", "Donk"), "choir": ("5years", "Cretacic"),
        "flour": ("5years", "Headache"), "bell": ("none", 0),
        "kit": {"style": "groove", "kick": (25, 25, 25),
                "snare": "clap", "hats": "offbeat"},
        "spine": ("Faux", "Boass", "Digivice", "Machine Drone", "Taiga"),
        "seeds": (17, 28, 39, 50, 13),
    },
    "pange_lingua": {
        "title": "tutti_pange_lingua",
        "form": [("vigil", 6, "vigil"), ("rebuild", 8, "grind"),
                 ("entry", 8, "pressure"), ("peak", 8, "lunge"),
                 ("ritual", 4, "vigil")],
        "accents": ("B", "A", "C"), "lead": "lead_tau",
        "wall": ("5years", "Malfunction"), "bass": ("tngkaos", "Fat Bass"),
        "fm": ("5years", "Acid Bass 3"), "choir": ("5years", "Melloflute"),
        "flour": ("5years", "Cryogen"), "bell": ("spec_imp", 0),
        "kit": {"style": "half", "kick": (75, 50, 25),
                "snare": "snare+clap", "hats": "sparse"},
        "spine": ("Lysergic", "St. George", "Ether", "Faulty Connection",
                  "Machine Drone"), "seeds": (19, 30, 41, 52, 15),
    },
    "lhomme_arme": {
        "title": "tutti_lhomme_arme",
        "form": [("entry", 8, "ratchet"), ("peak", 8, "swagger"),
                 ("ritual", 6, "pressure"), ("peak", 8, "ratchet"),
                 ("outro", 4, "vigil")],
        "accents": ("A", "B", "A"), "lead": "lead_shotgun",
        "wall": ("5years", "Movie Intro"), "bass": ("5years", "Follin"),
        "fm": ("5years", "Supersync"), "choir": ("5years", "Museum"),
        "flour": ("5years", "Western"), "bell": ("authored", 7),
        "kit": {"style": "dbeat", "kick": (25, 75, 50),
                "snare": "snare+clap", "hats": "offbeat"},
        "spine": ("Machine Drone", "Taiga", "Boass", "Daphne Oram 2",
                  "St. George"), "seeds": (21, 32, 43, 54, 17),
    },
    "old_100th_dark": {
        "title": "tutti_old_100th_dark",
        "form": [("ritual", 8, "vigil"), ("develop", 8, "grind"),
                 ("entry", 6, "pressure"), ("peak", 8, "ratchet"),
                 ("outro", 4, "vigil")],
        "accents": ("B", "C", "B"), "lead": "lead_gland",
        "wall": ("5years", "Home Run"), "bass": ("5years", "Bamboo"),
        "fm": ("5years", "Sonar"), "choir": ("5years", "Hypercube PAD"),
        "flour": ("5years", "Gecko"), "bell": ("ride", 0),
        "kit": {"style": "groove", "kick": (50, 25, 75),
                "snare": "rim", "hats": "quarter"},
        "spine": ("St. George", "Lysergic", "Faulty Connection", "Ether",
                  "Taiga"), "seeds": (23, 34, 45, 56, 19),
    },
}
```

`sec_vigil` opens with the choir carrying the melody and the monk replying in call and response. `sec_ritual` consists of drumless choir bars. `sec_entry` adds drums, bass, and 2 performances of the riff wall panned left and right. `sec_develop` adds FM bass and the lead phrase, then pulls the lanes down half a bar before a peak. `sec_rebuild` begins with one element and adds layers progressively.

`sec_peak` opens with a riser, crash, and bell, then runs the walls at their highest level. At each calm-to-band boundary, `_boundary_tell` places 4 events in the `tells` lane. They are a pink-noise riser, a reversed crash tail, a forward crash, and a 55 Hz hit. The monk follows a 72 BPM chant grid over the band's 110 BPM clock. The drum bus processes saturation, digital distortion, and spring reverb in parallel.

### Caveats

- `sec_vigil` and `sec_outro` ignore their progression argument. The progression value in those `form` entries has no effect.

- The `bell` axis of `check_uniqueness` compares the `variant` only, not the shift. 2 specified bells with different shifts count as one element.

- A missing Crackle Impactor sample surfaces as `ValueError("spec_imp")`, which does not identify the missing sample.

- The lead lane sounds only during `develop` sections. Because `media_vita` and `lhomme_arme` contain no such section, they have no audible lead lane.

- Hat velocities can exceed 1.0 before the kit clamp.

## `tutti_bank` — `track` to chunk `bank` (`tools/musicgen/tutti_bank.py`)

### Goal

This tool turns one lane-collected composition run into the bank consumed by the chunk-queue engine. The engine advances through the complete form while music values gate individual lanes.

The tool incorporates test results from 2026-07-16 and 2026-07-17. It folds loop tails in the FL Studio style and removes DC at the final write point. It detects chant gaps from the voice lane. It also renders gated stems across the full form instead of stopping after an early successful check. It automatically ships the bank when the build finishes.

### Invariants

- Each stem passes through `_dc_kill`, a 10 Hz high-pass filter, before the tool writes it. The function raises `ValueError` if residual DC stays above `0.003`, because gain changes on a DC offset click at clip boundaries.

- The prayer stem has no run of 2 or more bars below -15 dB relative to its median level.

- For chant coverage, no pair of bars may have both the voice marker (`monksig`) and the fills below -15 dB simultaneously. The function raises `ValueError` if it finds such a pair. This check was added after a build on 2026-07-17 failed to trigger the earlier alarm.

- Each `bass_*` stem must have a low-band to mid-band power ratio of at least 3. If a retry render still misses that threshold, the tool raises `ValueError`.

- A missing `bell` sample crashes the build. The `bell` is a necessary part of the `bank`.

- `bank.json` always holds the section list. The engine loader refuses a `bank` without one.

- Each build ends with `ship_banks.main()`. On 2026-07-17, renders made after an earlier ship point used a stale product copy instead of the new stems. A final ship step in each build prevents that recurrence.

### Verification

The build-time checks provide verification. DC removal, the silent-bar assertion, chant coverage, and the band-ratio retry sequence all print results or raise errors. The per-bar voice map and fill count are also printed. `check_bank` independently verifies the product contract afterward.

### Implementation

`_fold_tail` sums the extra bar rendered after the form into bar 0. It caps the result at 1.12 times the median bar level, with one retry at a lower scale. The prayer tail instead ships separately as `prayer_tail.wav`. A copy in bar 0 creates a phantom second voice when form steering jumps back from the middle. The engine overlays the separate tail only at the true wrap from the last bar to bar 0.

`_fill_monk_gaps` detects gaps on the voice lane rather than the composite. The composite's drone spine can keep levels high while the voice rests for several bars. Landing bars below -12 dB receive a 2-bar slice of the distant monk. Runs of at least 2 bars below -15 dB receive the close monk. That slice comes from the render's most continuous sung stretch and fades out over a full bar. Before this repair, a 0.5-second exit fade cut the voice off mid-syllable.

The stalwart, contempt, drum, lead, and bass stems render across the entire form instead of album-lane copies. The engine can thus change any stem's gain at any form position. Lead-phrase count uses ceiling division because floor division left a 4-bar gap. Enemy basses use `_render_bass_in_band`, which lowers them by octaves and applies 2 160 Hz low-pass stages until the band ratio reaches 3.

### Caveats

- The module docstring states that `stalwart.wav` contains drums and transition cues. The code writes a separate drum stem and does not ship the `tells` lane, so the header is inaccurate.

- Of the 11 collected lanes, only `holy`, `spine`, and `monksig` are used. The other lanes are collected and discarded because full-form renders replace them, as the comments explain.

- The landing-bar threshold is -12 dB, while the multi-bar gap threshold is -15 dB. No comment explains the difference.

- `bed_t1` to `bed_t4` are 4 byte-equal files.

- The fills track reaches the coverage check through a module global, coupling the 2 functions.

## `generate_bank` — the version 1 `bank` generator (`tools/musicgen/generate_bank.py`)

### Goal

This tool is the first-generation bank generator. One melody produces the full dynamic stem set with Odin2 and Dexed factory presets. It uses a single loop length and 110 BPM, with a separate loudness target for each stem. The newer pipeline replaced it. It stays a shared library for the melody table, its `_dark` variants, the Dragonfly hall, and the enemy-cell table.

### Invariants

- Each loop stem is trimmed to the loop length after its tail is folded back and edge fades are applied.

- Each stem is normalized to its loudness target between -13 and -19 LUFS, with its peak capped at -1 dBFS.

- A missing factory patch raises `FileNotFoundError`, enforcing the presets-first requirement explicitly.

### Verification

The tool prints each `stem` name and duration. The checks of this generation live downstream in `check_bank`.

### Implementation

`MELODIES` merges the Dies Irae strophe with the menu. `harmony.recast` creates an `_dark` variant of each major-mode tune because its original harmonies clash with the minor modal register. Preset tables identify Odin2 and Dexed voices for the choir, organs, basses, 4 stage beds, 10 weapon leads, and 7 enemy cells. `hall` applies Dragonfly Hall reverb with a fixed parameter set scaled by a wet-level factor.

The instrument mappings and hall settings have these values:

```python
CHOIR = ("Pads", "Choir Aahs 1 [RS]")
ORGAN_HOLY = ("Organ", "Church Organ")
ORGAN_DEFIANT = ("Organ", "666-001-Organ")
BASS_DEEP = ("Bass", "DeepBass [Photonic]")
BASS_FM = ("Bass", "Growly FM Bass [XR]")
BEDS = {
    1: ("Drones", "Alone in the Subway"),
    2: ("Drones", "Creep ATMO [psylion]"),
    3: ("Drones", "S&H harsh "),
    4: ("Drones", "The Sound of Agony [psylion]"),
}
WEAPON_LEADS = {
    "knife": ("odin", ("Leads", "Karplus Lead"), 0),
    "pistol": ("dexed", 13, 0),
    "smg": ("odin", ("Leads", "Lead Squarepusher"), 0),
    "shotgun": ("odin", ("Stabs", "Lead Hit 1"), 0),
    "rail": ("odin", ("Leads", "Lead Rusty"), 0),
    "lightning": ("odin", ("Leads", "Filter LFO Lead"), 0),
    "tau": ("dexed", 16, 12),
    "hole": ("odin", ("Organ", "Phazzy Organ"), 0),
    "scrap": ("odin", ("Stabs", "Metallic (vel)"), 0),
    "gland": ("odin", ("Leads", "Glide Comb Lead"), -12),
}
ENEMY_CELLS = {
    "mite": ([(0, 12, 1), (4, 12, 1), (8, 12, 1), (12, 12, 1)], BASS_FM),
    "husk": ([(0, 0, 2), (4, 0, 2), (8, 0, 2), (12, 0, 2)], BASS_FM),
    "spitter": ([(0, 0, 2), (6, 1, 2), (10, 0, 2)], BASS_FM),
    "shrieker": ([(0, 6, 2), (8, 6, 2), (14, 7, 1)], BASS_FM),
    "brute": ([(0, 0, 8), (8, 7, 8)], BASS_DEEP),
    "warden": ([(0, -12, 16)], BASS_DEEP),
    "flicker": ([(6, 1, 1), (14, 13, 1)], BASS_FM),
}
HALL = {
    "dry_level": 80.0, "early_level": 10.0, "late_level": 20.0,
    "size_m": 40.0, "width": 80.0, "predelay_ms": 12.0,
    "diffuse": 80.0, "low_cut_hz": 4.0, "low_cross_hz": 700.0,
    "low_mult_x": 2.25, "high_cut_hz": 6250.0,
    "high_cross_hz": 4600.0, "high_mult_x": 0.30,
    "spin_hz": 2.1, "wander_ms": 17.0, "decay_s": 2.4,
    "early_send": 20.0, "modulation": 10.0,
}
```

The prayer stem mixes the monk, choir, organ, and bells placed at melody rests. The contempt stem combines a groove kit, FM bass, and stabs with ducking baked in. The stalwart stem combines the half-time kit, 2 performances of the sampled chug wall, and deep bass. The monk stays audible above all of them to preserve melody continuity.

### Caveats

- Defect: the `bank.json` of this generation holds no section list and no heading. The engine loader validates these fields and refuses such a `bank`. A version 1 `bank` loads only after `boss_stems` patches the sections in.

- The default output directory lacks an `album_` prefix, so `ship_banks` excludes a version 1 bank at its default path.

- The `Dragonfly` `plugin` finds with `next(rglob(...))` at import time. Without the `scratchpad`, the import of this module — and thus of `tutti` and the full active pipeline — raises `StopIteration`.

- `hall()` loads the `plugin` from disk on each call.

- `ORGAN_DEFIANT` and `melody_bars()` are dead in this file.

## `boss_stems` — the reserved boss layer (`tools/musicgen/boss_stems.py`)

### Goal

This tool builds 2 stems that play only above stalwart thresholds. `drums_boss` enters at 0.8 and uses denser drums because beat density is the clearest signal of increased danger. `overlay_boss` enters at 0.88 with a sub-octave root double and a quiet dread pedal. The tool also writes the stab hit and patches the section map into each `bank.json` in both `out/banks` and the product copy.

### Invariants

- All stem writes pass through the `tutti_bank` write gate and its DC check.

- The section patch checks that the `recipe` `bar` total equals the `bars` value of the active `bank.json`.

- `drums_boss` uses the same source kit, seed, and fills as the bank's `drums.wav`, so the 2 stems stay aligned.

### Verification

The tool prints the target directory and the section list for each `track`, and the write gate prints each `stem`. `check_bank` knows the 3 `stem` names.

### Implementation

`drums_boss` augments the source kit with a closed hi-hat on every other sixteenth note and a kick on each eighth note. It also adds a crash on each 4-bar downbeat. `overlay_boss` renders the sub lane with the recipe's bass voice at `26 + root`. It renders the dread pedal with the wall voice at `38 + root + 12`, one octave above the wall root. The comparative judge gave the tritone pedal a coherence score of 3 out of 10. This matched the clash heard by the director.

The octave alternative scored 10 out of 10 for coherence and 9 out of 10 for menace, so it became the shipped version. The stab combines a crash, 2 kick hits, and a snare without a bell. A bell every 4 bars sounded overly repetitive.

### Caveats

- The docstring promises “a quiet tritone dread pedal,” but the code ships the octave after the tritone was rejected, as recorded in its comment.

- The tool has no shipping step for its WAV files. New stems stay only in `out/banks`. Only the section patch reaches the product copy directly. The stale-copy window closed by `tutti_bank` thus reopens until the next shipping run.

- A directory without `bank.json` is skipped silently, leaving its WAV files without adjacent metadata.

## `bell_sting` — the recorded `bell` (`tools/musicgen/bell_sting.py`)

### Goal

Under a director instruction dated 2026-07-17, this tool renders sting and riser effects from a recorded chapel-bell sample. The source is a single, low-pitched strike of a large bell. Its license requires the sample pack to stay in the temporary work directory, so only rendered audio ships. The bell is pitched to MIDI note `38 + root`, while the boss sub lane doubles the same root one octave lower. This keeps them in key by construction.

### Invariants

- Bell output is always in key at `38 + root`, peak-normalized, and high-pass filtered at 24 Hz to remove subsonic rumble.

- The writes go through the `tutti_bank` write gate.

- The sample path is out of the repository, and only `renders` go into the `banks`.

### Verification

Judge mode provides the internal check by placing each sting variant in combat context and requesting comparative model scores. The selected amen-cadence sting ranked first in all 4 calls across 2 contexts and 2 repeated runs, as recorded in the `sting_rank` results.

### Implementation

`deep_bell` resamples the source in one operation and combines playback-rate and pitch changes. All frequency components thus scale together, and the bell retains its character. The measured source strike is near C5 at MIDI 72.22. `build_sting` offers several variants. The `bare` variant layers copies 1 and 2 octaves above the strike because a lone 73 Hz bell is inaudible beneath the combat mix.

`swell` uses the final 0.7 seconds of a reversed crash. `build_sting_halled` sends the bare bell through the track's hall at -4 dB. `build_sting_amen` contains no bell. It plays a 2-chord cadence through the track's choir voice and holy hall, so the music states amen at the kill.

The amen cadence is the selected sting. `build_riser` reverses the bell into a 2-bar rise with a 60 ms end fade. Without that fade, the reversed audio ends abruptly on the sample's attack. `build_riser_half` takes the final half-bar and fades it in to create the shorter ambush riser. `render()` writes the amen sting and both risers into each active bank.

### Caveats

- The per-melody message reports "written" after it checks only that the file exists, so it can print even when no audio was written. It also names the deep bell even though the amen cadence is shipped.

- An unknown `variant` name in `build_sting` returns 4 `bars` of silence, with no error.

- The bell path is hard-coded to a temporary work directory with a session ID. An empty temporary work directory breaks each bank build through `tutti_bank`'s fail-fast requirement.

- The bare command with no mode runs `judge`, not `render`, and thus calls the model API.

- The `rng` parameter of `build_sting_amen` is not used, and `tutti_bank` builds a generator only to give it to that function.

## `check_bank` — the `bank` contract check (`tools/musicgen/check_bank.py`)

### Goal

This tool validates a bank directory against the bank-production contract before the directory reaches the build or engine. It mirrors `tutti_bank`'s checks but reads the timing grid from `bank.json` through the engine loader. A manually authored bank at any tempo is thus checked against its own form.

Errors stop the run. Warnings identify cases requiring human listening, and none are suppressed.

### Invariants

- `bank.json` loads through `perihelion.music.load_bank_meta` — the engine loader. A loader refusal is a failure.

- Thresholds match the build. They are a band ratio of 3.0 and a quiet floor 15 dB below the median. Residual DC has a cap of 0.003 after a 10 Hz high-pass filter.

- The exit code is 0 only with zero errors.

### Verification

The tool is the verification instrument for `banks`. The observable output is the report for each `stem` and the exit code.

### Implementation

Known stem names fall into 3 groups. `prayer`, `contempt`, and `stalwart` are required. One-shots are `riser`, `riser_half`, `sting`, `stab`, and `prayer_tail`. The remaining known names cover drums, boss stems, beds, 10 leads, and 7 basses.

An unknown stem name produces a warning because the engine will slice but never play it. Missing required stems, sample rates other than 44,100 Hz, and residual DC above 0.003 are errors. A loop stem exactly one bar longer than the form produces a warning that its tail was not folded back. Any other length mismatch above 0.5 percent is an error.

A silent run of at least 2 bars is an error. In lead stems, it is a warning because accepted reference banks rest for 2 bars in every 4-bar phrase. A `bass_*` band ratio below 3 is also an error. So is a pair of prayer bars below the quiet floor.

After a successful check, the tool prints an important limitation: it inspected only the composite. Only the compose-time voice lane or human listening can confirm that the voice itself stays present.

### Caveats

- There is no loudness check, and the version 1 `banks` carried `LUFS` targets for each `stem`. A `bank` at an incorrect level is accepted.

- When both WAV and OGG versions of a stem exist, only the WAV is checked. A stale or corrupt product OGG beside a new WAV thus goes unnoticed.

- A missing command-line argument raises a bare `IndexError` without printing usage instructions.

## `ship_banks` — the ship step (`tools/musicgen/ship_banks.py`)

### Goal

This tool encodes stems from each `out/banks/album_*` directory as OGG quality 4, approximately 10:1 compression, and writes them with `bank.json` to `game/assets/music/<bank>/`. The game discovers and rotates these banks automatically without test-only flags or paths.

### Invariants

- Only `bank` directories with `bank.json` ship.

- An encoder failure stops the run because `ffmpeg` is called with `check=True`.

- A stem is re-encoded when its WAV is newer than its OGG, so only changed stems are processed. This timestamp check supports `tutti_bank`'s automatic shipping step.

### Verification

The tool prints each `bank` with its byte count and target, and a total. With no `banks` it exits with the message `no album banks in out/banks`.

### Implementation

The tool discovers bank directories by glob and creates each destination. It always copies `bank.json`. For each WAV, it skips encoding when an OGG with an equal or newer timestamp already exists. Otherwise it runs `ffmpeg -codec:a libvorbis -qscale:a 4`.

### Caveats

- There is no stale-file removal. A renamed or removed stem leaves its old OGG in the asset directory permanently, and the game continues to include it in rotation. `check_bank` cannot detect a stale OGG with a reused name because it reads the WAV.

- The reported total includes each OGG in each destination, not only files produced during the current run.

- The freshness check uses only file timestamps. A replaced WAV carrying an older timestamp is silently skipped.

## `gemini_listen` — the general listen module (`tools/musicgen/gemini_listen.py`)

### Goal

This module provides a thin general-purpose model call: the model hears one audio clip and answers a structured question supplied by the caller. It reuses the playtest judge's key loading, WAV-to-MP3 conversion, and cost logging. Unlike the comparative judge, it evaluates a single clip.

### Invariants

- A failed call never becomes a neutral or favorable result. After all retries, the function returns `{"error": ...}`.

- Each call's cost is logged to `tools/playtest/cost_log.json` under the tool tag `musicgen.gemini_listen`.

### Verification

Verification belongs to callers rather than this module. `analyze_blocks`, for example, prints each block result, error counts, and total cost.

### Implementation

`tell(wav, prompt, max_s=32, attempts=3)` converts a bounded portion of the clip to mono MP3. It posts the audio to OpenRouter's chat endpoint with the fast model at temperature 0.2. It logs the cost and parses the JSON response, even inside a Markdown code fence. On failure, it prints the error and retries. It waits 8 seconds before the first retry and 16 seconds before the second.

### Caveats

- The cost logs before the parse. A parse failure then counts the cost again on each `retry`.

## `judge_track` — the grounded `track` `judge` (`tools/musicgen/judge_track.py`)

### Goal

This tool scores a complete track against reference anchors, as required by the director on 2026-07-15. Each scoring run evaluates 3 clips in one request. A is an album track and serves as the positive anchor. B is a previously rejected render and serves as the negative anchor. C is the candidate.

A scoring run is discarded when the judge fails to distinguish the anchors, so it never contributes to the aggregate. The module also exports `_ask_multi` and `_stereo_mp3`. Nearly 10 adjacent tools import this shared multi-clip request path.

### Invariants

- A scoring run counts only when `score_a - score_b >= 3` — the anchor separation gate.

- Invalid scoring runs are discarded rather than included in the median.

- Clips are converted to stereo MP3 because mono conversion obscures the double-tracked wall.

- When given labels, `_ask_multi` inserts a text marker immediately before each audio block. Its docstring records a 2026-07-17 incident with unlabeled clips from the same passage. Those clips reduced the A/B/C mapping to chance. 2 blind-comparison rounds assigned the pair in opposite orders.

### Verification

The anchor separation is the internal control of each scoring run. The output holds the raw anchor `scores`, in sets of 3, and the discard count.

### Implementation

The brief asks for church music made by posthuman industrial machines that genuinely believe. It also requires meaningful combat symbolism in a retro-futuristic cosmic-horror game.

The prompt requests 1-to-10 scores for all 3 clips. It also requests concrete qualities that C lacks but A possesses and one sentence about what C should preserve. `judge(wav, n=3)` sends `n` requests to the pro model with a 420-second timeout. It then reports medians and a normalized score of `(c - b) / max(1, a - b)`.

### Caveats

- Defect: `judge()` calls `_ask_multi` without labels, although the prompt refers to tracks A, B, and C. This is the exact unsafe case described in `_ask_multi`'s docstring. Large differences among the 3 clips reduce but do not remove the risk.

- Anchor paths are hard-coded to temporary work directories with a session ID. In a new session they are invalid, and the judge fails during MP3 conversion.

- `_ask_multi` `retries` with no wait between tries.

- A parsed `reply` without `score_a` raises in the scoring loop and stops all scoring requests.

## `judge_video` — the video sync audit (`tools/musicgen/judge_video.py`)

### Goal

This tool sends a full gameplay video to the pro model and requests a timestamped audit of whether the music follows combat.

### Invariants

- The code provides no validity gate: it makes one call with no retry or control.

### Verification

The output timeline contains timestamps that a person can compare with the video. There is no internal check.

### Implementation

The tool reads the video, base64-encodes it into a `video_url` block, and posts it to the pro model with a 600-second timeout. The prompt describes the dynamic-music design and requests JSON with a timeline, synchronization score, music score, list of out-of-sync moments, and verdict. The call is logged under `musicgen.judge_video`.

### Caveats

- A network or parse failure raises a raw traceback. The adjacent tools return error records.

- The video occupies memory twice: once as raw bytes and once as base64 text.

## `pro_judge` — the fixture-gated `judge` (`tools/musicgen/pro_judge.py`)

### Goal

This tool evaluates assembled works with the pro model, following the director's rule that the fast model is reserved for solo instruments. No candidate score counts until a fixture run accepts a known-good album block and rejects the known-bad, condemned version 3 stem.

### Invariants

- The `score` path refuses with exit code 2 unless `analysis/pro_judge_fixtures.json` is present with `pass: true`.

- The gate accepts only with the good median at or above 0.6 and the bad median at or below 0.3.

- Fixture mode exits 0 when its gate accepts and 1 when the gate rejects.
  A `score` request exits 2 on fixture-record refusal. After that refusal check,
  the `score` path exits 0 even when all model calls fail and `judge` returns an
  error record.

### Verification

The `--fixtures` mode is the known-response check. Its committed successful record contains medians of 0.775 for the good fixture and 0.225 for the bad fixture.

### Implementation

The prompt discloses measurement limitations to the model: mono audio, underrepresented sub-bass, unreliable inferred timestamps, and an unknown source. It requests 3 independent assessments covering brief-independent musicality, production quality, and brief execution. Each response includes `works_as_music`, `p_first_draft_shippable`, `melody_followable`, `brief_execution`, `originality`, `three_strengths`, `three_problems`, and `verdict_sentence`. `judge` runs `n` calls, preserves their raw responses, and aggregates medians, problem lists, and verdicts.

### Caveats

- The gate record never expires because there is no date or model check. The fixture audio can also be removed without invalidating the record.

- Fixture paths and the work directory are tied to a temporary work directory from an expired session. `mkdtemp(dir=S)` currently fails there.

- This tool converts clips to mono, unlike `judge_track`'s deliberate stereo conversion. The prompt explicitly discloses the choice, but the 2 judges still use different representations.

- A `reply` without `p_first_draft_shippable` counts as 0.0 in the median, and not as a discard.

## `dynamic_judge` — the gameplay follow `judge` (`tools/musicgen/dynamic_judge.py`)

### Goal

This tool evaluates whether dynamic music follows gameplay before shipping. The model hears only the music channel. This prevents sound effects from revealing combat directly. The model receives a gameplay timeline derived from recorded sound-effect events. A result counts only when a static loop scores materially lower against the same timeline.

### Invariants

- The judge never receives the sound-effects channel.

- The verdict counts only when the dynamic median beats the static control median by 0.15 or more, recorded as `discriminates`.

### Verification

The static-loop control is the internal check. The result file records both medians and the discrimination result.

### Implementation

`gameplay_timeline` groups combat sound-effect events into 5-second bins and emits combat spans for bins with at least 3 events. `render_music_only` filters the event log to music events and reconstructs the mix offline with `mkvideo.build_mix`. `render_static_control` tiles the `hymn01` bank's stalwart stem to the same duration. The judge prompt asks only how accurately the music follows gameplay.

The rubric expects intensity to rise within 2 seconds after combat begins. It expects transitions to land musically. It also requires genuinely calmer material during calm stretches, not only lower volume. The output records `p_beta_shippable` medians for both renders and writes `analysis/dynamic_judge_result.json`.

### Caveats

- The docstring states that both clip orders are tested to control position bias. The code instead evaluates each clip alone in a separate request and has no order. That sentence comes from an earlier A/B comparison.

- The judge uses the fast model because the prompt evaluates only how well the system follows gameplay, not musical quality.

- Temporary work directories accumulate beside the recording and are never removed.

- The static control requires the ignored `hymn01` bank. A fresh repository copy lacks it until that bank is generated.

- The command records and prints `FAIL` when the control does not
  discriminate, but `main` returns no `status` value. A completed failure run
  thus exits 0.

## `vocal_check` — the sung sequence checker (`tools/musicgen/vocal_check.py`)

### Goal

This tool checks a rendered vocal against the written score through sequence alignment rather than fixed measurement windows. Fixed windows drifted relative to the render and caused 3 rounds of false defect investigations during M1. The tool extracts a sequence of sustained sung pitches from the audio and aligns it with the score. The Delay Lama strophe measured approximately 24 correct notes out of 27, with one merge of short groups below the detector's resolution.

### Invariants

- Accuracy uses global alignment. This prevents time drift from producing the original class of false mismatches.

- Consecutive equal written notes are merged before alignment because repeated legato pitches also merge into one detected run.

### Verification

The docstring's known result is approximately 24 of 27 notes for the strophe. Output includes the merged score, detected sung runs, and fraction of matched notes.

### Implementation

`sung_runs` tracks pitch with `parselmouth` every 10 ms between 80 and 350 Hz, then converts it to semitone offsets above D3 at 146.83 Hz. A run ends when a frame differs from the run median by more than 0.7 semitones. Runs of at least 12 frames are retained as their rounded median. `align_score` performs Needleman–Wunsch alignment with scores of +2 for a match, -1 for a mismatch, and -1 for a gap, then counts matches along the traceback.

### Caveats

- Merging can remove a correctly repeated sung note, so the check cannot verify such repetitions.

- A missing `parselmouth` or a recording with no voice gives an empty run list and accuracy 0, with no warning.

## `analyze_blocks` — the `album` close listen (`tools/musicgen/analyze_blocks.py`)

### Goal

This tool asks the model to analyze every 30-second block of the reference album with 5-second overlaps. It produces synthesis-oriented detail in one JSON file per block plus a merged data file. The album audio is not committed. Only the analysis text is retained.

### Invariants

- Error responses stay in block records instead of invented analysis.

- Per-block files make the run resumable. Completed blocks are skipped.

### Verification

The tool prints each block's intensity as soon as it reads the result. It then prints final counts of successful and failed blocks and the total cost.

### Implementation

The prompt casts the model as a game-audio composer and requests enough detail to reproduce each sound with a synthesizer. Each broad description is paired with waveform character, filter movement, attack and decay, distortion type, and register. The JSON schema includes tempo, meter, key or mode, and instruments with roles and timbres. It also includes rhythm patterns, one of 6 intensity levels, structural function, and change from the preceding block. Production notes and a summary complete the schema. `--only` reruns named blocks.

### Caveats

- Defect: `--only` writes the `merged` file from only the selected blocks. A rerun of one block erases all other blocks from `_corpus.json`. Individual block files stay, and a full run repairs the `merged` file.

- A later unfiltered run treats a saved error record as complete and does not retry it. Only `--only` retries errors.

## `build_playbook` — census to conditions (`tools/musicgen/build_playbook.py`)

### Goal

This tool summarizes per-block analyses into `playbook.json` and a human-readable `PLAYBOOK.md`. It counts recurring characteristics in reference examples and derives guidance from those counts rather than from unrelated sources.

### Invariants

- Each playbook item is either a count or text copied from block data. The tool invents no generalizations.

### Verification

The tool prints the block counts, and a person can check the committed outputs against the block data.

### Implementation

`_norm_role` classifies instrument roles by name fragments and uses the first match. `build` collects tempo values and histograms for meter, key, intensity, and structure.

For each role, it builds a palette from source timbre descriptions. It also collects each track's intensity arc and 20 specified transition records. `render_markdown` writes those sections.

### Caveats

- The `tempo` median uses the higher middle element for an even count.

- `render_markdown` receives the block data and does not use it. `import re` is not used.

## `album_census` — measured `ground truth` (`tools/musicgen/album_census.py`)

### Goal

This tool uses DSP to measure album blocks: level, crest factor, spectral centroid, band balance, onset density, articulation spread, and tempo. These values come from direct measurement rather than the model and sit beside the model's text records. The same census evaluates game renders, which must fall within the album's measured ranges. `--discriminate` collects all failures rather than stopping at the first one. The census must distinguish the album from condemned demos or its measurements are not useful.

### Invariants

- Acceptance ranges are derived only from measured album blocks.

- A demo is accepted for a measurement only when it falls within Tukey fences derived from the album quartiles.

- A missing block file reports with a clear error and does not fill in.

### Verification

`--discriminate` is the instrument's known-response check: condemned demos must accumulate measurement failures.

### Implementation

`census_one` calculates level and peak in dBFS, crest factor, and positive-only spectral flux. It also calculates power fractions across 5 bands from 20 to 16,000 Hz. It detects onsets from local-mean and percentile thresholds. It estimates tempo from flux autocorrelation between 60 and 200 BPM. It also counts low- and high-band onsets per beat.

Articulation spread is the excess of low-band onset flux above its mean. `tier_stats` computes quartiles for tiers mapped from the intensity levels.

### Caveats

- Defect: the tier map lacks the `dormant` and `release` levels permitted by the block prompt. Either value raises `KeyError`, although neither occurs in the active data.

- Defect: when the temporary work directory is unavailable, default mode replaces the committed `album_census.json` with an empty census after printing only a warning. In the same state, `--discriminate` reports success because it has no acceptance ranges to check, reversing the intended fail-fast behavior.

- The onset comment names a median, and the code calculates a mean.

- `tempo_strength` is near 1 by construction and distinguishes inputs only through negative autocorrelation lobes.

## `consult_machinery` — the consult engine (`tools/musicgen/consult_machinery.py`)

### Goal

This module consults an external model through OpenRouter with crash-safe streaming. It was copied unchanged from the `diet` repository on 2026-07-13. Its header distinguishes reusable and diet-specific portions. The reusable portion has prompt-block helpers, `stream_consult`, `stream_consult_responses`, and constants. The diet-specific portion has imports that do not exist in this repository.

### Invariants

- Each received stream line is appended to `raw.jsonl`, flushed, and synchronized to disk before further processing.

- Before an exception propagates, `meta.json` records the final state: `ok`, provider error, disconnect, or truncation. This prevents an incomplete disk record from appearing successful.

- The tool does not mistake a provider failure for continued reasoning. OpenRouter can report an upstream error inside a stream after returning HTTP 200, so the parser surfaces that event explicitly instead of an indefinite wait.

- The key comes only from the environment variables and does not print.

### Verification

Committed consult outputs demonstrate the engine end to end. For example, the soundtrack-gap consult's `meta.json` records `exit_status: ok`. A `--url` override can point the stream at a local test server.

### Implementation

Constants define the chat and responses endpoints, default model `openai/gpt-5.6-sol-pro`, high reasoning effort, and a 128,000-token output ceiling. An emphatic comment explains that the ceiling is a maximum rather than a reservation and must not be reduced to shorten a request. Reasoning effort is the control for reasoning length.

Comments record the measured campaign. Long reasoning calls on the chat endpoint failed after roughly 350 to 400 seconds with an in-stream 500 error and no content. The responses endpoint emits keepalive events throughout reasoning and survives that interval. OpenRouter does not support persistent background responses for later polling.

`stream_consult` uses the streaming chat endpoint. It writes the prompt and metadata and parses each stream line. It stores reasoning and answer text in separate files and returns 0 only for a complete stream. `stream_consult_responses` performs the equivalent operation through the responses endpoint and counts keepalive events. Reusable helpers wrap files in labeled blocks, copy the Bayescraft section verbatim from the global `CLAUDE.md`, and raise an error if it is absent.

### Caveats

- Defect: the `stream_consult` docstring states that OpenRouter selects a route when no provider is specified. In fact, each chat payload contains `{"sequence": ["openai"], "allow_fallbacks": False}`, forcing OpenAI without fallback. The responses variant correctly omits this block.

- The copied path constants point to `tools/`: the `dotenv` loads and the output root are dead artifacts here. The HTTP referer headers attribute the consults to the `diet` repository on `OpenRouter`.

- Failure behavior differs: the chat path raises on an in-stream provider error, while the responses path returns 1.

- `main`, `build_prompt`, and the example-capture code are unusable here because their imports fail. Callers reuse only the generic engine.

- When callers reuse a fixed output directory, raw and answer files append across runs while metadata describes only the most recent run.

## `consult_night` — the 2 large consults (`tools/musicgen/consult_night.py`)

### Goal

This tool runs the 2 large consultations requested by the director in sequence on 2026-07-17. One concerns improvements to the bot, and one concerns improvements to the music. Both use the `consult_machinery` engine with all potentially relevant context attached. Model responses stay advisory rather than authoritative.

### Invariants

- No key, no run.

- A nonzero engine return or raised exception counts as failure. The tool exits with an error if each candidate model fails.

### Verification

The engine's disk artifacts record each run, and the tool prints an estimated prompt-token count before it sends the request.

### Implementation

The bot prompt states its hard constraints. Fire at the closest enemy is a designer requirement, and each proposed change must include a farm comparison with at least 60 runs. The prompt also attaches the bot source, the game-feel document, and the results file.

The music prompt attaches the music specfile and the first 40,000 characters of the engine source. The truncation follows 3 provider 500 errors on the full prompt while the shorter bot prompt completed. Both prompts request the 8 highest-value concrete changes with verification methods. They use `gpt-5.6-sol-pro`. A comment records that Sol Ultra was unavailable through OpenRouter. This makes `gpt-5.6-sol-pro` the highest available Sol tier.

### Caveats

- `max_tokens=32000` violates the engine's rule against reducing the output-token ceiling.

- The mode argument is not validated. A missing argument raises `IndexError`, while any value other than the exact string `bot`, including a typo, silently runs the music consultation.

- Output directories are fixed, so repeated runs append to existing output.

## `consult_soundtrack_gap` — the round 2 consult (`tools/musicgen/consult_soundtrack_gap.py`)

### Goal

This tool asks an external model for concrete help to close the gap between “MIDI plus samples” and a shippable soundtrack. It attaches the complete record available at the time. That record includes the first-round verdict and the internal judge's misleading 0.85 score for that rejected draft. It also includes the second-round changes and the director's full recorded second-round verdict.

The request has 3 parts. It asks the model to identify root causes and rank feasible changes with an observable test for each. It also asks for an honest estimate of whether a rules-based melody generator can ever meet the quality bar.

### Invariants

- The `Bayescraft` section copies verbatim from the global `CLAUDE.md`, or the tool fails with a clear error.

- The engine writes crash-safe streaming artifacts.

### Verification

The committed artifacts in `analysis/soundtrack_gap_consult/` record the completed run.

### Implementation

The prompt assembles product context, the method section, 4 specfiles, and 4 source files in labeled blocks, followed by the request. The tool streams through the chat endpoint at high reasoning effort with `max_tokens=8000`.

### Caveats

- Defect: `max_tokens=8000` violates the engine's rule against a lower output ceiling. The recorded run ended with finish reason `length` before it reached its recommendations. This is exactly the failure warned about by the ceiling comment. It is also the reason that a part 2 tool exists.

- Missing attached source files are skipped silently, so the prompt can contain less context than specified.

- The output directory is fixed, so a subsequent run appends to the committed response.

## `consult_soundtrack_gap_part2` — the follow-up (`tools/musicgen/consult_soundtrack_gap_part2.py`)

### Goal

This tool continues the truncated first consultation, which reached its token cap before the recommendations. It sends only the prior diagnosis rather than the full original prompt and requests ranked changes plus a direct probability estimate.

### Invariants

- The tool reuses the prior diagnosis verbatim from disk.

### Verification

Committed part 2 artifacts record the result, and the tool prints the prompt length.

### Implementation

The prompt contains 2 blocks: the earlier response under `YOUR PRIOR DIAGNOSIS` and a follow-up request specifying the implementation constraints. The tool streams at medium reasoning effort with `max_tokens=4000`.

### Caveats

- `max_tokens=4000` is a third violation of the no-decrease rule, inside a tool created specifically because the same defect truncated the first consultation.

- The output directory is fixed, so subsequent runs append to its files.

## `prayer_probe` — the isolated voice `sweep` (`tools/musicgen/prayer_probe.py`)

### Goal

Under a director instruction dated 2026-07-17, this tool checks the monk channel in isolation. It checks each chunk for reported dropouts and abrupt cuts. It reconstructs only the holy lane from a recording's taps and divides the result into overlapping windows. The model then checks whether the solo voice cuts out, splices, or changes level abruptly. Output is a timestamped seam map.

### Invariants

- The tool isolates the voice by setting each lane except `holy` to zero gain. It also removes riser, sting, and stab events from the decision log. The mixer then renders only the voice lane.

- One global operation normalizes the full render to a 0.85 peak, preserving relative level changes across windows.

### Verification

Results print first as JSON lines and then as a time-sorted seam map. A summary reports the number of defects across all windows.

### Implementation

Windows are 24 seconds long with a 20-second hop and are sent in groups of 4 in each model request. The prompt allows breaths between phrases and gentle level movement. It defines 4 defects: a mid-syllable cut, an abrupt level step, a long silent stretch, or a doubled voice. A silent stretch is long when it exceeds 4 seconds. Each response lists defect times within a clip. The tool maps those times back to the full render.

### Caveats

- Reconstruction is invoked through `assert MK._mix_music_rich(...)`, so it does not run under `python -O`.

- The work directory and renders stay under `/tmp`. The tool prints their path.

## `monk_fullmix_probe` — the product `mix` `hunt` (`tools/musicgen/monk_fullmix_probe.py`)

### Goal

This tool locates defects reported by the director in the product mix during the 2026-07-17 investigation. It confirms each defect with the model before repair. The tool analyzes overlapping windows from the full mix of a product video. It does not use an isolated channel or fresh render. It asks only about audible chant-voice defects of types `CUT-OUT`, `GONE`, and `SLAM-IN`.

### Invariants

- The preferred source is the product video. Video audio is copied without processing, WAV input is read directly, and only a recording directory triggers offline reconstruction.

### Verification

The results print as `JSON` lines and a list sorted by time, with types. The `timestamps` come back for each window, to align with the `taps`.

### Implementation

Windows are 30 seconds long with a 25-second hop and are sent in groups of 4 in each request. The prompt explains that the chant may become quieter during combat. It must not disappear or return abruptly. The prompt then requests timestamped `CUT-OUT`, `GONE`, and `SLAM-IN` events for each clip. Video audio is copied through `ffmpeg` to 44,100 Hz stereo.

### Caveats

- `soundfile` is imported twice.

- Recording-directory input is globally normalized to a 0.85 peak, while video input is not normalized, so the 2 source types undergo different level processing.

## `monk_ab` — before and after, blind (`tools/musicgen/monk_ab.py`)

### Goal

This tool blindly evaluates monk-seam corrections at defect timestamps found by the sweeps. The first version is the product mix with old banks. The second reconstructs the same recording with corrected banks. Each window receives a blind A/B comparison for both the full mix and isolated voice. The tool reports selections with complete reasons, treating a bare A or B response as noise.

### Invariants

- A seeded 50/50 random choice determines the A/B order for each window, and the tool reveals the corresponding version after the response.

- The defect table is fixed at 9 timestamps from the 2026-07-17 sweeps, each accompanied by its recorded description.

### Verification

The results print for each window with the winner and the cause, and the totals write to `out/consults/monk_ab_results.json`.

### Implementation

Previous audio loads from a file. Video input is first converted with `ffmpeg`, and its sample rate is checked. The new full mix is reconstructed from taps, and `prayer_probe.isolate_holy` supplies the new solo voice. Each comparison window spans 16 seconds around a defect. The prompt asks which render handles the voice better and requests defect notes plus a reason. The solo comparison runs only when the saved previous solo exists at its recorded `/tmp` path.

### Caveats

- The prompt asks for a reason consistent with the selection, but the code does not validate that consistency. Reasons are printed for human review.

- The new full mix is not normalized, while old audio retains its recorded level. A level difference can reveal the versions to the judge.

- The previous solo path is hard-coded to one sweep's `/tmp` directory, so most machines skip the solo comparison.

## `transition_probe` — each `transition`, judged (`tools/musicgen/transition_probe.py`)

### Goal

This tool extracts each music-state transition from a recording. Types include form changes, seamless loops, boss releases, bank rotations, risers, sudden wall increases, and death halts. It sends transitions to the model in batches to determine whether they sound intentional or like splices. A blind A/B mode also compares 2 mixes of the same recording at identical transition points.

### Invariants

- The transition list comes only from the event log. Sudden wall increases are derived from the logged value curve as a stalwart change of at least 0.25 between consecutive samples.

- Each clip is normalized independently, and a seeded generator shuffles A/B order at each point.

### Verification

`list` mode prints the transition table for inspection. `probe` mode prints each score and summarizes transitions scoring 6 or lower. `ab` mode prints the winner at each point and aggregate totals.

### Implementation

Each clip spans 6 seconds before through 8 seconds after its event. `transitions` interprets `music_jump` with a `~s` suffix as a seamless loop. It interprets `music_rel` as a boss release and `music_halt` as a death. A `music_bank` event after the first second is a rotation. A riser begins when its value increases above 0.01. Same-type transitions less than 1.5 seconds apart are deduplicated.

The probe sends 4 clips in each request and asks for a 1-to-10 score plus either a description of audible artifacts or `none` for each clip.

### Caveats

- The duplicate filter retains nearby transitions of different types, although its comment states only “keep the first.”

- In A/B mode, any response other than exactly `A` or `B` is counted as a selection of the second clip.

## `transition_iter` — the `transition` `grammar` `A/B` (`tools/musicgen/transition_iter.py`)

### Goal

Under a director instruction dated 2026-07-16, this tool iterates on transition behavior. It asks whether each transition sounds musical or abruptly cut. Scripted value trajectories drive the product engine in tick-clock mode and the product offline mixer. This isolates transition behavior in the clips.

A/B mode renders each scenario twice. One render has the new behavior, and one has the hard-switch behavior built by `harden`. The judge selects the more musical render.

### Invariants

- The engine is the product `MusicSystem` with `tick_clock=True` and the product bank. Only its value function is replaced by a scripted trajectory.

- `harden` derives its simulation from the same tap stream. Farewell keys become silent, and gain snaps to 0 when it falls below 70 percent of its preceding value.

- The tool restores the value function after each scenario, including an error path.

### Verification

A/B mode prints each selection with its margin and reason, plus the new behavior's win count across 2 repeated runs. Judge mode requests per-clip scores and a `what_would_a_composer_do` field.

### Implementation

4 scenarios script 3 values per bar over 24 bars. They are battle to calm, calm to battle, boss to calm, and one-bar skirmish spikes. The spikes should not wake the full mix. `run_scenario` collects taps through a fake session and tap hook. `render_pair` mixes both the new event stream and the stream produced by `harden`, then writes 2 clips. The A/B judge evaluates the 2 scenarios that end in calm with seeded clip order.

### Caveats

- Defect: in the judge-mode prompt, clip B's label appears literally as `B={1}` because the string is not an f-string. The scenario name is absent, and the judge receives a brace expression instead.

- Scenario runs replace the same module-level value function, so parallel runs could race. The tool executes them sequentially.

## `overlay_iter` — the boss overlay `variants` (`tools/musicgen/overlay_iter.py`)

### Goal

This tool iterates on `overlay_boss` after the director reported that it clashes with the melody. It renders the peak section of the full combat mix without an overlay. It also renders 4 alternatives: sub only, sub plus fifth, sub plus tritone, and sub plus octave. One model request compares all 4 alternatives with the no-overlay reference.

### Invariants

- All 5 clips cut from the same `peak` section of the same `mix`, and only the overlay is different.

### Verification

Output JSON contains the rank order, coherence and menace scores for each clip, clash notes, and a verdict. `boss_stems` records and ships the preference for the octave over the tritone.

### Implementation

`render_variant` builds the sub lane with the recipe's bass voice at `26 + root`. Every other bar, it adds a pedal on the wall voice at `38 + root + interval`. `peak_mix` locates the recipe's peak section, loads 6 stems at fixed gains, and adds the overlay at 0.9. MP3 clips are limited to 40 seconds.

### Caveats

- The mix loads `bass_warden`, `lead_rail`, and `bed_t3` by name. A bank missing those stems is mixed without warning, while a bank without a peak section raises `TypeError`.

## `sting_iter` — the `sting` audit (`tools/musicgen/sting_iter.py`)

### Goal

Under a director instruction dated 2026-07-16, this tool audits stings both alone and in context after descriptions compared most of them to random noise. Clip A is the bare sting, B places that sting in a combat passage, and C and D place alternatives in the same passage. C uses a reversed-crash swell, while D is a low, full hit without a bell.

### Invariants

- The 3 context clips are the same `combat` section stretch with the `sting` at the same `bar`.

### Verification

The output `JSON` holds music quality `scores` for each clip, a ranking, a sentence on the bare `sting`, and a verdict.

### Implementation

The context mixes 6 stems at fixed gains over 24 bars. It places the sting at bar 10, approximately 22 seconds at 110 BPM, as stated in the prompt. `sting_swell` ramps a reversed crash into a forward crash plus the bank bell. `sting_lowhit` layers a crash, 2 kick hits, and a snare.

### Caveats

- A `bank` without `sting.wav` crashes on `len(None)`.

## `sting_rank` — release punctuation in context (`tools/musicgen/sting_rank.py`)

### Goal

This tool ranks boss-release accent variants at release points from a recording. A director goal requires the stinger to sound like part of the song, not an added effect. No accent is also a candidate. The 4 variants are none, the bare bell, and the bell through the song's hall at -4 dB. The choir's amen cadence is the fourth variant.

### Invariants

- The source mix is rendered with sting taps removed, so each variant enters over the same sting-free bed at the release tap.

- Each context uses the same window from 10 seconds before through 10 seconds after release, and each clip is normalized independently.

### Verification

Each context receives 2 judge runs, and each run prints full ranking JSON. The amen cadence won all 4 recorded calls and ships as the `tutti_bank` sting.

### Implementation

The tool reads release and bank taps from the recording, uses the first 2 releases, and finds the active bank at each. It builds 3 audible variants through `bell_sting`. The fourth candidate is silence. Each audible variant is overlaid on both channels at release time. One ranking request contains all 4 clips and is repeated twice per context.

### Caveats

- A release before the first `bank` `tap` raises `IndexError` on the `bank` lookup.

- One shared random generator serves all contexts sequentially, so variant renders differ between contexts.

## `slam_rank` — the `ambush` `lead`-up (`tools/musicgen/slam_rank.py`)

### Goal

This tool ranks lead-ins for an ambush slam under a director goal. The slam introduces a boss from darkness but needs approximately half a bar of warning. 4 variants use the same scripted ambush. They are the old instant slam, a half-bar ramp, and a short half-bar riser followed by an instant wall. A combined ramp plus riser is the fourth variant.

### Invariants

- Each variant uses the same ambush script: a warden and brute enter halfway through bar 7 of 14. The product engine runs in tick-clock mode with the product bank.

- The ramp changes through mixer constant `COMEUP_DELTA`, which the tool restores after each `render`.

### Verification

The ranking request runs twice, and each response is printed in full.

### Implementation

Variant 1 forces the engine's ambush window open on each tick, so the slam has zero transition width. Variants 3 and 4 enable `slam_riser`. The mixer renders each tap stream offline, and clips are independently normalized and limited to 35 seconds.

### Caveats

- The inner function `_no_window_decay` is defined but never called.

- The mixer constant patch is module-global. Parallel `renders` can race, and the tool runs in sequence.

## `loop_seam_rank` — the loop arrival treatments (`tools/musicgen/loop_seam_rank.py`)

### Goal

This tool blindly ranks seamless-loop arrival treatments. A measurement sweep flagged seams with a level change of 8 to 12 dB within 50 ms. Only a listening test can determine whether such an arrival is a composed downbeat or a splice. The same recording is rendered with 3 treatments: clean, a short crossfade, and a half-bar ramp. The model ranks identical seam windows from each render.

### Invariants

- All 3 renders come from the same recording. Only the mixer's `LOOP_SEAM` mode changes.

- A seeded generator shuffles clip order for each seam. This keeps the judge blind to treatment.

### Verification

Each seam prints the sequence, the ranking, and the cause, and the tool prints a point total for all seams, higher is better.

### Implementation

Seam times come from the command line. Each clip spans 7 seconds before through 7 seconds after a seam. Rank positions are converted to points counted from the bottom, then summed for each treatment.

### Caveats

- The tool holds all 3 complete `renders` in memory at the same time.

## `mgui` — the tool `UI` kit (`tools/musicgen/mgui.py`)

### Goal

This module is the music tools' local UI compatibility layer over the frozen engine stack in `game/perihelion`. It exposes only the engine features those tools use, plus additional key constants needed by the DAW and an expanded platform-key table. It also provides a `Rect` with retained geometry helpers, a frame-paced `Clock`, and a `Display` with the engine window and drawing buffer. A single-channel `OneShot` player supports immediate audio playback after a click.

### Invariants

- The `fb` frame is a `(W, H, 3)` unsigned-byte view into a single RGBA buffer with the engine's axis order.

- A headless `Display` creates no window but still permits drawing and returns an empty event list. The DAW fault suite uses this mode.

- Mouse button events always contain a position, and key events always contain the live shift state. The platform reports neither value.

### Verification

Each windowed music tool uses this kit, and the DAW fault suite verifies its headless path.

### Implementation

Additional key constants are SDL codes copied from `pygame-ce` 2.5.7: comma, period, minus, equals, slash, F1, home, end, and keypad plus and minus. `from_platform` extends the engine's key translation over this larger table and maps unknown names to -1. `Rect.collidepoint` uses half-open bounds.

`Clock.tick(fps)` sleeps until the frame target, while `Display` calls `pump()` once during construction because the initial pump satisfies the compositor. `events()` drains the window and adds current mouse position to button events and the current shift mask to key events. `audio()` returns one engine mixer per process, and `audio_reinit()` replaces it so the DAW can recover from audio-device failure. `OneShot.play` stops the channel, frees its previous sound, and plays the newly loaded file.

### Caveats

- `OneShot.play` raises `RuntimeError` when loading fails while a mixer exists. With no mixer, it silently does nothing to support headless operation.

## `instrument` — the ear check instrument (`tools/musicgen/instrument.py`)

### Goal

This windowed tool operates the game music engine with generated banks through the same `MusicSystem` and mixer path used by the game. It plays at an audible level while the user configures simulated combat through enemies, HP, weapon, and stage tier. The user can listen to the automatic response or adjust the 3 music values manually.

### Invariants

- The engine is the production `MusicSystem` and uses only `out/banks/album_*` banks, excluding rejected banks from the previous generator as directed.

- If no banks exist, the tool prints instructions for running the generator and exits without fabricating placeholder audio.

- In `AUTO`, values come from the engine battery applied to the fake session. In `MANUAL`, 3 sliders override them through `override_vals`.

### Verification

The screen shows the engine state each frame: the values, the live lane `gains`, the `bar` index, the `tempo`, and the `riser` `gain`. A user compares the sound against the display directly.

### Implementation

`FakeSession` implements the engine's complete input surface controlled by the UI: enemy types and states, HP, weapon, tier, and a one-polygon map. A melody selection loads its bank, and keys 1 through 4 set the tier. The weapon list and `[` or `]` cycle weapons. Plus and minus buttons add or remove enemies of each type.

A slider changes HP, and `M` toggles automatic mode. `T` toggles tension: it adds or removes a lurking flicker. `R` reloads the active bank from disk, so a user can audition a replaced stem immediately.

`SPACE` or the fire button fires the active weapon with its product sound. `A` enables fire on even eighth notes, and `Q` quantizes a shot to the eighth-note grid with engine music time. The beat strip marks all 8 eighth notes in the bar and the current position.

### Caveats

- The readout uses internal engine fields `_live`, `_bar_idx`, `_riser_gain`, and `_lanes`. Only the display depends on these internals. The audio path does not.

- Button and slider hit tests run sequentially, so overlapping controls could both trigger. The current layout prevents overlap.

## `instrument_lab` — the slot ear check lab (`tools/musicgen/instrument_lab.py`)

### Goal

This windowed tool auditions each instrument slot with its specified musical material. Each row identifies a slot's role, preset, and material. A click plays the cached render for the selected melody. Labels come from `vital_bank.SLOTS`. This keeps displayed preset names aligned with rendered audio.

### Invariants

- A slot from `vital_bank.SLOTS` displays the preset directly from that table rather than a separate hard-coded string, so label and render share one source.

- The player reads cached WAV files and never renders clips. A missing render appears as a dim row labeled `not rendered`.

- Batch mode with `--render` writes each missing `(melody, slot)` clip. Failures are printed without stopping the batch.

### Verification

A user hears each slot against its label. The `batch` mode prints each `render` and each failure with its cause.

### Implementation

The slot list has 9 fixed roles: monk, choir, holy organ, defiant organ, bell, wall, drums, deep bass, and FM bass. It also includes 4 stage beds, one lead per weapon, and one bass cell per enemy type. Specimen candidates cover 4 background beds, 2 impacts, each riser, and a keyed bass.

Renderers build role-specific material. The wall performance follows the album's musical idiom on a validated grid. It uses uniform velocity except for downbeat accents. Power chords occupy accent positions, and chugs reach true silence with a 3 ms fade. 2 performances with different seeds are panned hard left and right.

Leads render as continuous sequences with small note overlaps over a quiet combat bed. An isolated line consistently sounds wrong. Beds sustain through the end of the clip because a decaying demo tail suggests that the sound cannot loop.

### Caveats

- Defect: the module docstring claims that the first click triggers background rendering. The player never renders clips. Batch mode is the only render path.

- The render-cache path is hard-coded to a temporary work directory with a session ID.

- The green playback indicator stays on the most recently played row after the clip ends.

- `_patch_path` is dead code.

## `daw` — the session `DAW` (`tools/musicgen/daw.py`)

### Goal

This windowed tool opens a recorded game-session music decision log as a DAW project. The project includes a video monitor, transport, and ruler with sections and bank spans. It also includes 3 value curves, event markers, and one track per lane with gain automation and clip data. A stem replacement in a monitored bank directory rebuilds the mix in approximately 1 to 2 seconds. It does not move the playhead.

Reconstruction uses the same decision log, offline mixer, and bank directories as the game and the product-video render path. The user thus hears the sound the game would play.

### Invariants

- Mute and solo modify the decision log rather than the mixer. Silenced lane entries are rewritten with zero gain, and muted FX events are removed. The mixer thus renders as if the engine never played those lanes. Audio and display share one predicate for effective mute state, with mute taking precedence over solo.

- One `bank.json` gate, `_bank_valid`, protects parsing, the health panel, the picker, the `--use` flag, and session recall. No path accepts an incomplete bank.

- A stale render cannot update status, commit its buffer, or write a clipping verdict. A generation-checked lock guards the commit.

- Audio freshness is derived from committed change generations rather than a Boolean flag. A mix is current only when its committed build includes each detected change. A rebuild that races an incomplete file transfer thus cannot report an up-to-date status.

- The loudness anchor is latched once from the first complete unmuted mix, preserving real loudness changes across rebuilds. Rescoring a bank resets the anchor.

- The stem-cache key includes file size, so a timestamp-preserving replacement still changes the key when its byte count differs.

- The player end, the `overview`, and the ruler all span the same sample count.

- Each mixer call runs on the single audio thread. If the backend dies, the tool preserves the last valid playhead, displays a red error line, and stays running. `R` retries initialization.

- Each failure appears as a red on-screen line that names the corrective action. Examples include a 48,000 Hz or 24-bit stem, missing bank or video, and missing `ffmpeg`. The file watcher cannot die silently: a guarded loop and main-loop watchdog restart it and report the event on screen. Changes to a shadowed bank copy identify the copy that wins resolution. Truncated messages expand after pointer hover, and full-width text mirrors each error's remedy.

- Stem files must use 44,100 Hz audio, and WAV stems must use 16-bit PCM. Otherwise rebuilding fails with an export instruction.

### Verification

`daw_fault_suite.py` forces each condition and checks its visible indicator as well as audio behavior. For manual verification, replace a stem in a monitored directory and observe `detected — settling`. Confirm that `ready` appears approximately 1 to 2 seconds later with no playhead change.

### Implementation

`Project` parses `events.jsonl` once. It reads bar taps with lane, key, gain, and farewell flag. It also reads the value curve, bank spans and metadata, markers, halts, riser spans, and rotation crossfades. `played_keys` lists each stem name used by the session.

The watcher can thus report whether a changed file is audible in the current session. Before each rebuild, `health()` treats a missing bank or incomplete `bank.json` as an error. A stem shorter or longer than the form produces a `later bars silent` warning.

`Player` streams the mix in 0.1-second chunks through the engine channel queue on one dedicated audio thread. Play, pause, seek, and buffer-replacement calls synchronize with that thread under a 30-second stall guard. Seeking changes the chunk index, while hot buffer replacement preserves playhead and playback state.

`VideoPlayer` decodes through a continuous `ffmpeg` raw-video pipe with a 30-frame buffer and uses the audio clock as master. Seeking outside the buffered span starts a new pipe, rate-limited to 4 starts per second while the playhead is dragged. A changed video restarts the stream, while a removed video produces a red error line.

The watcher polls bank directories under both music roots every 0.7 seconds with modification time and byte count. A relevant change increments the generation counter, displays `detected — settling`, and waits for 0.6 seconds with no further changes. A slow file copy thus triggers one rebuild from complete files. Irrelevant or invalid drops produce explanatory warnings, including name-pattern mismatches, files unused by the session, and unsupported stem formats. A change in a shadowed copy identifies the path that wins resolution. A change to a muted lane suggests that the user unmute it.

The render thread waits 50 ms and coalesces triggers that arrive during that interval. It then mixes with `MK._mix_music_rich`. It applies the loudness anchor and calculates a clipping verdict from dB values and the loudest second. It trims to session length and commits under the generation lock.

`set_bank` rescans only the section under the playhead and preserves scores for adjacent sections. This retains transition-review context. A modal blocks old audio until the new render arrives.

`SPACE` toggles play and pause. Dragging on the ruler creates a loop selection. The waveform strip stays a full-session overview beneath the zoomable timeline, and plus or minus zooms around the playhead.

Arrows move by one `bar`, or by 10 seconds with `shift`, and repeat while held. `,` and `.` add marks, and up and down move between sections. `G` or the clock opens time entry. `M` and `S` affect the selected lane. `A` compares against the old `mix`, `B` bounces the loop to a wav, and `C` copies the `timestamp`.

`R` retries failed components, `F1` or `?` opens help, and `ESC` closes overlays or exits. The live picker lists each directory with `bank.json` under both roots, dims incomplete banks, and refuses them with an explanation.

The transport displays status, render progress relative to the retained estimate, clipping verdict, and A/B state. It also shows watcher state or the age of stale audio. The timeline contains a ruler, section strip, value curves, and lane rows with one clip per bar. It also contains a full-session waveform with death halts shown in red.

Clip height and brightness follow gain, and farewell bars taper to a point at the right edge. The marker row and legend share one glyph table. This prevents their labels from diverging.

When no buffer is playable, a modal dims the timeline and names the blocking state. On exit, the tool writes state to `daw_session.json`. State includes playhead, mute and solo state, selection, loop, zoom, and section scores. The tool restores them when the project reopens.

### Caveats

- The default video is attached only when the recording argument exactly equals the default recording path. The same directory supplied through a relative path silently omits the monitor.

- A truncated status chip with a click target does not register its full text for hover expansion. Only noninteractive chip text expands.

- If the video file is removed, the reader thread stays blocked at the buffer cap until shutdown.

- `set_bank` clears the player buffer under the application lock rather than on the audio thread. This is currently safe only because buffer-reference assignment is atomic and playback is paused first.

- `health()` skips unreadable stems with a bare `continue`. The later render guard reports their names, as its comment states.

- The video docstring claims decoding at 12 times real time, while the buffer-coverage estimate conservatively assumes 6 times real time.

- `_describe_format` has an unused parameter, and the `watcher` path for `daw_session.json` is dead code.

### The lanes

The lane rows are `holy`, `bed`, `drums`, `wall`, `groove`, `lead`, `lead2`, `bass`, and `boss`. `fx` is one mute group for the `riser`, `sting`, and stab one-shots.

## `daw_fault_suite` — the `DAW` error `suite` (`tools/musicgen/daw_fault_suite.py`)

### Goal

This tool forces each P0 failure case from the DAW UX plan and checks the corresponding indicator. Checks cover audio, the status chip, the note, the health line, and modal pixels. It uses a synthetic recording and 2 synthetic banks in a temporary directory grafted onto the music roots. No product bank is touched, and the exit code is 0 only when each forced case behaves as required.

### Invariants

- All synthetic files live in one work directory under `/tmp`, which the run removes at the end.

- Each case restores the component it changed, leaving the same process valid for the next case.

- Each case checks either an on-screen indicator or direct ground truth. A spectral peak identifies the audible file. Buffer identity proves that the last good mix continued. Screen pixels verify the modal. Subprocess error text verifies a clean refusal.

### Verification

The suite is the DAW's verification harness. For each of 39 forced cases, it prints `PASS` or `FAIL` with the case name and duration, followed by summary counts.

### Implementation

Fixtures comprise 2 banks of 10 sine-wave and click stems at 220 and 262 Hz with valid `bank.json` files. They accompany a 14-bar recording with bank rotation, farewell bars, a value curve, and each marker type. Format cases cover 48,000 Hz audio, 24-bit WAV, unsupported stem format, invalid name, and truncated files. Each must display its named error while retaining the last good mix. A synchronized copy performed in thirds verifies, by rebuild count and spectral peak, that the watcher rebuilds exactly once from the complete file.

Watcher cases verify the guarded loop and watchdog restart. The mute/solo case checks both display state and a render with all lanes at zero. The stale-render case verifies that clipping status stays current. Audio- and video-backend failures verify red error lines, retry behavior, and the absence of duplicate concurrent processes. Resetting a file timestamp tests the byte-count cache key. Bank cases verify health lines, the live picker, the single schema gate, and clean rejection of an invalid bank.

The race case sends rapid seeks during hot buffer replacements. Feature cases verify loop playback, bounce export, marker changes, time entry, A/B playback, loudness anchoring, and restart at the end. The modal case measures timeline dim level in pixels, and the shutdown case proves that no event is processed after exit.

### Caveats

- The docstring describes a 35-second recording, while the fixture lasts approximately 30.4 seconds.

- One assertion in the no-taps case can no longer satisfy its first branch because the DAW note text changed. Only the second branch can make it true.

- At import, the suite appends its temporary work root to the global `MUSIC_ROOTS` list. One case replaces the entire list and restores it afterward, so correctness depends on a single sequential run.

- Some cases depend on the specified run order and host environment. 2 require the product video to exist, and 2 require `ffmpeg`. Without those dependencies, the suite reports failures even when the DAW is correct.

- Secondary application instances do not join their threads on close, so those threads stay alive until the process ends.
