---
This specfile records what the April 2025 prototype level editor IS, at the resolution of the code. It covers `leveledit.py`, `test_leveledit.py`, and the level JSON format that the editor reads and writes. It describes the prototype as it exists. It does not describe the future port.

Standards, per `spec/standards/manifest.md`:

- `litc-clear-technical-prose.md` applies to all text in this file.
- `ux-principles-interactable-software.md` applies to the editor, because the editor ships to players as part of the product. This file describes the 2025 prototype, so audit-relevant observations against that standard are recorded as caveats, not failures. The unit "The regression test" describes `test_leveledit.py`, which the manifest excludes from the UX standard as development harness.
- `ste-simplified-technical-english.md` is a pinned source for the writing system, not an applied standard, so it does not bind this file.
---

# Prototype level editor

`leveledit.py` is a standalone Pygame program. A designer draws polygonal rooms, links room edges into portal connections, and places game entities. The editor saves the result as a level JSON file that `main.py` can load. The world is deliberately non-Euclidean: a connection joins two edges regardless of where the rooms sit, so overlapping and distant rooms can be neighbors. The editor imports entity classes from `main.py` but is otherwise self-contained. Coordinates are 2D world units with the y axis pointing down, matching the screen.

## The editor program and its main loop

### Goal

Running `leveledit.py` opens a resizable editor window with a toolbar, five tools, and a world viewport. An event loop runs at 60 frames per second until the window closes.

### Invariants

- Exactly one tool is current at any time. The Polygon tool is current at startup.

- Mouse events whose position lies in the top 100 pixels never reach the current tool.

- Every frame draws in a fixed order: background fill, grid and rooms, the current tool's overlay, then the toolbar. The F1 help overlay and the save-warning box draw last, each only when active.

### Verification

- Launching the program shows a 1600 by 900 resizable window with a dark gray viewport, a toolbar across the top, and the Polygon tool active.

- Keys 1 through 4 switch to the Polygon, Vertex, Connection, and Entities tools. Clicking any of the five toolbar tool buttons, including Move, switches to that tool.

- F1 toggles a translucent help overlay that shows the current tool's help text. G toggles grid snap. E toggles edge scrolling. Plus and minus change the grid size in steps of 5, with a floor of 5.

- Dragging the window border shows a "RESIZING..." screen, and the editor resumes at the new size about half a second after the last resize event.

### Implementation

Importing the module calls `pygame.init()` and creates four fonts from the system font "Fixedsys Excelsior 3.01" (sizes 16, 16, 16, and 32). `level_editor()` is the entry point. It creates the display (1600 by 900, resizable), an empty `EditorWorld`, records one undo state, and builds the five tool objects: `PolygonTool`, `VertexTool`, `ConnectionTool`, `EntitiesTool`, `MoveTool`. Tool objects live for the whole session and keep their state across tool switches.

Each frame ticks a clock at 60 fps, recomputes `SCREEN_CENTER` from the window size, and routes every pending event through `process_event`:

- `QUIT` calls `pygame.quit()` and exits the process.

- `VIDEORESIZE` sets a resize latch. While the latch is set, the frame draws only a "RESIZING..." message. When 500 ms pass without another resize event, `handle_resize` reads the new window size, recreates the display, and clears the latch.

- `KEYDOWN` goes to `process_key_event`. F1 toggles the help overlay, and keys 1 through 4 call `switch_tool`. G toggles `SNAP_TO_GRID`, E toggles `EDGE_CAMERA_MOVEMENT`, and plus and equals add 5 to `GRID_SIZE`, while minus subtracts 5 down to a floor of 5. Ctrl+Z and Ctrl+Y call the undo manager, and the S key calls `handle_save` (Shift+S becomes Save As). The function returns the possibly replaced world object.

- Mouse events go to `process_mouse_event` (wheel zoom, middle-button pan or room split, toolbar clicks — detailed in later units). A mouse event with `pos[1] < 100` is then marked consumed. Unconsumed events go to `current_tool.handle_event`.

The toolbar is an 80-pixel translucent ribbon rendered by `draw_tool_ribbon` every frame. It holds the file buttons Load, Save, Save As, and New (80 by 30), and five tool toggle buttons (100 by 30) with the current tool shown active. Undo and Redo buttons (40 by 24) sit at the top right. The ribbon also shows a one-line tool description, a status line ("Snap: ON/OFF, Grid: N, Edge: ON/OFF"), and the current tool's short button help wrapped into columns. `process_toolbar_click` hit-tests toolbar clicks. It calls `draw_tool_ribbon` again during event handling to rebuild the button rectangles, then compares the click position against the file and tool buttons.

`switch_tool` maps keys 1 through 5 to the five tools and sets the help-overlay text to the new tool's `help_text`. The F1 overlay (`draw_tooltip`) lays a translucent black layer over the window, from the top edge down to 80 pixels above the bottom. The layer dims the toolbar as well as the world, and the bottom 80 pixels stay clear. The help text renders line by line, starting just below the toolbar.

### Caveats

- Defect: `process_key_event` forwards only keys 1 through 4 to `switch_tool`, although `switch_tool` itself maps key 5 to the Move tool. The Move tool is reachable only by clicking its toolbar button, never by keyboard.

- Defect: the Undo and Redo toolbar buttons are drawn every frame but `process_toolbar_click` never hit-tests them. Clicking them does nothing. Ctrl+Z and Ctrl+Y are the only working undo controls.

