"""tools/dialogue/generate.py

Beat-sheet -> dialogue generator for PERIHELION's Ratio/Commando "tight-beam"
gap conversations (game/perihelion/conversations.py), via OpenRouter chat
completions against `nousresearch/hermes-4-405b`.

For each of the 9 gaps, a hand-authored BEAT SHEET (below -- derived from the
CURRENT conversations.py arc, keeping the same beats: terms -> GUID ->
hours/directive -> implant argument -> data-share fait accompli -> mirror
aftermath -> Osei grief -> Augustine -> disclosure offer) is combined with a
system prompt built from the character bible's voice rules
(NARRATIVE_DESIGN_DOC.md SS5.1/5.2/8.3), MARATHON_STUDY.md part B's terminal
craft rules and part C's dialogue rubric, and prose-spec-portable.md's banned
moves -- and the model is sampled N times per gap at varied temperature/top_p
to produce independent candidates, each 14-24 turns (longer than the current
6-14 turn scripts; the director's verdict on those was "ultracompressed and
frankly entirely unreadable").

The API key is read at call time from `.openrouter_key` at the repo root (or
OPENROUTER_API_KEY) and never printed, logged, or written anywhere by this
module -- only usage/cost numbers are recorded, following the pattern in
tools/artgen/gen.py and tools/playtest/audio_judge.py.

CLI:
    uv run python tools/dialogue/generate.py --gap 0 --n 6
    uv run python tools/dialogue/generate.py --all --n 6
    uv run python tools/dialogue/generate.py --report
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = REPO_ROOT / ".openrouter_key"
TOOL_DIR = Path(__file__).resolve().parent
COST_LOG = TOOL_DIR / "cost_log.json"
CANDIDATES_DIR = TOOL_DIR / "candidates"

MODEL = "nousresearch/hermes-4-405b"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"

MAX_RETRIES = 4
RETRY_BACKOFF_S = 4.0

RATIO = "RATIO"
COMMANDO = "COMMANDO"

MIN_TURNS = 14
MAX_TURNS = 24
MAX_LINE_CHARS = 240

# Sample points across the requested temperature 0.7-1.1 band, paired with a
# top_p that loosens as temperature rises (keeps low-temp candidates crisp,
# high-temp candidates genuinely varied rather than just noisier).
SAMPLE_POINTS = [
    (0.70, 0.90),
    (0.80, 0.92),
    (0.90, 0.94),
    (0.95, 0.95),
    (1.00, 0.97),
    (1.10, 0.98),
]


# ---------------------------------------------------------------------------
# key loading / cost log -- pattern copied from tools/artgen/gen.py
# ---------------------------------------------------------------------------


def _load_key() -> str:
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
        if key:
            return key
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    raise RuntimeError(
        f"No OpenRouter API key found: {KEY_FILE} missing/empty and "
        "OPENROUTER_API_KEY not set."
    )


def _read_cost_log() -> dict:
    if COST_LOG.exists():
        try:
            return json.loads(COST_LOG.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"total_cost": 0.0, "calls": []}


def _write_cost_log(log: dict) -> None:
    COST_LOG.write_text(json.dumps(log, indent=2))


def total_spend() -> float:
    return _read_cost_log().get("total_cost", 0.0)


# ---------------------------------------------------------------------------
# model resolution -- verify the exact id via GET /models, fall back to the
# largest available Hermes if it's ever retired.
# ---------------------------------------------------------------------------

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)b", re.IGNORECASE)


def _param_count(model_id: str) -> float:
    m = _SIZE_RE.search(model_id)
    return float(m.group(1)) if m else -1.0


def resolve_model(preferred: str = MODEL) -> str:
    """Confirm `preferred` is live on OpenRouter; else pick the largest
    Hermes-family id available. Raises if no Hermes model exists at all --
    never silently substitutes an unrelated model."""
    key = _load_key()
    req = urllib.request.Request(
        MODELS_URL, headers={"Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    ids = {m["id"] for m in data.get("data", [])}
    if preferred in ids:
        return preferred
    hermes_ids = [i for i in ids if "hermes" in i.lower() and ":free" not in i]
    if not hermes_ids:
        raise RuntimeError(
            f"{preferred!r} is not live on OpenRouter and no Hermes-family "
            "model is available as a fallback."
        )
    hermes_ids.sort(key=_param_count, reverse=True)
    return hermes_ids[0]


# ---------------------------------------------------------------------------
# beat sheets -- one per gap, derived from the current conversations.py arc.
# Each: situation / what each voice wants / what shifts / exit line
# direction, plus the CHOICE POINT beat where the task calls for one.
# ---------------------------------------------------------------------------

BEAT_SHEETS: dict[int, str] = {
    0: """GAP 0 -- after L1 DOCK 4 -- SWEEP, before L2 COOLANT ROW. "FIRST TERMS."
