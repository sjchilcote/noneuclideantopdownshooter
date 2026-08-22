#!/usr/bin/env python3
"""
COPIED VERBATIM (2026-07-13) from diet_app/scripts/consult_planner_diagnostics.py
for reuse as the generic "consult an external model over OpenRouter" engine.
The original is untouched; this copy exists so PERIHELION's musicgen work can
build its own prompt (e.g. calibrating an intensity metric) without
reimplementing the streaming/crash-safety machinery.

REUSABLE (generic, not diet_app-specific) -- import these:
    read_source, section, file_block, extract_bayescraft, tokenish_size,
    stream_consult, stream_consult_responses
    + constants: OPENROUTER_URL, OPENROUTER_RESPONSES_URL, DEFAULT_MODEL,
      DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_CONNECT_TIMEOUT_S,
      GLOBAL_CLAUDE_MD

DIET_APP-SPECIFIC (left in place for reference; do not call as-is here) --
    capture_real_examples, build_prompt, main(), PRODUCT_CONTEXT, ASK,
    RUST_FILES, PYTHON_FILES -- these import engine.plan/planner_rs etc.
    (diet_app modules that do not exist in this repo) and describe the meal
    planner, not music. Before running a real consult for musicgen, write a
    new build_prompt()/ASK tailored to the intensity-metric question and a
    thin CLI, reusing only the REUSABLE list above (see consult_telemetry.py
    in diet_app/scripts/ for a worked example of doing exactly that: it
    imports stream_consult_responses etc. from this module and defines its
    own product-specific prompt).

--------------------------------------------------------------------------
ORIGINAL DOCSTRING BELOW, describing the diet_app planner consult this file
was written for:
--------------------------------------------------------------------------

Consult an EXTERNAL model (OpenAI GPT-5.6 Sol Pro, via OpenRouter) about our
Rust A* meal planner's diagnostics design.

WHY: engine/plan.py + planner_rs compute a lot during a planning run (pool
diversity, search-node expansions, near-miss rejections, per-slot macro
slack, postmortem shortfalls...) and throw almost all of it away. We want an
outside model, with no stake in our design and no sunk cost in our
abstractions, to propose theories -- with testable hypotheses, falsifying
observations, and confidence thresholds -- for how that thrown-away data
could become ACTIONABLE FEEDBACK TO THE USER ("your pantry is protein-thin
for your goals", "buy 2lb of chicken and the week plans"). We test the
theories against our real 52-pantry corpus before implementing any of them;
this script only produces the consult, it does not implement anything.

This script does NOT touch app/coach.py, app/ops.py, app/jobs.py, engine/,
or planner_rs/ -- it only READS them to assemble a prompt, and writes to its
own scripts/out/planner_consult/ directory.

Usage:
    # Sanity-check the prompt (no network, no API key needed) --------------
    uv run python scripts/consult_planner_diagnostics.py --dry-run

    # The real, possibly-many-minutes xhigh-reasoning consult --------------
    uv run python scripts/consult_planner_diagnostics.py

Requires OPENROUTER_API_KEY in the environment or a .env file at the repo
root (python-dotenv). The script fails loudly and immediately if it is
missing -- it never prints the key and never hardcodes one.

Output (new timestamped directory per run, so reruns never clobber a prior
consult):
    scripts/out/planner_consult/<UTC-timestamp>/prompt.txt       -- exact prompt sent
    scripts/out/planner_consult/<UTC-timestamp>/raw.jsonl        -- every raw SSE line, appended+flushed live
    scripts/out/planner_consult/<UTC-timestamp>/reasoning.txt    -- reasoning deltas, appended+flushed live
    scripts/out/planner_consult/<UTC-timestamp>/answer.md        -- content deltas, appended+flushed live
    scripts/out/planner_consult/<UTC-timestamp>/meta.json        -- run metadata (model, effort, tokens, exit status)

Streaming-to-disk is the critical requirement here: gpt-5.6-sol-pro at
"xhigh" reasoning effort can think for many minutes. Every SSE chunk is
appended AND fsync'd to disk the moment it arrives, so a crash, a timeout, or
a mid-stream disconnect still leaves everything received up to that point on
disk -- this script never buffers in memory and writes at the end.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Same convention as app/auth.py / app/api.py: secrets.env first (if present),
# then a plain .env, both repo-root. Never hardcode a key; this is the only
# source of OPENROUTER_API_KEY.
load_dotenv(PROJECT_ROOT / "secrets.env")
load_dotenv(PROJECT_ROOT / ".env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_RESPONSES_URL = "https://openrouter.ai/api/v1/responses"
DEFAULT_MODEL = "openai/gpt-5.6-sol-pro"
# READ THE DOCS BEFORE TOUCHING THESE TWO. They are coupled, and getting them
# wrong is why this script failed 5/5 while looking like a provider problem.
#
# OpenRouter derives the REASONING BUDGET from max_tokens by effort:
#     xhigh/max ~95%   high ~80%   medium ~50%   low ~20%   minimal ~10%
# (https://openrouter.ai/docs/use-cases/reasoning-tokens)
#
# We previously ran effort=xhigh with max_tokens=128_000. That commissions a
# ~121,600-token THINK and leaves ~6,400 tokens to write the answer in. Every
# run died at 350-410s with a 500, on BOTH Azure and OpenAI, and we diagnosed a
# "hard upstream inference-time ceiling". There is no such ceiling: we were
# simply asking for a think so long nothing upstream would sit through it, and
# `low` (a ~25k-token think) completed the identical prompt in 55s.
# It also could not have succeeded on its own terms -- 6.4k output tokens cannot
# hold the exhaustive answer we were asking for. The configuration was
# self-defeating in both directions, and the comment on this very line used to
# say "xhigh burns up to ~95% of this on reasoning" while setting it to 128k.
#
# Note also: OpenAI's reasoning models DO NOT STREAM their reasoning tokens, so a
# long think looks EXACTLY like a hang -- keep-alives and nothing else. That is
# what made this so easy to misread.
#
# **max_tokens IS ALWAYS THE MODEL'S MAXIMUM. Never shrink it.** It is a CEILING,
# not a reservation -- you pay for tokens GENERATED, so a high limit costs nothing
# and only prevents truncation. Shrinking it is pure loss, and doing so has caused
# a string of real bugs in this codebase (empty coach replies, silently truncated
# oracle results, a tool-call cap the model hit mid-haul).
#
# So EFFORT is the knob for think length, not max_tokens. Tune effort down if a
# run does not return; never starve the answer to shorten the think.
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 128_000   # sol-pro's max_completion_tokens (probed via /endpoints)
DEFAULT_CONNECT_TIMEOUT_S = 15.0  # connect only -- the read side must NOT time out a long think

# =============================================================================
# WHICH API SKIN TO USE, AND WHY IT IS NOT A STYLE CHOICE
# =============================================================================
# Measured 2026-07-12, not guessed. On /chat/completions, EVERY long think
# died: 5/5 at effort=xhigh and 1/1 at effort=high, each one an in-stream HTTP
# 500 ("error_type": "server") with ZERO content bytes, landing in a tight
# 348-406s band -- on BOTH the Azure and the OpenAI endpoints, and at prompt
# sizes from 131k to 703k chars. effort=low on the very same prompt returned
# real content in 55s. So it is not a sick provider, not the prompt, and not
# prompt size: it is a hard ceiling on how long a /chat/completions request may
# sit without the UPSTREAM leg producing anything.
#
# The mechanism: reasoning deltas do not stream DURING an OpenAI-model think --
# at effort=low the entire 456 bytes of reasoning arrived at t+54.7s, i.e. at
# the END. OpenRouter's own ": OPENROUTER PROCESSING" comments keep OUR leg
# alive, but they do nothing for the upstream leg, which stays silent for the
# whole think and gets reaped at ~6 minutes.
#
# The documented answer for long reasoning is background mode (POST with
# background:true, then poll GET /v1/responses/{id}). OPENROUTER CANNOT DO
# THIS -- probed directly: its Responses schema rejects `store: true`
# ("invalid_value ... expected false") and forces `background: false`, and
# GET /v1/responses/{id} 404s. It is a stateless proxy; there is nothing to
# poll. Background mode would require an OpenAI key, which this repo does not
# have (.env carries ANTHROPIC_API_KEY and OPENROUTER_API_KEY only).
#
# What DOES work, and is what stream_consult_responses below uses: the
# Responses API skin (/api/v1/responses), which emits its own `keepalive`
# SSE events on the upstream leg for the entire think. Same model, same
# effort, same prompt -- it sails straight past the ~400s wall that killed
# every chat-completions run. That is the whole fix.
# =============================================================================

OUT_ROOT = PROJECT_ROOT / "scripts" / "out" / "planner_consult"

GLOBAL_CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"

# Real source files inlined VERBATIM into the prompt (not summarized). Order
# mirrors the PyO3 call chain: low-level types up to the module boundary.
RUST_FILES = [
    "planner_rs/src/types.rs",
    "planner_rs/src/matching.rs",
    "planner_rs/src/portions.rs",
    "planner_rs/src/solver.rs",
    "planner_rs/src/pool_gen.rs",
    "planner_rs/src/coherence.rs",
    "planner_rs/src/astar.rs",
    "planner_rs/src/lib.rs",
]
PYTHON_FILES = [
    "engine/plan.py",
    "engine/counterfactual.py",
    "engine/pantry.py",
    "engine/meal_template.py",
]
EXAMPLE_PANTRY_REL = "data/pantries/pantry_default.xml"
TEMPLATES_REL = "data/meal_templates.xml"


# =============================================================================
# Source assembly -- read the REAL files off disk every time. No paraphrase,
# no cached snapshot: whatever is on disk right now is what gets inlined.
# =============================================================================

def read_source(rel_path: str) -> str:
    path = PROJECT_ROOT / rel_path
    if not path.exists():
        raise FileNotFoundError(
            f"Expected source file missing: {rel_path}. This script inlines REAL "
            f"code into the prompt; it will not substitute a placeholder."
        )
    return path.read_text()


def section(title: str, body: str) -> str:
    bar = "=" * 78
    return f"{bar}\n{title}\n{bar}\n{body}\n"


def file_block(rel_path: str) -> str:
    text = read_source(rel_path)
    n_lines = text.count("\n") + 1
    header = f"----- FILE: {rel_path} ({n_lines} lines, {len(text)} chars) -----"
    footer = f"----- END FILE: {rel_path} -----"
    return f"{header}\n{text}\n{footer}\n"


def extract_bayescraft(claude_md_path: Path) -> str:
    """Copy the '# Bayescraft' section verbatim out of the user's global
    CLAUDE.md -- from the '# Bayescraft' heading up to (not including) the
    next top-level '# ' heading ('# How I work with Stephen'). Fails loudly
    if the file or the section is missing; never fabricates the framework.
    """
    if not claude_md_path.exists():
        raise FileNotFoundError(
            f"Cannot find {claude_md_path} -- required to inline the Bayescraft "
            f"framework verbatim. Pass --claude-md to point at the right file."
        )
    text = claude_md_path.read_text()
    start = text.find("\n# Bayescraft")
    if start == -1:
        start = 0 if text.startswith("# Bayescraft") else -1
    if start == -1:
        raise ValueError(f"'# Bayescraft' heading not found in {claude_md_path}")
    start = text.find("# Bayescraft", start)
    # Next top-level heading after Bayescraft's own heading line.
    search_from = start + len("# Bayescraft")
    next_heading = text.find("\n# ", search_from)
    end = next_heading if next_heading != -1 else len(text)
    return text[start:end].strip() + "\n"


# =============================================================================
# Real planner runs -- success + an engineered (honestly-labeled) failure.
# These are ACTUAL PlanningResult objects from the real Rust A* planner, not
# invented text. Failure is produced by multiplying the protein target until
# the real solver actually reports failure (a crude by-hand version of the
# parameterized "strain" transform the consult itself is being asked about).
# =============================================================================

def capture_real_examples(
    pantry_rel: str,
    templates_rel: str,
    with_counterfactual: bool = False,
) -> str:
    """Run the REAL planner and return its REAL output as prompt text.

    `with_counterfactual`: engine/plan.py:2942 auto-runs the phantom
    counterfactual experiment on any Rust-path failure (n_seeds=5 -> 10 more
    full planning runs, each itself a failing 3-pass run). On a strained,
    deliberately-infeasible target that costs ~25 minutes. It is therefore
    DISABLED by default here, and the prompt says so explicitly rather than
    implying we ran it. Pass --with-counterfactual to actually run it and
    inline the real shopping list it computes.
    """
    from engine.customer_profile import CustomerProfile
    from engine.meal_template import MealTemplateCollection
    from engine.pantry import MacroNutrients, Pantry
    from engine.plan import MealPlan

    pantry_path = PROJECT_ROOT / pantry_rel
    templates_path = PROJECT_ROOT / templates_rel
    templates = MealTemplateCollection.from_file(templates_path)
    profile = CustomerProfile.from_xml_file(pantry_path)

    out = []
    out.append(f"Pantry file: {pantry_rel}  (profile name: {profile.name!r})")
    if profile.description:
        out.append(f"Profile description: {profile.description}")
    t = profile.target_macros
    out.append(
        f"Declared daily target: {t.protein:.0f}p / {t.carbs:.0f}c / {t.fat:.0f}f / "
        f"{t.calories:.0f}cal, undershoot_tolerance={profile.undershoot_tolerance}, "
        f"overshoot_tolerance={profile.overshoot_tolerance}, "
        f"max_meal_mass={profile.max_meal_mass}"
    )
    out.append(f"Pantry item count: {len(profile.receipt.items)}")

    # ---- Example A: SUCCESS, exactly as declared in the pantry XML --------
    out.append("\n--- EXAMPLE A: real SUCCESS run (pantry's own declared target) ---")
    print("  [example A] running real planner at declared target...", file=sys.stderr, flush=True)
    random.seed(42)  # legacy-path convention; the Rust path mints its own fresh seed by default now
    pantry = Pantry()
    pantry.add_receipt(profile.receipt)
    mp = MealPlan(
        profile.target_macros,
        meal_plan_structure=profile.get_meal_schedule(),
        undershoot_tolerance=profile.undershoot_tolerance,
        overshoot_tolerance=profile.overshoot_tolerance,
        max_meal_mass=profile.max_meal_mass,
    )
    mp.run_counterfactual_on_failure = with_counterfactual
    t0 = time.time()
    result = mp.plan_meals(pantry, templates)
    dt = time.time() - t0
    print(f"  [example A] success={result.success} in {dt:.1f}s", file=sys.stderr, flush=True)
    out.append(f"wall time: {dt:.1f}s   rust_seed: {mp.seed}")
    out.append(f"result.success = {result.success}")
    if result.success:
        weekly = result.get_weekly_macros()
        avg = weekly * (Decimal(1) / Decimal(7))
        out.append(
            f"weekly totals: {weekly.protein:.0f}p/{weekly.carbs:.0f}c/"
            f"{weekly.fat:.0f}f/{weekly.calories:.0f}cal"
        )
        out.append(
            f"daily average:  {avg.protein:.0f}p/{avg.carbs:.0f}c/"
            f"{avg.fat:.0f}f/{avg.calories:.0f}cal"
        )
        out.append("Sample of planned slots (first 4 of "
                    f"{len(result.planned_meals)}):")
        for key in list(result.planned_meals.keys())[:4]:
            day, meal_name = key
            for meal in result.planned_meals[key]:
                title = meal.template.title if meal.template else "Freeform"
                m = meal.total_macros
                out.append(
                    f"  {day} {meal_name} [{title}] "
                    f"{m.protein:.0f}p/{m.carbs:.0f}c/{m.fat:.0f}f/{m.calories:.0f}cal, "
                    f"{meal.mass:.0f}g total"
                )
                for slot_name, portion in meal.allocations.items():
                    if portion is not None:
                        out.append(f"      - {slot_name}: {portion.item_name} ({round(portion.amount)}g)")
    else:
        out.append(f"reason_for_failure = {result.reason_for_failure!r}")
        if result.postmortem_report:
            out.append(result.postmortem_report.format_summary())

    # ---- Example B: engineered FAILURE, escalating protein strain ---------
    out.append(
        "\n--- EXAMPLE B: real FAILURE run (same pantry, protein target walked up "
        "a fine strain ladder until the real Rust A* planner actually reports "
        "failure, so the captured failure is the MOST MARGINAL one this ladder "
        "finds, not an obviously-infeasible one -- honestly labeled: this is a "
        "hand-rolled stand-in for exactly the parameterized 'strain' transform the "
        "consult below is asked to design experiments around. Every probe's real "
        "outcome and wall time is listed) ---"
    )
    # Fine-grained ladder, ascending: we want the FIRST (i.e. most marginal)
    # failure, not an obviously-infeasible one. A coarse jump (e.g. straight to
    # 4x protein) fails with empty pools at slot 0/21, which exercises none of
    # the postmortem's shortfall machinery and would show the consult a
    # degenerate failure mode. Walking up in small steps lands us as close to
    # the real feasibility boundary as this ladder allows.
    strain_result = None
    for mult in ("1.25", "1.5", "1.75", "2", "2.5", "3", "4", "8"):
        print(f"  [example B] strain probe: protein x{mult}...", file=sys.stderr, flush=True)
        random.seed(42)
        strained_target = MacroNutrients(
            t.protein * Decimal(mult), t.carbs, t.fat, t.calories,
        )
        pantry_b = Pantry()
        pantry_b.add_receipt(profile.receipt)
        mp_b = MealPlan(
            strained_target,
            meal_plan_structure=profile.get_meal_schedule(),
            undershoot_tolerance=Decimal("0.0"),
            overshoot_tolerance=profile.overshoot_tolerance,
            max_meal_mass=profile.max_meal_mass,
        )
        # engine/plan.py:2942 would otherwise fire a 5-seed counterfactual
        # (10 more full planning runs) on EVERY failed probe. Opt-in only.
        mp_b.run_counterfactual_on_failure = with_counterfactual
        t0 = time.time()
        r = mp_b.plan_meals(pantry_b, templates)
        dt_b = time.time() - t0
        print(f"  [example B] x{mult}: success={r.success} in {dt_b:.1f}s",
              file=sys.stderr, flush=True)
        if not r.success:
            strain_result = r
            out.append(
                f"protein target x{mult} = {strained_target.protein:.0f}g/day -> "
                f"FAILED after {dt_b:.1f}s (as expected)"
            )
            break
        out.append(
            f"protein target x{mult} = {strained_target.protein:.0f}g/day -> "
            f"succeeded in {dt_b:.1f}s, escalating strain further"
        )

    if strain_result is not None:
        out.append(f"\nresult.success = {strain_result.success}")
        out.append(f"reason_for_failure = {strain_result.reason_for_failure!r}")
        if strain_result.postmortem_report:
            out.append("\npostmortem_report.format_summary():")
            out.append(strain_result.postmortem_report.format_summary())
        if strain_result.remaining_pantry:
            overdrawn = {k: v for k, v in strain_result.remaining_pantry.items() if v < 0}
            if overdrawn:
                out.append("\noverdrawn items (remaining_pantry < 0):")
                for name, grams in sorted(overdrawn.items(), key=lambda kv: kv[1]):
                    out.append(f"  {name}: {grams:.0f}g")

        # The counterfactual ("what would fix this pantry") -- only present if
        # it was actually run. We never synthesize one.
        cf = getattr(strain_result.postmortem_report, "counterfactual_result", None) \
            if strain_result.postmortem_report else None
        if cf is not None:
            from engine.counterfactual import format_report, format_shopping_list
            out.append(
                "\n--- REAL counterfactual experiment output for the failure above "
                "(engine/counterfactual.py, phantom-injection, n_seeds=5, run just "
                "now -- this is the computed 'what would fix this' answer) ---"
            )
            out.append(format_shopping_list(cf))
            out.append(format_report(cf))
        else:
            out.append(
                "\nNOTE (no fabrication): the phantom counterfactual experiment "
                "(engine/counterfactual.py -- the code that computes the 'what "
                "would fix this pantry' shopping list, invoked automatically at "
                "engine/plan.py:2942 on failure) was NOT run for this captured "
                "example, because on a deliberately-infeasible strained target it "
                "costs 10 additional full failing planning runs (~25 min). Its "
                "complete source, including run_counterfactual_experiment() and "
                "format_shopping_list(), is inlined verbatim in section 3 above -- "
                "reason about it from the code, and note that in normal production "
                "operation a real user's failed plan DOES carry this "
                "ExperimentResult on postmortem_report.counterfactual_result."
            )
    else:
        out.append(
            "NOTE: every strain level on the ladder above still succeeded for this "
            "pantry -- reporting the highest-strain success honestly instead of "
            "inventing a failure."
        )

    return "\n".join(out) + "\n"


# =============================================================================
# Prompt assembly
# =============================================================================

PRODUCT_CONTEXT = """\
This is a trainer-first meal planning app: a coach chatbot plus a GOFAI
(good-old-fashioned-AI) planner that operates over a real user's actual
pantry. Key facts you need to reason correctly about this system:

- The PANTRY IS REAL FOOD. `data/pantries/*.xml` is a ~52-file test-harness
  CORPUS of synthetic archetypes (bodybuilder, keto, budget family, historical
  diets, medical diets, etc.) used to exercise the planner broadly -- it is
  NOT product data, and the corpus is never seeded/cloned into product
  accounts. A live user's pantry is their literal groceries: what SimPantry
  matches against is what is physically in their kitchen. We can run
  experiments on the corpus completely freely (no user-facing cost); we
  cannot ship any diagnostic to a user that isn't honestly true of one
  person's fridge.
- Every diagnostic idea proposed below must eventually cash out as feedback
  to a REAL HUMAN using the app -- e.g. "your pantry is protein-thin for
  your goals" or "buy 2lb of chicken and the week plans" -- not raw solver
  internals (node counts, A* g-scores, DFS call counts) dumped verbatim.
- The Rust A* planner (`planner_rs`, the sole production path -- see
  `engine/plan.py:2519`, `getattr(self, 'use_rust', True)`) is SEEDED and
  MUST STAY BIT-FOR-BIT DETERMINISTIC. Any diagnostic that requires recording
  new data must be pure OBSERVATION of the existing deterministic search --
  logging/counting what already happens -- never an INTERVENTION that
  changes search order, pruning, or the random draws. Flag explicitly
  anywhere your proposal would require changing search behavior to get the
  signal; that is out of scope for "free" instrumentation and needs separate
  justification.