- `draw_tool_ribbon` is defined twice. The second definition (with file buttons) shadows the first. The first is dead code, as are `draw_hotkey_guide` and `EditorWorld.get_room_at_point` (a duplicate of `get_polygon_under_cursor`).

- The `Button` class supports callbacks and toggle state, but every toolbar callback is `lambda: None` and `Button.handle_event` is never called. All real click handling happens in `process_toolbar_click`.

- The window title is never set, and the name of the open file appears nowhere on screen. There is also no feedback when a save succeeds. No unsaved-changes warning appears when the window closes or when New or Load discards work. These are audit-relevant observations under the UX standard.

- `process_mouse_event` runs before the consumption check, so camera panning still works over the toolbar area while tool interactions there are blocked.

- Tool state survives tool switches. For example, a half-drawn polygon is hidden while another tool is current and reappears on return.

- The module docstring is empty.

## Viewport: camera, zoom, and grid

### Goal

The editor views an unbounded 2D world through a pan-and-zoom camera and draws a square reference grid. Two optional behaviors assist layout: points snap to that grid, and the camera scrolls when the cursor touches the window border.

### Invariants

- `world_to_screen` and `screen_to_world` are inverse transforms built from the camera offset, the zoom factor, and the screen center.

- When `SNAP_TO_GRID` is on, `snap_point` rounds each coordinate to the nearest multiple of `GRID_SIZE`. When it is off, `snap_point` returns the point unchanged.

- The grid renders brighter (128 gray) when snap is on and dimmer (64 gray) when snap is off, so the snap state is always visible.

### Verification

- Scrolling the mouse wheel zooms in and out around the screen center. Dragging with the middle button over empty space pans the camera.

- With edge scrolling enabled, holding the cursor within 8 pixels of a window border moves the camera toward that border.

- With snap on, new polygon vertices land on grid intersections. Pressing G dims or brightens the grid immediately.

### Implementation

`world_to_screen` maps a world point to `(pt - camera_offset) * zoom + SCREEN_CENTER`. `screen_to_world` inverts it using the size argument it receives. The mouse wheel multiplies `zoom` by `1.1` per scroll step in either direction, with no bounds. A middle-button press over empty space starts a camera drag: each motion event subtracts the screen delta divided by `zoom` from `camera_offset`.

`edge_camera_movement` runs every frame while the window has mouse focus. Within an 8-pixel border band, it builds a direction vector scaled by penetration into the band and normalizes it. It then moves the camera at 300 screen pixels per second, divided by `zoom` to convert to world units. `EditorWorld.draw` draws grid lines at every multiple of `GRID_SIZE` across the visible world rectangle, then draws each room.

### Caveats

- Zoom is unbounded in both directions and always centers on the screen center, not on the cursor.

- A middle-button press over a room does not pan. It splits the room (see "Room splitting").

- `world_to_screen` reads the global `SCREEN_CENTER` and ignores its screen-size parameter, while `screen_to_world` derives the center from the parameter. Both agree because the main loop keeps `SCREEN_CENTER` current.

- `EditorRoom.draw` builds the entity transform from the global `camera_offset` rather than its `cam` parameter. The two are the same object in every call.

## Rooms, connections, and the editor world

### Goal

An `EditorRoom` is a polygon with an integer id and a list of vertices in world coordinates. Each room also carries a dictionary of edge connections and a list of placed entities. Edge `i` runs from vertex `i` to vertex `i+1`, wrapping at the end. A connection entry `connections[i] = (other_id, j)` declares that edge `i` is a portal onto edge `j` of the room with id `other_id`. An `EditorWorld` is a list of rooms. Rooms render so that convexity, connection state, and entity positions are all visible at a glance.

### Invariants

- Room ids are unique within a session. A class counter starting at 1 assigns them, and loading a file advances the counter past the largest loaded id.

- A room created by the Polygon tool is normalized so its shoelace signed area is nonnegative before it enters the world. Rooms from splits inherit their vertex order instead (see "Room splitting").

- Tool paths that create a connection always write both directions: `connections[i] = (B.id, j)` on room A and `connections[j] = (A.id, i)` on room B. Exceptions that break reciprocity are recorded in the caveats of the units that cause them.

### Verification

- A convex room draws with a dark gray fill, gray edges, and red vertex dots. Dragging a vertex to make it concave switches the fill to dark red and the edges to bright red on the next frame.

- Connected edges draw as thick translucent blue lines, and a dotted blue line joins the midpoints of each connected edge pair.

- Executed check (2026-08-22): creating rooms in one session assigns ids 1, 2, 3, and loading `cool_level_1.json` continues numbering above its largest id.

### Implementation

`EditorRoom.get_center` returns the vertex mean. `is_convex` walks consecutive vertex triples and returns False when two nonzero cross products disagree in sign (collinear triples are ignored). `move` translates every vertex.

`fix_winding(desired_sign, world)` computes the shoelace sum, treats a negative sum as `current_sign` True, and reverses the vertex list when the sign differs from the desired one. After reversing, it rebuilds the connection dictionary. For each old connection it finds the new edge whose midpoint is nearest the old edge midpoint (`find_closest_edge_index`). It keeps the connection only when that distance is under 30 world units. It updates the partner room's back-reference when the partner still points at this room.

