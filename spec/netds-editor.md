---
This specfile tells the work of the NETDS level editor: the package `game/perihelion/editor/` (`__init__.py`, `__main__.py`, `model.py`, `view.py`), the editor's side of the level JSON contract with `game/perihelion/levels.py`, and the root document `EDITOR.md`, which this file audits against the code. It is a Phase 0 decompile of the 2026-07-09 loop result after the de-narrativization and the engine port. All sections describe the editor as it is.

The standards manifest applies `ux-principles-interactable-software.md` to the editor, because the editor ships to players (`spec/open-questions.md` NETDS-3). The audit findings against that standard are recorded in the Caveats sections as caveats, not failures. They are inputs to the P4 build spec.

---

# NETDS level editor

The editor is a 2D drafting canvas for the level JSON files in `levels/`. It edits the resolved level dict directly — the exact shape the game loader reads — and writes it back with the same formatting. The world on the canvas is Euclidean. Non-Euclidean structure exists only as connection records between edges, drawn as colored arcs.

The code has two halves. `model.py` is the pure-Python state and file layer, with no `pygame` import. `view.py` is the `pygame` window, camera, renderer, and input translator on top of it. `game/tests/test_editor.py` exercises the model headlessly.

The package and window still carry the name PERIHELION. That name now belongs to the other game (`spec/open-questions.md` NETDS-4).

## Launch and shell (`editor/__main__.py`, `view.EditorApp`)

### Goal

The editor starts from the command line with an optional level file and runs as one resizable window until the user closes it.

### Invariants

- `model.py` imports no `pygame`. All level logic lives in the model, and the view only translates input and draws.

- A load failure at launch never crashes the editor. The error goes to the status bar and the model stays blank.

### Verification

`uv run python -m perihelion.editor levels/l03.json` opens the level. With `SDL_VIDEODRIVER=dummy` the app constructs, loads the file, and renders frames headlessly. This drive was performed for this decompile.

### Implementation

`__main__.py` parses one optional positional argument, the level path, and calls `view.run`. `EditorApp.__init__` initializes `pygame`, sets the caption `PERIHELION -- Level Editor`, and opens a resizable 1440x900 window. When a path was given it calls `model.load` and puts the result in the status bar. It then fits the camera to the level bounds.

The main loop runs at 60 frames per second: dispatch each `pygame` event, apply arrow-key panning from the live keyboard state, draw one frame. On quit the app terminates a live playtest process and calls `pygame.quit`.

The view imports `get_font` from `perihelion.menus` and the color tables `ENEMY_COLOR` and `KEY_COLORS` from `perihelion.render`. The editor therefore needs the game package, not only the model.

### Caveats

- The window caption and the module path say PERIHELION. Decision open (see `spec/open-questions.md` item NETDS-4).

- Closing the window with unsaved changes discards them. No prompt, no autosave, and no recovery path exists. The status bar shows a dirty star, and that is the only signal (UX standard section 7). Decision open (see `spec/open-questions.md` item NETDS-3).

## The level dict and file operations (`model.EditorModel`)

### Goal

The model holds the literal level dict — the same shape as the JSON on disk — and edits it in place. A failed load never destroys good state. A save never writes an invalid level. Undo restores exact prior states.

### Invariants

- `load` on an unreadable, unparseable, or non-object file returns error strings and leaves the model untouched.

- `save` writes only when `validate` returns no errors. A refused save leaves no file behind.

- `dirty` is true exactly when the current dict differs from the last loaded or saved snapshot.

- `undo` restores the exact prior dict. The undo and redo stacks each keep at most 100 entries.

- `export` writes to an arbitrary path without a change to `path`, `dirty`, or the saved snapshot.

### Verification

`game/tests/test_editor.py` checks: a load of `levels/l01.json` gives 12 rooms, zero validation errors, and a clean dirty flag. A load of invalid JSON and a load of a missing file both return errors and leave the previous state intact. Two mutations then two undo calls restore the exact prior dict, and a third undo returns `False`. A refused save creates no file.

For this decompile, all 12 shipped level files were cycled through load, save, and reload. Every file came back byte-identical, with zero validation errors and no entity duplication or loss.

### Implementation

A blank level is `{"version": 2, "name": "untitled", "tier": 1, "ambience": "amb_drone_early", "rooms": [], "connects": [], "connects_x": [], "doors": [], "player": None, "exit": None}`.

