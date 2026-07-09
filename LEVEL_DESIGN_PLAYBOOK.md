# LEVEL DESIGN PLAYBOOK — PERIHELION
### A place-first authoring reference for `tools/levelgen/campaign.py` and the level editor

*Synthesized from `MARATHON_STUDY.md` Part A (level-as-place conventions) and Part D
(structural recommendations), `design_document_2.md` §8 (the escalation curve),
`NARRATIVE_DESIGN_DOC.md` §4 and §9, and a direct read of `game/perihelion/levels.py`
and `game/perihelion/render.py`'s per-room-kind prop generators. Format follows the
numbered-principle / terse-rationale / concrete-do-don't convention of
`gauntlet/ux-principles-web-apps.md`. `prose-spec-portable.md` governs all prose this
document or any terminal/radio text produces — nothing here licenses self-grading
narration or uniform sparkle in level text.*

---

## 0. The Complaint This Document Answers

Director's verdict on the pre-overhaul levels: *"They feel like game levels, not a
space station... Why are these terminals just lying around in random spots? And guns
and ammo?"* That is a specific, checkable diagnosis, not a mood: props and fixtures
were placed by combat-pacing logic alone (spread enemies for a fair fight, drop loot
where the fight ended) with no place-logic layered underneath. The fix is not "add
detail" — `render.py` already generates dense per-room-kind dressing once a room
carries a `kind`. The fix is **placement discipline**: every fixture answers "what
function put this object at this exact point," and if the honest answer is "the level
generator's spread formula," the object moves.

---

## 1. A Room Is a Place, Named By What Happens In It

**Rule.** Choose a room's `kind` (`dock`, `corridor`, `transit`, `storage`, `pump`,
`lab`, `quarters`, `chapel`, `records`, `medbay`, `core`, `generic`) from its
in-fiction *function*, before deciding its shape or its fight. Marathon's automap
labels rooms operationally ("BioCore Vent," "Engineering Storage," "M.C. Control") so
the station reads as a working system even in rooms the player never gets a terminal
for (`MARATHON_STUDY.md` A14). PERIHELION's `kind` tag is the same device, and it is
not cosmetic — `render.py`'s `_ROOM_PROP_GENERATORS` dispatch table draws function-
appropriate furniture *only* from this tag (crate stacks for `storage`, cot bays for
`quarters`, pew rows for `chapel`, shelf ranks for `records`...). An untagged room
silently falls through to `_props_generic` — a handful of anonymous rivets and grime,
the exact "game level, not a station" texture the director flagged.

- **Do** pick `kind` from what a crew member would say the room is *for* — "this is
  where we store the drums," not "this is where six husks stand."
- **Do** let one room have exactly one primary function. A room that is simultaneously
  filing cabinet, gun locker, and boss arena reads as a video-game encounter box no
  matter how it's dressed.
- **Don't** tag a room `generic` because nothing in the vocabulary fits perfectly.
  Pick the nearest working analogue (a morgue reads close enough to `medbay`; a
  server-closet of recovered minds reads close enough to `core`) and let the prose
  carry the rest — texture from furniture and texture from text don't have to agree
  down to the noun.
- **Don't** invent a new `kind` string without adding its generator to `render.py`.
  An unrecognized tag silently renders as `generic`, which reintroduces exactly the
  bug this rule exists to close, without an error to catch it.
- **Exception, stated on purpose:** the pure-graph tier (§8) is allowed — sometimes
  required — to tag rooms uniformly `generic`. Identical, function-less cells *are*
  the place at that tier; see §8 before "fixing" this.

---

## 2. Corridors Connect Functions; Nobody Builds a Corridor To Nowhere

**Rule.** A corridor exists because two named functions need a documented way to
reach each other, not because the map needed connective tissue. Before drawing a
corridor, name the two rooms it serves and what a crew member walking it would say
it's *between*.

`design_document_2.md` §8.2 already frames level geometry as authored, connected
rooms, but a room graph with no `corridor`/`transit` rooms at all reads as a suite of
arenas stapled together by doorways — no station has zero-length halls between every
department. PERIHELION's own baseline mostly gets this right by accident (an `entry`
or `hall` room already sits between the spawn and the first set-piece in most
levels) — the fix in this pass is to *tag* those rooms `corridor`/`transit` so the
renderer dresses them as passages (pipe runs, floor chevrons, vent grates — see
`_props_corridor` in `render.py`) instead of leaving them undressed.