`EditorRoom.detect_vertex_list_changes(world)` returns a context manager used around vertex insertion and deletion. On entry it records, for every connected edge, the fraction of the room perimeter at that edge's midpoint. On exit it maps each recorded connection to the new edge whose perimeter fraction is closest, with no distance cap. Partner back-references update the same way as in `fix_winding`.

Rendering (`EditorRoom.draw`): fill color (50, 50, 50) for convex rooms, (70, 0, 0) for concave. Unconnected edges draw opaque — gray width 4 on convex rooms, red width 6 on concave. Connected edges draw on a shared per-room alpha surface — blue (150, 150, 255, 128) width 7 on convex rooms, red (255, 0, 0, 128) width 9 on concave. Every connection also draws a dotted blue line between the two edge midpoints.

Vertices draw as red circles with radius `max(2, int(4 * zoom))`. Entities draw last, through a camera matrix. `draw_highlight` outlines the polygon in yellow (hover, width 3) or green (selected, width 5).

### Caveats

- The code comment on winding calls nonnegative shoelace area "counterclockwise". That is the y-up mathematical convention. On the editor's y-down screen, this vertex order appears clockwise.

- The perimeter-fraction remap in the change detector can silently drop a connection. When two old edges map to the same new edge, the second dictionary write overwrites the first.

- `fix_winding` silently drops a connection when no new edge midpoint lies within 30 world units of the old one.

- `is_spawn` and `selected` are initialized on every room and never read. Spawn rooms do not exist in this editor. The player position comes from a placed Player entity.

- A fully collinear vertex list passes `is_convex`, so a degenerate zero-area room counts as convex everywhere, including the save gate.

## Pointing: what the cursor is over

### Goal

Each tool answers "what is under the cursor" with a shared set of geometric queries so that highlights and clicks agree.

### Invariants

- `get_polygon_under_cursor` returns the containing room whose center is nearest the point, or None. Point-in-polygon is an even-odd ray cast.

- `get_nearest_vertex` and `get_nearest_edge` return the closest candidate strictly within their threshold, or None. Thresholds are in world units (vertex and edge picks use 8 or 10 depending on the caller).

### Verification

- Hovering a room with the Polygon or Move tool outlines it in yellow. Where two rooms overlap, the one whose center is closer to the cursor gets the highlight.

- With the Vertex tool, hovering within a few pixels of a vertex circles it in yellow. Slightly farther away but near an edge, a yellow insertion preview appears on the edge instead.

### Implementation

`point_in_polygon` is a standard crossing-number test with a `1e-10` guard against division by zero. `point_line_distance` measures the distance to a segment, clamped to its endpoints. `project_point_on_line` projects onto the segment's infinite line, without clamping.

`edges_are_collinear(a1, a2, b1, b2, tol)` requires the two direction unit vectors to have an absolute dot product within 0.01 of 1. It also requires the clamped segment distance from the point `b1` to the first edge to be within `tol`. `edges_share_vertex` compares edge index adjacency within one room and vertex equality (`==`) across rooms. `find_closest_edge_index` returns the edge whose midpoint is nearest a given point, plus that distance.

### Caveats

- Pick thresholds are world units, so the effective screen-space pick radius scales with zoom. At zoom 0.25 a vertex pick demands a hit within 2 screen pixels. The Entities tool divides by zoom instead and keeps a constant 15-screen-pixel radius, so pick feel differs between tools. Audit-relevant under the UX standard.

- Defect: `edges_share_vertex` compares vertices with `==`. Rooms built in-session store tuples, and rooms loaded from JSON store lists. A tuple never equals a list, so the shared-vertex guard fails between a loaded room and a new room. The Connection tool then connects such edges even when they share a vertex.

- Because `edges_are_collinear` clamps the distance to the first edge's segment, the test depends on which edge comes first and where `b1` sits. Two edges on one line can fail the test when `b1` lies far past the first edge's endpoints.

## Polygon tool: create, drag, and delete rooms

### Goal

The default tool. The designer clicks out a chain of vertices and closes it into a room. The same tool drags whole rooms and deletes rooms. New rooms automatically connect to edges they exactly coincide with.

### Invariants

- A room is only created from three or more proposed vertices.

- Every created room passes through `fix_winding` before it enters the world, so it enters with nonnegative shoelace area.

- Room creation, room deletion, and the end of a room drag each record one undo state.

### Verification

- Clicking three empty-space points and pressing Enter (or right-clicking, or clicking the first vertex again) creates a room. With snap on, all vertices lie on grid intersections.

- Drawing a second room that shares a full edge with the first (exact vertex coincidence, which snap makes routine) creates the connection automatically: the shared edge renders blue on both rooms.

- With no proposal active, dragging inside a room moves the whole room in grid steps. Right-clicking a room deletes it.

### Implementation

The tool keeps a `proposed` vertex list. A left click in empty space appends the snapped world point. A left click within 8 world units of any existing room vertex appends that exact vertex instead (vertex merge). Merged vertices are how a designer draws exact edge coincidence by hand.

A left click within 8 world units of the first proposed vertex closes the polygon. With three or more vertices, closing builds the room, fixes winding, adds it to the world, auto-connects, and records undo state. Enter and right-click close the same way. Escape discards the proposal and cancels a room drag.

With no proposal active, a left click inside a room starts a room drag with a center-relative offset. Motion moves the room by the cursor delta, rounded to whole grid steps when snap is on. Release records undo state. A right click on a room removes it from the world and records undo state.

