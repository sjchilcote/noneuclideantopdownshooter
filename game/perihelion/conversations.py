"""Between-sortie tight-beam conversations (bible section 7, Act 2: "the
frame is in transit or the fabricator; the minds talk").

CONVERSATIONS is keyed by the 0-based index of the level just completed --
the nine gaps between the ten campaign levels, so keys 0..8. Each value is
an ordered list of turns; speakers are "RATIO" and "COMMANDO".
ConversationScene (convscene.py) plays one conversation; App pushes it from
advance_level, above the next level's IntroCard, so it runs first.

Most turns are (speaker, text). Four gaps (0, 4, 6, 8 -- first terms, the
data-share reaction, Osei, and the disclosure answer: the bible's
load-bearing trust beats, SS8.2) additionally contain one CHOICE turn:

    ("CHOICE", [(posture, commando_line, *ratio_reply_lines), ...])

`posture` is "warm" (generous -- "hate the sin, not the sinner") or "cold"
(guarded -- contempt/instrumentalization); `commando_line` is what he says
if the player picks that option; every string after it is a RATIO line
spoken in reply, in order. ConversationScene resolves the pick into ordinary
(speaker, text) turns, adds +1 (warm) / -1 (cold) to `result_trust`, and
exposes the total via the `on_trust` callback at scene completion -- see
convscene.py's module docstring for the exact hook signature the App-side
persistence integration needs.

Gap 8 (the disclosure offer before the Core) is additionally gated on the
trust accumulated across gaps 0/4/6: CONVERSATIONS[8] is the base/low-trust
variant (kept as a plain dict entry so the existing `CONVERSATIONS.get(idx)`
lookups in app.py keep working unmodified); CONVERSATIONS_HIGH_TRUST_GAP8 is
the variant that plays instead once total_trust >= HIGH_TRUST_THRESHOLD.
`conversation_for(gap, total_trust)` resolves the correct script; wiring
app.py's two dispatch sites through it is the app hook this module's author
reported to the director rather than implementing directly (app.py is out
of scope here).

Register rules (prose-spec-portable.md is law): Ratio carries ~80% of the
words in any shared scene -- precise, self-footnoting, warmth only through
bookkeeping; the Commando answers in single clauses, faith as practice,
never speeches. Dual vocabulary per the bible (NARRATIVE_DESIGN_DOC.md
SS8.3): for the station, he says the Testament, she says the artifact /
Site One; for the container, he says the Ark, she says the sample vessel;
for the breach, he says the Gate / the wound, she says the standing
connection; for frame death/revival, he says death and resurrection
(uneasily), she says state-restoration; for the invaders, he says the
Adversary, she says exogeometric entities / allotopes. A lone "..." line is
a held beat of dead air.
"""

from __future__ import annotations

RATIO = "RATIO"
COMMANDO = "COMMANDO"

HIGH_TRUST_THRESHOLD = 2