- **Do** put an antechamber before a big room the way a station puts a foyer before a
  cargo bay — a beat of "this is where I'm about to go" between the safe corridor and
  the loud set-piece.
- **Do** use `transit` for a room that functions as a multi-way junction (three or
  more departments hang off it) and `corridor` for a simple point-to-point hall — the
  renderer treats them identically today, but the distinction documents intent for
  the next author.
- **Don't** draw a corridor whose only purpose is to hold the enemies the room graph
  needed somewhere to put. If a hallway exists purely for a squad spawn, it is an
  arena wearing a hallway's shape; either give it a real function (maintenance
  crawlway, a checkpoint) or fold it into the room it serves.
- **Don't** let a corridor stub dead-end without a reason a crew member would accept
  ("sealed after the incident," "leads to the ring's ninth segment nobody logged").
  An unexplained dead end reads as unfinished level geometry, not as a station.

---

## 3. Prop Language Is a Vocabulary, Not Decoration — Learn What Each Kind Says

**Rule.** Each `kind`'s generator has a *specific* visual grammar (§1's table below).
Choosing a kind is choosing what the room says about itself before the player reads
a word of text — this is A14's "operational floor plan" principle made literal in
pixels.

| kind | what it draws | reads as |
|---|---|---|
| `dock` | corner crate stacks, hazard-stripe strip, wall-mounted mooring rings | a bay things move through |
| `corridor` / `transit` | wall-hugging pipe runs with elbow joints, floor chevrons, vent grates | a passage, not a destination |
| `storage` | dense crate rows with a walkable aisle, shelf lines on the walls | a place with an inventory |
| `pump` | a tank ring (sometimes two) with an inflow pipe, floor puddle stains | mechanical, wet, load-bearing |
| `lab` | console blocks with lit screens along the walls, a center specimen table | instrumented, someone works here |
| `quarters` | cot bays along the walls, each with a pillow and a footlocker | someone slept here |
| `chapel` | pew rows facing a front wall, a dais arc | someone gathered here on purpose |
| `records` | long parallel shelf-stack lines filling the room in ranks | filed, searchable, bureaucratic |
| `medbay` | cots with curtain arcs, a cross-marked cabinet | treated, or meant to be |
| `core` | concentric ring inlays, radial conduit spokes, an amber hazard ring | the thing everything else defends |
| `generic` | sparse plates/rivets/grime, no furniture | untagged, or deliberately featureless (§8) |

- **Do** cross-check a room's terminal/radio prose against its kind before shipping —
  if the text says "filter room" and the kind is `lab`, the console dressing and the
  words are describing two different rooms to the player.
- **Do** treat the table above as ground truth over intuition; if a room's fiction
  wants furniture the generator can't produce, that's a signal to either retag or
  file an engine request — not to fight the renderer with prose.
- **Don't** stack two kinds' worth of implied function into one text description and
  expect the single generator to sell both.

---

## 4. Terminals Live In Wall Alcoves, Not On the Floor

**Rule.** A terminal is a fixture bolted to a wall at a control position, not a pickup
sitting in open floor. Every `TerminalSpec` (`levels.py:37-40`) is a bare `(room, pos,
text)` point — the engine enforces nothing about *where* in the room that point sits,
which means placement discipline is 100% an authoring responsibility. Concretely:
place the point **~15 units in from a wall** (`inset` in the `wall_pos()` helper),
never at or near a room's centroid, and prefer a wall that plausibly hosts a duty
desk or control lectern for that room's `kind` — a `lab`'s console wall, a `dock`'s
manifest board, a `records` room's shelf-end reader.

This is Marathon's convention (`MARATHON_STUDY.md` A1, A9): terminals are wall
fixtures with one fixed shell and a swappable payload; *where* a terminal sits inside
a room is itself part of the reading, not incidental. A21/D.1 add the corollary
PERIHELION should hold to going forward: which wall a terminal sits on can itself
carry meaning (a terminal on the wall facing the door you're about to open vs. one
facing away from it reads differently) — use this deliberately once a level wants it,
don't let it be arbitrary.

