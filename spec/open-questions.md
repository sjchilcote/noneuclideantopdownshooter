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
