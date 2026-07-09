# The PERIHELION level editor

```bash
uv run python -m perihelion.editor                  # blank canvas
uv run python -m perihelion.editor levels/l03.json  # open a level
```

The editor is a Euclidean drafting view of a non-Euclidean world: rooms are
laid out on an infinite canvas, and connections — which need not make any
spatial sense in-game — are drawn as colored arcs between edges. Cyan arcs
are ordinary connections, magenta are explicit-transform connections, amber
are keyed doors, red are self-connections (mirrors).

Rooms placed flush against each other connect automatically when the level
loads: a shorter wall touching a longer one becomes a doorway (the builder
splits the long wall). Everything impossible is authored with the connect
tool.

## Keys

| Key | Action |
|---|---|
| MMB drag / arrows | pan |
| wheel | zoom to cursor (cycles entity palette while in E mode) |
| G / S / I | toggle grid / snap / edge-index labels |
| click | select room, vertex, entity, or connection (nearest wins) |
| drag vertex | reshape a room — concave vertices flash red and block saving |
| RMB drag (or M, then drag) | move a room with its entities and markers |
| DEL / Backspace | delete selection (room deletion reindexes the whole file) |
| Ctrl+Z / Ctrl+Y | undo / redo |
| R, then drag | draw a rectangular room |
| P, click vertices, Enter | draw a polygon room (winding auto-corrected) |
| E, then `[` / `]` or wheel | entity palette; click to place |
| C, click edge, click edge | connect two edges — same edge twice makes a mirror |
| C, Shift on the second edge | make it a keyed door (prompts for the key) |
| X | delete the selected connection |
| Ctrl+S | save (validation-gated: convexity, winding, spawn, edge conflicts) |
| Ctrl+N | new blank level |
| F5 | save to a temp file and test-play it; F5 again restarts |
| Esc | cancel the current tool |

## Notes

- The player spawn and exit are placed from the entity palette like any
  other entity; placing a new one moves the existing marker.
- Terminals prompt for their text on placement.
- A door with the key name `shoot` is a secret: it renders in-game as an
  ordinary wall with a hairline crack and opens to gunfire.
- Edge lengths on connected pairs should match; the engine scales mismatched
  pairs, which reads as a funhouse lens — the editor warns above 2%.
