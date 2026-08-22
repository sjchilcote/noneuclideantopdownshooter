"""Historical tune parsers — Lilypond \\relative + ABC subsets.

Sources (fetched, in scratchpad/musicgen/tunes/):
- lhomme.wiki    en.wikipedia L'homme armé <score> (Lilypond, F maj sig)
- old100.wiki    en.wikipedia Old 100th <score> 0 — 1551 Genevan rhythm
- christlag.wiki en.wikipedia Christ lag in Todesbanden <score> — Bach
                 BWV 4 soprano (first << >> voice)
- efb.abc        abcnotation.com / ifdo.ca kern2abc Bach chorale 20,
                 Ein feste Burg soprano [V:1], K:D
- idumea.abc     abcnotation.com / folkinfo Sacred Harp Denson 1971,
                 melody = Tenor [V:3], K:Am
- admortem.abc   abcnotation.com / alijc Llibre Vermell 24, [V:1], K:C

Output convention = chants.DIES_IRAE_STROPHE: (semitones_from_final,
dur_16th_steps), None = rest; quarter note = 4 steps.
"""
from __future__ import annotations

import re
from pathlib import Path

S = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
         "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b"
         "/scratchpad/musicgen/tunes")

_PC = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)


# --------------------------------------------------------------------------
# Lilypond \relative subset
# --------------------------------------------------------------------------
_LY_NOTE = re.compile(
    r"(?<![a-z\\])([a-g])((?:is|es|s)*)([',]*)(\d+)?(\.?)(~?)")


def _ly_strip(src: str) -> str:
    src = re.sub(r"%.*", "", src)
    src = re.sub(r"\\addlyrics\s*\{.*", "", src, flags=re.S)
    # keep only the first voice of each << {A} \\ {B} >> pair
    while True:
        m = re.search(r"<<\s*\{", src)
        if not m:
            break
        depth, i = 1, m.end()
        a_end = None
        while i < len(src) and depth:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        a_end = i
        m2 = re.compile(r">>").search(src, a_end)
        src = src[:m.start()] + src[m.end():a_end - 1] + src[m2.end():]
    # expand \repeat unfold N { ... }
    while True:
        m = re.search(r"\\repeat\s+unfold\s+(\d+)\s*\{", src)
        if not m:
            break
        depth, i = 1, m.end()
        while i < len(src) and depth:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        body = src[m.end():i - 1]
        src = src[:m.start()] + body * int(m.group(1)) + src[i:]
    # \relative X resets the octave anchor mid-piece: keep as a marker
    src = re.sub(r"\\relative\s+([a-g](?:is|es)*[',]*)", r" @\1@ ", src)
    # commands whose ARGUMENT would otherwise read as a note
    src = re.sub(r"\\key\s+[a-g](?:is|es)*\s*\\(major|minor|dorian|phrygian"
                 r"|lydian|mixolydian|aeolian|locrian)", " ", src)
    src = re.sub(r"\\(time|partial|clef|tempo|bar)\s+\S+", " ", src)
    src = re.sub(r"\\[a-zA-Z]+", " ", src)
    src = re.sub(r'"[^"]*"', " ", src)
    # settings residue ("Score.BarNumber #'transparent = ##t"): any word
    # containing an uppercase letter, '#', or '=' is not music (dots are
    # left alone — "g2." is a dotted note)
    src = re.sub(r"\S*[A-Z#=]\S*", " ", src)
    return src


