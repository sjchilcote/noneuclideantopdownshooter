# MARATHON STUDY — a reference for PERIHELION's diegetic overhaul

*Compiled from (1) direct inspection of the three Aleph One Steam releases
installed locally, and (2) Hamish Sinclair's "Marathon's Story"
(marathon.bungie.org), read across a substantial sample of terminal-transcript
pages and "Facts and puzzling things about..." analysis pages spanning all
three games. Bungie's terminal prose is copyrighted; this document analyzes
structure, craft, and convention, and quotes only briefly (for criticism/
analysis) with attribution. Nothing here is extracted for reuse as content.*

*Local sources inspected (paths on this machine):*
- `~/.local/share/Steam/steamapps/common/Classic Marathon/` (Marathon 1)
- `~/.local/share/Steam/steamapps/common/Classic Marathon 2/` (Marathon 2)
- `~/.local/share/Steam/steamapps/common/Classic Marathon Infinity/`

---

## 0. LOCAL FILE STRUCTURE — what the installed scenarios actually look like on disk

Confirmed by `file(1)`, a Python MacBinary-header parse, and `strings` against
the isolated data forks (methodology below).

**Container format.** Every scenario's map (`Map.scen` for M1, `Map.sceA` for
M2/Infinity) is a **MacBinary-encoded classic-Mac dual-fork file**: a 128-byte
MacBinary header, then a data fork, then a resource fork. Parsing the header:

| Scenario | file type/creator | data fork | resource fork |
|---|---|---|---|
| Marathon 1 | `scen` / `26.2` | 3,863,478 B | 319 B |
| Marathon 2 | `sce2` / `52.4` | 5,479,687 B | 14,998,386 B |
| Marathon Infinity | `sce2` / `26.∞` | 9,889,973 B | 10,863,690 B |

Two things worth stealing as *flavor*, not mechanism: (1) Bungie's app
**creator code doubled as a version signature** — `26.2` for the original,
`52.4` for the sequel, and `26.∞` (a literal infinity glyph) for the
"infinite" expansion. A diegetic system that encodes its own version/edition
into an otherwise-inert file-format field is a nice piece of texture. (2) For
M1 almost everything lives in the *data* fork (the resource fork is
vestigial); for M2/Infinity the resource fork balloons to carry additional
resources (image previews etc.) alongside the same data-fork payload — the
container format evolved without breaking backward compatibility, which is
its own kind of world-building (a piece of tech visibly aged between games).

**Per-level container (the "wad").** Inside the data fork, `strings` on the
raw bytes recovers a stable set of short all-caps chunk tags repeated across
all three games' map files: `PNTS`/`EPNT` (points/endpoints), `LINS` (lines),
`SIDS` (sides/wall surfaces), `POLY` (polygons/rooms), `OBJS` (object —
monster/item/player — placements), `LITE` (lights), `PLAT` (platforms: doors,
lifts), `NOTE` (map notes), and, in M1 only, a `NAME` tag. Each level is one
self-contained chunked record inside one shared file — geometry, object
placement, and lighting all travel together per-level, the way PERIHELION's
`levels/l0N.json` bundles `rooms`, `entities`, `doors`, and `lore` into one
file per level (`game/perihelion/levels.py`).

**Terminal text is NOT plain-recoverable by `strings`.** I searched the
isolated data forks of all three map files for the literal names "Durandal",
"Tycho", "Leela", "S'pht", "Thoth" — zero hits in all three. Level *names*
("Requiem For a Cyborg", "The Big House", "Aye Mak Sicur" — all recovered
cleanly as plain ASCII runs) sit in the same container ungarbled, so the
container isn't encrypted wholesale. The honest reading is: terminal prose is
stored as a **distinct, more tightly-packed payload** than the level-name
field — consistent with Marathon's terminal system compiling text into
grouped/paginated records with interleaved control codes (style, pause,
graphic-embed markers) rather than storing it as loose flat strings. I did
not reverse-engineer the exact packing (out of scope, and Bungie's file
format for terminal groupings is not something I extracted) — flagging this
as a structural inference with an honest gap, not a verified fact. Structural
lesson worth keeping regardless: **terminal text was engineered as a
first-class typed payload (the game had a purpose-built format for it, not a
generic string table)** — supports Part B's point that formatting *is*
content in Marathon.