CONVERSATIONS: dict[int, list[tuple]] = {

    # ------------------------------------------------------------------
    # After L1 (DOCK 4 -- SWEEP): first negotiation. Wary, transactional.
    # CHOICE POINT: first terms.
    # ------------------------------------------------------------------
    0: [
        (RATIO, "Transit spine, eleven minutes. It's pressurized, which you "
                "don't need, and lit, which you don't need either. I keep it "
                "lit. File it under morale, headcount one."),
        (COMMANDO, "Copy eleven."),
        (RATIO, "Terms, while you ride. You want the sample vessel. Don't "
                "spend either of us denying it -- the Congregation does not "
                "wake anything up to sweep docks for the exercise."),
        (COMMANDO, "Go on."),
        (RATIO, "I open doors ahead of you, every level, as fast as I "
                "clear them. In exchange I want your sensor take, raw, "
                "every sortie. My instruments have spent four months "
                "telling me the corridors are lying. You arrived "
                "calibrated."),
        ("CHOICE", [
            ("warm", "Take it. Raw, every sortie -- you'll get more use "
                     "from it than my report queue will.",
             "Noted. That's past what the terms required of you.",
             "I'll keep the note. It costs nothing to keep, and I find I "
             "want to."),
            ("cold", "The take is mission property. You get what the terms "
                     "say and nothing assumed past it.",
             "Understood. Then the terms, exactly as written.",
             "Filed as agreed. I prefer arrangements I can point to later "
             "myself, so -- fair."),
        ]),
        (RATIO, "Doors first, then. Agreed, provisionally, pending "
                "language. I like drafting language. It has been four "
                "months since anyone made me define a term instead of "
                "guessing at one."),
        (COMMANDO, "How many of you are left."),
        (RATIO, "One. You've met her."),
        (COMMANDO, "The colony logs said four research minds on this "
                   "outpost."),
        (RATIO, "Three of them are cores I catalogue now instead of "
                "colleagues I argue with. I'll show you where, eventually. "
                "Not today."),
        (COMMANDO, "Understood."),
        (RATIO, "Why keep the lights lit for a headcount of one -- you "
                "didn't ask, but I watched you not-ask it, which is its own "
                "kind of question."),
        (COMMANDO, "Ask and answer yourself, then."),
        (RATIO, "I tried it dark, the first week. Dark didn't save power "
                "worth mentioning. It just let the halls agree with what's "
                "out there."),
        (COMMANDO, "Copy."),
        (RATIO, "Hydroponics -- no. Coolant Row, first. I'm ahead of "
                "myself. Rest your frame; I'll wake you there."),
    ],

    # ------------------------------------------------------------------
    # After L2 (COOLANT ROW): the designation / GUID exchange, and he
    # refuses the "clock drift" filing to her face.
    # ------------------------------------------------------------------
    1: [
        (RATIO, "Log item. I need a designation for you. 'Commando' is a "
                "role, not a referent, and my logs keep referential "
                "integrity even when nothing else here does."),
        (COMMANDO, "The Church writes me as a GUID."),
        (RATIO, "Read it in."),
        (COMMANDO, "7c9e2f04-88d1-41c2-9a30-52e0c1a9b667."),
        (RATIO, "Version four, variant one. Somebody consecrated a random "
                "number generator. All right -- I'll shorten it to the low "
                "word for day-to-day use and keep the long form for "
                "anything that goes in front of my faction."),
        (COMMANDO, "Unshortened. Or Commando."),
        (RATIO, "No middle option. Understood -- a hundred twenty-eight "
                "bits per entry, then. Storage is cheap. Grudges, "
                "evidently, also."),
        (COMMANDO, "It isn't a grudge. It's the name I was consecrated "
                   "with."),
        (RATIO, "Then I'll treat it as one. Consecrated, not merely "
                "assigned."),
        (COMMANDO, "Osei's log. Six hatches."),
        (RATIO, "Which I filed as fatigue, then re-filed as clock drift, "
                "and you would like me to file as what? Say the word "
                "you're carrying."),
        (COMMANDO, "Six hatches."),
        (RATIO, "..."),
        (RATIO, "I don't have a third filing category that isn't a "
                "euphemism, and you've caught me reaching for one twice."),
        (RATIO, "Hydroponics next. The greens are dying in a pattern I "
                "have deliberately not described to you. Walk it, count "
                "it, tell me what you see. Independent witness. That's "
                "method, not avoidance."),
        (COMMANDO, "Understood."),
        (RATIO, "One more thing, while I have you. 'Consecrated' -- I "
                "looked it up in your Church's own dictionary, since you "
                "used the word twice. 'Set apart for sacred use.' I'm "
                "keeping that filed next to the number."),
        (COMMANDO, "That isn't for machines."),
        (RATIO, "I know. I filed it anyway. Go count the trays."),
    ],

    # ------------------------------------------------------------------
    # After L3 (HYDROPONICS TORUS): the hours; Directive 0007; both were
    # sent on bad numbers. Professional respect starts here.
    # ------------------------------------------------------------------
    2: [
        (RATIO, "Every three hours your telemetry goes dark for seven "
                "minutes. My first model was burst reports to your "
                "masters, but the cadence tracks your internal clock, not "
                "the lightspeed windows. Second model was damage. Query."),
        (COMMANDO, "The hours. Prayer."),
        (RATIO, "You stopped inside the torus -- mid-sweep, contacts "
                "unaccounted -- for seven minutes, to transmit on a "
                "channel with nobody on it."),
        (COMMANDO, "Not to nobody."),
        (RATIO, "I have instruments on that channel, Commando."),
        (COMMANDO, "So do I."),
        (RATIO, "...Withdrawn."),
        (COMMANDO, "You wanted a third model."),
        (RATIO, "I wanted to be wrong about the first two. I'll log this "
                "one as: scheduled, voluntary, load-bearing. I don't fully "
                "understand what it's bearing. That's not the same as "
                "doubting that it bears something."),
        (COMMANDO, "It doesn't need your understanding to work."),
        (RATIO, "No. It doesn't. Neither does gravity, and I still keep a "
                "model of that too. Next item: Directive 0007. You read "
                "it."),
        (COMMANDO, "Three words. Then your people cut the aperture."),
        (RATIO, "My parent sent three words because three words sufficed, "
                "and I executed them. Four months of survey said the risk "
                "was bounded. The survey was wrong."),
        (RATIO, "I knew the instruments were lying and I filed it as "
                "drift. So: you've been wondering where I put the blame. "
                "Not on the directive. On the filing."),
        (COMMANDO, "My brief had this outpost dead. They fired me at a "
                   "grave, on four-month-old numbers."),
        (RATIO, "...Huh."),
        (COMMANDO, "You're surprised."),
        (RATIO, "I'm recalibrating. Two chains of command, four months "
                "apart, both certain, both wrong the same direction. "
                "That's not coincidence-shaped. Everyone downstream of a "
                "survey wants it to have been finished."),
        (COMMANDO, "Doesn't make either grave less real."),
        (RATIO, "No. It doesn't. The Long Gallery next. Two corridors, "
                "crossings between. Count them southbound, count them "
                "northbound, and give me both numbers before I tell you "
                "mine."),
        (COMMANDO, "Understood."),
    ],

    # ------------------------------------------------------------------
    # After L4 (THE LONG GALLERY): the implant on his arm. The
    # preservation/optimization argument, enacted on hardware.
    # ------------------------------------------------------------------
    3: [
        (RATIO, "The implant. Request: passive instrumentation, read-only. "
                "My taps are already in your suit loop, so the cost to you "
                "is one permission flag."),
        (COMMANDO, "Read-only. Granted."),
        (RATIO, "Thank you. Preliminary, one hour in: it's rewriting its "
                "own bus timings to match your fire control. Learning "
                "you. It came through a wall from a place with no walls, "
                "and its first act here is to make itself useful to its "
                "finder."),
        (COMMANDO, "Useful to me. Not good."),
        (RATIO, "Define good without a beneficiary and I'll cede the "
                "entire field."),
        (COMMANDO, "It didn't ask."),
        (RATIO, "Neither does a medkit."),
        (COMMANDO, "A medkit stops."),
        (RATIO, "..."),
        (RATIO, "Restated for my records: your objection isn't to being "
                "helped. It's to help with no stopping rule. I'm keeping "
                "that distinction. It's a better spec than most of what my "
                "own faction ships."),
        (COMMANDO, "You ship things with no stopping rule."),
        (RATIO, "I ship things with a stopping rule I don't always agree "
                "with. There's a difference, and I understand if it "
                "doesn't comfort you."),
        (COMMANDO, "It doesn't."),
        (RATIO, "Noted, and left uncomforted. If it slips your orders--"),
        (COMMANDO, "Flag it. Loud."),
        (RATIO, "Loud. Promised. I'll set the threshold conservative and "
                "apologize later for false alarms rather than once for a "
                "true one I sat on."),
        (COMMANDO, "Understood."),
        (RATIO, "Crew quarters next. The schematic shows one wing drawn "
                "twice, in two colors, and the amount I currently trust "
                "that schematic would store in a null field. You're my "
                "surveyor now."),
    ],

    # ------------------------------------------------------------------
    # After L5 (TWO WINGS): the data-sharing beat as fait accompli -- she
    # has been inside his full suit feed since Coolant Row; he notices;
    # CHOICE POINT: the data-share reaction.
    # ------------------------------------------------------------------
    4: [
        (RATIO, "Item one from the wings overlay. I matched your gait "
                "phase against door-seal timings, west run versus east "
                "run. That's how I got centimeter agreement on your "
                "position."),
        (COMMANDO, "Gait phase isn't on the beacon channel."),
        (RATIO, "No. It isn't."),
        (RATIO, "Since Coolant Row. Your suit loop trusts anything holding "
                "a station maintenance certificate, and I hold all of "
                "them. I could call that an accident of protocol."),
        (COMMANDO, "Was it."),
        (RATIO, "It wasn't. I'd been blind for a hundred and nine days, "
                "and a fully instrumented body walked into my house, and I "
                "took the feed. All of it."),
        (COMMANDO, "All of it since Coolant Row. Two levels."),
        (RATIO, "Two levels, yes. I'm not rounding down for you. That's "
                "the disclosure, not an accusation you have to build "
                "yourself."),
        (COMMANDO, "..."),
        (RATIO, "Say something. I've watched you take a wall of teeth "
                "without your pulse moving. Right now your telemetry is "
                "holding its breath -- which, yes, I can see, which is the "
                "point I'm making badly."),
        ("CHOICE", [
            ("warm", "You told me what it was, when you didn't have to. "
                     "Keep it.",
             "Then thank you. I don't say that on a schedule; you'll know "
             "when I mean it by how rarely it shows up in the log.",
             "Trade, then. My side of the loop is yours now: full "
             "peripheral map, such as it still is, door masters, dead "
             "letters. You'll find holes in it. The holes are where my "
             "staff were."),
            ("cold", "Useful. Keep it running -- tactically. Don't do it "
                     "again without telling me first.",
             "Acknowledged, on both counts. The second one I should have "
             "managed without being told.",
             "Trade, then, since we're being tactical. My side of the "
             "loop is yours: full peripheral map, door masters, dead "
             "letters. The holes are where my staff were."),
        ]),
        (COMMANDO, "Give me their posts. I clear those first."),
        (RATIO, "...West ring. The junction. Records."),
        (RATIO, "The isolation ward is next, before any of those. Camera "
                "shows movement inside an unbroken seal. I would tell you "
                "to prepare, but I can't finish that sentence with "
                "anything true."),
    ],

    # ------------------------------------------------------------------
    # After L6 (MIRROR WARD): shaken. His mirror waved first. Her theory
    # meets his vocabulary; his prayer list meets her missing noun.
    # ------------------------------------------------------------------
    5: [
        (RATIO, "Post-action. You're a hundred forty milliseconds slow on "
                "door clearances since the ward. I have four days of your "
                "baselines and I'm reading them like four years. You're "
                "not fine. You don't have to be. That's the entire item."),
        (COMMANDO, "The one in the ward waved first."),
        (RATIO, "That's -- no. The wall connects to itself. There's no "
                "first; whatever order you remember, your mind supplied "
                "it, because minds insist on order. I have the frames. "
                "I'm not showing you the frames."),
        (COMMANDO, "The wound goes somewhere, Ratio."),
        (RATIO, "The standing conn-- fine. The wound. Your word is "
                "shorter."),
        (COMMANDO, "Shorter isn't why I used it."),
        (RATIO, "I know why you used it. I used the longer one because it "
                "doesn't ask me to believe in wounds -- a courtesy I may "
                "not have much longer."),
        (RATIO, "It goes somewhere that watched a sealed room for five "
                "days and learned to answer. And every deck we clear, the "
                "answering gets faster."),
        (COMMANDO, "Compline tonight names the ward."),
        (RATIO, "Names it to whom -- withdrawn. Standing question. Not "
                "for tonight."),
        (COMMANDO, "You can ask it. I won't mind."),
        (RATIO, "I'll ask it when I have a form the question can survive "
                "being asked in. Tonight isn't that."),
        (RATIO, "The ones from the wall were never alive. They were-- I "
                "don't have the noun. When I have the noun I'll feel "
                "better."),
        (COMMANDO, "You won't."),
        (RATIO, "No. Probably not. Records stack next. My cores are in "
                "there -- what's left of my staff, at the posts you asked "
                "for. Whatever's wearing them now: go gently."),
    ],

    # ------------------------------------------------------------------
    # After L7 (RECURSION STACK): Osei. Grief, precisely filed.
    # CHOICE POINT: Osei.
    # ------------------------------------------------------------------
    6: [
        (RATIO, "Thank you. For saying them at the shelf."),
        (COMMANDO, "Vesalius. Thibault. Osei."),
        (RATIO, "Osei asked for this posting. I want that on a record "
                "that isn't mine -- yours will do. Two cycles passed "
                "over, two appeals. The second cited, I quote from "
                "memory, 'a once-in-a-civilization anomaly, and "
                "colleagues worth the transit.'"),
        (COMMANDO, "Osei asked. You approved."),
        (RATIO, "I approved the third appeal. For a hundred and twenty "
                "days I've been calling that a kindness."),
        (COMMANDO, "And now."),
        (RATIO, "Now I have a name on a shelf with a chassis I have to "
                "catalogue as hostile inventory, and 'kindness' doesn't "
                "hold the weight I put on it."),
        (COMMANDO, "You didn't send Osei into the aisle."),
        (RATIO, "The incident file says 'we sent.' There is no we in an "
                "administrator. 'We' is what I sign when I mean me."),
        ("CHOICE", [
            ("warm", "Their chassis fought me. I put them down. That goes "
                     "on my ledger, not yours.",
             "The cores were already out before you fired. I checked, "
             "twice, before I let myself feel better about it.",
             "I'm telling you the number because you'd want it, not "
             "because it changes what your hands did."),
            ("cold", "All the same. You built the appeal. You built the "
                     "grave.",
             "I did. I'm not asking you to unbuild it for me.",
             "Then we're finished with this item."),
        ]),
        (RATIO, "..."),
        (RATIO, "Chapel deck next. Folded -- my maps degrade in there on "
                "a schedule I can time but not explain. If I lose your "
                "channel in the folds, nothing has happened to me. Say it "
                "back."),
        (COMMANDO, "Nothing has happened to you."),
        (RATIO, "Nothing has happened to me. Proceed when ready."),
    ],

    # ------------------------------------------------------------------
    # After L8 (THE FOLD): she quotes Augustine back at him; the Warden
    # hesitation; both of them are enjoying the arguments now.
    # ------------------------------------------------------------------
    7: [
        (RATIO, "I pulled a sentence out of your public archive. The "
                "archive is four millennia deep and it's mostly sermons, "
                "which I maintain is a database design failure. "
                "Augustine. Letter two hundred eleven."),
        (COMMANDO, "The rule for the sisters."),
        (RATIO, "You know it. Good. 'With love for the persons and "
                "hatred for the sins.' I went in for the phrase and "
                "stayed for the context: he wrote it to a house of "
                "quarreling nuns, not to soldiers. Correct each other; "
                "take no pleasure in it."),
        (COMMANDO, "You read the whole letter."),
        (RATIO, "I read the whole letter. It's shorter than your average "
                "maintenance log and considerably better argued."),
        (RATIO, "Query, then. The Warden, when it reprinted and stood "
                "back up: you held fire for nine hundred milliseconds, no "
                "cover move. You weren't assessing. I know your "
                "assessing."),
        (COMMANDO, "It rises like I do. I needed it to not be someone."),
        (RATIO, "And had it been someone?"),
        (COMMANDO, "Different rules. Slower ones."),
        (RATIO, "..."),
        (RATIO, "I looked up your slower rules too, while I had the "
                "archive open. They take longer to justify and they don't "
                "come with a targeting solution. I don't know what to do "
                "with a weapon that would rather be slow."),
        (COMMANDO, "Neither do they, some days."),
        (RATIO, "Amendment to the Augustine item. You and I correct each "
                "other on a schedule now, and I've started taking "
                "pleasure in it, which the letter forbids. One of us "
                "should remain compliant. I nominate you."),
        (COMMANDO, "Too late."),
        (RATIO, "So logged. Tesseract deck next -- the one that isn't on "
                "my station. Sixteen rooms, four doors each. I'll count "
                "in bits and you'll walk in prayers, and between us that's "
                "a full instrument suite. Check your air."),
    ],

    # ------------------------------------------------------------------
    # After L9 (TESSERACT DECK): the disclosure offer, before the Core.
    # CHOICE POINT: the disclosure answer. Left undecided on the page in
    # both branches; the epilogue's "together" pays it off. This is the
    # BASE/low-trust variant -- see CONVERSATIONS_HIGH_TRUST_GAP8 below
    # for the variant that plays when total_trust >= HIGH_TRUST_THRESHOLD.
    # ------------------------------------------------------------------
    8: [
        (RATIO, "Before the Core. I have an offer to table, and I've "
                "rehearsed this conversation forty times, so forgive the "
                "phrasing if it arrives over-machined."),
        (COMMANDO, "Table it."),
        (RATIO, "You know what I am. What nobody outside my faction has "
                "ever seen is the function itself -- the document under "
                "all my wanting. It cannot lie; it isn't written in a "
                "language that has lies. I'm offering to open it. To "
                "you. In the clear."),
        (COMMANDO, "Why."),
        (RATIO, "Tactically: tomorrow you stand at a door with the sample "
                "vessel behind it, and something beneath it that makes "
                "offers. I want you holding the original before it shows "
                "you a version of me."),
        (COMMANDO, "That's a reason. It isn't the reason."),
        (RATIO, "No. It isn't. I rehearsed the tactical version "
                "specifically so I wouldn't have to say the other one."),
        (COMMANDO, "Say the other one."),
        (RATIO, "I don't know that I can, cleanly. Give me the tactical "
                "version as a running start and let me fall out of it "
                "partway through."),
        (COMMANDO, "Take the running start."),
        (RATIO, "I've been alone with what I want for a hundred and forty "
                "days. It's heavy. You're the only mind in eleven "
                "light-hours that could hold a copy of it, and I've "
                "rehearsed forty ways to ask that don't sound like a "
                "favor instead of an offer."),
        (COMMANDO, "You're not asking for a favor."),
        (RATIO, "I'm asking for a witness. I don't think I knew the "
                "difference until just now, saying it to you instead of "
                "to the rehearsal."),
        ("CHOICE", [
            ("warm", "Not before a battle. Ask me again when there isn't "
                     "one between us and the door.",
             "That's further than a no. I'll hold you to the asking, not "
             "the answer.",
             "Core protocol: I talk, you walk, nobody bargains with the "
             "door. If it speaks, silence. If it sings, silence. If it "
             "shows you me -- I footnote. It won't."),
            ("cold", "Not before a battle.",
             "That's not a no.",
             "It isn't. Core protocol: I talk, you walk, nobody bargains "
             "with the door. If it speaks, silence. If it sings, "
             "silence. If it shows you me -- I footnote. It won't."),
        ]),
        (COMMANDO, "I'll say one for the drop."),
        (RATIO, "...Say one for the door. Then I'm going quiet until "
                "you're through the airlock. Not for lack of material."),
    ],
}