Overlay drawing shows the proposal chain in yellow and proposed vertices in translucent red. When a merge candidate is highlighted, the candidate draws as a filled yellow circle and the last placed vertex turns green. Over empty space the overlay draws a snapped preview dot, and a dragged room gets a green outline.

`_auto_connect` compares every edge of the new room against every edge of every other room. When both endpoints coincide within `1e-5` in either order, it writes the reciprocal connection pair.

### Caveats

- Defect: deleting a room does not touch other rooms' connections. Every partner connection keeps pointing at the deleted id. The renderer tolerates this (missing partner lookups return None), and the save path writes these dangling connections to disk. The comment above the export loop says "Only save valid connections", which the code does not do — nothing validates them.

- Closing a proposal with fewer than three vertices (clicking the first vertex again, or right-clicking) silently discards the proposal.

- `_auto_connect` overwrites any existing connection on the partner edge, leaving the partner's previous partner with a stale one-directional connection.

- Deletion has no confirmation and no way to recover except Ctrl+Z. Audit-relevant under the UX standard.

- While a proposal is active, `what_is_mouse_over` reports only nearby vertices, so room hover highlights disappear until the proposal is closed or canceled.

## Vertex tool: move, insert, and delete vertices

### Goal

Reshape existing rooms one vertex at a time: drag a vertex, insert a vertex on an edge, or delete a vertex. Edge connections stay attached to the geometrically corresponding edges.

### Invariants

- A vertex deletion is refused when the room has only three vertices.

- Vertex insertion and deletion run inside `detect_vertex_list_changes`, so connections remap to the closest perimeter position and partner rooms are updated.

- Vertex insertion and deletion, and the release of a vertex drag, each record one undo state.

### Verification

- Dragging a vertex moves it with grid snap. Insertion on an edge places the new vertex at the snapped point. When snapping would move the point more than 8 world units, the vertex lands at the cursor's perpendicular projection onto the edge instead.

- Deleting a vertex of a quadrilateral leaves a triangle. Right-clicking a triangle's vertex does nothing.

- Executed check (2026-08-22): a vertex drag across the opposite edge of a triangle flips the shoelace sign from positive to negative. The polygon stays convex, and nothing corrects the winding (see caveats).

### Implementation

`what_is_mouse_over` prefers a vertex within 8 world units, then an edge within 8 world units. A left press on a vertex starts a drag and switches the system cursor to a move cursor. The drag stores the room, the vertex index, a cursor offset, and the room's current winding sign. Motion writes the snapped position straight into the vertex list. Release clears the drag, restores the arrow cursor, and records undo state. Escape cancels the drag without recording, leaving the vertex wherever the last motion put it.

A left press on an edge (with no vertex nearby) inserts a vertex after that edge's start, at the snapped cursor point. When snapping would displace the point by more than 8 world units, the insertion uses the perpendicular projection onto the edge's line instead. A right press on a vertex deletes it when more than three vertices remain. The overlay circles the hovered vertex or the projected insertion point in yellow and fills the dragged vertex in green.

### Caveats

- Defect: the tool's help text promises "the tool preserves the original winding (auto-corrects if reversed)", and a code comment says structural changes are handled on mouse release. Neither is implemented. The drag stores the original winding sign and never reads it again, and release only records undo state. A drag can therefore reverse a room's winding. The reversed room still passes the convexity save gate, and the file saves with negative shoelace area (verified by execution).

- Dragging a vertex bypasses the connection remap entirely — only insertion and deletion use the change detector. Dragging cannot change edge indices, so connections stay index-correct, but a drag that makes an edge degenerate leaves its connection in place.

- The edge pick reaches 8 world units past an edge's endpoints, and neither the snapped point nor the unclamped projection is confined to the edge. A click just past an endpoint can insert a vertex outside the original segment.

- After a vertex deletion, the stored hover highlight can reference the removed index for one frame. The draw code catches the `IndexError` and skips the highlight.

## Connection tool: link and unlink edges

### Goal

Create the portal connections that make the world non-Euclidean. In normal mode the designer clicks two unconnected edges to join them. In matched-edge mode (Shift) the tool highlights edges that already lie collinear and adjacent. The designer connects them by clicking pairs or by box-selecting a group. Right-click breaks a connection.

### Invariants

- Only unconnected edges are selectable: `what_is_mouse_over` returns None for an edge that already has a connection.

- Every connection this tool creates is written on both rooms.

- In normal mode, two edges that share a vertex are refused. In matched-edge mode, the two edges must belong to different rooms and be collinear within 2 world units. Their closest endpoint pair must lie within 8 world units.

- Breaking a connection removes both directions and records one undo state.

### Verification

- Clicking one unconnected edge draws it with a blue glow. Clicking a second edge of another room connects them: both render as thick blue connected edges with a dotted line between their midpoints.

- Holding Shift highlights every unconnected edge that has a collinear partner nearby. Box-dragging with Shift over a seam of touching rooms connects every eligible pair inside the box in one gesture.

- Right-clicking a connected edge removes the connection from both rooms.

### Implementation

The tool keeps `first_edge`. In normal mode a left click on a highlighted edge arms it as `first_edge`. The second click checks `edges_share_vertex` and writes the reciprocal pair. Normal mode has no collinearity requirement, and the two edges may belong to the same room. A room can therefore connect to itself on non-adjacent edges.