`_normalize` fills each absent key of a loaded dict and gives each room a `verts` and an `entities` list. It keeps every unknown key at the top level, in rooms, and in entities. `load` parses the file, rejects a non-object root, normalizes, and only then replaces the model state. Load and `new` clear both undo stacks, the selection, and the error list, and they reset the saved snapshot.

`save` validates, resolves the target (the given path or the stored `path`), writes, and updates `path` and the snapshot. `_write_out` copies the dict, stamps `version = 2`, and writes `json.dumps(..., indent=1)`. `export` validates and writes only.

`snapshot` pushes a deep copy of the current dict to the undo stack before a mutation and clears the redo stack. Every mutating model call snapshots first. `undo` and `redo` swap the current dict with the stack tops and clear the selection.

### Caveats

- Defect: a session with no stored path can never save. `save` without a path returns `no file path to save to`, and the view calls `save` with no argument. A blank-canvas start, a `Ctrl+N` level, and a session whose launch load failed all have no path, and no save-as affordance exists. The blank-canvas mode that `EDITOR.md` advertises cannot produce a file. The only workaround is to create a stub JSON file by hand and open it (UX standard sections 3 and 11).

- The model does not read the `version` value. A file with a different version number opens without a warning, and the save stamps version 2 on disk. The game loader rejects any version other than 2.

- `_write_out` stamps the version into a copy. After a save of an old-version file the in-memory dict keeps the old number while the disk says 2. The dirty flag compares against the in-memory snapshot, so it stays clean.

- A minimal hand-made file gains the default keys on save. `{}` becomes a full blank level named `untitled`. This is fill-in, not loss. No key is ever removed.

## The save gate (`model.validate`)

### Goal

The gate refuses to write a level that the game loader or the engine would reject. The checks: too few vertices, wrong winding, concave rooms, absent spawn markers, connection indices out of range, and one edge claimed by two connection records.

### Invariants

- `validate` returns a list of error strings and stores it in `last_errors`. An empty list is the only pass.

- A level with `vigil` set is exempt from the exit requirement. Every other level must have a player and an exit whose room indices are in range.

- The same edge as both sides of one record (a mirror connect) is not a conflict. The same edge in two different records is.

### Verification

`game/tests/test_editor.py` checks: a concave vertex blocks the save with a `concave` error. Reversed winding blocks with a `winding` error. A removed player blocks with `no player spawn`. A second record on an already-used edge blocks with `used by multiple connections`, and a self mirror connect does not. `levels/vigil.json`, which has no exit, validates clean.

### Implementation

Per room: fewer than 3 vertices, non-negative shoelace area (the winding rule is y-down visual-CCW), and the per-vertex convexity flags from `convex_flags`. Each room check runs in its own try block, so one malformed room becomes one error line. Then the player and exit checks. Then each entry of `connects`, `connects_x`, and `doors` gets a range check on both room and edge indices. Every valid endpoint is recorded in an edge-use table. Any edge with more than one distinct record label becomes a conflict error.

`convex_flags` marks a vertex only on a genuine sign flip against the overall winding. Collinear vertices, which doorway-split walls have by design, pass.

### Caveats

- Defect: the gate assumes `player` and `exit` are objects. A hand-edited file with `"player": [1, 2]` makes `validate` raise `AttributeError` instead of returning an error. The view calls `validate` every frame for the status bar and also draws the marker, so the editor crashes at launch on such a file. A connection that references a room with an empty vertex list crashes the same way (`ZeroDivisionError` in `edge_midpoint`). Both crashes were reproduced headlessly for this decompile. This breaks the model's own stated goal that broken entries surface through `validate`.

- The gate does not check: entity types, entity or marker positions against room shapes, door key values, edge-length agreement of connected pairs, or `gate_kind` values. The game rejects unknown entity types at session start (see the contract unit).

## Room operations (`model`, room half)

### Goal

Rooms are created as rectangles or free polygons, reshaped by vertex, and moved with their contents. A room delete fully reindexes everything that references rooms.

### Invariants

- A polygon room is stored in canonical winding: negative shoelace area, matching the loader and the engine.

- `delete_vertex` never drops a room below a triangle.

- A connection bound to an edge that a deleted vertex touched is dropped, never reattached to a differently-shaped edge.

- After `delete_room` no record references the removed room. Every higher room index in `connects`, `connects_x`, `doors`, `player`, and `exit` shifts down by 1. A marker in the deleted room becomes `None`.