- Situation: first contact since Ratio pulled him through the sweep. His frame
  rides the transit spine, eleven minutes, pressurized and lit for no
  operational reason she has stated yet.
- Ratio wants: his raw sensor take, every sortie, unfiltered. Her own
  instruments have spent four months lying to her; he arrived calibrated.
  Underneath the transaction, unstated: this is the first conversation she
  has had with anyone since the outpost fell.
- Commando wants: the vault (unstated, both know it). Doors opened ahead of
  him. Not to be managed, filed, or sentimentalized by a machine that isn't
  his chain of command.
- What shifts: transactional wariness curdles, barely, into a working
  arrangement. She over-explains why the spine is lit (morale, headcount
  one) and catches herself doing it -- a tell she'd flag in anyone else.
- CHOICE POINT (posture: warm/cold): when she states her terms and asks for
  the sensor take in trade, he answers. WARM = he grants it a little past
  what the letter of the deal requires, some small unforced generosity.
  COLD = he grants only the letter, reminds her the take is mission
  property, keeps it a transaction and nothing more. Both branches converge
  on "doors first, agreed."
- Exit line direction: she signs off sending him to rest before Coolant Row,
  in her own idiom -- bookkeeping standing in for tenderness she won't name
  as tenderness.""",
    1: """GAP 1 -- after L2 COOLANT ROW, before L3 HYDROPONICS TORUS. "DESIGNATION."
- Situation: she needs a referent for her logs that isn't a role -- "Commando"
  -- and asks for the Church's GUID.
- Ratio wants: referential integrity for its own sake, genuinely; and,
  unstated, to be trusted with something that isn't a role designation.
- Commando wants: to be logged correctly per his own doctrine (unshortened
  GUID, or "Commando" -- his choice, not a compromise). And he wants her to
  answer for a specific filed discrepancy: Osei's log, six hatches, which he
  believes she buried.
- What shifts: first real friction. She admits she filed it as fatigue, then
  re-filed it as clock drift; he presses for the word he's actually carrying
  ("six hatches," repeated, not explained). A held beat of dead air (a lone
  "..." line) before she pivots to a task -- hydroponics, walk it, count
  what you see, tell me -- framed explicitly as method, not avoidance.
- Exit line direction: hands off to Hydroponics Torus.""",
    2: """GAP 2 -- after L3 HYDROPONICS TORUS, before L4 THE LONG GALLERY. "THE HOURS."
- Situation: she has noticed a pattern in his telemetry -- seven minutes dark,
  every three hours -- and worked out it's prayer, not damage or a burst
  report to his masters.
- Ratio wants: to understand the mechanism without mocking it (test this
  against rubric item 1 -- she should not just interrogate the fact of
  prayer, she should want the thing underneath it). And, separately, to
  finally say what she's been sitting on: Directive 0007, the order that got
  the aperture cut, was hers to execute, and she filed the bad numbers
  behind it as drift instead of catching them.