With Shift held, a click on a highlighted edge arms or pairs the same way, but the pair check is the matched-edge rule (different rooms, collinear within `MATCHED_EDGE_FUDGE` = 2, endpoints within `MATCHED_EDGE_CONNECTION_THRESHOLD` = 8). A Shift-click on empty space starts a box selection. On release, every pair of edges whose midpoints fall in the box is tested against the matched-edge rule, and each passing pair connects. Escape clears the armed edge and the box. Right-click looks up the nearest edge within 10 world units regardless of highlight rules. It pops the connection, deletes the partner's back-reference, and records undo state.

The overlay draws armed and hovered edges with a two-layer blue glow. In Shift mode it also scans every unconnected edge pair each frame and glows every edge that has an eligible partner. The selection box draws as a cyan outline.

### Caveats

- Defect: no connection-creation path records an undo state. Ctrl+Z after creating connections skips back to whatever the previous recorded state was, discarding other work along with the connections. Breaking a connection does record.

- The help text claims that in matched-edge mode "clicking one creates a connection with its matched partner (pre-highlighted in blue)". The code requires clicking both edges (or box-selecting). One-click pairing does not exist.

- The tuple-versus-list equality defect (see "Pointing") disables the shared-vertex guard between loaded rooms and new rooms.

- Because connected edges are invisible to `what_is_mouse_over`, there is no way to select a connected edge except right-clicking to break it.

- The Shift-mode highlight pass compares all unconnected edge pairs every frame, which grows quadratically with edge count.

- An armed `first_edge` survives tool switches and world reloads, and can therefore reference a room that is no longer in the world. Pairing then writes a connection onto an orphaned room object, which is lost silently.

## Entities tool: place game entities

### Goal

Place, move, and delete instances of the game's entity classes inside rooms. A second ribbon row below the toolbar offers one button per placeable class, with a live preview sprite. The level therefore carries its own Player start and Enemy placements.

### Invariants

- The class list comes from the game: `get_all_entity_subclasses()` in `main.py`, which returns every `Entity` subclass except the ones named `Bullet` and `LightningDart`. In the prototype that means Player and Enemy.

- An entity can only be placed by clicking inside a room. The `Entity` constructor itself appends the instance to the room's entity list, and the tool appends nothing.

- Placement, deletion, and the end of an entity drag each record one undo state.

- The selected class persists across tool switches for the whole session (stored on the class, default Player).

### Verification

- The passing regression test (see "The regression test") places three enemies by simulated clicks. Exactly three entities appear in the room and in the export, with distinct positions.

- Selecting Enemy in the ribbon and clicking inside a room draws an enemy triangle sprite there. Hovering it shows a yellow halo, dragging shows green, and releasing in another room re-parents it.

- Dragging an entity to empty space outside every room deletes it, as the help text states.

### Implementation

Construction imports the entity classes from `main.py` and renders one preview image per class. The preview instantiates the class with a dummy room and calls the game's own `Entity.draw` with a 0.8-scale matrix onto a 60 by 60 surface. Failures to instantiate print a warning and skip the preview.

Any mouse press with `pos[1] < 150` is treated as a ribbon interaction: a hit on a class button (any mouse button) selects that class. Below the ribbon, a left press inside a room first tries to grab an entity within 15 screen pixels (radius `15 / zoom` in world units). With no entity in range, the press instantiates the selected class at the click's world position. Entity positions are not grid-snapped.

Motion writes the dragged position directly. Release inside a different room moves the entity between the two rooms' lists and updates `parent_room`. Release outside every room removes the entity from its room. Right-click arms a delete candidate on press. The release deletes the candidate only when it still lies within the pick radius of the same entity. Escape cancels a drag or an armed delete without recording.

The overlay draws the ribbon (dark strip from y = 80 to 150, class buttons with hover, active, and label states), a yellow halo on the hovered entity, and a green halo on the dragged entity.

### Caveats

- Entity positions in the editor are absolute world coordinates. The game loader converts them to room-local coordinates on load (see "The level JSON format").

