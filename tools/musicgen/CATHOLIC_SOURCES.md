# Catholic liturgical-music sources for round-2 PERIHELION score

Director's order: melodic material must derive from CATHOLIC liturgical tradition
only — Gregorian chant and Renaissance Catholic polyphony — strictly separated from
Protestant tradition (no chorales, no metrical psalters, no gospel hymnody). Goal:
chant-derived cantus firmus fused with industrial metal, using the church modes as
the harmonic/melodic backbone (Dorian/Phrygian map naturally onto metal idiom).

All melodic data below was captured from real, cited sources, not invented.

---

## 1. The eight Gregorian church modes

Modes come in four authentic/plagal pairs. The **final** is the note the chant
resolves to (root of the scale for our purposes). The **dominant/tenor** is the
reciting tone used for psalmody. Authentic and plagal modes of the same pair share
the same final and the same diatonic note collection (same "scale"); they differ in
ambitus (range around the final) and in dominant.

| # | Mode | Type | Final | Dominant (reciting tone) | Semitone offsets from final (diatonic scale) | Note letters (final=D shown as example root) |
|---|------|------|-------|---------------------------|-----------------------------------------------|------------------------------------------------|
| I | Dorian | Authentic | D | A (5th above final) | 0, 2, 3, 5, 7, 9, 10, 12 | D E F G A B C D |
| II | Hypodorian | Plagal (of I) | D | F (3rd above final) | 0, 2, 3, 5, 7, 9, 10, 12 (same collection as I, lower ambitus) | D E F G A B C D |
| III | Phrygian | Authentic | E | C (per some sources) / B (older, avoiding the unstable step above final) | 0, 1, 3, 5, 7, 8, 10, 12 | E F G A B C D E |
| IV | Hypophrygian | Plagal (of III) | E | A (4th above final) | 0, 1, 3, 5, 7, 8, 10, 12 | E F G A B C D E |
| V | Lydian | Authentic | F | C (5th above final) | 0, 2, 4, 6, 7, 9, 11, 12 | F G A B C D E F |
| VI | Hypolydian | Plagal (of V) | F | A (3rd above final) | 0, 2, 4, 6, 7, 9, 11, 12 | F G A B C D E F |
| VII | Mixolydian | Authentic | G | D (5th above final) | 0, 2, 4, 5, 7, 9, 10, 12 | G A B C D E F G |
| VIII | Hypomixolydian | Plagal (of VII) | G | C (per some tables) / D (4th above final, per others) | 0, 2, 4, 5, 7, 9, 10, 12 | G A B C D E F G |

Programmer's takeaway: each pair reduces to one of four **interval patterns**
(Dorian-species, Phrygian-species, Lydian-species, Mixolydian-species). To build a
scale in code, pick a root pitch class, apply the semitone-offset list above, and
treat authentic vs. plagal only as a *range/tessitura* choice (plagal sits roughly a
4th lower, centered around the final rather than built up from it) plus a different
reciting tone for any recitation-style writing over the cantus firmus.

Characteristic flavor for fusion with metal:
- **Dorian** (D E F G A B C D): natural-minor-like but with a *raised 6th* (B
  natural, not B-flat) — this is the mode of the *Dies irae* itself and reads as
  minor/ominous without being a plain Aeolian minor. Good default for verse riffs.
- **Phrygian** (E F G A B C D E): minor with a *flat 2nd* (F over E) — the classic
  "flamenco/metal" half-step-above-the-root sound; very strong for aggressive
  sections.
- **Mixolydian** (G A B C D E F G): major with a *flat 7th* — usable for
  triumphant/"Alleluia" cues (see Victimae Paschali Laudes below).
- **Lydian** (F G A B C D E F): major with a *raised 4th* — brighter, useful for
  transcendence/hope cues, less useful for the industrial-metal backbone.