- `move_room` translates the vertices, the room's entities, and any marker whose `room` is that room, by the same delta.

### Verification

`game/tests/test_editor.py` checks: a room move translates vertices, entities, and the player marker together, leaves other rooms untouched, and is one undo step. A delete of room 3 in `l01` produces the exact expected remap of every `connects` entry, shifts the exit marker from room 7 to 6, and validates clean. A delete of the player's room clears the marker and `validate` reports `no player spawn`. A vertex delete leaves every remaining edge index of that room in range. A triangle refuses vertex deletion.

### Implementation

`add_rect_room(x, y, w, h)` appends 4 vertices in canonical order. `add_poly_room` runs `canonical_winding`, which reverses the input when the shoelace area is positive. Both return the new room index.

`delete_vertex` builds an old-edge to new-edge map. Edges that touched the removed vertex map to nothing, and the rewrite of `connects`, `connects_x`, and `doors` drops any record whose edge maps to nothing. `delete_room` rewrites the same 3 lists with room remapping and drops records that touch the removed room, then remaps the markers.

`set_vertex` writes one vertex. Each operation snapshots once, so each is one undo step.

### Caveats

- `move_room` applies the raw drag delta. The result is unsnapped even when snap is on, because the view snaps point placements but not drag deltas.

- A malformed entry in `connects` or `connects_x` (wrong arity) is silently dropped by the rewrite passes of `delete_vertex` and `delete_room`, not reported.

## Entities and the two markers (`model`, entity half)

### Goal

Enemies and pickups are placed from a palette into a room's own `entities` list. The player spawn and the exit are singleton markers, placed from the same palette, and placing a new one replaces the old.

### Invariants

- `add_entity` accepts only the room-entity types (6 enemies, 12 pickups) and raises `ValueError` for anything else, including `player` and `exit`.

- `set_player` and `set_exit` replace the marker. `set_exit` keeps an existing `key` and `gate_kind` across re-placement.

### Verification

`game/tests/test_editor.py` checks: `add_entity(0, "player", ...)` raises, and an entity delete shrinks the room's list by one.

### Implementation

The palette order is `player` and `exit` first, then the 6 enemies, then the 12 pickups.

- Enemies: `husk`, `mite`, `spitter`, `brute`, `shrieker`, `warden`.

- Pickups: `ammo_9mm`, `ammo_shell`, `ammo_cell`, `medkit`, `weapon_smg`, `weapon_shotgun`, `weapon_rail`, `implant_lightning`, `key_red`, `key_blue`, `key_gold`, `key_void`.

An entity record is `{"type": ..., "pos": [x, y]}` plus an optional `props` dict. `move_entity` and `delete_entity` act by room and list index. `set_exit_key` and `set_exit_gate_kind` write or remove the exit's `key` and `gate_kind` fields.

### Caveats

- The view never calls `set_exit_key` or `set_exit_gate_kind`, and nothing reads `GATE_KIND_PRESETS`. A loaded exit key or gate kind shows in the marker label and survives re-placement, but the editor cannot author, change, or remove one (UX standard section 3). Decision open (see `spec/open-questions.md` item NETDS-3).

- The view never passes `props`. Entity properties such as `hp` and `tether`, which the game reads, can come only from hand-edited files.

- The game accepts 4 pickup types the palette lacks: `portable_hole`, `safe_room_core`, `turret`, `weapon_tau`. The portable hole is a named NETDS scope item, and the shipped editor cannot place it. Decision open (see `spec/open-questions.md` item NETDS-3).

- Placement requires a containing room, but a later entity drag can end outside every room, and the gate does not check positions. The engine clamps a spawned body into its polygon, so such a position shifts in game.

- The markers cannot be dragged. The only ways to move one are re-placement from the palette and deletion.

## Connections (`model`, connection half)

### Goal

A connection joins two room edges into a portal pair. The same edge picked twice is a deliberate mirror. A door is a keyed connection that the game keeps closed until unlocked. Connections are deletable one record at a time.

### Invariants

- `connect_edges` appends `[ra, ea, rb, eb]` to `connects` with no further checks. The save gate, not the connect call, enforces single use per edge.

- `connect_door` appends `{"a", "ea", "b", "eb", "key"}` to `doors`.

- A mirror record (both sides the same edge) passes the save gate. `levels/l06.json` ships one: `[2, 1, 2, 1]`.

### Verification