- A code comment records that a duplicated `room.entities.append` was removed from placement, because the constructor already appends. The import path kept the same double-append and still has it (see the format unit's caveats).

- Latent defect: a class whose preview instantiation fails is skipped from the preview cache but stays in the class list. Drawing the ribbon would then raise `KeyError`. Player and Enemy both instantiate cleanly today, so the path never fires.

- The ribbon claims all clicks above y = 150, including right-clicks and the 100-to-150 band below the main toolbar, so entities cannot be manipulated there.

- Escape during a drag leaves the entity at its dragged position without recording an undo state.

- Nothing prevents placing multiple Players. The game keeps the first and discards the rest with a console warning.

## Move tool: select and move rooms together

### Goal

Select any set of rooms and drag them as a group. Because connections are portal links rather than shared geometry, moving rooms apart never breaks their connections. This is the primary way to lay out a non-Euclidean map so all rooms remain visible.

### Invariants

- Dragging moves every selected room by the same delta, measured from the vertex positions at drag start. With snap on, the delta rounds to whole grid steps.

- Connections are untouched by movement: edge indices do not change, so every connection stays exactly as it was regardless of distance.

- Every left-button release in this tool records one undo state.

### Verification

- Left-clicking a room selects it (green outline). Shift-click adds to the selection. Right-click toggles a room in and out of the selection. Escape clears it.

- Dragging on empty space draws a cyan box. Releasing selects the boxed rooms — a down-right drag selects rooms whose bounding boxes touch the box, an up-left drag (dashed box) selects only rooms fully inside it.

- Dragging two connected rooms apart leaves their shared edge pair blue and the dotted midpoint line stretching between them.

### Implementation

A left press on a room keeps the existing selection when the room is already in it. Otherwise the press replaces the selection, or appends to it with Shift held. The press then starts a drag by snapshotting every selected room's vertex list. Motion recomputes each room's vertices as snapshot plus snapped delta. A left press on empty space starts a box selection instead.

On release, `box_select_rooms` collects rooms by bounding-box intersection ("inclusive") or containment ("exclusive"). Drag direction chooses the mode: down-right is inclusive, up-left is exclusive, and mixed directions are inclusive. Release merges or replaces the selection per Shift and records undo state. Right-click toggles membership. A middle press on a room triggers a room split (next unit). The overlay outlines selected rooms in green, box-preview rooms in yellow, and draws the box solid for inclusive mode or dashed for exclusive.

### Caveats

- Selection-only clicks also record undo states (every left release records), so the undo stack fills with states in which nothing about the world changed.

- The selection list holds room object references. After Ctrl+Z, Load, or New replaces the world's rooms, the stale selection still references the old objects. Dragging it then moves rooms that are no longer in the world. Escape clears it.

- The help text says middle-click "splits a concave room into two convex parts". The split applies one chord per click, so a room with several reflex vertices can come out still concave. The Move tool's own middle-click handler also stacks on the global one (next unit).

## Room splitting

### Goal

Turn a concave room into convex pieces, because the save gate refuses concave rooms. A middle click on a room splits it by a chord at a reflex vertex. When no chord works, a fallback rebuilds the polygon as an inscribed-in-a-circle approximation.

### Invariants

- `fix_room` always returns at least one replacement room: the two chord parts, or one circle-mapped room.

- A chord split joins the two parts with a reciprocal connection across the chord edge.

- Chord candidates must not intersect any non-incident edge and their midpoint must lie inside the polygon.

### Verification

- Middle-clicking an L-shaped room splits it into two quadrilaterals joined by a blue connected edge along the cut.

- Executed check (2026-08-22): splitting an L-shaped room whose edge was connected to a neighbor leaves the neighbor's connection pointing at the deleted room's id (see caveats).

- Executed check (2026-08-22): middle-clicking a convex 100-unit square replaces it with an irregular quadrilateral. Three sides keep length 100 and the closing side has length 53 (see caveats).

### Implementation

`fix_room_by_chord` scans vertices for the first reflex vertex (negative cross product of the neighboring edges). It then tries chords from that vertex to each non-adjacent vertex. The first chord that intersects no other edge and whose midpoint lies inside the polygon wins. It cuts the vertex list into `verts[i..j]` and `verts[j..] + verts[..i]` and builds two new rooms. The old room's connections redistribute: each old connection goes to whichever part has the nearest edge midpoint, when that distance is under 30 world units. The chord edge of each part (the last edge of each new vertex list) gets the reciprocal part-to-part connection.

When no reflex vertex or no valid chord exists, `fix_room_by_circular` runs instead. It solves by 50 bisection steps for a circle radius where the polygon's edge lengths fit as chords around the full circle. It rebuilds the polygon on that circle around the old vertex mean, starting at angle zero. Connections remap by the same nearest-midpoint rule.

Two callers exist. `process_mouse_event` (any tool): a middle press on any room replaces it with `fix_room`'s output and records undo state. This caller does not repair other rooms' references to the old id. `MoveTool.handle_event`: its own middle press handler does the same replacement. It then rewrites every connection in the world that pointed at the old room id to point at `(parts[0].id, 0)`. That target is the first part's edge 0, regardless of geometry.

### Caveats

- Defect: both split functions update partner rooms with the old room's id (`target.connections[...] = (room.id, new_idx)`), and the callers then delete that room. Every neighbor of a split room ends up with a dangling connection (verified by execution). The `fix_winding` remap does this correctly (same room object, same id). The split functions copied the pattern into a context where the id dies.

- Defect: the global middle-click handler applies to convex rooms too, and the circular fallback distorts them. Its bisection upper bound (`total_perimeter / 2π`, or twice the longest half-edge) can exclude the true circumradius. The rebuilt polygon then does not close with the original lengths — the verified square became three sides of 100 and one of 53. A stray middle click on a finished room silently corrupts it, and the room also loses its original orientation (rebuild starts at angle zero from the centroid).

- Defect: with the Move tool current, a middle click splits twice. The global handler splits the room first. The Move tool's handler then finds one of the new parts under the cursor and applies `fix_room` to it. The part is convex, so the circular fallback distorts it. One click on a concave room with the Move tool active therefore produces a chord split plus one circle-distorted part (both handlers record undo states).

- The Move tool's reference rewrite points every old inbound connection at edge 0 of the first part, which is geometrically arbitrary.

- The chord split applies exactly one cut. Deeply concave rooms need repeated clicks, and each click multiplies the dangling-reference damage above.

- Neither split path calls `fix_winding`. The parts inherit the source room's vertex order, so a reversed-winding source yields reversed-winding parts.

## Undo and redo

### Goal

Every editing action can be undone and redone, with the whole world snapshotted per step.

### Invariants

- `UndoManager` keeps two stacks of deep-copied `EditorWorld` snapshots. `record_state` pushes a copy of the current world onto the undo stack and clears the redo stack.

- `undo` pushes a copy of the current world onto the redo stack and returns the popped undo snapshot. `redo` mirrors it. Both return the current world unchanged when their stack is empty.

### Verification

- Executed check (2026-08-22): after one room is created, the first Ctrl+Z leaves the room in place and the second Ctrl+Z removes it. This reproduces the off-by-one described in the caveats against the real `UndoManager`.

- Ctrl+Z immediately after Load or New restores the pre-Load or pre-New world in one press.

### Implementation

One global `undo_manager` exists. `level_editor` records the empty world at startup. Tool actions record after the mutation. Recording actions: room create, room delete, room drag release, vertex insert, vertex delete, and vertex drag release. The list continues with entity place, entity delete, entity drag release, connection break, box-select release, and room split.

Two toolbar actions record before the mutation instead: Load records, then replaces the rooms, and New records, then clears them. `process_key_event` rebinds the loop's `world` variable to the snapshot returned by `undo` or `redo`.

### Caveats

- Defect: because tool actions record after mutating, the top of the undo stack always equals the current state. The first Ctrl+Z after any tool action is a visible no-op, and every action needs one extra press. Load and New record before mutating and undo in one press, so the off-by-one is inconsistent across actions.

- Defect: connection creation records nothing (see the Connection tool), so those changes cannot be reached as an undo boundary at all.

- Undo swaps the world object, but tools keep references into the old one (Move selection, armed connection edge, entity drag). Acting on those references edits orphaned rooms.

- Escape-canceled vertex and entity drags leave mutations that no snapshot bounds.

- Snapshots are unbounded deep copies of the entire world, one per action, including the selection-only records from the Move tool.

## Saving, loading, and the file dialog

### Goal

Save the world to a level JSON file and load one back, through toolbar buttons and the S key, with an in-window file dialog. A save is refused while any room is concave, because the game expects convex rooms. The refusal points the designer at the offending room.

### Invariants

- No file is written while a concave room exists. The refusal shows a red warning box naming the concave-room count, with a "Go To" button that centers the camera on the first one.

- Save with a current file writes to it directly. Save As always asks for a name. A successful Save As or Load makes that file current.

- Loading replaces the world's rooms in place, applies the file's grid and toggle settings, and records the pre-load state for undo.

### Verification

- With one concave room, pressing S shows "Cannot save - there is 1 concave polygon." in the bottom-right corner. Clicking Go To centers the camera on it. After splitting the room convex, S opens the save dialog (first save) and writes the file.

- Toolbar Load opens the dialog, and picking a level file replaces the current world with the file's rooms, connections, and entities.

- New empties the world and clears the current file, and Ctrl+Z restores the previous world.

### Implementation

`handle_save` (S key) collects concave rooms. If any exist it calls `shake_camera` and stores the list in `concave_warning`. Otherwise, with Shift held, it asks for a filename and saves (Save As). Without Shift it saves to the current file, or asks for a filename when none is set. The toolbar Save and Save As buttons run the same gate through `process_toolbar_click`.

The warning box renders each frame while `concave_warning` is set. Its Go To button is not part of event routing. The main loop polls the mouse each frame. A pressed left button over the box centers the camera on the first concave room and clears the warning.

Toolbar New records undo state, clears `world.rooms`, and clears the current file. Toolbar Load records undo state, imports the chosen file, and assigns the loaded rooms into the live world list.

`pygame_file_dialog` is a modal 400 by 300 dialog with its own event loop at 30 fps. It shows a directory listing (directories first, then files, case-insensitive), a text input in save mode, and OK and Cancel buttons. Clicking a directory enters it, and ".." goes up. In open mode, clicking a file returns it immediately.

In save mode, typed characters append to the name (`event.unicode`), Backspace deletes, and Enter or OK confirms. The return value joins the current directory with the typed name. Escape or Cancel returns None, and an empty name confirms as None. A `QUIT` event inside the dialog exits the whole process.

### Caveats

- Defect: `shake_camera` does not shake. Its own comment says so. The function loops for 500 ms, moves `camera_offset`, and flips the display without redrawing the scene. The save refusal therefore presents as a half-second freeze. The visible refusal feedback is only the warning box.

- Defect: the dialog cannot scroll. `scroll_offset` exists but nothing changes it, and the list area shows 8 rows. Files beyond the first 8 entries of a directory can never be chosen.

- Defect: the toolbar Save button does nothing when no file is current — no dialog, no message. The S key in the same state opens the save dialog. Audit-relevant inconsistency under the UX standard.

- The Go To click is polled outside event routing, so the same click also reaches the active tool through the normal path. With the Polygon tool current, it plants a stray proposed vertex under the button.

- The dialog never asks before overwriting an existing file, and it accepts any typed name with no extension handling. Clicking a file in save mode highlights it without copying its name into the input field.

- The concave gate is the only validation. Winding is not checked (a convex room with reversed winding saves), and dangling connections are written as-is.

- Loading leaves `EditorRoom._id_counter` past the file's largest id, and pushes the file's `grid_size`, `snap_to_grid`, and `edge_camera_movement` into the editor's global settings.

## The level JSON format

### Goal

One JSON document holds a complete level: editor settings, rooms with their vertices, the connection graph, and entity placements. The editor writes and re-reads it, and the game's `load_level_from_file` consumes the same format.

### Invariants

- `export_level_to_json` writes: a top-level `version` string `"1.0"`, a `meta` object with `grid_size` (integer), `snap_to_grid` and `edge_camera_movement` (booleans), and a `rooms` array.

- Each room object holds `id` (integer), `vertices` (array of `[x, y]` pairs in absolute world coordinates), `connections` (object mapping the edge index as a string to `{"target_room": id, "target_edge": index}`), and `entities` (array of `{"type": class name, "pos": [x, y]}` with float absolute world coordinates).

- Because tool paths write both directions of every connection, a well-formed export lists each connection twice, once per room. All five parseable repository artifacts are fully reciprocal, with no dangling ids and no self-connections.

### Verification

- The regression test exports a one-room world and finds the room, its three entities, and their distinct positions in the parsed JSON.

- Executed check (2026-08-22): all repository level files except `level_with_enemies.json` parse and are reciprocal. `cool_level_1.json` holds 33 rooms, 80 connection entries, and 280 entities.

### Implementation

Export walks `world.rooms` in order and dumps with `indent=2`. Vertex numbers appear as the editor holds them — integers for snapped points, floats otherwise. Entity positions are forced to float. Nothing else about a room is serialized: `is_spawn` and `selected` do not exist in the format.

`import_level_from_json` reads `meta` with the current global settings as defaults and overwrites the globals from it. It builds an `EditorRoom` per room object and restores `id` and `connections` (keys back to int, values to tuples). Each entity instantiates through the class registry from `main.py`, and the loop then appends the instance a second time (the constructor already appended it — the doubling defect in the caveats). An unknown `type` prints a console warning and is skipped. It finally sets the room id counter to the maximum loaded id plus one. `version` is written as a constant and read by nobody, in the editor or the game.

For the game side (recorded here because the editor defines the format): `main.load_level_from_file` recenters each room's vertices about their mean. It converts entity positions to room-local by subtracting that mean. It reads `meta.grid_size` only (default 20 against the editor's default 50) for the floor texture, and ignores `version`, `snap_to_grid`, and `edge_camera_movement`.

