# Separation plan: NETDS and PERIHELION

Ratified by the owner 2026-08-22 (question rounds in the orchestrating session). This file is the founding record of the split.

## The two products

- **NETDS** (this repository; working title: Non-Euclidean Top Down Shooter). A standard top-down shooter whose only gimmick is the non-Euclidean world. Product definition: the April 2025 autonomous-iteration prototype. Shipping vehicle: the `necore` engine. Deliberately scoped to finish in a couple of months; released free or cheap.
- **PERIHELION** (currently `~/PycharmProjects/noneuclideantopdownshooter`, branch `rewrite`). The hyperambitious dream game, built on top of NETDS's engine. Years of prototyping ahead. Keeps its warm-start corpus, its narrative and Adversary systems, and its in-flight work.

## Owner decisions of record

1. **Baseline**: the prototype defines the product; NETDS ships on `necore` ("NETDS migrates to necore"). The restoration is a port of the prototype's design onto the new engine, not a revival of the old code.
2. **Structure**: layered with a shared engine. `necore` will live in the NETDS repository; PERIHELION consumes it as a dependency, so engine fixes made for the shipping game flow up to the dream game.
3. **NETDS scope beyond the world gimmick**: the dynamic music runtime, the portable hole and mirror tricks, the level editor (shipped to players), and the music authoring toolchain (`musicgen`/`musiccal`).
4. **Sequencing**: split first; each project ratifies its own spec subset. The PERIHELION corpus stays parked at its Phase 6 boundary.
5. **Repo naming**: the current repository becomes `perihelion`; NETDS takes the `noneuclideantopdownshooter` name. The swap happens at the owner's keyboard (open IDE and live sessions point at the current paths).

## The baseline, verified

`git master` commit `5f1caa6` is the authoritative prototype state. Verification (2026-08-22): `noneucideantopdownshooter_perfect.zip` and `Archive.zip` are byte-identical; master's `main.py` differs from perfect.zip's only by the scalar-math performance pass the old `AGENTS.md` commissioned (139 changed lines, no gameplay change, verified by diff). Master additionally carries the level collection, `util.py`, and the test/perf harness that perfect.zip lacks. This repository's `main` branch is grafted from that commit — same object, real lineage.

## Phases

- **P1 — Foundation (done 2026-08-22).** This repository founded from `5f1caa6`. litc seeded: current process file, clear-technical-prose standard, UX standard (scope includes the shipped editor), audited glossary copied from PERIHELION (prune pass deferred to NETDS's own audit). Prototype decompile launched: `spec/prototype-game.md` and `spec/prototype-editor.md` describe the April 2025 game as it is — the product definition.
- **P2 — Landing and swap (executed 2026-08-22, owner's order: "finish the job").** PERIHELION's in-flight work lands through its playtest gate, run by the orchestrator. The directory swap (decision 5) follows once the prototype decompile agents finish writing in this repository.
- **P3 — The engine move (executed 2026-08-22).** `engine/` (`necore`, `necore-py`) transferred from PERIHELION to this repository at its HEAD state (PERIHELION's history keeps the engine's past). `spec/engine-core.md`, `spec/engine-binding.md`, and `spec/tools-music.md` transferred with their code. `tools/musicgen` and `tools/musiccal` transferred. PERIHELION's build, check script, and README now consume the engine from this repository as a sibling checkout. The music runtime (`game/perihelion/music.py`, `audio.py`) stays in PERIHELION with `spec/audio.md`; specs follow code ownership, and NETDS's music runtime port gets its spec in P4 with PERIHELION's as reference.
- **P4 — The NETDS spec.** Phase 2 change analysis: the prototype spec (what the product is) crossed with `necore` reality (what the engine provides) produces the NETDS build spec. Known open questions to surface there, not decide here: whether the prototype's level format converts to the rewrite's version-2 format or keeps its own; which editor codebase serves players (the prototype's `leveledit.py` definition on the new engine, or the rewrite editor with prototype scope); what "standard enemies" keep from the prototype's bot behavior; how the music runtime binds without the PERIHELION value battery. The owner ratifies; then Phase 3 compilation begins.

## Not decided here

Free versus cheap, the release title, whether NETDS adopts a filmed-playtest commit gate like PERIHELION's, and every P4 open question. These are owner decisions, recorded when made.