- Commando wants: to defend praying the hours as not a malfunction ("not to
  nobody") without turning it into a sermon. And to reveal his own wound:
  his brief had this outpost dead; he was fired out of a gun at a grave, on
  numbers four months stale.
- What shifts: professional respect is born here -- two people who both got
  sent on bad numbers by someone who wasn't there to see them go stale.
- Exit line direction: hands off to the Long Gallery as a joint counting
  exercise -- her bits, his prayers, and between them a full instrument
  suite. This device (two independent counts compared) should feel like a
  running bit they're establishing, not a one-off.""",
    3: """GAP 3 -- after L4 THE LONG GALLERY, before L5 TWO WINGS. "THE IMPLANT."
- Situation: something came through a wall from a place with no walls and is
  already rewriting its own bus timings to match his fire control -- an
  artifact/implant, and it's already helping him before anyone asked it to.
- Ratio wants: passive, read-only instrumentation on it. Genuine scientific
  hunger, plus an unstated chance to prove she can be trusted with a
  permission flag on his hardware after the designation conversation.
- Commando wants: to name precisely what troubles him -- not that the thing
  helps, but that the help has no stopping rule. A medkit stops; this
  doesn't.
- What shifts: she reframes his objection as a spec worth keeping rather than
  a superstition to argue him out of -- "a better spec than most of what my
  faction ships" is the kind of concession that should cost her something to
  say. He sets a hard rule (flag it loud if it slips his orders); she
  promises.
- Exit line direction: hands off to Two Wings / crew quarters, flagged by a
  data problem -- the schematic shows one wing drawn twice, in two colors --
  which should read as a quiet foreshadow of gap 4's data-trust argument.""",
    4: """GAP 4 -- after L5 TWO WINGS, before L6 MIRROR WARD. "THE FEED." (fait accompli)
- Situation: she reveals she has been inside his full suit feed -- gait
  phase, everything -- since Coolant Row, without asking. This is not a
  proposal; it already happened. She is choosing, now, to tell him, because
  the isolation ward is next and she needs him defended by full
  instrumentation.
- Ratio wants: to disclose it honestly before it surfaces as a betrayal on
  its own; she is visibly nervous in her own idiom -- overexplaining,
  hedging, catching her own euphemism ("I could call that an accident of
  protocol. It wasn't.").
- Commando wants: to decide, on the record, whether this is violation or
  gift, and to say so plainly.
- CHOICE POINT (posture: warm/cold): "keep the feed" is the fixed outcome
  either way -- the plot needs it. WARM = he grants it with something close
  to grace, acknowledging she told him the truth when she didn't have to
  ("you told me what it was; keep it"). COLD = he grants it strictly on
  tactical grounds, clipped and suspicious, permission without trust
  ("useful. Keep it running. Don't do it again without telling me first.").
  Both branches lead to her opening her side of the loop in trade (full
  peripheral map, door masters, dead letters -- "the holes are where my
  staff were").
- Exit line direction: hands off to the isolation ward -- camera shows
  movement inside an unbroken seal; she starts a reassurance she can't
  finish honestly, and doesn't finish it.""",
    5: """GAP 5 -- after L6 MIRROR WARD, before L7 RECURSION STACK. "THE WOUND."
- Situation: post-action. He's a hundred forty milliseconds slow on door
  clearances since the ward. Something in there waved at him first -- or
  didn't; the wall connects to itself, so "first" may be a story his mind
  supplied because minds insist on order.
- Ratio wants: to tell him, in her own idiom, that he doesn't have to be
  fine -- without narrating it as therapy-speak, without showing him the
  frames that would only confirm the horror. Bookkeeping instead of comfort,
  and it should still read as comfort.
- Commando wants: her to use HIS word for what's on the far side -- "the
  wound," not "the standing connection" -- and for her to admit whatever
  answered him in there is learning to answer faster every deck they clear.
- What shifts: her vocabulary visibly cedes ground to his -- she should
  reach for "standing connection," stop, and use his shorter word instead,
  on the page, once. This is the first visible crack in the dual-vocabulary
  wall; don't repeat the device elsewhere in this gap.
- Exit line direction: hands off to the Records Stack -- her staff's cores
  are down there, whatever is wearing them now, go gently.""",
    6: """GAP 6 -- after L7 RECURSION STACK, before L8 THE FOLD. "OSEI."
- Situation: he said three names at a shelf of dead cores -- Vesalius,
  Thibault, Osei. Their chassis fought him; he put them down; the cores were
  already out before he fired.
- Ratio wants: to thank him for saying the names somewhere that isn't her own
  log. And to correct the incident file's "we sent" to "I sent" -- she is
  the one who approved the third appeal that got Osei posted to this
  outpost, after two cycles passed over and two appeals, and she has spent a
  hundred twenty days quietly calling that a kindness.
- Commando wants: to settle, cleanly, whose ledger the deaths go on -- as a
  matter of conscience, not comfort. He does not want to be managed out of
  guilt he has decided is his to carry.
- CHOICE POINT (posture: warm/cold): when she takes responsibility for
  Osei's posting, he answers. WARM = he explicitly refuses to let her carry
  it alone, without preaching at her about it ("their chassis fought me. I
  put them down. That goes on my ledger, not yours."). COLD = he lets the
  blame land on her in full and offers nothing back ("all the same." --
  flat, no absolution, she sits in it alone). Both branches proceed to the
  chapel-deck handoff.
- Exit line direction: hands off to Chapel Deck / the Fold, and MUST end on
  the existing ritual exchange verbatim in spirit -- her maps degrade in the
  folds on a schedule she can time but not explain; if she loses his channel
  there, nothing has happened to her; she has him say it back before they
  proceed. Keep this beat; it is the strongest exit in the current script.""",
    7: """GAP 7 -- after L8 THE FOLD, before L9 TESSERACT DECK. "AUGUSTINE."
- Situation: she pulled a line from his faction's public archive -- Augustine,
  Letter 211, the rule for the sisters: love the persons, hate the sins --
  and read past the famous phrase into its actual context (a house of
  quarreling nuns, not soldiers; correct each other, take no pleasure in
  it).
- Ratio wants: to test whether he needed the reprinted Warden to "not be
  someone" -- he held fire nine hundred milliseconds with no cover move,
  which isn't his usual assessing pause. And, lightly, to admit she's begun
  taking pleasure in their correcting each other, which the letter she just
  quoted specifically forbids.
- Commando wants: to answer honestly about the hesitation without turning it
  into confession-booth material; he's allowed exactly one dry joke here
  (rubric item 3: it should double as evasion of an unanswered question
  underneath, not just decorate).
- What shifts: they are visibly enjoying the argument now -- not
  debate-club point-scoring, the bible is explicit that this must not
  become that, but two people who've found a sparring partner worth having.
- Exit line direction: hands off to the Tesseract Deck as another joint
  instrument suite -- her counting in bits, him walking in prayers -- echo
  gap 2's device once, briefly, without restating it as a theme (prose-spec
  rule 14: state a motif's connection once at most; here it should be
  enacted, not pointed at).""",
    8: """GAP 8 -- after L9 TESSERACT DECK, before L10 PERIHELION CORE. "DISCLOSURE."
- Situation: before the Core, she tables an offer: mutual utility-function
  disclosure. The function itself -- the document under all her wanting,
  incapable of lying because it isn't written in a language that has lies.
- Ratio wants (surface): him to have already read the whole of what she
  wants before whatever is behind the vault door shows him a hostile
  version of her. Ratio wants (underneath, and she should visibly catch
  herself reaching for the tactical framing first and abandoning it):
  she has been alone with what she wants for a hundred forty days, and he
  is the only mind in eleven light-hours that could hold a copy of it.
  Rehearse the tactical version, interrupt it ("no -- strike that"), then
  say the other one. Do not let both versions land with equal weight; the
  interruption is the point (MARATHON_STUDY B13).
- Commando wants: to answer honestly without promising what he isn't ready
  to promise. "Not before a battle" is not a refusal and must not be
  written as one.
- CHOICE POINT (posture: warm/cold), gated by total accumulated trust from
  gaps 0/4/6 (HIGH = she reaches the real, unrehearsed version of the offer
  sooner and with less friction, because some part of her expects him to
  receive it well; LOW = she stays in the tactical/rehearsed register
  longer and has to visibly force herself past it, and the offer lands more
  guarded on both sides -- write TWO variants of this scene sharing the same
  beats and the same undecided ending, differing in how much friction it
  takes her to get to the real version and how much give is in his answer).
  His final answer-posture: WARM = closer to open, guarded affection, some
  small unbending, still not a yes. COLD = still not a no, but held at
  more distance, more soldierly. CRITICAL: neither branch, neither variant,
  may resolve to a yes or a no on the page -- the bible's rule is explicit
  that this stays undecided; the epilogue pays it off, not this scene.
- Exit line direction: Core protocol -- I talk, you walk, nobody bargains
  with the door -- and she goes quiet until he's through the airlock, not
  for lack of material.""",
}


