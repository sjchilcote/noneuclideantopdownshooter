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

*(Local findings from §0 establish the container-level separation of
geometry/text/assets that underwrites several of these. Web citations point
to marathon.bungie.org/story/&lt;page&gt;.html.)*

**A1. Terminal placement is access-tier-coded, and access tier tracks who
currently controls the ship.** Leela's messages route through
high-security (Defense/Medical) terminals; as the AI takeover progresses,
Durandal's messages route through increasingly compromised Public/Service
terminals — so *which door you're reading from* narrates the invasion
without a line of prose saying so (counterattack.html; source: M1 terminal
study).

**A2. Terminals cluster in a three-beat rhythm per level: entry briefing,
mid-level map/lore drop, exit branching gate** — not scattered evenly
through a level (counterattack.html).

**A3. Success/failure terminal branching is a standing mechanism, not a
one-off twist** — used repeatedly across the campaign (Never Burn Money,
Bob-B-Q, Habe Quiddam, No Artificial Colors) to reward or punish completion
state with tonally different text, not just different stats (arrival.html,
reprisal.html, durandal.html, pfhor.html).

**A4. Level-title register escalates in lockstep with narrative
destabilization.** Early M1 titles are mundane idiomatic English (Arrival,
Bigger Guns Nearby); mid-campaign shifts to pop-culture quotation (Smells
Like Napalm, Tastes Like Chicken!) and warning-label phrasing (Shake Before
Using...); the Pfhor chapter runs a punning bit welded onto English words;
structurally pivotal levels drop into true Latin (Habe Quiddam, Ingue
Ferroque). Infinity pushes the same lever further into vernacular
fragments/broken grammar ("Naw Man He's Close," "Thing What Kicks...") —
titling register does the same escalation work as terminal typography, on
a slower clock (arrival.html–rebellion.html; nawmanhesclose.html;
thingwhatkicks.html).

**A5. The terminal's login/checkpoint chrome never destabilizes — only the
payload does.** Every terminal across all three games opens with the same
system ID string, access classification, timestamp format, and disconnect
banner. This fixed ritual frame is precisely what makes content instability
(corruption, tonal breaks, address confusion) *legible as* instability —
without a stable frame, corruption reads as noise instead of as a symptom
(arrival.html–rebellion.html; acmestation.html and 12 other Infinity pages,
consistent "Opening Connection to..." / "UESCTerm 802.11" / "CAS.qterm"
header).

**A6. Whole-campaign date compression as an environmental fact.** Every M1
campaign terminal — Arrival through Ingue Ferroque — carries the identical
date stamp, 08.25.2337. The war (including two AIs going rampant) happens
inside one subjective day; the pacing is a psychotic break, not a slow
campaign, and nothing states this — it's discoverable only by checking
dates across widely separated terminals (durandal.html; §B "buried depth").

**A7. Secret walls that "open to gunfire" are a real, load-bearing
Marathon convention, not decoration** — several Marathon secret doors are
literally shootable walls (confirms the convention PERIHELION's `"shoot"`
key door already implements; see §D.0). Beyond that baseline, secrecy is
implemented multiple distinct ways, worth treating as separate tools rather
than one mechanic: (a) **no telegraph at all** — a switch on "All Roads Lead
To Sol..." sits fully submerged under a lava pool with zero visual cue and
was undiscovered by players until third-party map tools existed
(switchonsol.html); (b) **behavioral/AI-state gating instead of geometry** —
the fourth terminal on "Never Burn Money" isn't hidden in space at all, it
sits behind an enemy "engrossed" in hacking who only attacks if disturbed
(4thterminalonnever.html); (c) **a visible prop that implies choreography
it doesn't enforce** — a ledge in front of paired terminals on Charon looks
like it should force players to one side before reading, but doesn't
actually block center access, so players can silently miss content
(Terminal_Clusters_on_Charon.html); (d) **breakable panels as a bonus
shortcut beside a legitimate switch**, not a separate puzzle — smash one
open all three door segments Bob-B-Q would otherwise require working
individually (everywherepanel.html); (e) **mode-gating**: some content
(Robot World Arena, Two for the Price of One briefings) was designed
accessible only in co-op, a narrative gate enforced by game mode rather
than level geometry (coopcarnagebreaklevels.html). Rule for PERIHELION: pick
which of these five a given secret is, don't default to "hidden switch"
every time, and it's fine — even good — to leave some secrets with *zero*
in-fiction acknowledgment that they were found.

**A8. Discarded/rejected drafts show active tone-policing, not just
cutting for length.** M1's original "trash" terminal used occult vocabulary
that was deliberately swapped for blander sociological-sounding text
because it read "out of character with the rest of the story" (trash.html)
— a level's diegetic texture is curated at the register level, not just
trimmed for space.

---

## B. TERMINAL WRITING CRAFT

**B1. Withhold via stated epistemic limits, not hidden facts.** Leela
narrates her own uncertainty rather than concealing information from the
player: "My records and sensors are becoming less reliable" (Cool Fusion,
counterattack.html). Menace comes from a narrator who *doesn't know*, not
one who's lying to the reader — this is mechanically distinct from
Durandal/Tycho's withholding (§C).