`game/tests/test_editor.py` connects a new room to a free edge of `l01`. The result validates, saves, and loads through the real `perihelion.levels` loader. It then runs 60 ticks in a live `GameSession` without a player death. A mirror connect does not trip the double-use error.

### Implementation

`delete_connection(kind, idx)` deletes by list kind (`connect`, `connect_x`, `door`) and index, with a silent no-op for an index out of range. The door key comes from the view's `KeyPrompt` overlay. It offers the 4 presets `red`, `blue`, `gold`, and `void` on keys 1 to 4. Escape cancels. Every other key is ignored while the prompt is open.

### Caveats

- `connects_x` records (explicit-transform connections) are displayed and deletable but cannot be created. No UI path authors one. Every shipped level has an empty `connects_x`.

- The door prompt offers only the 4 preset keys. The game still implements the `shoot` door, a secret that renders as a cracked wall and opens to gunfire (`sim.py`, `render.py`). The editor cannot author one. `EDITOR.md` documents that door as an editor feature (see the manual unit). Decision open (see `spec/open-questions.md` item NETDS-3).

- Nothing checks edge-length agreement at connect time. The canvas warns later (see the rendering unit), and the engine scales mismatched pairs.

## Picking (`model`, picking half)

### Goal

A click resolves to the object the user meant: a vertex, an entity or marker, a connection arc, or a room.

### Invariants

- The category order is fixed: vertex first, then entity-like (entities, player, exit), then connection, then room. Distance competes only inside a category.

- The pick tolerance is 8 screen pixels, converted to world units by the current zoom.

### Verification

The selection drives every keyboard action on the selection (delete, X). The tests exercise the resulting model calls. No test drives `pick` directly.

### Implementation

`nearest_vertex`, `nearest_entity_like`, and `nearest_connection` each scan their category with squared-distance tolerance. Connections are measured against the segment between the two edge midpoints. `nearest_room` is a point-in-polygon test, and among overlapping rooms the last room in file order wins, which is the room drawn on top. `pick` tries the 4 categories in order and returns the first hit.

### Caveats

- `EDITOR.md` says `nearest wins`. Category order wins first. A vertex inside tolerance beats a nearer entity or arc.

## Camera, canvas, and rendering (`view`, drawing half)

### Goal

The canvas shows the whole level as a drafting view. It draws the grid, the rooms with ids and edge indices, connection arcs colored by kind, entity glyph discs, and the two markers. It also draws live previews for gestures in progress, a mode HUD, and a one-line status bar that always reflects the model.

### Invariants

- The status bar derives from the model every frame. It shows the file name, a dirty star, the selection, the snap and grid states, and the zoom. When `validate` reports errors the message area shows `INVALID (n):` with the first error in red.

- Vertices where the room is concave or degenerate render red. Arc colors by kind: cyan for `connects`, magenta for `connects_x`, amber for `doors`, red for a mirror (drawn as a circle on the edge), white when selected.

- A connected pair whose edge lengths differ by more than 2 percent gets an amber warning triangle at the arc midpoint.

### Verification

Headless drives with `SDL_VIDEODRIVER=dummy` were performed for this decompile. Frames render for a shipped level. After a forced concave edit the status bar shows `INVALID (2)` with the first error. The color and threshold values are read from the source.

### Implementation

The camera is a center point and a zoom. `_fit_camera` centers the level bounds and clamps zoom to 0.05 through 3.0 with a 0.85 margin. Wheel zoom multiplies by 1.1 per notch toward the cursor, clamped to 0.02 through 20. The status strip is 22 pixels tall, and the world transform centers on the remaining area. Snap rounds to the fixed 10-unit grid when enabled. The grid draws when its spacing is at least 4 pixels, with the axes highlighted.

Rooms draw as filled polygons with an outline, a brighter fill and thicker outline when selected. Room drags and vertex drags render from the live drag state, so the preview matches the eventual commit. Edge index labels draw at edge midpoints when the `I` toggle is on. The room id `#n` draws at the vertex mean.

Arcs are quadratic curves bulged perpendicular to the chord. A mirror draws as a red circle of radius 10 at the edge midpoint. A door's key renders as text near the arc. Entities draw as colored discs with a single-character glyph, colors from the game's own tables. The player is a circle marked `P`, the exit a triangle labeled `EXIT`, with `+key` and `/gate_kind` suffixes when present.

Three previews draw for gestures in progress. The rect tool shows its outline box. The poly tool shows the point chain with a rubber line to the cursor. The connect tool shows a white ring on the first picked edge. The mode HUD sits top-left, and in entity mode it names the current palette type.