The game loader applies a connection only from the room with the smaller or equal id, expecting reciprocal files. It warns and skips a connection whose target room id does not appear in the file. It keeps the first Player and removes any further ones with a warning. When the file holds no Player, it creates a default Player in the first room.

### Caveats

- Defect: `level_with_enemies.json` in the repository is not valid JSON — a trailing comma after an entity object, the signature of a hand edit. Neither the editor nor the game can load it.

- Defect: `import_level_from_json` appends each entity twice — the `Entity` constructor appends the instance to `room.entities`, and the import loop appends it again. Loading therefore doubles every entity in memory, and a load-save cycle doubles them on disk (verified by execution: `level.json` holds 8 entity entries, loads as 16, and re-saves as 16). The game loader constructs entities once and does not double.

- The repository level files carry the damage: `level.json`, `cool_level_1.json`, `simple_corridors_w_enemies.json`, and `squares.json` all contain entity pairs at identical positions, including duplicate Players (`cool_level_1.json` has 8 Player entries). A code comment in the Entities tool also records a removed placement double-append (see that unit). The game discards extra Players with a warning and spawns duplicate enemies stacked.

- The format offers no schema validation on either reader. A room without `id` or `vertices` raises `KeyError`, and `rooms`, `connections`, `entities`, and `meta` all default to empty when absent.