Sources: [Church mode / Gregorian mode — Wikipedia](https://en.wikipedia.org/wiki/Church_modes), [Britannica: Mode (Plainchant, Medieval, Gregorian)](https://www.britannica.com/art/mode-music/Plainchant), [Britannica: Church mode](https://www.britannica.com/art/church-mode).

---

## 2. Captured chant melodies (note-name sequences)

All four chants below were pulled from **GregoBase** (gregobase.selapa.net), a
public database of Gregorian chant scores encoded in **GABC** notation and sourced
from the Solesmes editions (*Graduale Romanum* 1961, *Liber Usualis* 1961,
*Liber antiphonarius* 1960, *Chants of the Church* 1956). GABC pitch letters
(`a b c d e f g h i j k l m ...`) are a diatonic (white-note) alphabet — `c`=C,
`d`=D, `e`=E, `f`=F, `g`=G, `h`=A, `i`=B, then the alphabet continues up an octave
(`j`=C, `k`=D, ...). Punctuation/prefixes (`.`, `'`, `//`, `[ll:1]`) are rhythmic and
episema markings, not pitches, and were dropped when extracting the note sequence.
GABC syntax itself is documented at [gregorio-project on GitHub](https://github.com/gregorio-project/gregorio) / referenced throughout GregoBase.

### 2a. Dies Irae (Sequence, Requiem Mass) — PRIMARY source for judgment/apocalypse motif

- **GregoBase**: https://gregobase.selapa.net/chant.php?id=1198
- **Source cited on page**: *Graduale Romanum*, Solesmes, 1961, p. 96; also *The Liber Usualis* (1961) and *Chants of the Church* (1956).
- **Mode**: Dorian (Mode I), final D. Confirmed independently by [Wikipedia: Dies irae](https://en.wikipedia.org/wiki/Dies_irae) ("the original Gregorian setting... is in the Dorian mode") and [interlude.hk](https://interlude.hk/the-melody-of-death-the-dies-irae/) / [Open Culture](https://www.openculture.com/2019/09/the-creepy-13th-century-song-that-shows-up-in-movies-again-again.html) (the famous 4-note "doom motif" quoted by Berlioz, Liszt, Rachmaninoff, Mahler, and dozens of film scores derives from this incipit).
- **GABC incipit** ("Dies irae, dies illa"): `(c4) DI(f)es(e) i(f)rae,(d) di(e)es(c) il(d)la,(d.)`
- **Captured note sequence** (syllable-aligned): **F E F D | E C D D**
  (Di-es i-rae | di-es il-la). Descending, interlocking 2nds/3rds, landing on the
  final D — matches the "descending stepwise, no leading tone" character noted by
  multiple sources.
- **Why usable**: this is literally the most famous "doom" cantus firmus in Western
  music and is already thematically the game's judgment/apocalypse material. It is
  the obvious top choice for a boss/apocalypse leitmotif.
- **PD status**: 13th-century plainchant, composer unknown/traditional (often
  attributed to Thomas of Celano). The melody-as-composition is public domain. The
  specific Solesmes 1961 engraving is a modern edition, but we are only extracting
  the note sequence as documented musicological fact, not reproducing or
  distributing the engraved page/audio.

### 2b. Victimae Paschali Laudes (Easter Sequence)

- **GregoBase**: https://gregobase.selapa.net/chant.php?id=1086
- **Source cited on page**: *Graduale Romanum*, Solesmes, 1961, p. 242; *The Liber Usualis*, Solesmes, 1961, p. 780; *Chants of the Church*, Solesmes, 1956, p. 162.
- **Mode**: sources disagree slightly — [Grokipedia](https://grokipedia.com/page/Victimae_paschali_laudes) gives Hypodorian (Mode II), final D, range ~a 10th; other sources list Mode I. Either way, final = D, same Dorian-species note collection as Dies Irae.
- **GABC incipit** ("Victimae paschali laudes"): `(c4) VI(d)cti(c)mae(d) pa(f)schá(g)li(f) lau(e)des(d.)`
- **Captured note sequence**: **D C D F G F E D**
  (Vi-cti-mae pa-schá-li lau-des) — an ascending-then-descending arch, ending back
  on the D final. Attributed to Wipo of Burgundy, c. 1040; one of only four
  sequences retained in the Roman Missal after Trent (1570).
- **Why usable**: shares the same Dorian tonal center as Dies Irae (a fifth/motif
  family the two can share in the score), but has a triumphant/Paschal-victory
  character (also famous for melismatic "Alleluia" extensions) — usable as a
  contrasting "hope/resurrection" motif built from the *same mode* as the judgment
  theme, which is compositionally convenient for a score that needs both.
- **PD status**: 11th-century composition, public domain; Solesmes engraving used
  only for the note sequence.

### 2c. Salve Regina (Marian antiphon)

- **GregoBase**: https://gregobase.selapa.net/chant.php?id=2715
- **Source cited on page**: *The Liber Usualis*, Solesmes, 1961, p. 276; *Liber antiphonarius*, Solesmes, 1960, p. 68.
- **Mode**: attested as Mode I (Dorian family) by [AllMusic](https://www.allmusic.com/composition/salve-regina-antiphon-in-mode-1-mc0002410123) and [Classical Archives](https://www.classicalarchives.com/work/208551.html) for the standard antiphon; the "solemn tone" setting is separately sung in Mode V (Lydian family) — both traditions exist and are documented, so treat mode as a choice depending on which historical setting is used.
- **GABC incipit** ("Salve Regina, mater misericordiae"): `(c4) SAl(hhgh)ve,(d.) *(,) Re(hg)gí(fe//fgf)na,(e[ll:1]d..) (;) ma(c)ter(d) mi(dc)se(d)ri(ef)có(g)rdi(dec)ae`
- **Captured note sequence** (letters only, GABC h=A, i=B): **A A G A D | A G F E F G F E D | C D | D C D E F G D E C**
  (Sal-ve | Re-gí-na | ma-ter | mi-se-ri-cór-di-ae). Wide, arching, melismatic —
  contrasts with the terse syllabic Dies Irae incipit; good source for a lyrical
  "mercy/intercession" theme (e.g., a rest-point or safe-zone motif) rather than
  combat material.
- **PD status**: 11th-century antiphon (commonly attributed to Hermann of Reichenau),
  public domain; Solesmes engraving used only for the note sequence.

### 2d. Veni Creator Spiritus (Pentecost hymn) — secondary/bonus capture

- **GregoBase**: https://gregobase.selapa.net/chant.php?id=2923
- **Source cited on page**: *Graduale Romanum*, Solesmes, 1961, p. 150.
- **Mode**: most sources describe Mode VIII (Hypomixolydian); Sarum-tradition
  sources give Mode VII (Mixolydian) for a variant setting — both are the
  Mixolydian-family (final G) per the mode table above.
- **GABC incipit** ("Veni Creator Spiritus"): `(c3) VE(e[...])ni(f) Cre(e[ll:1]d)á(e)tor(fe) Spí(h')ri(i)tus,(h.)`
- **Captured note sequence** (h=A, i=B): **E F E D E F E | A B A**
  (Ve-ni Cre-á-tor | Spí-ri-tus). Recorded here as a spare/reserve motif; not
  analyzed further since the director asked for 2-3 chants and Dies Irae /
  Victimae Paschali Laudes / Salve Regina already cover the judgment, triumph, and
  mercy registers.

---

## 3. Catholic polyphony reference points (orientation only, not full analysis)

- **Giovanni Pierluigi da Palestrina** (c. 1525–1594): stepwise melodic motion in
  each voice producing smooth arch-shaped contours; dissonance tightly controlled
  (prepared and resolved) so the counterpoint resolves to full triadic sonorities on
  strong beats. This "Palestrina style" was later codified as the model of strict
  16th-century counterpoint (Fux's *Gradus ad Parnassum*). Reference:
  [Palestrina — Wikipedia](https://en.wikipedia.org/wiki/Giovanni_Pierluigi_da_Palestrina), [Palestrina style — ars-nova.com](https://www.ars-nova.com/cpmanual/palestrina.htm).
- **Tomás Luis de Victoria** (c. 1548–1611): trained partly in Rome, influenced by
  Palestrina, but freer — prefers simpler, more homophonic textures over dense
  imitative counterpoint, seeks rhythmic variety and occasional dramatic/expressive
  dissonance (e.g. unconventional intervals such as ascending major sixths) not
  found in strict Palestrina practice. Reused his own material via parody technique.
  Reference: [Tomás Luis de Victoria — Wikipedia](https://en.wikipedia.org/wiki/Tom%C3%A1s_Luis_de_Victoria), [Britannica: Tomás Luis de Victoria](https://www.britannica.com/biography/Tomas-Luis-de-Victoria).
- Both are useful as **stylistic reference points** for how to harmonize/extend a
  chant-derived cantus firmus polyphonically (smooth stepwise voice-leading,
  controlled dissonance) if the score ever layers vocal-style pads under the metal
  instrumentation — not melodic *source material* themselves (no specific melodic
  incipits captured from either composer for this pass; the chant melodies above
  are the primary note-data source).

---

## 4. Catholic vs. Protestant liturgical music — the actual distinction

This is a real historical/musicological distinction, not an invented one:

- **Gregorian chant** is the plainchant repertory that developed within the Roman
  Catholic liturgy from roughly the 8th–10th centuries onward (codified under/named
  for Pope Gregory I, though the historical attribution is legendary), used for the
  Mass Proper/Ordinary and Divine Office. It **predates the Reformation by
  600+ years** and has remained the Roman Catholic Church's own liturgical chant
  tradition continuously since. The Second Vatican Council's implementing
  instruction **Musicam Sacram** (1967) explicitly reaffirms this status: "Gregorian
  chant, as proper to the Roman liturgy, should be given pride of place, other
  things being equal" (§50a). Source: [Musicam Sacram, full text — vatican.va](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_instr_19670305_musicam-sacram_en.html).
- **Renaissance Catholic polyphony** (Palestrina, Victoria, Lassus, etc.) is
  liturgical music written *for the Latin Mass* under Counter-Reformation
  discipline (the Council of Trent's concern that polyphony not obscure the sacred
  text), and it is built directly on top of chant material (paraphrase/parody Mass
  technique routinely uses a chant cantus firmus). It is continuous with, not a
  break from, the chant tradition.
- **Lutheran chorale** melodies are a distinct **Reformation-era, vernacular,
  congregational-singing** tradition initiated by Martin Luther in the 1520s —
  German-language strophic hymn tunes meant for the whole congregation to sing
  together in the vernacular, a deliberate departure from Latin plainchant and
  clerical/choral exclusivity. Source: [Lutheran chorale — Grokipedia](https://grokipedia.com/page/Lutheran_chorale).
- **Genevan Psalter** (1539–1562, Calvin/Beza/Bourgeois/Goudimel) is an even more
  restrictive Reformed tradition: metrical, rhymed vernacular translations of the
  biblical Psalms only (no freely composed hymn texts), sung unaccompanied by the
  congregation — a Calvinist doctrinal position (*sola scriptura* applied to sung
  text) that has no equivalent in Catholic liturgical practice. Source:
  [Genevan Psalter — Wikipedia](https://en.wikipedia.org/wiki/Genevan_Psalter), [A Reformed Approach to Psalmody — Calvin Institute of Christian Worship](https://worship.calvin.edu/resources/articles/reformed-approach-psalmody-legacy-genevan-psalter).
- **Gospel hymnody** is a later (19th–20th century, largely Anglo-American
  revivalist/Protestant) tradition entirely outside Catholic liturgical history.

**Bottom line**: chant + Catholic Renaissance polyphony are excluded from and
historically prior to the vernacular-congregational-hymnody tradition the
Reformation created; the two repertoires diverge doctrinally (Latin/clerical vs.
vernacular/congregational, free composition vs. psalms-only in the Genevan case)
and chronologically (pre-Reformation vs. Reformation-era), and the Catholic Church's
own governing document for liturgical music (Musicam Sacram) singles out Gregorian
chant, not chorale, as "proper to the Roman liturgy." This is why Dorian/Phrygian
chant modes and the Dies Irae/Victimae Paschali Laudes/Salve Regina melodies above
are in-lane for this game's Catholic-register score and Lutheran chorales or
Genevan Psalter tunes are not, regardless of superficial modal similarity.

---

## 5. Licensing / PD summary

Everything captured above is **note-name/scale-degree text data only** — no audio
files, no copyrighted score images, no PDF/engraving reproduction. Per-item status:

| Item | Composition date/status | PD basis |
|---|---|---|
| Dorian/Phrygian/Lydian/Mixolydian mode definitions | Medieval theoretical framework, codified centuries ago | Music theory / facts, not copyrightable |
| Dies Irae melody | 13th c., traditional/anonymous | Public domain (composition); note sequence extracted as documented fact from a 1961 Solesmes engraving, not the engraving itself |
| Victimae Paschali Laudes melody | c. 1040, Wipo of Burgundy | Public domain (composition); same extraction-as-fact basis |
| Salve Regina melody | 11th c., traditional (attrib. Hermann of Reichenau) | Public domain (composition); same extraction-as-fact basis |
| Veni Creator Spiritus melody | c. 9th–10th c. (attrib. Rabanus Maurus for text; melody from c. 1000, Kempten Abbey tradition) | Public domain (composition); same extraction-as-fact basis |

No audio was downloaded or referenced for reuse; YouTube/Spotify links surfaced
during research are cited only as corroborating documentation of mode/attribution,
not as asset sources.
