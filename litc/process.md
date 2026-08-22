# Literate Compiler — process spec (v0)

A natural-language compiler in the lineage of Knuth's Literate Programming. Knuth treated a code file as an essay; the Literate Compiler turns essays into code, and the code back into the essay.

**The problem it solves: flashover.** Iterative AI-assisted development accumulates small misspecifications until the user is *confidently wrong* about how critical parts of the application work — misspecifications stacked on misspecifications. The countermeasure is a format that forces full specification and keeps the human's mental model synchronized with what the code actually does.

**The core thesis: the specfile is the only channel.** Implementation, review, and reader agents receive only the specfiles and the repository — never the conversation in which the spec was developed. Anything not written down does not exist. Underspecification is a compile error, not a license to guess.

## Objects

### Specfiles

Markdown essays that ARE the design spec — a small natural-language codebase, worked on in Claude Code.

- **Organization follows the author's model of the product, not a fixed schema.** The author groups specs according to how they understand the problem: for chat_reader_zonos, by pipeline stage (gather messages → voice messages → wait for silence and play); for a game, per element and per level; for a web app, per page. Two fixed levels provide enough structure without prescribing file organization:
  - **Micro, fixed:** every unit gets the five sections. Spec'ing a unit is filling in named holes, never inventing a format.
  - **Macro, fixed:** the coverage rule (below). The compiler rejects gaps, never organization — file structure is not validated at all.
  - **Middle (file organization), free — but never blank.** The author starts with a draft to correct. For existing code, warm-start generates the corpus. For greenfield work, spec authoring opens with a short interview about the system's parts and relationships. The answer generates stub specfiles with titles and one-line placeholder goals. The author can rename, merge, split, and rearrange them. Example organizations (pipeline app → per-stage; game → per-element/per-level; web app → per-page) are guidance, not requirements.
- **The coverage rule is separate from organization:** every function in the code must trace to a goal *somewhere* in the corpus. Boilerplate (imports, dataclass field plumbing, obvious glue) is exempt.
- **Sections per unit:**
  - **Goal** — what the unit *accomplishes*, in full resolution, without prescribing mechanics. Human free prose, the author's voice. (E.g., "the projectile uses runge-kutta-inspired methods to integrate its high-speed motion, avoiding forward-Euler wall-phasing — the bullet sprite can collide with tens of objects in a single frame!" How to implement runge-kutta is the implementer's inference; only the goal is specified.)
  - **Invariants** — properties that must always hold.
  - **Verification** — goal-level evidence: what observable behaviors prove the unit works. The implementation agent designs the actual tests from this.
  - **Implementation** — machine-written after each build, in verified clear technical prose. Specifies exactly what the code does, at the code's own resolution minus boilerplate.
  - **Caveats** — anything else the writer sees fit.
- **Language rule:** everything agent-authored (Implementation sections and warm-start specfiles) follows `litc-clear-technical-prose.md`. Human-authored sections stay free prose.
- **Clarity rule:** natural, precise communication outranks conformity to ASD-STE100. The writing system takes useful constraints from STE, but it does not optimize for machine translation and does not require STE vocabulary or its prescribed paraphrases. Prose must not become telegraphic, unnatural, or less precise to satisfy a checker.

### Standards files