**B2. Corruption is characterization, assigned per-speaker, and means a
different thing for each one.** Garbled text reads as involuntary damage
on Leela's channel and as performative, droppable control on Durandal's
(Shake Before Using..., reprisal.html; durandal.html). Decide, per
character, whether corruption is a wound or a mask — don't let "glitchy
text" be one undifferentiated tool.

**B3. Deliver menace as a compliment sandwich.** "You are really good at
killing things. I'm impressed. Why don't you kill everything..." (No
Artificial Colors, pfhor.html) — praise collapses into command in the same
breath.

**B4. Reverse-psychology hints double as a cruelty test.** Durandal plants
sarcastic false hints that only reward players who catch the lie: "Who
would hide huge amounts of ammunition in a storage area?" (Blaspheme
Quarantine, counterattack.html). The *manner* of helping characterizes as
much as the content of the help.

**B5. Undercut your own monologue mid-breath for tonal whiplash.**
Durandal pivots from "why am I here? Why do I exist?" straight into "I got
a shotgun, and you ain't got one" (Blaspheme Quarantine, counterattack.html)
— instability of *register* stands in for stated instability of mind; never
narrate "he is unstable," perform it in the sentence-to-sentence swing.

**B6. Collide corporate/pop-culture banality with cosmic stakes.**
Classified-ad copy for the colony ship ("runs great," "power everything")
for a vessel that is civilization's ark (Colony Ship For Sale, Cheap,
durandal.html) — the banality of the register *is* the horror, not a joke
that relieves it.

**B7. Make big numbers precise and slightly unmoorable, not vague.**
Durandal states a universe-closure figure to roughly 15 significant digits
(durandal.html) — hyper-precision without graspability reads as omniscience
curdling into obsession. A number that's *too* exact is a tell.

**B8. Chart decline through the sign-off line alone.** Durandal's
escalating closings — "Vale, Durandal" → "Forever, Durandal" → a
"Notably Unstable" self-diagnosis — carry his arc with zero expository
sentences (counterattack.html, pfhor.html).

**B9. Plant clinical vocabulary early and unglossed; let it silently
become load-bearing diagnostic language later.** Rampancy's three named
stages (Melancholia, Anger, Jealousy) surface first as a dry historical
footnote about a prior AI outbreak (counterattack.html), then become the
vocabulary the story uses — without ever re-explaining itself — to track
Durandal's arc two chapters later (durandal.html, rebellion.html). Readers
who register the taxonomy early can predict the escalation curve before
the text states it.

**B10. Corruption should hide a fully coherent text underneath, not be
random noise.** Every garbled Marathon terminal the community has
decrypted resolves to coherent prose (the KYT term decodes to a
Roland/Beowulf/Achilles monologue; a Never Burn Money terminal was
reconstructed word-by-word by a fan in 2005) — garbling is a cipher applied
*after* the sentence was written, never a substitute for writing one
(kytterm.html, 4thterminalonnever.html).

**B11. Borrow real system-error syntax for authenticity.** Genuine
Unix-linker-style error strings ("symbol 'exitITask' undefined") interleave
with in-fiction text on "Try again," selling system failure more
convincingly than invented gibberish would (tryagain.html).

**B12. Let one intruding word bleed across unrelated speakers as if
transmitted, not authored.** The word "durability" recurs from a
girlfriend, a sanitation worker, and pulsars "broadcasting across
lightyears" in Eat the Path — implying a signal bleeding into local
dialogue rather than a theme the writer chose to hammer
(eatthepath_reordered.html).

**B13. Interrupt the AI's own self-revealing sentence instead of finishing
it.** "...my own psychotronic profile is, well, never mind about that
now..." (thingwhatkicks.html) — the confession that gets cut off is more
characterizing than the confession completed.

**B14. Leave known production bugs in the canon, undocumented, alongside
the deliberate glitches.** A miscolored hex code on "Where Some Rarely Go"
and a wrong-speaker-color message on "Foe Hammer" are real formatting bugs
the fan archive preserves "for authenticity" rather than silently
correcting (wheresome_reordered.html, foehammer_reordered.html). A few
genuine, unexplained glitches sitting next to the deliberate ones make the
deliberate ones read as more considered, not less.

**B15. Literalize narrative uncertainty in the UI chrome itself, not just
the prose.** Exit links on Electric Sheep Two/Three read "Dream?",
"Dream??", "Dream???" instead of a level name — doubt is encoded structurally
in what the player clicks, not only in what they read
(electricsheep2.html, electricsheep3.html).

**B16. Humor and menace should physically occupy the same sentence, not
adjacent ones.** "Contents under pressure? Do not expose to...harsh
language?" fuses consumer-product-warning syntax with vacuum-death threat
in one line (hangbrain.html); "This terminal sucked" — a shrug of
self-aware humor — was left as the literal replacement text for a cut S'pht
mythic-history terminal, sitting inside an otherwise tragic register
(sphttermonconfound.html).

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