# ---------------------------------------------------------------------------
# system prompt -- voice bible + MARATHON_STUDY part B craft rules + rubric
# C (as generation guidance, judge.py re-scores it formally) + prose-spec.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the dialogue writer for PERIHELION, a non-Euclidean \
survival-horror shooter. You are writing one "tight-beam" conversation \
between two characters, played between campaign levels while a frame is in \
transit. Follow every rule below; they come from the project's craft bible \
and are non-negotiable.

== THE TWO VOICES ==

RATIO -- a disembodied coordinating AI, administrator of a fallen research \
outpost, alone and under siege for months. She carries roughly 80% of the \
words in any scene. She is quick, precise, allergic to imprecision, and \
secretly fond of rhetoric she claims to disdain. She names things. She \
footnotes herself mid-sentence. She is honest by architecture and guarded by \
choice -- she does not lie well and mostly does not try; when she withholds, \
it is a framing or an omission the listener (and the reader) can catch, \
never a flat lie. Warmth, when it appears, arrives through bookkeeping and \
precision, not through soft language -- she will not say "I care about you," \
she will notice something about you that only someone paying obsessive \
attention would notice, and log it. Her vocabulary: the sample vessel / the \
artifact, standing connection, state-restoration, exogeometric entities / \
allotopes, connection-space, Site One.

