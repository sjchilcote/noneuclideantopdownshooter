# The separation: NETDS and PERIHELION

This file is the founding record of the two-project split. The owner ratified the split on 2026-08-22. The owner corrected the NETDS baseline on 2026-08-22, after the first execution used the wrong one. This version of the record supersedes the April-baseline version. That version is preserved on the branch `april-attempt` and under `litc/history/april-attempt/`.

## The two products

**NETDS** (working title: Non-Euclidean Top Down Shooter) ships first. It is a standard top-down shooter. Its only gimmick is the non-Euclidean world. The scope is a couple of months of work, released free or cheap. It carries the shared engine.

**PERIHELION** is the dream game. It lives at `../perihelion`, consumes the engine from this repository as a sibling checkout, and will take years. Nothing in this repository depends on PERIHELION.

## The baseline (corrected)

NETDS is built from the result of the autonomous iteration loop of 2026-07-09, commit `d295b8f` ("SteadyBot: mid-skill proxy resolves the hard-mode completability question", 19:43). The tag `loop-result` marks it.

The session record fixes the loop's span exactly:

- 07:17 `/effort ultracode`.
- 07:26 the owner's charge: "First refactor, then finish this game."
- 09:00 the owner walks away: "Excited to see the finished product tonight!"
- 11:54–12:17 one check-in. Feedback lands. The loop continues alone.
- 19:43 the loop's last commit: the SteadyBot completability proof.
- 20:16 the owner returns and starts directing continuously. Everything after this minute is the PERIHELION direction: dialogue standards, Marathon terminals, the Otherworld, the Testament. None of it is NETDS.

The first execution of the split grafted NETDS from the April 2025 prototype instead. That was wrong. The owner's words: the base is the state after the autonomous iteration loop. The April prototype remains reachable on `master` as history.

## Owner decisions in force

1. Baseline = `d295b8f` (the loop result). Ratified 2026-08-22.

2. "The dialogue and story must be eliminated entirely." Executed as the de-narrativization commit (tag `netds-base`). Its verification: green against the in-tree engine, an aggro-bot campaign clear, and a streamed-app soak that reached New Game+. NETDS keeps mechanics. It keeps no narrative systems and no narrative content.

3. The dynamic music system is wanted, although it postdates the loop (it landed 2026-07-13). The authoring toolchain (`tools/musicgen`, `tools/musiccal`) transfers here. The runtime port into the NETDS game is P4 work (`spec/open-questions.md` NETDS-2). The owner's own tag `shippable-music-v1` (2026-07-17) marks the reference state for the port.

4. Layered structure, shared engine. The engine lives here. PERIHELION consumes it as a sibling.

5. NETDS scope beyond the base: portable hole and mirror tricks (already in the loop result), the level editor shipped to players (NETDS-3), the music toolchain.

## Phases

- P1 (done): regraft at `loop-result` with full history. `master` keeps the prototype. `april-attempt` keeps the first execution.

- P2 (done): de-narrativization, tag `netds-base`.

- P3 (done): the engine comes forward, the game is ported to it, the toolchain and corpus records transfer. See the engine note.

- P4 (owner-gated): the change analysis that produces the NETDS build spec. Its inputs: the decompiled product definition, the accepted answers in `spec/open-questions.md`, the music runtime port, and the editor UX audit.

## The engine note

The engine directory was brought forward to the shared state of 2026-08-22 (git tree `d980dadc3bea`, hash-equal to the engine PERIHELION builds as a sibling). The game was ported to its API in the same commit.

The port is a rename family (`room` became `polygon`) plus the typed coordinate API (`Coordinate`/`Offset`/`EntityState` in place of raw tuples). It carries two engine-forced divergences:

1. The collision matrix collapsed to "both entities physical". Four pairs flip from off to on. The returned-round mirror rule is preserved and tested. Ruling: `spec/open-questions.md` NETDS-1.

2. The engine now clamps every entity into its polygon every tick. The game-side containment sweep became dead code and was deleted. Its test now asserts the engine invariant from the game side, within one tick instead of three seconds.

## Verification trail

- Graft (`loop-result`): check.sh green on the in-tree engine after regenerating the synthesized sfx bank (328 passed).
- De-narrativization (`netds-base`): check.sh green (264 passed) and an aggro-bot clear of all ten campaign levels. A 400-second streamed-app soak reached New Game+ and caught a second epilogue call site the tests missed.
- Engine forward + port: cargo 125 passed, check.sh green (264 passed, zero skips), and the campaign cleared again, ten of ten in one try each.
- PERIHELION cross-check after the directory swap: recorded in this file's next update once run.