- **Do** pick (or default to) a wall that is *not* a doorway — a terminal wedged into
  an open portal reads as a placement bug, not a fixture. For rectangular rooms
  authored with `b.rect`, edges are stable and known: `0=west, 1=south, 2=east,
  3=north` (verified against `LevelBuilder.rect`'s vertex order) — pass that index
  explicitly rather than trusting an auto-picked "longest wall," which can land on a
  portal edge for non-rectangular rooms.
- **Do** cluster terminals in the three-beat rhythm Marathon uses when a level's
  shape supports it — one near the entry (briefing), one mid-level (a discrepancy or
  discovery), one near the exit (a branching or capping note) — per A2. Not every
  level needs exactly three; the point is deliberate spacing, not even scattering.
- **Don't** center a terminal in open floor "so the player doesn't miss it." A
  terminal the player has to walk *toward a wall* to reach is legible as a fixture;
  a terminal in the middle of a fight is legible as a spawn point.
- **Don't** put a terminal in a room whose `kind` gives it no plausible reason to have
  one, unless the terminal's own text explains the mismatch (a terminal relocated
  after an incident, a jury-rigged field unit) — otherwise retag the room or move the
  terminal.

---

## 5. Weapons and Ammo Live Where a Quartermaster Would Put Them

**Rule.** A cache is a locker, a rack, a supply crate, or a body — never a pile that
spawned at a room's center because that's where the placement helper defaults to.
Marathon gates weapon pickups to a named functional room and lets the terminal
foreshadow the reward before the player reaches it (`MARATHON_STUDY.md` A15); the
weakest version of this rule is simply *placing the cache against a wall inside a
room whose kind justifies storage* instead of floating it in open floor.

Four legitimate cache framings, use whichever fits the room:

1. **The rack** — a `storage` or `dock` room, cache racked along a wall (the default
   `cache(..., wall=<edge>)` behavior below).
2. **The armory** — a dedicated `storage`-kind room gated behind a key or a shot-open
   wall, explicitly named as such in terminal/radio text (L2's armory annex is the
   existing model: red key, terminal narrating the delivery, exit built into it).
3. **Beside the dead** — a cache co-located with a squad's spawn point, read as
   "recovered from whoever didn't make it," reinforced by a terminal or radio line
   that says so in as many words. No corpse-decal system exists yet (`prose-
   spec-portable.md` still governs any text used here — don't invent narration the
   engine can't back up); the *text* carries this framing, the geometry just needs to
   put the cache in the same room as the fight, against a wall.
4. **The find** — a small cache paired with a lore terminal in the same alcove,
   read as "someone else stashed this and didn't come back for it." Pair placement
   with a terminal within the same wall run, not across the room.

- **Do** use the `cache()` helper's `wall=` parameter for any rectangular room —
  it racks items in a single row along the chosen wall's tangent, inset from it,
  which reads as a shelf regardless of room proportions.
- **Do** leave a cache on `off=(0,0)` (room-center) placement *only* when the room
  itself is small enough that "center" and "against a wall" are visually
  indistinguishable, or when centering is load-bearing for a puzzle (see §7).
- **Don't** auto-rack a cache against a wall in an irregular polygon room (a hex, an
  ngon petal, a tesseract cell) without checking the wall isn't a portal edge first —
  unlike rectangles, these rooms don't have a stable, memorized edge-to-compass-
  direction mapping, and a blind "longest wall" heuristic can rack a locker across an
  open doorway. When in doubt, compute the explicit point by hand and leave a comment
  showing the reasoning.
- **Don't** let cache size scale past what a wall run can hold without spilling into
  the doorway or out of the room. A seven-item finale cache needs either a longer
  wall or a lower per-wall item budget, not a wider centered grid.

### 5.1 A unique reward's placement is gameplay, not just texture — validated against the bot