- The 52-pantry corpus plus a parameterized "strain" transform (we can make
  any pantry arbitrarily harder along a knob: comfortable -> marginal-but-
  feasible -> barely infeasible -> obviously infeasible, e.g. by scaling
  macro targets, tightening tolerances, or depleting items) is our free
  experimental apparatus. Any hypothesis you propose should be testable by
  running the real (already-built, already-fast: single runs take seconds to
  about a minute) planner across this corpus at varying strain levels.
"""

ASK = """\
================================================================================
THE ASK
================================================================================
You have just been given, in full and verbatim, the actual production
source of a Rust A* meal-planning solver (planner_rs/src/*.rs), its Python
orchestration layer (engine/plan.py, engine/counterfactual.py, engine/pantry.py,
engine/meal_template.py), a real pantry from our test corpus, and two REAL
planning results captured by actually running that planner just now: one
success and one engineered failure. You were also given, verbatim, the
Bayescraft framework we use to reason about evidence.

Your job: enumerate every way the data a planning run produces -- or COULD be
made to produce, subject to the determinism constraint above -- can be used
to analyze that run, with an eye to ACTIONABLE FEEDBACK TO THE USER.

For EACH candidate signal, give ALL of the following, structured as a
Bayesian, falsifiable claim -- not a brainstorm entry:

  1. THEORY: what the signal means mechanistically, given the solver's ACTUAL
     design as shown above (not a generic meal-planning platitude -- ground it
     in specific mechanisms: e.g. pool_gen.rs's DFS exhaustion criteria,
     astar.rs's g-score/heuristic, the three-pass strict/multi_meal/freeform
     relaxation in engine/plan.py, the postmortem's ingredient_shortfalls, the
     counterfactual phantom-injection experiment, etc.)

  2. TESTABLE HYPOTHESIS: stated so it could be FALSIFIED by data we can
     gather from the 52-pantry corpus plus the parameterized strain
     transform. Not "sparse pools indicate a hard pantry" (unfalsifiable
     mush) -- something like "mean pool size per template drops below N
     before the planner's own success rate drops below M%, giving at least
     K percentage points of strain-level lead time."

  3. EXPERIMENT + DISCONFIRMING OBSERVATION: the actual experiment to run
     against the corpus + strain transform, AND the specific observation that
     would LOWER your credence in the hypothesis. Per conservation of
     expected evidence: if no possible outcome would lower your credence,
     say so explicitly and rank the idea as untested speculation, not a
     theory.

  4. PRIOR (odds) + EXPECTED LIKELIHOOD RATIO: your prior odds that this
     signal is genuinely useful (not just "looks smart"), and the LR you'd
     expect the experiment to produce if the hypothesis is true. Use these to
     RANK what to test first -- don't just list ideas in the order you
     thought of them.

  5. CONFIDENCE THRESHOLD: at what measured separation (effect size, not
     "statistically significant" hand-waving) would this be worth SURFACING
     to a real user, and at what point is it indistinguishable from noise?

  6. USER-FACING MESSAGE: the concrete sentence(s) this would enable (in the
     register of "your pantry is protein-thin for your goals" / "buy 2lb of
     chicken and the week plans"), and explicitly what it must NOT claim
     (avoid overclaiming causality, precision, or generality the underlying
     signal doesn't support).

THEN:

  - Explicitly call out signals that LOOK meaningful but are probably NOISE
    -- things whose semantics can't be honestly stated as a user-facing
    claim even if they correlate with something.
  - Flag any place our CURRENT design (as shown in the real success/failure
    examples and the postmortem/counterfactual code) is likely to MISLEAD a
    user if surfaced naively.
  - RANK everything by (value to the user) x (probability the hypothesis
    survives testing), not by novelty or cleverness.
  - For every candidate, explicitly state whether the planner ALREADY
    records what's needed (pure observation, free) or would need to be
    MODIFIED to record it -- and if modified, confirm/deny that the
    modification is observation-only (a new counter/log write) versus an
    actual change to search behavior (forbidden, breaks determinism).

Do not pad this with generic ML-diagnostics advice ("track more metrics",
"build a dashboard") -- every entry must be traceable to a specific
mechanism in the code you were just shown, with a specific file/line
reference.
"""


def build_prompt(
    pantry_rel: str,
    templates_rel: str,
    claude_md_path: Path,
    with_counterfactual: bool = False,
) -> str:
    parts = []

    parts.append(
        "EXTERNAL CONSULT: Rust A* Meal Planner -- Diagnostics & "
        "Actionable-User-Feedback Design Review\n\n"
        "You are being asked to review a real production meal-planning solver "
        "and propose, in Bayesian/falsifiable form, every way its discarded "
        "search-time data could become actionable feedback to a real user. "
        "The full, precise ask -- including the exact required structure for "
        "each proposal -- is given in the final section of this prompt "
        "('THE ASK'). Read the source and the Bayescraft framework first; "
        "they are real and exhaustive, not summarized.\n"
    )

    parts.append(section("0. PRODUCT CONTEXT", PRODUCT_CONTEXT))

    parts.append(section(
        "1. THE BAYESCRAFT FRAMEWORK (verbatim, copied from our internal "
        "engineering standard -- structure every proposal below this way)",
        extract_bayescraft(claude_md_path),
    ))

    rust_body = "\n".join(file_block(p) for p in RUST_FILES)
    parts.append(section(
        "2. RUST A* PLANNER SOURCE (planner_rs/src/*.rs) -- the sole "
        "production planning path. Order: types -> matching -> portions -> "
        "solver -> pool_gen -> coherence -> astar -> lib (the PyO3 boundary "
        "that engine/plan.py calls through).",
        rust_body,
    ))

    py_body = "\n".join(file_block(p) for p in PYTHON_FILES)
    parts.append(section(
        "3. PYTHON ENGINE SOURCE -- orchestration, macro/tolerance model, "
        "the three-pass relaxation, postmortem, and the counterfactual "
        "'what would fix this pantry' experiment.",
        py_body,
    ))

    pantry_body = file_block(pantry_rel)
    parts.append(section(
        "4. A REAL CORPUS PANTRY (data/pantries/pantry_default.xml) -- a "
        "concrete example of the <profile> (targets/tolerances/schedule) + "
        "<items> shape every pantry in the corpus follows.",
        pantry_body,
    ))

    examples_body = capture_real_examples(pantry_rel, templates_rel, with_counterfactual)
    parts.append(section(
        "5. REAL PLANNING RESULTS -- an actual success and an actual "
        "engineered failure, produced by running the real planner just now "
        "against the pantry above (NOT invented output).",
        examples_body,
    ))

    parts.append(ASK)

    return "\n".join(parts)


def tokenish_size(text: str) -> int:
    """Rough token-count heuristic (~4 chars/token). Not exact -- for sanity
    -checking prompt size against the model's context window only."""
    return len(text) // 4


# =============================================================================
# Streaming API call
# =============================================================================

def stream_consult(
    prompt: str,
    api_key: str,
    model: str,
    effort: str,
    max_tokens: int,
    connect_timeout_s: float,
    out_dir: Path,
    url: str = OPENROUTER_URL,
    provider_prefs: dict | None = None,
) -> int:
    """``provider_prefs``: an OpenRouter "provider" routing block, e.g.
    ``{"ignore": ["Azure"]}`` or ``{"order": ["OpenAI"], "allow_fallbacks":
    False}``. Default None -> the key is omitted entirely and OpenRouter picks
    the route, i.e. EXACTLY the behavior every existing caller already gets.

    Why this exists: OpenRouter load-balances one model id across several
    upstream providers, and a single sick provider takes the whole consult
    down with an in-stream 500 that no amount of retrying routes around --
    2026-07-13, gpt-5.6-sol-pro's Azure endpoints 500'd twice in a row (~6
    min of keep-alives, zero content bytes, both runs) while its OpenAI
    endpoints sat deranked, so every retry landed back on the broken one.
    Being able to NAME the provider is the difference between "retry into the
    same wall" and actually getting the answer.
    """
    import httpx

    raw_path = out_dir / "raw.jsonl"
    reasoning_path = out_dir / "reasoning.txt"
    answer_path = out_dir / "answer.md"
    meta_path = out_dir / "meta.json"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "reasoning": {"effort": effort},
        "max_tokens": max_tokens,
        # Route around Azure. It serves this model, but it cannot hold a
        # connection through a ~170k-token prompt at xhigh effort: two runs died
        # mid-stream after an hour of keep-alives (a 500, then a 502 "Network
        # connection lost"). OpenAI serves the same model directly. allow_fallbacks
        # stays False -- silently falling back to the provider we are avoiding
        # would just reproduce the failure while looking like a routing success.
        "provider": {"order": ["openai"], "allow_fallbacks": False},
    }
    if provider_prefs:
        payload["provider"] = provider_prefs
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/diet-app/planner-diagnostics-consult",
        "X-Title": "diet-app planner diagnostics consult",
    }
    # Connect timeout only. Read=None means "no read timeout" -- an xhigh
    # think can legitimately run for many minutes and must not be killed by
    # an idle-read deadline.
    timeout = httpx.Timeout(connect=connect_timeout_s, read=None, write=30.0, pool=connect_timeout_s)

    meta = {
        "model": model,
        "effort": effort,
        "max_tokens": max_tokens,
        "provider_prefs": provider_prefs,
        "prompt_chars": len(prompt),
        "prompt_tokenish": tokenish_size(prompt),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
        "exit_status": None,
        "reasoning_bytes": 0,
        "content_bytes": 0,
        "finish_reason": None,
        "usage": None,
    }

    def _write_meta():
        meta_path.write_text(json.dumps(meta, indent=2))

    _write_meta()

    reasoning_bytes = 0
    content_bytes = 0
    saw_done = False
    finish_reason = None
    usage = None
    t_start = time.time()

    def _progress():
        elapsed = time.time() - t_start
        sys.stderr.write(
            f"\r[t+{elapsed:6.1f}s] reasoning: {reasoning_bytes:>9} bytes | "
            f"content: {content_bytes:>8} bytes"
        )
        sys.stderr.flush()

    with open(raw_path, "a", buffering=1) as raw_f, \
         open(reasoning_path, "a", buffering=1) as reasoning_f, \
         open(answer_path, "a", buffering=1) as answer_f:

        def _append(fh, text: str):
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())

        try:
            with httpx.stream(
                "POST", url, headers=headers, json=payload, timeout=timeout,
            ) as response:
                if response.status_code != 200:
                    body = response.read().decode(errors="replace")
                    _append(raw_f, f"# HTTP {response.status_code} ERROR\n{body}\n")
                    print(
                        f"\nOpenRouter returned HTTP {response.status_code}:\n{body}",
                        file=sys.stderr,
                    )
                    meta["exit_status"] = f"http_error_{response.status_code}"
                    meta["ended_at"] = datetime.now(timezone.utc).isoformat()
                    meta["reasoning_bytes"] = reasoning_bytes
                    meta["content_bytes"] = content_bytes
                    _write_meta()
                    return 1

                for line in response.iter_lines():
                    if line is None:
                        continue
                    _append(raw_f, line + "\n")

                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        saw_done = True
                        break
                    if not data_str:
                        continue

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError as exc:
                        print(f"\nWARNING: malformed SSE chunk (kept in raw.jsonl): {exc}",
                              file=sys.stderr)
                        continue

                    # An in-stream error object. OpenRouter reports upstream
                    # provider failures HERE, not as an HTTP status -- the
                    # request 200s, streams keep-alive comments for as long as
                    # the provider takes to die, then emits this. Without this
                    # check the loop simply never sees a [DONE] and the script
                    # hangs forever: an hour of ": OPENROUTER PROCESSING" and a
                    # silent 500 (Azure, on gpt-5.6-sol-pro) is exactly how it
                    # failed. Fail LOUDLY -- a hang that looks like thinking is
                    # worse than an error.
                    if chunk.get("error"):
                        err = chunk["error"]
                        meta["exit_status"] = "provider_error"
                        meta["provider_error"] = err
                        meta["provider"] = chunk.get("provider")
                        meta["ended_at"] = datetime.now(timezone.utc).isoformat()
                        meta["reasoning_bytes"] = reasoning_bytes
                        meta["content_bytes"] = content_bytes
                        # Persist BEFORE raising. The raise is the loud part (a
                        # traceback + nonzero exit, so a caller can never mistake
                        # this for a slow think); _write_meta is the honest part
                        # -- without it the RuntimeError escapes the function and
                        # meta.json is left saying exit_status=null forever, i.e.
                        # the on-disk record of a REAL provider failure claims the
                        # run never finished rather than that it failed. A crash-
                        # safe log that lies about the outcome is worse than none.
                        _write_meta()
                        print(f"\nPROVIDER ERROR (code {err.get('code')}): "
                              f"{err.get('message')} -- provider={chunk.get('provider')}",
                              file=sys.stderr)
                        raise RuntimeError(f"upstream provider error: {err}")

                    if "usage" in chunk and chunk["usage"]:
                        usage = chunk["usage"]

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}

                    reasoning_piece = ""
                    if isinstance(delta.get("reasoning"), str):
                        reasoning_piece = delta["reasoning"]
                    elif isinstance(delta.get("reasoning_details"), list):
                        parts = []
                        for item in delta["reasoning_details"]:
                            if isinstance(item, dict):
                                parts.append(item.get("text") or item.get("summary") or "")
                        reasoning_piece = "".join(parts)
                    if reasoning_piece:
                        _append(reasoning_f, reasoning_piece)
                        reasoning_bytes += len(reasoning_piece.encode())

                    content_piece = delta.get("content")
                    if isinstance(content_piece, str) and content_piece:
                        _append(answer_f, content_piece)
                        content_bytes += len(content_piece.encode())

                    _progress()

        except httpx.HTTPError as exc:
            print(
                f"\n\nSTREAM DISCONNECTED mid-response ({type(exc).__name__}: {exc}). "
                f"Captured so far: {reasoning_bytes} bytes reasoning, "
                f"{content_bytes} bytes content. This is NOT a success -- "
                f"whatever is on disk in {out_dir} is a partial, crash-safe record.",
                file=sys.stderr,
            )
            meta["exit_status"] = f"disconnected_{type(exc).__name__}"
            meta["ended_at"] = datetime.now(timezone.utc).isoformat()
            meta["reasoning_bytes"] = reasoning_bytes
            meta["content_bytes"] = content_bytes
            _write_meta()
            return 1

    print()  # newline after the last \r progress line
    meta["ended_at"] = datetime.now(timezone.utc).isoformat()
    meta["reasoning_bytes"] = reasoning_bytes
    meta["content_bytes"] = content_bytes
    meta["finish_reason"] = finish_reason
    meta["usage"] = usage

    if not saw_done:
        print(
            f"STREAM ENDED WITHOUT [DONE] terminator -- the connection was lost "
            f"before the server signalled completion. Captured {reasoning_bytes} "
            f"bytes reasoning, {content_bytes} bytes content. Treating as failure.",
            file=sys.stderr,
        )
        meta["exit_status"] = "truncated_no_done"
        _write_meta()
        return 1

    meta["exit_status"] = "ok"
    _write_meta()
    print(
        f"Done. finish_reason={finish_reason!r} usage={usage} -- "
        f"{reasoning_bytes} bytes reasoning, {content_bytes} bytes content.",
        file=sys.stderr,
    )
    if finish_reason == "length":
        print(
            "WARNING: finish_reason='length' -- the model hit max_tokens before "
            "finishing naturally. The response completed the HTTP exchange "
            "(this is exit 0) but the answer may be cut off; rerun with a "
            "higher --max-tokens if answer.md looks truncated.",
            file=sys.stderr,
        )
    return 0


def stream_consult_responses(
    prompt: str | list,
    api_key: str,
    model: str,
    effort: str,
    max_tokens: int,
    connect_timeout_s: float,
    out_dir: Path,
    url: str = OPENROUTER_RESPONSES_URL,
    provider_prefs: dict | None = None,
) -> int:
    """Same contract as stream_consult (same files, same crash-safety, same
    loud-failure discipline, same return codes) but over OpenRouter's
    RESPONSES API skin instead of /chat/completions.

    This is the one that survives a long xhigh think -- see the big comment at
    the top of this module for the measurements. The operative difference is
    that this endpoint emits `keepalive` SSE events on the upstream leg for the
    whole think, so the request is never reaped mid-reasoning; /chat/completions
    goes silent upstream and dies at ~400s, every single time.

    SSE event shapes consumed here (OpenAI Responses semantics):
      response.created / response.in_progress   -- lifecycle, logged only
      response.reasoning_summary_text.delta     -- reasoning summary -> reasoning.txt
      response.output_text.delta                -- the answer          -> answer.md
      response.completed                        -- terminal success (carries usage)
      response.failed / response.incomplete     -- terminal failure, FAIL LOUDLY
      error                                     -- in-stream provider error, FAIL LOUDLY
      keepalive                                 -- the thing that makes this work
    """
    import httpx

    raw_path = out_dir / "raw.jsonl"
    reasoning_path = out_dir / "reasoning.txt"
    answer_path = out_dir / "answer.md"
    meta_path = out_dir / "meta.json"

    # `prompt` may be a plain string or a full Responses-API input list
    # (role/content items, e.g. input_text + input_image parts) — the
    # payload carries it verbatim either way. Sizing meta uses the text
    # form in both cases.
    prompt_text = prompt if isinstance(prompt, str) else json.dumps(prompt)
    payload = {
        "model": model,
        "input": prompt,
        "stream": True,
        "reasoning": {"effort": effort, "summary": "auto"},
        "max_output_tokens": max_tokens,
    }
    if provider_prefs:
        payload["provider"] = provider_prefs
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/diet-app/consult",
        "X-Title": "diet-app consult",
    }
    timeout = httpx.Timeout(connect=connect_timeout_s, read=None, write=30.0, pool=connect_timeout_s)

    meta = {
        "api": "responses",
        "model": model,
        "effort": effort,
        "max_output_tokens": max_tokens,
        "provider_prefs": provider_prefs,
        "prompt_chars": len(prompt_text),
        "prompt_tokenish": tokenish_size(prompt_text),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
        "exit_status": None,
        "reasoning_bytes": 0,
        "content_bytes": 0,
        "keepalives": 0,
        "usage": None,
    }

    def _write_meta():
        meta_path.write_text(json.dumps(meta, indent=2))

    _write_meta()

    reasoning_bytes = 0
    content_bytes = 0
    keepalives = 0
    completed = False
    usage = None
    t_start = time.time()

    def _progress():
        elapsed = time.time() - t_start
        sys.stderr.write(
            f"\r[t+{elapsed:6.1f}s] reasoning: {reasoning_bytes:>9} bytes | "
            f"content: {content_bytes:>8} bytes | keepalives: {keepalives:>4}"
        )
        sys.stderr.flush()

    with open(raw_path, "a", buffering=1) as raw_f, \
         open(reasoning_path, "a", buffering=1) as reasoning_f, \
         open(answer_path, "a", buffering=1) as answer_f:

        def _append(fh, text: str):
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())

        def _die(status: str, msg: str) -> int:
            meta["exit_status"] = status
            meta["ended_at"] = datetime.now(timezone.utc).isoformat()
            meta["reasoning_bytes"] = reasoning_bytes
            meta["content_bytes"] = content_bytes
            meta["keepalives"] = keepalives
            _write_meta()
            print(f"\n{msg}", file=sys.stderr)
            return 1

        try:
            with httpx.stream(
                "POST", url, headers=headers, json=payload, timeout=timeout,
            ) as response:
                if response.status_code != 200:
                    body = response.read().decode(errors="replace")
                    _append(raw_f, f"# HTTP {response.status_code} ERROR\n{body}\n")
                    return _die(
                        f"http_error_{response.status_code}",
                        f"OpenRouter returned HTTP {response.status_code}:\n{body}",
                    )

                for line in response.iter_lines():
                    if line is None:
                        continue
                    _append(raw_f, line + "\n")
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str or data_str == "[DONE]":
                        continue

                    try:
                        ev = json.loads(data_str)
                    except json.JSONDecodeError as exc:
                        print(f"\nWARNING: malformed SSE event (kept in raw.jsonl): {exc}",
                              file=sys.stderr)
                        continue

                    etype = ev.get("type", "")

                    # In-stream provider error, or a terminal failure state.
                    # Same rule as the chat path: a hang that looks like
                    # thinking is worse than an error -- fail LOUDLY.
                    if etype == "error" or ev.get("error"):
                        err = ev.get("error") or ev
                        meta["provider_error"] = err
                        return _die("provider_error", f"PROVIDER ERROR: {json.dumps(err)[:500]}")
                    if etype in ("response.failed", "response.incomplete"):
                        resp = ev.get("response") or {}
                        detail = resp.get("error") or resp.get("incomplete_details") or resp
                        meta["provider_error"] = detail
                        return _die(
                            "response_failed",
                            f"RESPONSE {etype.split('.')[-1].upper()}: {json.dumps(detail)[:500]}",
                        )

                    if etype == "keepalive":
                        keepalives += 1
                        _progress()
                        continue

                    if etype.endswith("reasoning_summary_text.delta"):
                        piece = ev.get("delta") or ""
                        if piece:
                            _append(reasoning_f, piece)
                            reasoning_bytes += len(piece.encode())
                    elif etype == "response.output_text.delta":
                        piece = ev.get("delta") or ""
                        if piece:
                            _append(answer_f, piece)
                            content_bytes += len(piece.encode())
                    elif etype == "response.completed":
                        completed = True
                        usage = (ev.get("response") or {}).get("usage")

                    _progress()

        except httpx.HTTPError as exc:
            return _die(
                f"disconnected_{type(exc).__name__}",
                f"\nSTREAM DISCONNECTED mid-response ({type(exc).__name__}: {exc}). "
                f"Captured {reasoning_bytes} bytes reasoning, {content_bytes} bytes "
                f"content. This is NOT a success -- whatever is on disk in {out_dir} "
                f"is a partial, crash-safe record.",
            )

    print()
    meta["ended_at"] = datetime.now(timezone.utc).isoformat()
    meta["reasoning_bytes"] = reasoning_bytes
    meta["content_bytes"] = content_bytes
    meta["keepalives"] = keepalives
    meta["usage"] = usage

    if not completed:
        meta["exit_status"] = "truncated_no_completed"
        _write_meta()
        print(
            f"STREAM ENDED WITHOUT response.completed -- the connection was lost "
            f"before the server signalled completion. Captured {reasoning_bytes} "
            f"bytes reasoning, {content_bytes} bytes content. Treating as failure.",
            file=sys.stderr,
        )
        return 1

    meta["exit_status"] = "ok"
    _write_meta()
    print(
        f"Done. usage={usage} -- {reasoning_bytes} bytes reasoning, "
        f"{content_bytes} bytes content, {keepalives} keepalives.",
        file=sys.stderr,
    )
    return 0


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Assemble and write prompt.txt, print its size, and exit WITHOUT calling the API.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default=DEFAULT_EFFORT,
                    help="OpenRouter reasoning effort: max/xhigh/high/medium/low/minimal/none.")
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--connect-timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT_S)
    ap.add_argument("--url", default=OPENROUTER_URL,
                    help="Chat-completions endpoint. Override only to point at a local "
                         "fake SSE server when testing the streaming/crash-safety path.")
    ap.add_argument("--pantry", default=EXAMPLE_PANTRY_REL,
                    help="Pantry XML (repo-relative) to use for the real example section.")
    ap.add_argument("--templates", default=TEMPLATES_REL)
    ap.add_argument("--claude-md", default=str(GLOBAL_CLAUDE_MD),
                    help="Path to the CLAUDE.md file to extract the Bayescraft section from.")
    ap.add_argument("--with-counterfactual", action="store_true",
                    help="Also run the real phantom-counterfactual experiment on the captured "
                         "failure and inline its real shopping list. SLOW (~25 min: 10 extra "
                         "full failing planning runs). Off by default; the prompt says so.")
    ap.add_argument("--out-root", default=str(OUT_ROOT))
    args = ap.parse_args()

    # Auth check FIRST -- before the (multi-minute) prompt assembly, which runs
    # the real planner. A missing key must fail loudly and immediately, not
    # after we've already spent minutes planning. --dry-run needs no key.
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not args.dry_run and (not api_key or not api_key.strip()):
        print(
            "FATAL: OPENROUTER_API_KEY is not set. Checked the environment and "
            f"{PROJECT_ROOT / 'secrets.env'} / {PROJECT_ROOT / '.env'}. "
            "Refusing to proceed -- this script never falls back to a hardcoded "
            "key. Set it and re-run, or use --dry-run to build the prompt only.",
            file=sys.stderr,
        )
        return 2

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_root / stamp
    out_dir.mkdir(parents=True, exist_ok=False)

    print("Assembling prompt (running the real planner for section 5)...", file=sys.stderr)
    prompt = build_prompt(
        args.pantry, args.templates, Path(args.claude_md), args.with_counterfactual,
    )

    prompt_path = out_dir / "prompt.txt"
    prompt_path.write_text(prompt)

    n_chars = len(prompt)
    n_tokenish = tokenish_size(prompt)
    print(f"\nWrote {prompt_path}")
    print(f"Prompt size: {n_chars:,} chars  (~{n_tokenish:,} tokens, 4 chars/token heuristic)")
    print("Section headers:")
    for m in re.finditer(r"^={10,}\n(.+)\n={10,}$", prompt, re.MULTILINE):
        print(f"  - {m.group(1)}")

    # Prove the prompt carries REAL inlined source, not summaries.
    print("Inlined source files (verbatim):")
    for rel in RUST_FILES + PYTHON_FILES + [args.pantry]:
        marker = f"----- FILE: {rel} ("
        idx = prompt.find(marker)
        if idx == -1:
            print(f"  !! MISSING: {rel}")
            continue
        end = prompt.find(")", idx)
        print(f"  - {rel} {prompt[idx + len(marker) - 1:end + 1]}")

    if args.dry_run:
        print("\n--dry-run: no API call made.")
        return 0

    print(
        f"\nCalling OpenRouter: model={args.model} effort={args.effort} "
        f"max_tokens={args.max_tokens} -- streaming to {out_dir}\n"
        f"(an xhigh-effort think on a ~170k-token prompt can run for up to an "
        f"hour; there is deliberately NO read timeout. Every chunk is fsync'd "
        f"as it arrives, so killing this process still leaves everything "
        f"received so far on disk.)",
        file=sys.stderr,
    )
    return stream_consult(
        prompt=prompt,
        api_key=api_key,
        model=args.model,
        effort=args.effort,
        max_tokens=args.max_tokens,
        connect_timeout_s=args.connect_timeout,
        out_dir=out_dir,
        url=args.url,
    )


if __name__ == "__main__":
    sys.exit(main())
