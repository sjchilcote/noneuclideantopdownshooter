# Standards manifest

This file lists the standards files that apply to `NETDS` (working title: Non-Euclidean Top Down Shooter). A standards file does not apply from a different location.

| Standards file | Version | Scope |
|---|---|---|
| `litc-clear-technical-prose.md` | 2026-08-04 | All agent text: Implementation sections, warm-start specfiles, comments, and prompts. The checks do not parse comments. |
| `ux-principles-interactable-software.md` | copied 2026-08-03 | The standard scope below. |

`ste-simplified-technical-english.md` is a pinned source for the writing system. It is not an applied compliance standard.

### Scope of the standard

The standard applies to all runtime surfaces and outputs of the released game: window, input, audio, rendered feedback, menus, and modes. It also applies to the level editor, because the editor ships to players as part of the product. This is a deliberate difference from `PERIHELION`, where the editor is internal tooling.

The standard does not apply to the development harness (`perf_test.py`, `dip_test.py`, `test_leveledit.py`) or to future internal test tooling. The prototype specfiles (`spec/prototype-*.md`) describe the 2025 prototype as it is. The standard binds the product that will be built from that definition. Audit findings against the prototype are recorded as caveats, not failures.

`engine-core.md`, `engine-binding.md`, and `tools-music.md` transferred here with their code in the separation of 2026-08-22. The engine specfiles cover library units: section 0 of the UX standard selects what binds, through the game surfaces that use them. `tools-music.md` covers internal authoring tools, outside the UX scope. These three files were written and audited under the PERIHELION corpus. Their frontmatter still names that corpus and is corrected at this corpus's next audit.