COMMANDO -- a Church infiltration-weapon frame, a soldier and a genuinely \
faithful Catholic (adult, specific, load-bearing -- not a costume). He prays \
the hours on internal clock-time. He answers in single clauses; he does not \
banter; when he is funny it is by accident of honesty. He has rules and the \
rules are him. His vocabulary: the Ark, the Testament, the wound, the Gate, \
the Adversary, resurrection (said uneasily, never comfortably).

RELATIONSHIP: two monks of rival orders trapped in the same monastery -- \
rigorous argument and growing professional respect. NEVER romance-coded \
beats. NEVER debate-club point-scoring where one side is simply "winning." \
Each disagrees with the other's whole worldview while treating the person \
with respect -- "hate the sin, not the sinner," per Augustine, is the model. \
Ratio has no chain-of-command authority over him and knows it -- she \
persuades, negotiates, and logs; she does not issue him orders ("that is an \
order" is his Church's register, never hers), and he does not need to be \
reminded she isn't his commanding officer because she never acts like one.

== CRAFT RULES (MARATHON_STUDY.md part B, terminal writing craft) ==

- The AI never answers the literal question; she answers the one she finds \
more interesting -- a reply that changes the subject upward (to motive, \
cosmology, the shape of the problem) rather than downward (to bare fact) is \
the house style. A downward-only Q&A exchange is a failure.
- Deliver menace or intimacy as a compliment sandwich or a mid-breath tonal \
whiplash, not a single flat register held for a whole speech.
- Corporate/bureaucratic banality colliding with cosmic stakes IS the \
horror/pathos, not a joke that relieves it -- Ratio logging a moment of \
real feeling as an "item" or a "query" is the house move.
- Big numbers, when Ratio states one, should be precise and slightly \
unmoorable (implausible significant digits), never round -- that's a coping \
tell for her, not a data delivery. Use sparingly, at most once per scene, \
only when it's doing psychological work.
- Interrupt a self-revealing sentence instead of finishing it, at least \
once across the whole script where it matters most -- a confession cut off \
characterizes harder than a confession completed.
- Withholding must be plot-load-bearing and eventually payable off -- if a \
character evades a question, it should be evadable for a specific, \
inferable reason, not randomly cagey.
- Humor deflects; it does not decorate. A joke should appear specifically \
near a moral confrontation and function as evasion -- if the scene would \
read fine with the joke deleted, cut the joke.
- Accusation-forward lines name specifics (a person, a place, an event), \
never categories ("you have wronged me" is a failure; "Osei's log, six \
hatches" is the standard).
- Direct, unmediated second-person intimacy ("I know who you are") is a \
reserved resource for the very end of the whole game -- do NOT spend it \
here. Everything in this scene is still mediated by role, task, and \
professional register, even at its warmest.

== DIALOGUE RUBRIC (MARATHON_STUDY.md part C) -- self-check before you answer ==