def parse_lilypond(src: str, relative: str = "c''"):
    """-> [(abs_semitone, steps) | (None, steps)], quarter = 4 steps."""
    body = _ly_strip(src)

    def anchor(pitch: str):
        m = re.match(r"([a-g])((?:is|es|s)*)([',]*)", pitch)
        deg = "cdefgab".index(m.group(1))
        octv = 4 + m.group(3).count("'") - m.group(3).count(",")
        return deg, octv

    prev_deg, prev_oct = anchor(relative)
    dur = 4.0
    out = []
    tie = False
    for tok in re.finditer(
            r"@([a-g](?:is|es)*[',]*)@"
            r"|([a-g])((?:is|es)*)([',]*)(\d+)?(\.*)(~?)"
            r"|(?<![a-zA-Z])([rR])(\d+)?(\.*)",
            body):
        if tok.group(1):                       # \relative reset
            prev_deg, prev_oct = anchor(tok.group(1))
            continue
        if tok.group(8):                       # rest
            if tok.group(9):
                dur = 16.0 / int(tok.group(9))
                if tok.group(10):
                    dur *= 1.5
            out.append([None, dur])
            continue
        letter, acc, octm, d, dots, tie_m = tok.group(2, 3, 4, 5, 6, 7)
        deg = "cdefgab".index(letter)
        # relative octave: closest to previous degree, then ' , shifts
        diff = deg - prev_deg
        octv = prev_oct
        if diff > 3:
            octv -= 1
        elif diff < -3:
            octv += 1
        octv += octm.count("'") - octm.count(",")
        semi = _PC[letter] + 12 * octv \
            + 1 * (acc.count("is")) - 1 * (acc.count("es"))
        if d:
            dur = 16.0 / int(d)
            if dots:
                dur *= 1.5 * len(dots) if len(dots) == 1 else 1.75
        elif dots:
            dur *= 1.5
        if tie and out and out[-1][0] == semi:
            out[-1][1] += dur
        else:
            out.append([semi, dur])
        tie = bool(tie_m)
        prev_deg, prev_oct = deg, octv
    return out


# --------------------------------------------------------------------------
# ABC subset
# --------------------------------------------------------------------------
_KEYSIG = {
    "C": {}, "Am": {},
    "G": {"f": 1}, "Em": {"f": 1},
    "D": {"f": 1, "c": 1}, "Bm": {"f": 1, "c": 1},
    "A": {"f": 1, "c": 1, "g": 1},
    "F": {"b": -1}, "Dm": {"b": -1},
    "Bb": {"b": -1, "e": -1}, "Gm": {"b": -1, "e": -1},
}


def parse_abc(src: str, voice: str = "1"):
    """-> [(abs_semitone, steps) | (None, steps)]. Handles K:, L:,
    measure-scoped accidentals, |: :| |1 |2 repeats, chords (top note),
    slurs, w: lines."""
    key, unit = "C", 0.125
    lines = []
    cur_voice = "1"
    in_header = True
    for ln in src.splitlines():
        if re.match(r"^K:\s*(\S+)", ln):
            key = re.match(r"^K:\s*(\S+)", ln).group(1)
            in_header = False
            continue
        if re.match(r"^L:\s*", ln):
            a, b = re.match(r"^L:\s*(\d+)/(\d+)", ln).groups()
            unit = int(a) / int(b)
            continue
        m = re.match(r"^V:\s*(\S+)", ln)
        if m:
            cur_voice = m.group(1)
            continue
        if ln.startswith(f"[V:{voice}]"):
            lines.append(ln[len(f"[V:{voice}]"):])
        elif (not in_header and cur_voice == voice
              and not re.match(r"^[A-Za-z]:|^%", ln) and ln.strip()):
            lines.append(ln)
    body = " ".join(lines)
    body = re.sub(r'"[^"]*"', "", body)
    body = re.sub(r"\[[A-Za-z]:[^\]]*\]", "", body)   # inline fields
    body = re.sub(r"![^!]*!", "", body)               # decorations
    # repeats: expand |:  A |1 x :|2 y |]  ->  A x A y
    m = re.search(r"\|:(.*?)\|1(.*?):\|2(.*?)(\|\]|$)", body)
    if m:
        body = (body[:m.start()] + m.group(1) + m.group(2)
                + m.group(1) + m.group(3))
    body = body.replace("|:", "|").replace(":|", "|").replace("|]", "|")
    sig = dict(_KEYSIG[key])
    unit_steps = unit * 16          # whole note = 16 sixteenth-steps
    out = []
    meas_acc: dict[str, int] = {}
    i = 0
    tokre = re.compile(
        r"(\|)|(\[)|(\])|([_^=]+)?([A-Ga-g])([,']*)"
        r"(\d+(?:/\d+)?|/\d*)?|(z|x)(\d+)?|(\()|(\))")
    in_chord = False
    chord_done = False
    for t in tokre.finditer(body):
        if t.group(1):
            meas_acc.clear()
            continue
        if t.group(2):
            in_chord, chord_done = True, False
            continue
        if t.group(3):
            in_chord = False
            continue
        if t.group(8):
            n = float(t.group(9) or 1)
            out.append([None, unit_steps * n])
            continue
        if t.group(5):
            if in_chord and chord_done:
                continue
            acc, letter, octm, dstr = t.group(4, 5, 6, 7)
            low = letter.lower()
            octv = 5 if letter.islower() else 4
            octv += octm.count("'") - octm.count(",")
            if acc:
                delta = acc.count("^") - acc.count("_")
                if "=" in acc:
                    delta = 0
                meas_acc[low + str(octv)] = delta
            delta = meas_acc.get(low + str(octv), sig.get(low, 0))
            semi = _PC[low] + 12 * octv + delta
            n = 1.0
            if dstr:
                if dstr.startswith("/"):
                    n = 1.0 / float(dstr[1:] or 2)
                elif "/" in dstr:
                    a, b = dstr.split("/")
                    n = float(a) / float(b)
                else:
                    n = float(dstr)
            out.append([semi, unit_steps * n])
            if in_chord:
                chord_done = True
    return out