A *one-time* weapon (a level's namesake smg, shotgun, rail gun, tau rifle) is not like
an ammo pickup: missing it once means the rest of the campaign is fought without it,
compounding. This pass found, by driving `AggroBot` through every level and reading
its inventory at each chunk boundary, that **"placed at the exit" is not the same
guarantee it looks like**, for two independent reasons:

1. **`AggroBot` only ever detours for medkits (when hurt and safe) and ammo (when
   critical) — never for an unclaimed weapon.** A cache sitting one room off the
   critical path (a side detour like L3's storeroom) is *never* visited by a
   route-following bot, no matter how well it's dressed. If a level's design intends
   a weapon as a real progression beat (its header comment names it, the way L3's
   says "Shotgun"), it must sit in a room the critical path actually enters — verify
   this against the room graph, not against how the level "should" play.
2. **In streamed play, the walking target inside an exit room is the carved spine
   doorway (`stream.py`'s `_carve_in_chunk`), not the level's authored `exit_pos`.**
   `carve_door` snaps to whichever wall is nearest that point — which can be a
   different wall than the one a cache was centered against, so "at the exit" and
   "on the wall the run actually crosses" are not the same claim. Measured effect on
   this campaign: before this fix, a weapon placed at a room's center (co-located
   with its `exit()` call) was picked up in roughly half of runs or fewer.

**The fix, validated by re-running the bot 10-20 times per level:** place a unique
reward within a few units of the room's *entry* threshold — the exact point the
player is standing at when a fight or a beeline starts — rather than at the room's
center or against whichever wall looks nicest. Every route out of a room starts from
the same entry point regardless of which portal it heads for next, so a cache there
is crossed on the first tick in the room, before any routing choice diverges. This
raised single-run pickup reliability from roughly 0-50% to 90-100% across the
levels tested, with zero changes to enemy counts, connectivity, or text.

- **Do** treat a unique weapon's cache position as a testable claim, not a vibe:
  drive a bot (or `campaign_run.py`) through the level a dozen times and check its
  final `weapons` list. If a weapon is sometimes missing, the placement is wrong,
  not the bot.
- **Do**, when a room has more than one valid entry (two wings converging on one
  chapel, say), either rack the reward near *every* entry (duplicate weapon pickups
  are a harmless idempotent no-op if a second copy is also reached) or accept
  materially lower reliability and say so in a comment.
- **Don't** assume "it's in the room the level design says is mandatory" is
  sufficient — mandatory-per-design and mandatory-per-actual-graph-shortest-path are
  different claims when a level has a paradox shortcut (a mobius glue, a fold) that a
  routing bot will take even when a human wouldn't think to.

---

## 6. Lighting and Quiet Are Pacing Tools, Not Empty Rooms

**Rule.** A room with nothing in it is not filler — it's the beat between two loud
rooms, and it should read as one. `NARRATIVE_DESIGN_DOC.md` §9.5 sets the
environmental-storytelling priority order (outpost's fall → Testators' story →
geometry-doubt seeds → faction-war context); a quiet room is where a lower-priority
detail gets to exist without competing with combat or a terminal for attention.

- **Do** let some rooms carry zero enemies and zero pickups on purpose — an empty
  `quarters` bunk row after a loud `storage` room is a rest beat, not a wasted room.
- **Do** use a corridor's inherent dimness (see `render.py`'s player-centered
  darkness field) as the natural site for these beats — a lit `lab` is a
  destination; a dim `corridor` between two destinations is where dread accumulates.
- **Don't** pad a quiet room with generic detail to make it "feel less empty." An
  unfurnished room a player passes through quickly is doing its job; over-dressing it
  fights the pacing it was placed for.

---

## 7. Secrets: Pick Which of Five Mechanisms You're Using, Don't Default to One

**Rule.** `MARATHON_STUDY.md` A7 documents five *distinct* Marathon secret
mechanisms — PERIHELION currently implements exactly one (`"shoot"` doors,
`EDITOR.md`). Before authoring a secret, decide which of these it is; don't reach for
shootable-wall by default just because it's the only one wired up.

1. **No telegraph at all** — a `door_pts`/`no_connect` pairing with a key that has no
   in-fiction acknowledgment anywhere. Legitimate; some secrets should stay unfound
   by most players.
2. **Behavioral/AI-state gating** — content reachable only if an enemy or event state
   permits it (not yet built in PERIHELION; note for future engine work rather than
   fake it with geometry).
3. **A prop that implies choreography it doesn't enforce** — a visual suggestion
   (a ledge, a barrier) that *looks* load-bearing but isn't actually collision-
   blocking. Use sparingly; it's a texture read, not a puzzle.
4. **A breakable panel as a bonus shortcut beside a legitimate route** — the
   `"shoot"` door convention already covers this; keep using it for exactly this
   framing (a faster way to something also reachable normally), not as the only
   secret type in the game.
5. **Mode/state gating** — content that only makes sense or only unlocks under a
   specific run condition. Speculative for PERIHELION; flag rather than force it.

- **Do** let a secret cache use *centered* placement (§5's exception) when the
  secret's discovery moment — the wall opening, the light coming on — is doing the
  "this is a locker" work that wall-racking would otherwise carry. The reveal is the
  frame; the placement doesn't also need to be.
- **Don't** acknowledge every secret in text. Per A7's closing rule, it's fine — even
  good — to leave some secrets with zero in-fiction confirmation that they were found.

---

## 8. Non-Euclidean Escalation Is Staged, and Each Stage Has a Textual Twin

**Rule.** `design_document_2.md` §8.1's four-tier curve (deniable → confirmable →
overt → pure graph) is a *place-legibility* curve as much as a difficulty curve, and
`MARATHON_STUDY.md` §A.d is the single most load-bearing finding in this document:
Marathon signals "this space is wrong" almost entirely through **textual
contradiction and structural repetition**, not through visibly warped geometry. Pair
every geometric anomaly with a line (terminal, radio, NPC) that contradicts what the
player already believes about the space — the contradiction carries the narrative
weight, not the warped room alone.

| Tier | Levels | Place-ness target | Textual pairing |
|---|---|---|---|
| Deniable | L1-L2 | Still reads as a normal station; kind-tag and dress every room as if nothing is wrong | One line that quietly doesn't add up (Ratio: "that beacon just left my deck plan") |
| Confirmable | L3-L5 | Place-ness holds, but a room's *content* starts contradicting its neighbor's | Two accounts that can't both be true, resolved (or not) by a third voice |
| Overt | L6-L7 | Geometry openly hostile; place-ness *thins deliberately* — a room can be dressed and still be impossible | The contradiction gets stated almost flatly; withholding drops away |
| Pure graph | L8-L10 | Architecture is allowed to abandon place-ness — `generic`-tagged, identical cells are correct here, not a lapse | Terminal density should go *up*, not down, to keep the pairing intact even as geometry stops pretending to be a building (D.6's explicit warning: the endgame levels are the ones most likely to let geometry do all the work alone) |

- **Do** keep dressing early-tier rooms fully as if they were ordinary — the
  wrongness is supposed to be invisible to a player who isn't looking closely yet.
- **Do**, at the pure-graph tier, treat uniform `generic` tagging as a *choice*, and
  say so in a comment at the point of choice — a reviewer six months from now needs
  to know it wasn't an oversight.
- **Don't** let a late-tier level's geometry outrun its text. If a room's impossibility
  would take a careful player several minutes to notice, and there's no terminal or
  radio line anywhere nearby confirming it wasn't imagined, the level is spending
  geometry it isn't backing up.
- **Don't** solve "this room is repetitive" by varying its kind tags at the
  pure-graph tier — the repetition is the point; solve staleness with pacing or
  enemy variety instead.

---

## 9. Scale and Proportion: Build For a Body, Then Break the Rule On Purpose

**Rule.** `NARRATIVE_DESIGN_DOC.md` §4.1-4.2 establishes that even the non-Euclidean
strata are "built for creatures" — corridors and doorways sized for an embodied
occupant, until Stratum Three drops the concession entirely. Room proportions should
telegraph function the same way real architecture does: a `quarters` room reads
smaller and more subdivided than a `dock`; a `corridor` reads narrow and long rather
than square.

- **Do** keep new rooms proportioned to function when nothing else constrains them —
  an antechamber is small, a cargo bay is large, a records stack is long and shallow
  (shelf ranks want run length, not width).
- **Do** treat existing rooms' exact dimensions as load-bearing once they participate
  in auto-adjacency (two rooms whose shared wall segment is matched by exact or
  contained coincidence, per `LevelBuilder.resolve()`'s doorway-splitter) — resizing
  one can silently break the connection with *no error raised*, only a disconnected
  room discovered later by a routing failure. Prefer adding a right-sized new room
  over resizing a working one.
- **Don't** treat "rooms sized to function" as a mandate to retrofit every existing
  room. Preserving a level's proven, validated connectivity outranks a proportion
  fix that's cosmetic — see §11 (paradox constructs are sacred) for the same
  principle applied to geometry specifically.

---

## 10. Each Level Is a Station District, Chained By Transit Spines

**Rule.** `game/perihelion/stream.py` streams campaign levels as chunks joined by
carved transit spines — two `transit`-kind corridor rooms between chunk *k*'s exit
and chunk *k+1*'s entry, with a tight-beam relay terminal riding the spine. This
makes the *level* the wrong unit to think in during authoring; the right unit is
**a station district**, one of several the player crosses in one continuous walk.

Concretely, this constrains authoring in two ways:

- **Every level needs a carvable solid wall** (`elen >= width + 8`, i.e. **≥78
  units** for the default 70-unit spine door) in its exit room, or in a room the
  streamer's BFS can reach within the same chunk (`WorldStreamer._carve_in_chunk`),
  and likewise near the player spawn (for the *previous* chunk's spine to carve an
  entry). A level whose exit room is fully portal-saturated (no wall long enough to
  carve) breaks the streamer with no in-game error — it fails silently at world-build
  time. Verify this explicitly per level; don't assume it.
- **A new security zone clears held keys on arrival** (`stream.py`'s `tick()`:
  `s.keys = set()` on crossing into a new chunk). Don't author an exit-gate key in
  one level that's meant to double as an entry requirement for the next — the
  streaming model treats each district as re-secured on entry, which is itself in-
  fiction correct (badges don't carry between security zones) and should be treated
  as a constraint, not a bug to route around.

- **Do** think of a level's first room as "the door into this district" and its exit
  room as "the door out" — both need to physically support a carved doorway, and
  both benefit from reading as thresholds (an airlock, a checkpoint) rather than
  starting mid-room.
- **Don't** author a level's exit pad inside a room so geometrically saturated
  (six-plus portals, like a `core` ngon or a Cayley-graph cell) that no wall segment
  reaches 78 units — either give the exit room one deliberately blank wall, or place
  the exit in a lightly-connected antechamber just off the saturated room.

---

## 11. The Paradox Constructs Are Sacred

**Rule.** Every level's impossible-geometry mechanic — the phantom ring segment
(L1), the pump hatch (L2), the Möbius torus (L3), the crossing-count gallery (L4),
the same-volume wings (L5), the mirror ward (L6), the infinite aisle (L7), the fold
(L8), the tesseract with its chamfered corners (L9), the Cayley core (L10) — is the
mechanical reason the level exists. Place-ness work in this pass (kind tags, terminal
and cache repositioning, antechambers) must never touch the `connect_pts` / `door_pts`
/ `no_connect` calls that implement these, nor the exact coordinates those calls
target, without re-validating the specific paradox by hand afterward.

- **Do** treat every `connect_pts(room, point, ...)` call's `point` as a coordinate
  that must continue to resolve to the *same wall* after any edit — `resolve()`
  matches by nearest edge midpoint, so a moved or resized room can silently
  re-target a connection to the wrong wall with no error.
- **Do** re-run the level generator and the full validation suite (regeneration,
  `pytest`, the streamed campaign run, and a per-level bot completion check) after
  *any* geometry-adjacent change, even one that looks purely cosmetic.
- **Don't** resize a room that participates in auto-adjacency (an edge matched by
  exact/contained coincidence rather than an explicit `connect_pts`/`door_pts` call)
  to chase §9's proportion guidance. The risk-to-cosmetic-value ratio is wrong; add a
  new, correctly-sized room instead.
- **Don't** "clean up" an intentionally-odd room count, connection, or dead end
  without checking the level's paradox description first — the oddness is very
  often the mechanic, not an authoring mistake.

---

## Summary: The Eleven Rules in One Pass

1. Tag every room by function first; the renderer's furniture comes free once you do.
2. A corridor connects two named functions — never build one to nowhere.
3. Learn each `kind`'s visual grammar before assigning it; don't fight the generator.
4. Terminals sit in wall alcoves, ~15 units in, on a non-portal wall — never floor-center.
5. Caches rack against a wall in a room a quartermaster would use — never a centered pile;
   a *unique* reward's placement is a testable claim (§5.1) — verify it against a bot, not a vibe.
6. Empty rooms are a pacing tool; don't pad them just to avoid emptiness.
7. Pick one of five secret mechanisms deliberately; don't default to shootable walls.
8. Pair every geometric anomaly with a textual one, at every escalation tier including the last.
9. Size rooms to function when nothing else constrains them; never resize a working connection to chase it.
10. Author levels as station districts — verify a carvable wall exists at every spine seam.
11. The paradox constructs are sacred: re-validate the mechanic after every edit near it.

---

## Sources

- `MARATHON_STUDY.md` — Parts A (level-as-place conventions) and D (structural
  recommendations for this repo), primary source for §§1, 2, 4, 5, 7, 8 above.
- `design_document_2.md` §8 (The Escalation Curve, The Level Editor).
- `NARRATIVE_DESIGN_DOC.md` §4 (the three strata), §9.4-9.5 (atmosphere and
  environmental-storytelling budget).
- `game/perihelion/levels.py` (`LevelBuilder`, `TerminalSpec`, doorway-splitter
  semantics) and `game/perihelion/render.py` (`_ROOM_PROP_GENERATORS` and the
  per-kind prop functions) — read directly for this document's §§1, 3-5, 10.
- `game/perihelion/stream.py` and `game/tests/test_stream.py` — read directly for
  §10's carvable-wall constraint.
- `gauntlet/ux-principles-web-apps.md` — format exemplar (numbered principles,
  terse rationale, concrete do/don't, closing one-pass summary).
