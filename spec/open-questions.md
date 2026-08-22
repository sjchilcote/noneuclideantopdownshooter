# Open questions

Each entry is a decision the owner has not ratified. Each carries a proposed answer. The proposal stands as the recommended answer until the owner accepts it or vetoes it. P4 work applies the accepted answers.

## NETDS-1 — The four flipped collision pairs

The shared engine hardwired the collision rule to "both entities physical". The loop game configured pairs. Four pairs flip from off to on, and the game cannot represent the old setting without engine changes.

The flips: enemy shots now hit enemies, so spitters can be body-blocked. Player pellets interact with each other (mild spread perturbation, measured, no clumping). Player rounds deflect enemy shots. Radial bursts self-interact at spawn. The returned-round rule (player bullets hit the player through folds) is preserved, and the campaign clears.

Proposed answer: accept the shared engine's law. The flips are small, legible, and physical. Restoring pair granularity would fork the engine or push a config surface back into it that PERIHELION deliberately removed.

## NETDS-2 — Music runtime binding

The dynamic music runtime (owner tag `shippable-music-v1`) reads PERIHELION's value battery to pick intensity. NETDS has no value battery.

Proposed answer: bind track selection to the two signals the game already computes — campaign tier and live combat pressure (aggroed enemies, player integrity). Port the runtime at P4 against that binding. The authoring toolchain transfers unchanged.

## NETDS-3 — The editor as a shipped surface

The loop's level editor (`game/perihelion/editor/`) ships to players. That makes it a UX-standard surface, which it was never audited as.

Proposed answer: keep it in the product. Run the UX audit over it during P4 and treat findings as build-spec items, not blockers on ratifying the product definition.

## NETDS-4 — The PERIHELION name inside NETDS

The game package is named `perihelion` and the final level is "PERIHELION CORE". PERIHELION is now the other game's title.

Proposed answer: keep the package name as inert plumbing until release polish. Rename the player-facing level title at P4.

## NETDS-5 — The editor's new-file workflow

The editor cannot create or save a fresh level. A session with no stored path has no save affordance, although EDITOR.md promises a blank-canvas mode (`spec/netds-editor.md`, file-ops defect).

Proposed answer: add save-as and new-file as a P4 build-spec item. The editor ships to players (NETDS-3), so the promise must become real or die.

## NETDS-6 — Playtest from the shipped editor

F5 test play spawns `uv run python -m perihelion` from the repo root. A player install has neither `uv` nor the repo.

Proposed answer: route F5 through the same packaged entry point the player build ships. Keep the temp-export mechanism.

## NETDS-7 — The flush-autoconnect divergence

EDITOR.md claims flush walls autoconnect at load. The load path never runs the doorway-split pass — only the generator path does. Fixing either side changes the authoring model.

Proposed answer: keep load-path behavior as it is and correct the manual. The shipped levels and the connect tool already assume explicit connections.

## NETDS-8 — Editor palette gaps

The palette cannot place four types the game accepts: `portable_hole`, `safe_room_core`, `turret`, `weapon_tau`. The portable hole is a named NETDS scope item.

Proposed answer: add `portable_hole` at minimum. The owner rules on the other three.

## NETDS-9 — New Game+ credit from partial runs

Completing any streamed run increments `ng_plus` and stores the carried arsenal. A `--level` one-off or a level-select entry into the final chunk counts the same as a full loop (`spec/netds-game.md`, campaign flow unit).

Proposed answer: grant New Game+ only when the run started at chunk 0. New Game+ is framed as the loop beginning again, which is a full-loop reward.

## NETDS-10 — Stereo pan is plumbed but never fed

`Audio.handle_sounds` accepts visible instances and computes pan from them. The app never passes them, so every sound pans center.

Proposed answer: pass the frame's visible instances at P4, alongside the NETDS-2 music binding work. If the owner declines, delete the parameter.

## NETDS-11 — The empty door key

The level format reserves `key: ""`. Such a door loads and can never open.

Proposed answer: keep the value reserved and make the loader reject it until a semantic exists. A loud failure beats a silent dead door.