- Files written after in-editor deletions or splits can contain connections pointing at ids that no longer exist (see the Polygon tool and Room splitting). The game loader warns and skips them.

- The editor can save rooms with reversed winding (see the Vertex tool). The format does not record winding, and the game loader does not normalize it.

## The regression test

### Goal

`test_leveledit.py` holds one test that guards the entity double-append fix. Three simulated placement clicks must produce exactly three entities in the room. The export must hold exactly three as well, all at distinct positions.

### Invariants

- The test drives the real `EntitiesTool.handle_event` with synthetic `MOUSEBUTTONDOWN` events and the real `export_level_to_json` into a temporary file. Only the coordinate transform, the room-under-cursor lookup, the undo manager, and the display are mocked.

### Verification

- Executed 2026-08-22 with the pinned dependencies (`pygame==2.5.2`, `numpy==1.24.3`, `networkx==3.1`, Python 3.11) under the SDL dummy video driver: 1 test, OK, 0.04 s.

### Implementation

`setUp` initializes Pygame with a mocked `set_mode`, resets the editor's global settings, and replaces the global `undo_manager` with a `MagicMock`. The test builds a square room, constructs an `EntitiesTool`, and selects the `Enemy` class from the tool's own class list. It patches `screen_to_world` to the identity and `get_polygon_under_cursor` to return the room. It fires left-click events at three positions, asserts the room holds three entities, and exports. It then asserts the JSON holds one room with three entities whose position tuples are all distinct.

### Caveats

- The manifest excludes this file from the UX standard as development harness.

- The test runs against the current interpreter's installed packages. Under Python 3.14 with pygame 2.6.1 the import of `leveledit` itself fails inside `pygame.font`, before any test logic runs. The pinned requirements are load-bearing.

- Placement clicks must land at `y >= 150`, or the tool treats them as ribbon clicks. The chosen positions (y of 150 and 200) sit outside the ribbon band by construction of the `<` comparison.

- The test covers placement only. The import path's entity doubling (see "The level JSON format") has no test.