### Caveats

- The constant `KEYBIND_HELP` holds a full keyboard summary and no draw call reads it. The controls are discoverable only in `EDITOR.md` and the source, which the UX standard names as the anti-pattern for a shipped surface (section 3, recognition over recall). Decision open (see `spec/open-questions.md` item NETDS-3).

- During a room drag the room and its entity discs follow the preview, and the player and exit markers do not move until release.

- Status messages render as one unclipped line. A long error joins past the window edge, and only the first validation error is shown (UX standard section 10).

- `EDITOR.md` says concave vertices flash red. They render steady red.

## Input modes and gestures (`view`, input half)

### Goal

The editor is modal: `select`, `rect`, `poly`, `entity`, `connect`, `move`. One key enters each tool, and Escape returns to select. Each drag gesture commits exactly one model call on release, so one gesture is one undo step.

### Invariants

- Escape cancels the mode, the poly point chain, and a half-made connection.

- Middle-drag pans in every mode. Right-drag moves a room in every mode.

- While the door key prompt is open, every event except quit and resize goes to the prompt.

- A drag commits only when the position changed, so a plain click never pushes an empty undo step.

### Verification

A headless gesture drive was performed for this decompile: enter rect mode, press, drag, release. The model gains a snapped 100x60 room and the status line `room 9 created`. The model tests cover the calls each gesture makes.

### Implementation

Keyboard, with Ctrl meaning Ctrl or Meta: `Ctrl+S` save, `Ctrl+N` new, `Ctrl+Z` undo, `Ctrl+Y` redo, `Ctrl+O` prints the CLI load hint. `G`, `S`, `I` toggle grid, snap, and edge indices. `R`, `P`, `E`, `C`, `M` enter the tools. `[` and `]` cycle the palette. Enter commits a poly of at least 3 points.

Delete and Backspace delete the selection. `X` deletes the selection when it is a connection. `F5` starts a test play. Arrows pan at 14 pixels per frame scaled by zoom.

Mouse, left button by mode: `rect` starts a snapped drag box, committed on release when at least 4x4 world units. `poly` appends a snapped point. `entity` places the palette type at the snapped point inside its containing room, with player and exit routed to the marker calls. `connect` picks the nearest edge twice, and with Shift held on the second pick it opens the door key prompt instead of a plain connect. `select` picks, and a picked vertex or entity starts a live drag. The wheel zooms, except in entity mode, where it cycles the palette.

### Caveats

- `Ctrl+O` does not open a file. It prints `load via CLI arg only` with the command line. No open or save-as dialog exists anywhere in the app (UX standard section 3). Decision open (see `spec/open-questions.md` item NETDS-3).

- `Ctrl+N` replaces the level at once, and undo does not cross it. Unsaved work is lost without a prompt (UX standard section 7).

- Backspace is not mode-gated. During poly placement it deletes the current selection instead of the last placed point.

- Undo and redo clear the selection.

- Arrow-key panning reads the live keyboard state and stays active while the door prompt is open.

## Test play (`view._test_play`)

### Goal

`F5` runs the current level in the real game without a save of the working file. A second `F5` restarts the run.

### Invariants

- The export is validation-gated and touches neither `path` nor the dirty state. An invalid level refuses with `playtest refused:` and the errors.

- A prior playtest process is terminated before a new one starts, and on editor quit.

### Verification

The exact launched command was run for this decompile against an editor-authored file: `uv run python -m perihelion --level <tmp> --autoplay` ran headlessly for 12 seconds without a crash. The game's `--autoplay` flag skips the title menu and starts the level at once, and the player keeps normal control.

### Implementation

The export target is `perihelion_editor_playtest_<pid>.json` in the system temp directory. The child starts through `subprocess.Popen` with the repository root as its working directory. The status line shows the child pid on launch, or the launch failure.

### Caveats

- The mechanism presupposes a development checkout: `uv` on the PATH and the repository as the working directory. For a build shipped to players this launch path is undefined. Decision open (see `spec/open-questions.md` item NETDS-3).

- Nothing watches the child after launch. When the game exits at startup, the editor still shows `test play launched` and never reports the failure (UX standard sections 5 and 6). An entity type the editor accepted but the game rejects triggers exactly that exit.

- The temp file stays on disk after both programs exit.

## The level JSON contract with the game (`model` with `perihelion/levels.py`)