# --------------------------------------------------------------------------
# The menu
# --------------------------------------------------------------------------

def _rel_to_final(events):
    final = next(p for p, _ in reversed(events) if p is not None)
    out = []
    for p, d in events:
        d = int(round(d))
        if d <= 0:
            continue
        out.append((None if p is None else p - final, d))
    return out


def _wiki_score(name: str, idx: int = 0) -> str:
    t = (S / f"{name}.wiki").read_text()
    blocks = re.findall(r"<score[^>]*>(.*?)</score>", t, re.S)
    return blocks[idx]


def _ly_relative(src: str) -> str:
    m = re.search(r"\\relative\s+([a-g](?:is|es)*[',]*)", src)
    return m.group(1) if m else "c''"


def load_menu():
    """name -> (events, provenance) for the six grounded tunes."""
    out = {}
    ly = [("lhomme_arme", "lhomme", 0,
           "L'homme armé (15th c.) — en.wikipedia score"),
          ("old_100th", "old100", 0,
           "Old 100th, 1551 Genevan rhythm — en.wikipedia score 0"),
          ("christ_lag", "christlag", 0,
           "Christ lag in Todesbanden, Bach BWV 4 soprano — en.wikipedia")]
    for name, fn, idx, prov in ly:
        src = _wiki_score(fn, idx)
        if fn == "christlag":               # keep soprano staff only
            src = src.split("\\new Lyrics")[0]
        ev = parse_lilypond(src, _ly_relative(src))
        out[name] = (_rel_to_final(ev), prov)
    abc = [("ein_feste_burg", "efb", "1",
            "Ein feste Burg, Bach chorale 20 soprano — kern2abc"),
           ("idumea", "idumea", "3",
            "Idumea, Sacred Harp (Denson 1971) TENOR = melody"),
           ("ad_mortem", "admortem", "1",
            "Ad mortem festinamus, Llibre Vermell — alijc abc")]
    for name, fn, voice, prov in abc:
        ev = parse_abc((S / f"{fn}.abc").read_text(), voice)
        out[name] = (_rel_to_final(ev), prov)
    return out


if __name__ == "__main__":
    menu = load_menu()
    # incipit fixtures — independently known openings, rel to final
    FIX = {
        "lhomme_arme": [0, 0, 5, 5, 3, 2, 0],       # G G c c Bb A G
        "old_100th": [0, 0, -1, -3, -5, 0, 2, 4],   # G G F# E D G A B
        "christ_lag": [7, 6, 7, 9, 10, 12, 10, 9, 7],  # B A# B C# D E D C# B
        # soprano ends on D4 (source: "E2 D |]") — opening D5 is +12
        "ein_feste_burg": [12, 12, 12, 7, 9, 11],   # D D D A B C#
        # A2 | A4 (GA) | c4 (dc) | A4 e2 | g4 (ed) | c4 d2 | e4  (rel A)
        "idumea": [0, 0, -2, 0, 3, 5, 3, 0, 7, 10, 7, 5],
        "ad_mortem": [5, 7, 9, 5, 7, 7, 0, 2],      # F G A F | G G C D
    }
    ok = True
    for name, (ev, prov) in menu.items():
        sung = [p for p, _ in ev if p is not None]
        want = FIX[name]
        got = sung[:len(want)]
        match = got == want
        ok &= match
        print(f"{name:16s} {len(ev):3d} ev  incipit "
              f"{'OK' if match else 'MISMATCH'}")
        if not match:
            print("   want:", want)
            print("   got: ", got)
    print("ALL FIXTURES PASS" if ok else "FIXTURE FAILURES")
