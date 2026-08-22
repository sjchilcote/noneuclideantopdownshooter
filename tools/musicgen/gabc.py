"""GABC (GregoBase) -> chant event lists, DIES_IRAE_STROPHE conventions.

Pitch semantics (derived and fixture-verified against the hand-checked
Dies Irae transcription in chants.py, GregoBase 1198):

- pitch letters a..m are consecutive diatonic staff positions (index
  a=0 .. m=12);
- clef cN puts DO at position index 2N+1 (c4 -> j; c3 -> h); clef fN
  puts FA there (DO three diatonic steps lower);
- degree->semitone within the DO scale: do0 re2 mi4 fa5 sol7 la9 ti11;
- 'x' after a pitch flattens it (ti->te), 'y' naturalizes;
- output = semitones relative to the piece's FINAL (last sung note),
  matching the "semitones from the chant's own final" convention.

Rhythm (the strophe's syllabic convention): one syllable = 4 sixteenth
steps; multi-note neumes split the syllable evenly (2 notes = two 8ths);
a mora dot on a syllable's last note doubles that note; (;) = 4-step
breath rest, (::) = 8-step full stop, (:) = 4-step.
"""
from __future__ import annotations

import re

_DEG_SEMIS = [0, 2, 4, 5, 7, 9, 11]
_LETTERS = "abcdefghijklm"


def _clef_do_index(clef: str) -> int:
    kind, line = clef[0], int(clef[-1])
    idx = 2 * line + 1
    if kind == "f":
        idx -= 3            # FA on the clef line -> DO three steps down
    return idx


def _semitone(idx: int, do_idx: int, flat: bool) -> int:
    rel = idx - do_idx
    octave, degree = divmod(rel, 7)
    s = octave * 12 + _DEG_SEMIS[degree]
    if flat:
        s -= 1
    return s


_NOTE_RE = re.compile(r"([a-mA-M])([xy#]?)")
_STRIP = re.compile(r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>")


def parse(gabc: str):
    """-> (events, meta). events = [(semis_from_final, steps) | (None, steps)]
    exactly like chants.DIES_IRAE_STROPHE."""
    head, _, body = gabc.partition("%%")
    meta = dict(re.findall(r"(?m)^([\w-]+):\s*(.*?);?\s*$", head))
    body = _STRIP.sub("", body)

    do_idx = None
    syllables = []          # list of (pitch_list, mora_last) or ("rest", steps)
    for grp in re.findall(r"\(([^)]*)\)", body):
        g = grp.strip()
        m = re.match(r"^([cf][1-4])", g)
        if m:
            do_idx = _clef_do_index(m.group(1))
            continue
        if do_idx is None:
            continue
        if g in (";", ",", ";1", ";2", ";3"):
            syllables.append(("rest", 4) if g != "," else ("rest", 0))
            continue
        if g in ("::", ":", ":?"):
            syllables.append(("rest", 8 if g == "::" else 4))
            continue
        notes = []
        flat_state: dict[int, bool] = {}
        mora = False
        i = 0
        while i < len(g):
            ch = g[i]
            m2 = _NOTE_RE.match(g, i)
            if m2 and m2.start() == i:
                letter, acc = m2.group(1).lower(), m2.group(2)
                idx = _LETTERS.index(letter)
                if acc == "x":
                    flat_state[idx] = True
                    i = m2.end()
                    continue    # accidental only marks the position
                if acc == "y":
                    flat_state[idx] = False
                    i = m2.end()
                    continue
                notes.append(_semitone(idx, do_idx, flat_state.get(idx, False)))
                i = m2.end()
                continue
            if ch == ".":
                mora = True
            i += 1
        if notes:
            syllables.append((notes, mora))
    # final = last sung pitch
    final = None
    for s in reversed(syllables):
        if s[0] != "rest":
            final = s[0][-1]
            break
    events = []
    for s in syllables:
        if s[0] == "rest":
            if s[1]:
                events.append((None, s[1]))
            continue
        notes, mora = s
        base = 4
        if len(notes) == 1:
            events.append((notes[0] - final, base * (2 if mora else 1)))
        else:
            step = max(1, base // len(notes))
            for k, n in enumerate(notes):
                d = step
                if k == len(notes) - 1:
                    d = base - step * (len(notes) - 1)
                    if mora:
                        d += base // 2
                events.append((n - final, d))
    # merge consecutive rests
    out = []
    for e in events:
        if e[0] is None and out and out[-1][0] is None:
            out[-1] = (None, out[-1][1] + e[1])
        else:
            out.append(list(e))
    return [tuple(e) for e in out], meta


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from chants import DIES_IRAE_STROPHE
    S = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
             "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b"
             "/scratchpad/musicgen")
    text = (S / "dies_irae.gabc").read_text()
    ev, meta = parse(text)
    want = [p for p, _ in DIES_IRAE_STROPHE if p is not None]
    # first strophe = first len(want) sung pitches
    got = [p for p, _ in ev if p is not None][:len(want)]
    print("mode:", meta.get("mode"), "| events:", len(ev))
    print("fixture pitches match:", got == want)
    if got != want:
        print("want:", want)
        print("got: ", got)