### Goal

The editor edits the same dict that `perihelion.levels.load_level` reads, at the same file paths. The round trip is safe. A load, save, reload cycle changes nothing, and the save gate blocks what the loader would reject.

### Invariants

- The round trip loses no data and duplicates nothing. Unknown keys pass through untouched.

- The disk format is `json.dumps(..., indent=1)` with `version` 2, identical to the game's own `save_level`.

- The winding law is shared: the loader raises on a positive shoelace, and the save gate blocks it first.

### Verification

Executed for this decompile: all 12 shipped level files cycled through the editor model came back byte-identical. `game/tests/test_editor.py` carries an edited level through the real loader into a live `GameSession` for 60 ticks. The April-prototype editor doubled entities on import. This editor was checked for that class and has no load or save asymmetry.

### Implementation

The dict the loader reads:

- `rooms` with absolute canvas `verts`, optional `kind` and `detail_seed`, and per-room `entities` with `type`, `pos`, and optional `props`.

- `connects` as 4-int records, and `connects_x` as 4 ints plus a 9-value matrix.

- `doors` as keyed records.

- `player` and `exit` as `{room, pos}`, with optional exit `key` and `gate_kind`.

- The top-level `name`, `tier`, `ambience`, `alert_hops`, and `vigil`.

The loader re-centers each room on its area centroid and converts every position to room-local coordinates. Doors load as pending connections that stay walls until unlocked at runtime.

The editor works in the absolute canvas frame throughout and never performs the centroid conversion. It preserves `kind`, `detail_seed`, `alert_hops`, and `vigil` without an editing affordance for any of them.

### Caveats

- The doorway-split autoconnect lives in `LevelBuilder.resolve`, the programmatic generator path, and `load_level` never calls it. Two rooms saved by the editor with touching walls stay unconnected in the game. The verification was direct: a 2-room flush level saved by the editor loads with an empty `connects`. The same geometry through `LevelBuilder.resolve` gains the connection. Everything the editor authors must go through the connect tool, and `EDITOR.md` claims the opposite (see the manual unit).

- The editor accepts and re-saves entity types it does not know, and the game session raises `ValueError` for an unknown type at spawn time. A leftover narrative entity in a hand-kept file would pass the editor and stop the game. No shipped level holds one.

- Level metadata — `name`, `tier`, `ambience`, `alert_hops`, `vigil`, room `kind` and `detail_seed` — can only be set by hand in the JSON. Decision open (see `spec/open-questions.md` item NETDS-3).

- A version-1 file opens without a warning and saves as version 2 (see the file-operations unit).

## The `EDITOR.md` manual (repository root)

### Goal

`EDITOR.md` tells a human how to run and use the editor: the launch lines, the color language, the full key table, and workflow notes. If the editor ships to players, this document is currently its only manual.

### Invariants

None. The document is prose, and this unit records its audit.

### Verification

Every claim in the document was checked against the code and the headless drives for this decompile. The claims that hold:

- Both launch lines and the arc color language (cyan, magenta, amber, red).

- The pan, zoom, and toggle keys, selection and deletion, and undo and redo.

- Both room tools with auto-corrected winding, and the palette flow with wheel cycling in entity mode.

- The connect flow with the mirror rule and the Shift door, and `X` for connection deletion.

- The validation-gated `Ctrl+S`, `Ctrl+N`, and the `F5` restart behavior.

- The marker re-placement note and the 2 percent edge-length warning.

### Implementation

The document is 51 lines: launch, concept paragraph, key table, notes.

### Caveats

These claims do not hold against the code:

- `Rooms placed flush against each other connect automatically when the level loads` — false on the load path. The split-and-autoconnect pass runs only in the programmatic `LevelBuilder`, which the editor and the loader never invoke (verified, see the contract unit).

- `Terminals prompt for their text on placement` — no terminal exists in the palette or the game. The de-narrativization removed the lore and terminal affordances, and the sentence is a leftover.

- `click | select room, vertex, entity, or connection (nearest wins)` — category priority wins before distance (see the picking unit).

- `drag vertex | ... concave vertices flash red` — steady red, not flashing.

- `C, Shift on the second edge | make it a keyed door (prompts for the key)` together with the `shoot` note — the prompt is a 4-preset list, so the documented `shoot` secret door cannot be authored in the editor. The game itself still implements it.

- The title says PERIHELION. Decision open (see `spec/open-questions.md` item NETDS-4).