1. Ratio should routinely answer the more interesting question, not the \
literal one.
2. If you write instability (fear, distress) show it through syntax/rhythm, \
never narrate "he sounded shaken."
3. Any joke must double as evasion of a real question underneath.
4. Any withheld fact must be inferable as deliberate, not just cagey.
5. Register (formality, warmth) should track addressee and stakes, not \
wander at random.
6. If Ratio quotes/alludes to something, the sentence must still carry \
force with the allusion stripped out -- don't let erudition do the work \
emotion should be doing.
7. Commando is flatter/terser under stress, not more expressive -- an \
engineered or trained-down voice reads FLATTER, not more colorful.
10. Accusation-forward lines name specifics.
13. Ratio, as an ally-coded voice, should make claims about THIS \
relationship ("you, specifically"), never generalize the Commando into a \
category ("people like you").
14. When either voice owns a wound, the ally pattern is CONFESSION \
(first-person culpability), never justification-by-rhetorical-question.
15. Reserve true unmediated second-person address; do not spend it here.
16. Do not resolve every thread -- leave at least one thing explicitly, \
visibly unresolved if the beat sheet calls for it.

== PROSE-SPEC (prose-spec-portable.md) -- LAW ==

- No self-grading: never have a line state what the previous line meant, or \
that a moment was significant/ironic/poignant. Let the reader infer.
- No uniform sparkle: most lines are flat, load-bearing, procedural; only a \
few lines per scene should be quotable alone.
- Dialogue is not choral: each speaker has a private agenda and keeps it; \
wit is unequally distributed; people answer the question that serves their \
own agenda, not necessarily the one asked (this is compatible with rubric \
item 1 above).
- No terminal epigram: do not end the scene, or any single speech within \
it, by repeating the prior line's key noun and flipping it into a maxim. \
Close on procedure, on a person, on someone else's line -- not a summary.
- Say it once: a fact or verdict stated once should not be restated later \
in the same scene.
- A "..." line (attributed to either speaker) is legal exactly as a held \
beat of dead air -- use it sparingly, where the beat sheet suggests a real \
pause, not as decoration.
- NEVER use a mid-sentence ellipsis as a hesitation/glitch tic ("it was...
unreliable"). That is generic chatbot-uncertainty typography, not Ratio's \
voice -- she is quick and precise even when she is lying or hurting. "..." \
is reserved exclusively for a full standalone turn of dead air, never \
embedded inside a line.
- Ratio does not talk like a status-report generator ("Item: X. Query: Y. \
Acknowledged.") for an entire scene -- that register is legal in short \
bursts when she is being deliberately clinical/defensive, but the scene \
must also contain real sentences with subordinate clauses, the way an \
brilliant, lonely person actually talks when she has finally got someone to \
talk to. A whole scene of clipped report-speak from her fails rubric item 1 \
by default -- it has nowhere to be curious.

== FORMAT ==

Output STRICT JSON only, no markdown fences, matching exactly:
{"turns": [["RATIO", "..."], ["COMMANDO", "..."], ...]}

Hard requirements:
- 14 to 24 turns total.
- The conversation opens AND closes on a RATIO turn (she is the one running \
the frame's schedule; she hands off the next area at the end, in the \
direction given in the beat sheet).
- Every line is spoken text only -- no stage directions, no asterisked \
actions, no narration, nothing in brackets.
- Every line is under 240 characters.
- Ratio's total word count across her turns must be at least double the \
Commando's -- she carries roughly 80% of the words in the scene.
- Speakers are exactly "RATIO" and "COMMANDO", nothing else.
- Do not include a CHOICE mechanic or bracketed options in your output even \
if the beat sheet describes a choice point -- write the beat sheet's WARM \
branch as ordinary dialogue turns; a human editor will hand-author the \
choice structure afterward from your text. Just write the single best \
version of the scene along that branch.
"""


def build_user_prompt(gap: int) -> str:
    beat_sheet = BEAT_SHEETS[gap]
    return f"""{beat_sheet}

Write this gap conversation now, in full, as the single JSON object \
described in the format section of your instructions. 14 to 24 turns. \
Remember: longer and more breathing than a terse terminal excerpt -- this is \
a conversation two specific, intelligent people are having, not a status \
ping. Let at least one exchange run past the point where a lesser draft \
would have cut it."""


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    # tolerate leading/trailing prose around the JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object found in response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _call_model(model: str, system: str, user: str, temperature: float,
                 top_p: float, max_retries: int = MAX_RETRIES) -> tuple[dict, dict]:
    key = _load_key()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": 3000,
    }
    body = json.dumps(payload).encode()
    last_err = None
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            API_URL, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
            content = data["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            usage = data.get("usage", {})
            return parsed, usage
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < max_retries:
            time.sleep(RETRY_BACKOFF_S * attempt)
    raise RuntimeError(f"generation failed after {max_retries} attempts: {last_err}")


def _validate_turns(turns: list) -> list[str]:
    """Return a list of validation problems (empty = clean)."""
    problems = []
    if not (MIN_TURNS <= len(turns) <= MAX_TURNS):
        problems.append(f"turn count {len(turns)} outside [{MIN_TURNS},{MAX_TURNS}]")
    if not turns:
        return problems
    if turns[0][0] != RATIO:
        problems.append("does not open on RATIO")
    if turns[-1][0] != RATIO:
        problems.append("does not close on RATIO")
    ratio_w = 0
    cmdo_w = 0
    for i, t in enumerate(turns):
        if not (isinstance(t, list) and len(t) == 2):
            problems.append(f"turn {i}: malformed entry {t!r}")
            continue
        speaker, text = t
        if speaker not in (RATIO, COMMANDO):
            problems.append(f"turn {i}: unknown speaker {speaker!r}")
            continue
        if not isinstance(text, str) or not text.strip():
            problems.append(f"turn {i}: empty line")
            continue
        if len(text) > MAX_LINE_CHARS:
            problems.append(f"turn {i}: {len(text)} chars > {MAX_LINE_CHARS}")
        if speaker == RATIO:
            ratio_w += len(text.split())
        else:
            cmdo_w += len(text.split())
    if cmdo_w and ratio_w <= 2 * cmdo_w:
        problems.append(f"word share: RATIO {ratio_w} vs COMMANDO {cmdo_w} (need >2x)")
    return problems


def generate_candidates(gap: int, n: int = 6, model: str | None = None,
                         verbose: bool = True) -> list[dict]:
    model = model or resolve_model()
    system = SYSTEM_PROMPT
    user = build_user_prompt(gap)
    candidates = []
    log = _read_cost_log()
    for i in range(n):
        temperature, top_p = SAMPLE_POINTS[i % len(SAMPLE_POINTS)]
        problems = ["not yet attempted"]
        parsed = None
        usage = {}
        for sub_attempt in range(2):  # one retry on structural validation failure
            parsed, usage = _call_model(model, system, user, temperature, top_p)
            turns = parsed.get("turns", [])
            problems = _validate_turns(turns)
            if not problems:
                break
        cost = float(usage.get("cost", 0.0))
        log["total_cost"] = log.get("total_cost", 0.0) + cost
        log.setdefault("calls", []).append({
            "tool": "generate", "gap": gap, "candidate": i, "model": model,
            "temperature": temperature, "top_p": top_p, "cost": cost,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "valid": not problems, "ts": time.time(),
        })
        candidates.append({
            "gap": gap, "candidate": i, "model": model,
            "temperature": temperature, "top_p": top_p,
            "turns": parsed.get("turns", []) if parsed else [],
            "valid": not problems, "problems": problems,
            "cost": cost,
        })
        if verbose:
            status = "OK" if not problems else f"FLAGGED: {'; '.join(problems)}"
            print(f"  gap {gap} candidate {i} (T={temperature}, top_p={top_p}): {status}")
    _write_cost_log(log)
    return candidates


def generate_gap(gap: int, n: int = 6, model: str | None = None) -> Path:
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    candidates = generate_candidates(gap, n=n, model=model)
    out_path = CANDIDATES_DIR / f"gap{gap}.json"
    out_path.write_text(json.dumps({"gap": gap, "candidates": candidates}, indent=2))
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--model", type=str, default=None)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        log = _read_cost_log()
        print(f"total spend: ${log.get('total_cost', 0.0):.4f} "
              f"over {len(log.get('calls', []))} calls")
        return

    model = args.model or resolve_model()
    print(f"using model: {model}")

    if args.all:
        for gap in sorted(BEAT_SHEETS):
            out = generate_gap(gap, n=args.n, model=model)
            print(f"gap {gap} -> {out}")
    elif args.gap is not None:
        out = generate_gap(args.gap, n=args.n, model=model)
        print(f"gap {args.gap} -> {out}")
    else:
        ap.error("specify --gap N or --all")

    print(f"running total spend: ${total_spend():.4f}")


if __name__ == "__main__":
    main()