Playbooks the product is held to — e.g. `ux-principles-interactable-software.md` for anything a human operates at runtime. They answer the question the spec shouldn't have to: a GUI spec doesn't enumerate every widget; it has to survive an auditor holding the product to a named standard. Standards typically self-scope (the UX playbook's §0 paradigm gate selects which sections bind per unit), so declaration can be coarse.

- **Manifest-only attachment.** The manifest (`spec/standards/manifest.md`) is the single source of declared obligation: each applied standard with its scope. Standards are never declared anywhere else.
- **Coverage warnings — the Y/N/J protocol.** The pre-implementation check's agent scans for gaps and warns: "it looks like this module should have this standard applied, but it doesn't. Apply it? (Y/N/[J]ustify)"
  - **Y** → the agent modifies the manifest to apply the standard to the unit.
  - **N** → the agent records a manifest exemption for the unit, flagged *no reason given*.
  - **J** → the user means no, and is prompted for an explanation, which is written into the manifest exemption.

  Frontmatter is free prose that tells an agent how to process the document. It can explain which parts of an applied standard are relevant, but it cannot apply or exempt a standard. If the manifest applies a standard to a unit, that unit must _always_ be reviewed against the standard before implementation can begin. It only needs to be re-reviewed when changed; it does not need another review if it already passed the standard gate for the same content.
- **Acceptance gates, per applied standard.** The compiler does not accept the spec until both:
  1. P(the product will hold up against a reputable 3rd-party auditor holding the product to this standard) > 0.95
  2. P(the implementation agent won't find that it turned out to be underspecified upon implementation) > 0.95
- **Post-build discharge.** The Phase 5 verify gate re-runs the audit against the actual built product — for the UX standard that means driving the real app and producing the §15 human-path evidence ledger. The spec-time prediction gets discharged by real evidence, not left as a forecast.
- **Pinning.** Applying a standard copies it into `spec/standards/` at that version; receipts stay meaningful because the tree contains exactly the standard it was verified against. Upgrading a standard is an explicit spec change that triggers re-audit.
- **Unification:** the clear-technical-prose playbook is itself a standards file, applied to all agent-authored prose (Implementation sections and warm-start specfiles). ASD-STE100 remains a pinned reference for the rules that the playbook deliberately adopts; it is not an applied compliance standard.

### Receipts

A `litc verify` run executes the full gate and writes a receipt stamped with the exact tree hash it verified. The pre-commit hook is instant: it only checks that a fresh receipt exists for the staged tree. No verification is ever re-run on unchanged trees; no unverified tree can commit.

**Agents never commit.** The receipt hashes the whole tree, so a partial commit can never match while parallel work is in flight — by design. The orchestrator owns corpus-level commits, writes the receipt with the gate estimates recorded in it, and never lets one agent attest sibling work it did not verify.

## Lifecycle

### Phase 0 — Warm-start (optional, for existing codebases)

The reverse compiler. Turns existing code *into* specfiles, extracting the design in full detail: invariants, implementation details, verification steps, caveats, and whatever else the agent sees fit, in clear technical prose.

1. Decompile the whole codebase into a specfile corpus. **All sections describe the code as it IS** — a decompiled Verification never asserts behavior the recorded defects disprove. Where goal and reality diverge, the **qualify rule** applies: state the goal, point at the caveat; the divergence is a pending alter/rewrite decision, not a contradiction.
2. Reader-agent interrogation loop: fresh-context reader agents (no access to the code, primed with a brief profile of the user) interrogate each draft; revisers (with code access) fold the answers into the text; iterate rounds until the question flow dries (severity-labeled: BLOCKING/MINOR), then estimate P(the user will have no questions) > 0.95. Each revision agent touches ONLY its own specfile plus its glossary supplement (`spec/glossary-<worker>.md`, merged by the orchestrator); cross-file fixes are returned to the orchestrator, never applied directly.
3. Design-intent questions never get answered in the spec — they accumulate in `spec/open-questions.md`, the owner-decision surface (exempt from the agent-prose language gate by declared frontmatter reason). **Every open question ships with a proposed answer** derived from the owner's standing principles and the applied standards, naming its derivation; only questions with no derivable proposal reach the owner bare, marked as genuinely theirs. Ratification is by exception, Y/N/J style: the owner vetoes or edits; the rest compiles as proposed on their go. **Caveat markers:** `Defect:` only where an invariant or goal is not obeyed; `Decision open (see spec/open-questions.md item N)` where the owner must rule; unmarked caveats are plain facts.
4. The user then reads the whole corpus in one coherent pass, answers the open questions, ratifies the glossary, and corrects. The corpus becomes the source of truth.

**Observed behavior outranks static reading.** When the owner reports behavior that the spec or a code reading says cannot happen, the report is authoritative — N readings of the same text are correlated evidence, not N witnesses. Encode the observation as a Verification item and let the recompile kill the mechanism, whichever it is.

### Phase 1 — Spec authoring

The user specifies the problem and approach in conversation; Claude iterates on the exact specification; the user edits specfiles to clarify intent. Iterate until the pre-build gate passes:

> P(the implementation agent will not encounter ANY function whose goal is not specified by the specfiles) > 0.95

Estimated by spec-analysis agents that enumerate the functions/units the implementation will plausibly need and check each for goal coverage. Collect-all, not fail-fast — every gap reported at once, like a compiler listing all type errors.

The same check runs the standards machinery: coverage warnings (the Y/N/J protocol) for units a declared standard looks like it should bind, and the two per-standard acceptance gates (auditor-survival and not-underspecified, each > 0.95).

### Phase 2 — Change analysis (rebuilds only)

When specfiles change, an explicit step analyzes each changed unit: **alter** or **delete-and-rewrite**. The agent decides autonomously and logs its rationale in the build report.

### Phase 3 — Implementation

Fresh spec-only agents implement. **If the agent discovers it must invent significant unspecified units, or must guess at the user's intent, the build fails:**

1. Commit the attempt, tag it `litc/failed/<timestamp>` (survives GC, easy to salvage or delete later depending on how much the codebase changes after the underspecification is resolved).
2. Hard-reset HEAD back to the previous commit.
3. Write ALL collected underspecification errors as annotations into the working-tree specfiles (uncommitted — they survive the reset and sit exactly where specification is missing), each naming the unit, the missing decision, and the question needing an answer. A build-report file duplicates the list.

### Phase 4 — Essay-back

The implementation agent writes or updates the Implementation sections in clear technical prose, then the language gate runs in two stages:

1. **Deterministic linter** (`litc/ste/lint.py`, stdlib-only) — a fast heuristic check for structural risks that correlate with unclear writing, such as excessive sentence and paragraph complexity, malformed verb constructions, semicolons, and contractions. Backticked spans and code blocks are quoted-text exemptions. Dictionary membership, STE habit-word substitutions, and suffix-only `-ing` detection are not acceptance gates.
2. **Agent adjudication** applies `litc-clear-technical-prose.md` to meaning-level problems: unstable terminology, vague referents, figurative or nonstandard meanings, hidden causal steps, unsupported claims, and prose written to sound technical instead of to communicate. The adjudicator must consider the sentence in context and must not perform context-free substitutions.

**The checker is evidence, not the audience.** A writer never damages a sentence to remove a finding. The writer first decides whether the finding identifies a real communication problem. If it does, the writer rewrites the complete thought and preserves its meaning. If it does not, the finding does not block the build.

**The glossary kills private shorthand.** `spec/glossary.md` records recognized domain terms, proper names, file-format terms, and exact code-facing concepts that a reader needs. Definitions use the standard meaning of the term in its field or identify the exact project object. The glossary must not approve an ordinary word, a coined phrase, a metaphor, or a nonstandard meaning merely to make prose or a checker appear valid. Ordinary clear English does not need glossary permission.

### Phase 5 — Verify gate (produces the receipt)

- **Deep code review.**
- **Standards audits against the built product.** Auditor agents hold the real artifact to each applied standard — for the UX standard, driving the actual app through its real entry points and producing the §15 human-path evidence ledger.
- **Mutation testing run** (for example, if using Python, mutmut — but litc is deliberately platform agnostic, most popular languages should have a mutation testing tool available) with intelligent adjudication: each surviving mutant is examined and judged — does it represent a real missing test, or is it equivalent/irrelevant? Never blindly trust the tool's score. Leverage _property based testing_ to kill entire categories of mutants at once.
- **The four-clause gate.** Each clause independently estimated with explicit numbers; ALL must clear 0.95:
  1. P(the user will have no objections to any single line of the implementation section)
  2. P(the implementation section specifies exactly what the actual code does, to the same resolution as the code itself minus boilerplate)
  3. P(the software will be successful and useful for its designed purpose in the real world, in real application, in the hands of users)
  4. P(the implementation fully implements and matches the spec in the specfiles)

### Phase 6 — User verification

The user verifies the implementation, makes corrections if necessary, approves, and commits (the hook checks the receipt).

## Code comments

All comments follow the clear-technical-prose standard, although the checker does not parse them. A comment must pass a three-part test:

1. Does this sentence convey information
2. that someone reading this code would *need* to fully understand the effects of running or changing this code
3. that a competent programmer would not gather immediately from reading this unit's code?

Comments may *reference* spec files, but never *quote* or *restate* them — otherwise drift becomes possible. Comments are primarily *implementation notes*; *err against* including design intent in code comments.

## Prompts

All prompts litc drives its agents with follow the clear-technical-prose standard, and *every single line* must point to a stated requirement in the spec. In prompting, *less* is always more: provide the model with a complete specification of what the end state must look like, whatever other context it needs to understand, and *nothing else* — as concisely and clearly as possible. Do not include one-shots, examples, or anchors unless they have proven to be *necessary*. Default to trusting the agent's judgment.

## Edit discipline — two-track

- **Code diverges from spec** → recompile that unit (an agent fixes it; the spec is untouched).
- **Spec was wrong** → the user edits the spec; rebuild.
- Nobody hand-edits code silently. Every code change flows through the compiler.

## Fidelity bar — rebuildability

The Implementation section passes when a fresh agent given ONLY the essay (spec + implementation section) could produce functionally equivalent code. Spot-checked occasionally by actually performing that rebuild and diffing behavior.

## Success criteria (pilot)

1. **Flashover counterfactual** — successive real changes flow spec-first with zero moments of the user being confidently wrong about how the app works, and zero guessed intent by implementers.
2. **Rebuild fidelity** — rebuild-from-essay spot checks produce functionally equivalent code.
3. **Spec becomes source of truth** — the user reaches for the specfiles instead of the source to answer "how does this work," and they're never wrong.

(A time-and-motion study on change cost comes later, only if the process *feels* better.)

## Pilot plan (manual, this worktree, chat_reader_zonos as target)

No tooling is built until the process shape is learned by running it by hand.

1. **Warm-start the whole app** into specfiles, organized by pipeline stage. Agent-side iteration comes first; then the user reads the corpus in one coherent pass. The first applied standards are `ux-principles-interactable-software.md` and `litc-clear-technical-prose.md` (pinned into `spec/standards/`).
2. **A real change** flows through the full loop — spec edit → change analysis → spec-only implementation subagents → essay-back → manual gates → user verification.
3. **Automate what worked** into the `litc` CLI (Python/uv) orchestrating headless Claude agents; git hooks call the CLI; thin slash-commands wrap it in-session.

**Isolation is real from day one:** even in manual mode, all implementation/review/reader work runs in fresh subagents that receive only the specfiles + repo. The orchestrating session never leaks conversation context into them.

- **Name:** `litc`. **Layout:** specfile corpus under `spec/` at repo root; experiment artifacts under `litc/`.
- **Staffing:** every judgment-bearing agent (implementer, reviewers, readers, mutant adjudicator, gate estimators) runs the top model tier. No downgrades to save cost. Fable-level agents farm out all line-level edits to Sonnet subagents; frontier models build the spec, then _coordinate_ implementation. Sonnets do all the actual code edits, then a stronger model reviews its work for compliance and apply corrections.
- **Determinism stance:** the compiler guarantees spec-satisfaction, not bit-reproducible output — any compliant implementation is a valid compile.
- **Reader priming:** warm-start reader agents get a one-paragraph profile of the user (lifelong programmer, expert) so P(no questions) is estimated for the actual audience.
- **Language gate:** agent-graded against the clear-technical-prose playbook with specific findings tied to the text and its meaning.