**Assets are separate, shared, numerically-referenced files — never
embedded per-level.** Every scenario ships four sibling files alongside the
map: `Physics` (monster/weapon/projectile tuning tables — confirmed via
`strings` on M1's `Physics.phys`: raw binary with only five legible tags,
`mons`/`weap`/`proj`/`effe`/`phys`, i.e. pure numeric parameter blocks, zero
prose), `Shapes` (6.4–11.4 MB collections of wall textures and sprites),
`Sounds` (1–18.5 MB SFX banks), and, from M2 on, `Images` (a `PICT`-resource
file of static art — title screens, interface chrome — confirmed via `file`
showing "17 × PICT" resources in Infinity's `Images.imgA`). A level's `OBJS`
entries reference these by numeric ID; nothing is duplicated per-level. This
is exactly the separation PERIHELION already has: `levels/*.json` hold
geometry/entities/lore; `game/assets/{sfx,art,fonts}` are shared pools
referenced by type string, not embedded.

---

## A. LEVEL-AS-PLACE CONVENTIONS

*(Web-sourced findings from marathon.bungie.org integrated below — see
per-rule citations. Local findings above (0) established the container-level
separation of geometry/text/assets that underwrites several of these.)*

<!-- TODO: fold in agent reports (level-as-place structural study,
M1/M2/Infinity terminal transcript studies) -->

---

## B. TERMINAL WRITING CRAFT

<!-- TODO: fold in agent reports (AI voice deep dive, buried-depth lore,
typography/secrets study, M1/M2/Infinity terminal transcript studies) -->

---

## C. DIALOGUE NORTH-STAR RUBRIC

<!-- TODO: derive from AI voice deep dive agent report -->

---

## D. WHAT PERIHELION SHOULD STEAL STRUCTURALLY

<!-- TODO: map A/B findings onto game/perihelion/levels.py, conversations.py,
tools/levelgen/campaign.py, prose-spec-portable.md -->

### D.0 What PERIHELION already has right (baseline, confirmed by reading the code)

Before prescribing changes: a direct read of `game/perihelion/levels.py`,
`game/perihelion/conversations.py`, `tools/levelgen/campaign.py`,
`EDITOR.md`, and `NARRATIVE_DESIGN_DOC.md` shows the project already
converges on several Marathon conventions independently:

- **Terminals are point-fixtures, not full-wall set-dressing.** `TerminalSpec`
  (`levels.py:37-40`) is `(room, pos, text)` — a placed object in room-local
  space, scanned by proximity (`sim.py:_terminal_scan`) and rendered as a
  marker (`render.py:_draw_exit_and_terminals`), exactly Marathon's wall-panel
  convention (§A below) rather than ambient environmental text.
- **A secret-door convention already exists and already matches Marathon's:**
  `EDITOR.md` documents that a door keyed `"shoot"` "renders in-game as an
  ordinary wall with a hairline crack and opens to gunfire" — this is the
  same mechanic Marathon uses for several secret walls (confirmed by the web
  research below); PERIHELION should keep this and use it deliberately rather
  than incidentally.
- **Radio lines are trigger-keyed** (`RadioLine.trigger`: `start` /
  `enter_room:<idx>` / `kills:<n>` / `pickup:<key>` / `exit` —
  `levels.py:44-46`) — functionally Marathon's checkpoint/event-based
  terminal framing, already implemented as engine-native triggers rather than
  a cutscene system.
- **A two-name dual-vocabulary system already exists**
  (`NARRATIVE_DESIGN_DOC.md` §8.3: "the Adversary" vs. "exogeometric
  entities", "the Ark" vs. "the sample vessel", etc.) — this is structurally
  identical to how Marathon's terminal writers let each AI/faction name the
  same object differently and never gloss the discrepancy.
- **`conversations.py`'s existing Ratio/Commando exchanges already practice
  several Marathon-derived craft rules**: Ratio "footnotes" rather than
  answers directly ("...West ring. The junction. Records." after being asked
  a direct question), holds beats of dead air (bare `"..."` lines, called out
  explicitly in the module docstring), and reveals surveillance
  incrementally rather than declaring it ("Since Coolant Row... I took the
  feed. All of it. That is the disclosure.") — this is the Durandal
  "confession structure" pattern (see §B). This baseline should be the floor
  the rubric in §C is checked against, not the target.

---

*Executive summary delivered separately in the final chat message per the
task instructions.*