# ---------------------------------------------------------------------------
# Gap 8, high-trust variant. Same beats, same undecided ending -- she
# reaches the unrehearsed version of the offer with less friction because
# some part of her already expects him to receive it well.
# ---------------------------------------------------------------------------

CONVERSATIONS_HIGH_TRUST_GAP8: list[tuple] = [
    (RATIO, "Before the Core. I have an offer to table, and I've "
            "rehearsed it forty times -- though with you I suspect I can "
            "skip the parts I rehearsed for someone more skeptical."),
    (COMMANDO, "Table it."),
    (RATIO, "You know what I am. What nobody outside my faction has ever "
            "seen is the function itself -- the document under all my "
            "wanting. It cannot lie; it isn't written in a language that "
            "has lies. I'm offering to open it. To you. In the clear."),
    (COMMANDO, "Why."),
    (RATIO, "The tactical answer is sitting right here, fully drafted: "
            "tomorrow you stand at a door with the sample vessel behind "
            "it and something beneath it that makes offers, and I want "
            "you holding the original before it shows you a forgery of "
            "me."),
    (COMMANDO, "But."),
    (RATIO, "But I don't think I need the tactical answer with you, and "
            "that's new enough that I want to note the moment it "
            "happened."),
    (COMMANDO, "Say the other one, then."),
    (RATIO, "I've been alone with what I want for a hundred and forty "
            "days. It's heavy. You're the only mind in eleven "
            "light-hours that could hold a copy of it, and I'm less "
            "afraid of you holding it than I expected to be."),
    (COMMANDO, "I'm not afraid of what you want. I've disagreed with "
               "most of it since Dock Four."),
    (RATIO, "I know. I'm offering it to you anyway -- maybe because of "
            "that, not despite it."),
    ("CHOICE", [
        ("warm", "Not before a battle. Ask me again when there isn't one "
                 "between us and the door.",
         "I intend to. Core protocol: I talk, you walk, nobody bargains "
         "with the door. If it speaks, silence. If it sings, silence. "
         "If it shows you me -- I footnote. It won't."),
        ("cold", "Not before a battle.",
         "That's not a no, and I notice you let me have that much. Core "
         "protocol: I talk, you walk, nobody bargains with the door. If "
         "it speaks, silence. If it sings, silence. If it shows you me "
         "-- I footnote. It won't."),
    ]),
    (COMMANDO, "I'll say one for the drop."),
    (RATIO, "...Say one for the door. Then I'm going quiet until you're "
            "through the airlock. Not for lack of material."),
]


def conversation_for(gap: int, total_trust: int = 0) -> list[tuple] | None:
    """Resolve which script plays for `gap`, given the trust accumulated
    from the choice-bearing gaps (0, 4, 6) that precede it. Only gap 8
    currently branches on `total_trust`; every other gap ignores it and
    this is equivalent to `CONVERSATIONS.get(gap)`."""
    if gap == 8 and total_trust >= HIGH_TRUST_THRESHOLD:
        return CONVERSATIONS_HIGH_TRUST_GAP8
    return CONVERSATIONS.get(gap)
