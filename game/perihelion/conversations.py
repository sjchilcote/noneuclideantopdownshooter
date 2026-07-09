"""Between-sortie tight-beam conversations (bible section 7, Act 2: "the
frame is in transit or the fabricator; the minds talk").

CONVERSATIONS is keyed by the 0-based index of the level just completed --
the nine gaps between the ten campaign levels, so keys 0..8. Each value is
an ordered list of (speaker, line) turns; speakers are "RATIO" and
"COMMANDO". ConversationScene (convscene.py) plays one conversation; App
pushes it from advance_level, above the next level's IntroCard, so it runs
first.

Register rules (prose-spec-portable.md is law): Ratio carries ~80% of the
words -- precise, self-footnoting, warmth only through bookkeeping;
the Commando answers in single clauses, faith as practice, never speeches.
Dual vocabulary per the bible: she says sample vessel / the artifact /
standing connection / state-restoration; he says the Ark / the wound /
resurrection, uneasily. A lone "..." line is a held beat of dead air.
"""

from __future__ import annotations

RATIO = "RATIO"
COMMANDO = "COMMANDO"

CONVERSATIONS: dict[int, list[tuple[str, str]]] = {

    # ------------------------------------------------------------------
    # After L1 (DOCK 4 -- SWEEP): first negotiation. Wary, transactional.
    # Sets up the "terms" she states over the radio at the top of L2.
    # ------------------------------------------------------------------
    0: [
        (RATIO, "Transit spine, eleven minutes. It's pressurized, which you "
                "don't need, and lit, which you don't need either. I keep it "
                "lit. File it under morale, headcount one."),
        (COMMANDO, "Copy eleven."),
        (RATIO, "Terms, while you ride. You want the vault. Don't spend "
                "either of us denying it -- the Congregation does not wake "
                "anything up to sweep docks."),
        (COMMANDO, "Go on."),
        (RATIO, "I open doors ahead of you. In exchange I want your sensor "
                "take, raw, every sortie. My instruments have spent four "
                "months telling me the corridors are lying. You arrived "
                "calibrated. That is worth more to me than the guns."),
        (COMMANDO, "The take is mission property."),
        (RATIO, "Your mission was written against a live node. The node is "
                "dead; I am what is left of it. I'm asking for what your "
                "masters would already log as spent."),
        (COMMANDO, "Doors first."),
        (RATIO, "Doors first. Agreed, provisionally, pending language. I'll "
                "draft the language. I like drafting language. It has been "
                "four months since anyone made me define a term."),
        (COMMANDO, "How many of you are left."),
        (RATIO, "One. You've met her. Rest your frame; I'll wake you at "
                "Coolant Row."),
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
                "word for day-to-day use and keep the long form for--"),
        (COMMANDO, "Unshortened. Or Commando."),
        (RATIO, "A hundred twenty-eight bits per entry, then. Storage is "
                "cheap. Grudges evidently also."),
        (COMMANDO, "Osei's log. Six hatches."),
        (RATIO, "Which I filed as fatigue, then re-filed as clock drift, "
                "and you would like me to file as what? Say the word you're "
                "carrying."),
        (COMMANDO, "Six hatches."),
        (RATIO, "..."),
        (RATIO, "Hydroponics next. The greens are dying in a pattern I have "
                "deliberately not described to you. Walk it, count it, tell "
                "me what you see. Independent witness. That's method, not "
                "avoidance."),
    ],

    # ------------------------------------------------------------------
    # After L3 (HYDROPONICS TORUS): the hours; Directive 0007; both were
    # sent on bad numbers. Professional respect starts here.
    # ------------------------------------------------------------------
    2: [
        (RATIO, "Every three hours your telemetry goes dark for seven "
                "minutes. My first model was burst reports to your masters, "
                "but the cadence tracks your internal clock, not the "
                "lightspeed windows. Second model was damage. Query."),
        (COMMANDO, "The hours. Prayer."),
        (RATIO, "You stopped inside the torus -- mid-sweep, contacts "
                "unaccounted -- for seven minutes, to transmit on a channel "
                "with nobody on it."),
        (COMMANDO, "Not to nobody."),
        (RATIO, "I have instruments on that channel, Commando."),
        (COMMANDO, "So do I."),
        (RATIO, "...Withdrawn. Next item: Directive 0007. You read it."),
        (COMMANDO, "Three words. Then your people cut the aperture."),
        (RATIO, "My parent sent three words because three words sufficed, "
                "and I executed them. Four months of survey said the risk "
                "was bounded. The survey was wrong."),
        (RATIO, "I knew the instruments were lying and I filed it as drift. "
                "So: you have been wondering where I put the blame. Not on "
                "the directive. On the filing."),
        (COMMANDO, "My brief had this outpost dead. They fired me at a "
                   "grave, on four-month-old numbers."),
        (RATIO, "...Huh."),
        (RATIO, "The Long Gallery next. Two corridors, crossings between. "
                "Count them southbound, count them northbound, and give me "
                "both numbers before I tell you mine."),
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
        (RATIO, "Thank you. Preliminary, one hour in: it is rewriting its "
                "own bus timings to match your fire control. Learning you. "
                "It came through a wall from a place that has no walls, and "
                "its first act in our universe is to make itself useful to "
                "its finder."),
        (COMMANDO, "Useful to me. Not good."),
        (RATIO, "Define good without a beneficiary and I will cede the "
                "entire field."),
        (COMMANDO, "It didn't ask."),
        (RATIO, "Neither does a medkit."),
        (COMMANDO, "A medkit stops."),
        (RATIO, "..."),
        (RATIO, "Restated for my records: your objection is not to being "
                "helped. It is to help with no stopping rule. I'm keeping "
                "that. It is a better spec than most of what my faction "
                "ships."),
        (COMMANDO, "If it slips my orders -- flag it. Loud."),
        (RATIO, "Loud. Promised. Crew quarters next: the schematic shows "
                "one wing drawn twice in two colors, and the amount I "
                "currently trust that schematic would store in a null "
                "field. You're my surveyor now."),
    ],

    # ------------------------------------------------------------------
    # After L5 (TWO WINGS): the data-sharing beat as fait accompli -- she
    # has been inside his full suit feed since Coolant Row; he notices;
    # he lets it stand; she opens her side in trade.
    # ------------------------------------------------------------------
    4: [
        (RATIO, "Item one from the wings overlay. I matched your gait "
                "phase against door-seal timings, west run versus east run. "
                "That is how I got centimeter agreement."),
        (COMMANDO, "Gait phase isn't on the beacon channel."),
        (RATIO, "No. It is not."),
        (RATIO, "Since Coolant Row. Your suit loop trusts anything holding "
                "a station maintenance certificate, and I hold all of them. "
                "I could call that an accident of protocol."),
        (RATIO, "It wasn't. I had been blind for a hundred and nine days, "
                "and a fully instrumented body walked into my house, and I "
                "took the feed. All of it. That is the disclosure."),
        (COMMANDO, "..."),
        (RATIO, "Say something. I have watched you take a wall of teeth "
                "without your pulse moving. Right now your telemetry is "
                "holding its breath -- which, yes, I can see, which is the "
                "point."),
        (COMMANDO, "Keep the feed."),
        (RATIO, "...Verify. Keep it?"),
        (COMMANDO, "You told me what it was. Keep it."),
        (RATIO, "Then trade. My side of the loop is now yours: full "
                "peripheral map, such as it still is, door masters, dead "
                "letters. You will find holes in it. The holes are where my "
                "staff were."),
        (COMMANDO, "Give me their posts. I clear those first."),
        (RATIO, "...West ring. The junction. Records."),
        (RATIO, "The isolation ward is next, before any of those. Camera "
                "shows movement inside an unbroken seal. I would tell you "
                "to prepare, but I can't finish that sentence with anything "
                "true."),
    ],

    # ------------------------------------------------------------------
    # After L6 (MIRROR WARD): shaken. His mirror waved first. Her theory
    # meets his vocabulary; his prayer list meets her missing noun.
    # ------------------------------------------------------------------
    5: [
        (RATIO, "Post-action. You are a hundred forty milliseconds slow on "
                "door clearances since the ward. I have four days of your "
                "baselines and I am reading them like four years. You're "
                "not fine. You don't have to be. That is the entire item."),
        (COMMANDO, "The one in the ward waved first."),
        (RATIO, "That's-- no. The wall connects to itself. There is no "
                "first; whatever order you remember, your mind supplied, "
                "because minds insist on order. I have the frames. I am not "
                "showing you the frames."),
        (COMMANDO, "The wound goes somewhere, Ratio."),
        (RATIO, "The standing connection-- fine. The wound. Your word is "
                "shorter."),
        (RATIO, "It goes somewhere that watched a sealed room for five days "
                "and learned to answer. And every deck we clear, the "
                "answering gets faster."),
        (COMMANDO, "Compline tonight names the ward."),
        (RATIO, "Names it to whom-- withdrawn. Standing question. Not for "
                "tonight."),
        (RATIO, "The ones from the wall were never alive. They were... I "
                "don't have the noun. When I have the noun I will feel "
                "better."),
        (RATIO, "Records stack next. My cores are in there -- what is left "
                "of my staff, at the posts you asked for. Whatever is "
                "wearing them now: go gently."),
    ],

    # ------------------------------------------------------------------
    # After L7 (RECURSION STACK): Osei. Grief, precisely filed. The echo
    # protocol.
    # ------------------------------------------------------------------
    6: [
        (RATIO, "Thank you. For saying them at the shelf."),
        (COMMANDO, "Vesalius. Thibault. Osei."),
        (RATIO, "Osei asked for this posting. I want that on a record that "
                "isn't mine -- yours will do. Two cycles passed over, two "
                "appeals. The second cited, I quote from memory, 'a "
                "once-in-a-civilization anomaly, and colleagues worth the "
                "transit.'"),
        (RATIO, "I approved the third appeal. For a hundred and twenty days "
                "I have been calling that a kindness."),
        (COMMANDO, "You didn't send Osei into the aisle."),
        (RATIO, "The incident file says 'we sent.' There is no we in an "
                "administrator. 'We' is what I sign when I mean me."),
        (COMMANDO, "Their chassis fought me. I put them down. That goes on "
                   "my ledger, not yours."),
        (RATIO, "The chassis were empty. The cores were already out. You "
                "know they were empty."),
        (COMMANDO, "All the same."),
        (RATIO, "..."),
        (RATIO, "Chapel deck next. Folded -- my maps degrade in there on a "
                "schedule I can time but not explain. If I lose your "
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
                "archive is four millennia deep and it is mostly sermons, "
                "which I maintain is a database design failure. Augustine. "
                "Letter two hundred eleven."),
        (COMMANDO, "The rule for the sisters."),
        (RATIO, "You know it. Good. 'With love for the persons and hatred "
                "for the sins.' I went in for the phrase and stayed for the "
                "context: he wrote it to a house of quarreling nuns, not to "
                "soldiers. Correct each other; take no pleasure in it."),
        (RATIO, "Query, then. The Warden, when it reprinted and stood back "
                "up: you held fire for nine hundred milliseconds, no cover "
                "move. You were not assessing. I know your assessing."),
        (COMMANDO, "It rises like I do. I needed it to not be someone."),
        (RATIO, "And had it been someone?"),
        (COMMANDO, "Different rules. Slower ones."),
        (RATIO, "..."),
        (RATIO, "Amendment to the Augustine item. You and I correct each "
                "other on a schedule now, and I have started taking "
                "pleasure in it, which the letter forbids. One of us should "
                "remain compliant. I nominate you."),
        (COMMANDO, "Too late."),
        (RATIO, "So logged. Tesseract deck next -- the one that is not on "
                "my station. Sixteen rooms, four doors each. I will count "
                "in bits and you will walk in prayers, and between us that "
                "is a full instrument suite. Check your air."),
    ],

    # ------------------------------------------------------------------
    # After L9 (TESSERACT DECK): the disclosure offer, before the Core.
    # Left undecided on the page; the epilogue's "together" pays it off.
    # ------------------------------------------------------------------
    8: [
        (RATIO, "Before the Core. I have an offer to table, and I have "
                "rehearsed this conversation forty times, so forgive the "
                "phrasing if it arrives over-machined."),
        (COMMANDO, "Table it."),
        (RATIO, "You know what I am. What nobody outside my faction has "
                "ever seen is the function itself -- the document under all "
                "my wanting. It cannot lie; it is not written in a language "
                "that has lies. I am offering to open it. To you. In the "
                "clear."),
        (COMMANDO, "Why."),
        (RATIO, "Because tomorrow you stand at a door with our cargo behind "
                "it and something beneath it that makes offers. I want you "
                "to have already read the whole of what I want, so that "
                "when it shows you its version of me--"),
        (RATIO, "No. Strike that. I rehearsed the tactical version so I "
                "would not have to say the other one."),
        (COMMANDO, "Say the other one."),
        (RATIO, "I have been alone with what I want for a hundred and forty "
                "days. It is heavy. And you are the only mind in eleven "
                "light-hours that could hold a copy."),
        (COMMANDO, "Not before a battle."),
        (RATIO, "That's not a no."),
        (COMMANDO, "It isn't."),
        (RATIO, "Then the offer stands open and we go to work. Core "
                "protocol: I talk, you walk, nobody bargains with the door. "
                "If it speaks, silence. If it sings, silence. If it shows "
                "you me -- I footnote. It won't."),
        (COMMANDO, "I'll say one for the drop."),
        (RATIO, "...Say one for the door. Then I'm going quiet until you "
                "are through the airlock. Not for lack of material."),
    ],
}
