# logicxkit.logic — build Logic channel strips from JSON

A small, self-contained tool that builds Logic Pro **channel strip settings**
(`.cst`) for Logic's *native* **Channel EQ** and **Compressor** from a
human-readable JSON spec — and decodes existing strips back into that JSON.

`config/example-strips.json` is the neutral shape of that spec.

## Why it's template-based (and what it can't do)

A `.cst` is a proprietary binary file. Three layers:

1. **Binary header** (`OCuA` magic) — fader, pan, I/O bus, channel name. Not documented.
2. **Plugin-slot table** — which plugins load in which slots. Not documented.
3. **Plugin state** — for Logic native plugins, stored in `GAMETSPP` float blocks. **This is what we
   read/write.**

You **cannot** synthesise layers 1–2 from nothing without serious reverse
engineering. So this tool never builds a strip from scratch. Instead you point
it at a **template** `.cst` that already has the plugin chain you want (made
once, by hand, in Logic), and it clones the template and rewrites the EQ and
Compressor float blocks. The chain, routing, and fader come from the template;
only EQ/Comp *values* are yours to set.

### Support matrix

| Plugin | Status |
|---|---|
| Channel EQ | ✅ full — 8 bands + master gain. Verified against factory presets + round-trip. |
| Compressor | ✅ full — threshold…auto-release, all 9 circuit models. Verified. |
| Enveloper | ⚠️ **pass-through only** — copied untouched from the template. Its byte layout isn't reliably verifiable from factory presets (they store relative/empty deltas), so it is deliberately not parameterised. Set it by hand in the template. |
| Everything else | left exactly as the template has it. |

## The `GAMETSPP` format (reference)

```
offset  bytes  meaning
-12       4    uint32 LE — total chunk size (== 24 + n*4, plus any trailer)
 -8       4    uint32 LE — version (always 1)
 -4       4    uint32 LE — n_floats          <- the real parameter count
  0       8    "GAMETSPP" tag
  8       4    uint32 LE — plugin TYPE ID    <- NOT a size
 12       …    little-endian float32 array (the parameters)
```

⚠️ The word after the tag is a **plugin type id**, not a byte size: Channel EQ 236,
Compressor 154, Enveloper 157, Gain 183, Adaptive Limiter 193, Limiter 199. Deriving the
float count from it over-reports every block (a 13-float Limiter reads as 49) and runs past
the chunk into the next slot. Use the count at `-4`.

Plugin identity is read from the ASCII plugin name that precedes the chunk — the last
meaningful token before the 12-byte pre-header. Whole-token matching matters: a substring
test makes `Gain` match `Auto Gain`.

**Channel EQ** — 8 bands × 4 floats, then `float[32]` = master gain (dB).
Band order: `hpf, low_shelf, peak1, peak2, peak3, peak4, high_shelf, lpf`.
Each band is `[Q, enable, freq_Hz, gain_dB]`; for `hpf`/`lpf` the 4th float is
the filter **slope** and `enable` toggles the filter.
The block holds 52 floats from class v3 on; a class v2 strip holds 51, the same layout without
the trailing float (a v2 strip aligned against v3 and v5 blocks agrees at every index 0–50).
`chains` copies a v2 source's 51 floats positionally and keeps the donor's last one, reporting
it as an older layout, not a mismatch.

**Compressor** — `float[1]`=threshold dB, `[2]`=ratio, `[3]`=attack ms,
`[4]`=release ms, `[5]`=makeup gain dB, `[6]`=knee, `[7]`=peak/RMS,
`[8]`=auto-gain, `[9]`=output distortion, `[10]`=circuit type,
`[11]`=limiter threshold, `[12]`=limiter, `[13]`=auto-release.
Circuit types: `Platinum 0, ClassicVCA 1, VintageVCA 2, VintageFET 3,
VintageOpto 4, FET 5, StudioFET 6, StudioVCA 7, StudioOpto 8`.

### The output plug-ins — Linear Phase EQ, Multipressor, Adaptive Limiter, Limiter (measured 2026-09-16)

Type ids 243, 194, 193, 199; class v5 blocks of 52, 62, 10 and 13 floats at payload offset 184
(`master-*` goldens). Inserted on the Stereo Out they take the same records as on a track — the
two differ only in the mono/stereo fields and the per-instance id — and the Stereo Out's Linear
Phase EQ and Limiter inserts also wrote two records of the `Inst 1` channel (owner 8; not
understood). The plug-in whose window was edited last holds an expanded record (468 → 708 bytes
for the EQ) carrying a second copy of its block; it shrinks back when another plug-in is edited.

Measured float indices, one slider step per save (`services/mixer/output_params.py`):

| plug-in | index | parameter |
|---|---|---|
| Linear Phase EQ | 1 | Low Cut on/off; bands of four `[enable, freq_hz, gain_db, q]` from index 1 in the Channel EQ band order |
| | 18, 19, 20 | Peak 3 frequency (Hz), gain (dB), Q |
| Multipressor | 25 | Band 2 crossover 1/2 (Hz) |
| | 41, 42, 43 | Band 1 compressor threshold (dB), ratio, make-up (dB) |
| Adaptive Limiter | 2, 3, 5, 6 | Gain (dB), Out Ceiling (dB), Lookahead (ms), Remove DC (1/0) |
| Limiter | 1, 2, 4, 5 | Gain (dB), Lookahead (ms), Release (ms), Output Level (dB) |

The plug-in window's Controls view lists every parameter in the plug-in's own order; the float
order is not that order one for one ("Parameter tables from the Controls view", below).

### Gotchas learned from reading real strips

1. **Double blocks.** When Logic re-saves a strip, each EQ/Compressor slot is
   written as **two consecutive GAMETSPP blocks** of identical size, not one.
   The user-parameter floats are identical in both copies; they differ only in
   ~3 trailing internal floats (instance/meter state). The copy reads as
   `Unknown` because its plugin-name label sits outside `identify_plugin`'s
   220-byte window. **`build_strip` handles this**: it patches the identified
   block *and* every immediately-following same-size copy (writing only the
   user-param region, so each copy's trailing internal floats survive). Without
   this you get the classic "my edits didn't take / every strip sounds the same"
   symptom — Logic loads the stale copy. The slot writers do the same through
   `insert.state_blocks` (`add-plugin --set`, `chains`, the float overrides),
   and `project` reports the copy as part of its block, not as another plug-in.
   Projects carry the pairs too: across the real saves on hand most are equal in the user
   region and a few differ.
2. **Donor routing comes along.** The un-patched header layer carries the
   donor's fader, pan, output bus, and sends — cloning a whole `template` strip
   applies those too, not just the plugins (a strip cloned from `OH L.cst`
   routes to the Cym bus). **Fix: use `graft`** (below) to take routing from the
   real target channel and only the *chain* from the donor.
3. **AU/3rd-party state doesn't decode here — use `logicxkit au`.** FabFilter,
   iZotope, sonible, etc. store their state as an AU ClassInfo blob, not a
   GAMETSPP float array; this module recovers **plugin identity, chain position,
   and preset name** only. **Neural DSP** decodes via the `neural` command
   (below); for everything else `logicxkit au strip <file>` loads the embedded
   state into the installed AU headless and dumps real named values — see
   `src/logicxkit/au/README.md`.

## Applying plugins to a project — the format reference

Everything needed to add a working plugin to a Logic channel. Each rule below is what a real
Logic-written file does, and several are counter-intuitive.

**Where the measurements come from.** Every offset, count, flag and dated confirmation below was
measured against *controlled saves*: one project saved repeatedly in Logic with a single
deliberate change per save, so a diff between two consecutive saves isolates the bytes that
change. Those saves are Logic-authored project files and are not redistributable, so they are
not part of this repository — `resources/README.md` describes how the set is laid out and named
if you want to build your own.

### The record container

`.cst` and `ProjectData` share one grammar: a flat stream of self-describing records.

```
+0   4  tag            stored REVERSED — the channel tag's bytes are OCuA, and it READS "AuCO"
+4   2  class version  bumps when Logic upgrades the file (see "File formats" below)
+14  2  owner          which channel this record belongs to
+18  2  key            the record's role within that channel
+28  4  payload size   next record starts at pos + 36 + size
```

A `.cst` starts with the channel record at offset 0. `ProjectData` has a **24-byte file header**
first, and a total at **0x10 == filesize - 24** that must be rewritten after any length change.
There is no offset table, record count or checksum anywhere, which is what makes writing into
a project possible at all.

#### File formats

The file header starts `23 47 c0 ab`, and its u16 at **+4** names the format. Record classes
move with it (every file on hand, 2026-09-29; the classes are each record's own `+4`):

| header word | saved by | `ivnE` | `OCuA` | `UCuA` | `karT` | `gnoS` | `gRuA` |
|---|---|---|---|---|---|---|---|
| 2513 | Logic 12.3.1 | 12 | 7 | 5 | 6 | 8 | 3 |
| 2512 | an earlier Logic 12 | 12 | 7 | 5 | 6 | 6 | 3 |
| 2511 | Logic 11.2 | 12 | 6 | 4 | 5 | 6 | 2 |
| 2509, 2510 | before 11.2 | 11 | 6 | 2, 3 | 5 | 5, 6 | 2 |

Logic 12.4 (6707) writes 2513 too, with the same classes (`names-non-ascii-logic`, 2026-09-30;
it holds no `gRuA`). It re-saved each of the 61 public copies the writers made (2026-10-01): each
has the record list of Logic 12.3.1's re-save, tag for tag, and holds that re-save's goldens
(in the public corpus as `<key>-12-4`, `tests/goldens/test_logic_12_4.py`).
Where the two differ outside the per-save ids and stamps, 12.4 kept what was written: an
un-named instrument track keeps its object name (`Inst 1`) where 12.3.1 wrote the preset's
(`Untitled`, with `Untitled.aupreset` at the instrument slot's `+14`). An audio file skipped as
missing on load comes back with one byte of its `lFuA` record cleared; with the file in place
the record is ours byte for byte.

Every offset in this document is measured on 2513, and the writers take nothing else
(`retrack.stale_alternatives`, before a project is copied: an alternative of an earlier format is
left as it is when a current one sits beside it, as Logic keeps such bundles; a bundle with no
current alternative is refused). A Logic 11.2 project
(2511) reads — its object types and channel trailer are below — and no writer takes it: its
instrument channels sit sparse at fixed owners (the count record says 256; one song holds
`Inst 1`–`8` and `Inst 256`), and an instrument add's insert-and-shift, measured on Logic 12's
dense block, moved `Inst 8` to `Inst 9` there. Logic 12.4's save of that copy kept the new
track and left the moved one without a channel; its own conversion of the song keeps it
(`logic-11-2-inst-logic`, 2026-10-01).

Keys: **0-2 sends**, then the **plugin slots** from the project's slot base — 2 with up to one send
anywhere in the project, 3 with two, 4 with three (Logic re-keys every channel when a send pushes
it, and each channel record carries the base at +28; measured 2026-09-12) — and higher keys
per-channel properties (the `.cst` reference sits at a key that moves with the Logic build — 9, 10,
12 and 13 all occur, so never hardcode it). Gaps are normal; Logic writes sparse keys itself.

### The parameter chunk

```
-12  4  total size (== 24 + n*4, plus any trailer)
 -8  4  version (1)
 -4  4  n_floats          <- the REAL parameter count
  0  8  "GAMETSPP"
 +8  4  plugin TYPE ID    <- NOT a size
+12  …  float32 * n
```

⚠️ The word after the tag is a **type id**, not a byte size. Deriving a count from it
over-reports every block (a 13-float Limiter reads as 49) and runs past the chunk.

| id | plugin | | id | plugin |
|---|---|---|---|---|
| 147 | Tape Delay | | 199 | Limiter |
| 154 | Compressor | | 236 | Channel EQ |
| 157 | Enveloper | | 287 | ChromaVerb |
| 179 | Noise Gate | | 320 | Mastering Assistant |
| 183 | Gain | | 248 | Delay Designer |

### Mono vs stereo — seven fields, not one

A plugin instance carries its **own** width; Logic does not derive it from the channel, and its
own files contain channel/slot disagreements. Cloning a mono donor onto a stereo bus gives a
mono plugin on a stereo path.

- **Channel** width: `OCuA` payload **+123** — a literal channel count (1 mono, 2 stereo).
- **Slot** width: `+84`, `+118`, `+119` channel counts · `+81` a per-plugin **config index** ·
  `+116..117` the **plugin-variant id**, selecting the mono or stereo *build* · `+156` (`+157`)
  one byte per input bus, main then side chain.

Rebase the variant id rather than incrementing it: `new = old - old_cfg + new_cfg`. The config index
is **not** always the channel count — Gain's stereo index is 3, as are SilverVerb's, EnVerb's, Delay
Designer's, ChromaVerb's, Stereo Delay's, Sample Delay's, AutoFilter's and the Modulation group's;
Space Designer's is 9 and Quantec Room Simulator's 10. Fuzz-Wah, Spectral Gate and Rotor Cabinet
have one build: on a mono channel Logic inserts them Mono → Stereo and writes the stereo record
(counts 2, index 2), so `set_slot_format` leaves a `PLUGIN_CFG` entry with equal indices alone. The
channel record's width byte is then the chain's output: Logic's re-save of a mono strip given a
Fuzz-Wah wrote it stereo, the mono builds before it unchanged (`addplugin-fuzzwah-mono-*`), so a
channel carrying a one-build plug-in is not width-judged. EVOC 20 Filterbank's mono record counts
read 2, 1, 2 (`+84`, `+118`, `+119`). Leave `+82`/`+83` (bus counts) alone, and only follow `+157`
to `+156` when the two already agreed, or you destroy a legitimately mono side chain on a stereo
compressor.

`logic width PROJECT` prints every channel's width; `--out DIR --stereo 'Aux 13' --mono 'Aux 1'`
writes a copy through `widen_channels`, which moves the channel's three width bytes and
re-stamps each slot on it. **Confirmed 2026-09-08:** two drum-MIDI auxes made stereo on both
templates came back from Logic's re-save with the channels and their slots still stereo.

### Side chains

The source a plug-in's Side Chain menu selects is two bytes of its own slot record: payload
`+144` the kind — 0 with none set, `0x40` an audio channel, `0x41` an input, `0x45` a bus — and
`+145` the channel's zero-based number. A Compressor on Audio 2 pointed at Bus 1, Bus 2 and
Audio 1, one save each, changed that word and nothing else in the project (the `sidechain-*`
goldens, 2026-09-22); a Noise Gate and Pro-C 2 pointed at Bus 1 carry the same word at the same
place, so it is Logic's, not the plug-in's. Over the owner's mixes the slots read as audio
channels and buses that way, and one as an input. The word names the channel by number, so
`sidechain.carry` moves a slot between projects by its source's *name* — the bound track's or
aux return's, else the mixer label — and clears it, reported, when the destination has no such
channel. A Noise Gate written with `add-plugin --side-chain 'Bus 2'` opened in Logic with Bus 2 in
its header and re-saved as written (`sidechain-ours-resave-logic`). The menu showed the two
buses as "Bus 1 (Drums)" and "Bus 2 (Cymbals)"; the file holds
no such names (its aux returns are unnamed `Aux 1`/`Aux 2`), so the tools name a bus by the aux
track it feeds or fall back to `Bus N`.

### Settings across plug-ins

A family's vocabulary (`services/translate.VOCABULARY`: a compressor's threshold dB, ratio,
attack ms, release ms, knee dB, make-up dB, mix %, auto release, auto gain, look-ahead ms, input
and output gain dB) and one map per plug-in under `data/translate/` say how each plug-in stores
each item. Pro-C 2 keeps threshold, knee and side-chain level in dB as stored, its gains at 36 dB
per unit with -1 silent, mix x100, and ratio, attack and release normalized on curves — sampled
through the AU host at 41 points each (2026-09-22): ratio 0.6 is 4:1, attack 0.4 is 16 ms,
release 0.4 is 198 ms. Logic's Compressor is its measured table; its knee runs 0..1 with no dB
scale, so a knee crosses as dB/72 and the report says approximate. A -> B goes through the
vocabulary; what B lacks is reported, never guessed. Logic keeps a Compressor's values on grids
— threshold, make-up and the gains in 0.5 dB, ratio and knee in 0.1, mix in 0.5 % — and rounds
a written value to them on load (a 3.06:1 / 2.999 dB / 0.083 knee came back 3.1 / 3.0 / 0.1,
`translate-ours-resave-logic`), so the map rounds first. Attack and release, and the Noise
Gate's attack, hold and release, sit on their knobs' own positions rather than a uniform grid
(10.72 ms came back 10.5 and 40 came back 41; 115 ms came back 110 and 400 back 390; a gate
release of 350 came back 351), so those are written as read and Logic settles them on load;
measuring each knob's positions would make the write exact.

sonible's smart:gate and smart:comp 2 keep their values in the `jucePluginState` protobuf's
message 3, in real units — dB, ms, Hz, % — one field per parameter; the AU state's id/value
pairs beside it never change and are not read. Matched to Logic's Controls view row by row after
every slider moved 500 units (`sonible-*`, 2026-09-22: 42 of 45 changed fields on smart:comp 2
and 16 of 18 on smart:gate by value). smart:comp 2's two stages sit 16 fields apart (Threshold 1
at 3.17, Threshold 2 at 3.33; the ratios 3.12 and 3.28 are the pair left, placed by that
layout); only stage 1 crosses to a Compressor. smart:gate's threshold and tolerance are
percentages against its learned profile, so only its attack, hold and release cross to a Noise
Gate, and the report says why the rest do not.

iZotope's Neutron 5 keeps its state as a 16-byte header (magic `0x0080fb83`, a version, the
packed and the plain length) over zlib-compressed JSON of typed values
(`au/services/izotope`), every parameter in real units under
`DSP State/Value/DSP Elements/Value/<Module>/Value/<Parameter>`. It carries three families, so
it has three maps (`iZtp_ZNN5-compressor`, `-gate`, `-eq`) and `settings` prints a line per
family: a Dynamics element's band 0 (threshold dB, ratio, attack and release ms, knee, gain,
mix %), the first of the two not bypassed, with a note when both are, and then the native a
`replace-plugin --translate` makes from it goes in bypassed; the Gate Expander's band
0 (threshold — its Open — attack and release in ms, hold in seconds, hysteresis — its Close — a
positive amount where the vocabulary's is negative); the Dynamic EQ's twelve bands, a band's
Enable its existence, a band with its dynamics on flagged and its static curve crossed. Its
thirteen shapes, in the popup's order, cross as bells (Proportional Q, Bell, Band Shelf), low
shelves (Analog, Baxandall, Vintage), high shelves (the same three), high cuts (Flat and
Resonant Lowpass) and low cuts (Flat and Resonant Highpass). Its ratio expander, its punch,
its side-chain filters and bands 1 and 2 stay its own; the state is read, not written.
Logic-confirmed 2026-09-23 (`neutron-*`): a fresh instance's Controls view dialled — the C1
rows are Dynamics 0, the G1 rows the Gate Expander, EQ Main B1-B3 the Dynamic EQ — read back
as dialled through the three maps, and each family carried into a Compressor, a Noise Gate
and a Channel EQ, Logic showing the plans.

An EQ crosses as bands. Pro-Q 4 keeps its state in `FabFilterPluginState`, the `.ffp` layout
(`FFBS`, a version, 600 values by parameter id, then a trailer with the preset name): a band is
23 values from id 23(n-1) — Used, Enabled, frequency as log2 Hz, gain in dB, Q normalized on a
log curve (0.025 at 0, 1.0 at 0.5, 40 at 1), shape (Bell, Low Shelf, Low Cut, High Shelf, High
Cut, Notch, Band Pass, Tilt Shelf, Flat Tilt, All Pass), slope (0..96 dB/oct, brickwall), stereo
placement, the dynamics — read off the AU host, 2026-09-22. Channel EQ has one slot per shape
(Low Cut, Low Shelf, Peak 1-4, High Shelf, High Cut) in its measured table, so a Pro-Q 4's bands
land by shape, bells by rising frequency, and a fifth bell, a notch or a tilt is reported; the
cut slopes and the dynamics are not carried, and a shelf's or cut's Q is marked approximate
between two filter designs. Logic-confirmed 2026-09-22 (`translate-proq-*`): nine bands dialled
on a Pro-Q 4 read as its window showed them, and the Channel EQ written from them came back
from Logic's re-save with every float as written but the frequencies and one Q, which sit on
its knobs' own positions (250.01 Hz to 250, Q 2.43 to 2.50); gains step 0.1 dB.

**Writing a FabFilter state** (`services/translate/translate_write`, `au/services/austate_write`):
the record's XML plist holds the state as base64 `<data>` elements (wrapped at 68 characters, a
tab per line), so a value is patched into the decoded blob — a pair's float32 by id for Pro-C 2
and Pro-MB, a float32 LE by id in the FFBS blob for Pro-Q 4 — and the blob re-encoded into the
same span, base64 characters replaced in place and the whitespace kept; the record, the XML
length word in front of it (u32 LE at xml − 4, the text plus its newline) and every field after
it stay as Logic wrote them. A map item's `min`/`max` clamps a write with a note, and one of
Logic's own is held to its measured slider's ends the same way. Logic-confirmed
2026-09-23 (`write-*`): three items written into a Pro-C 2 in place, and a Compressor carried
into a Pro-C 2, came back from Logic's re-save shown as written; a normalized curve item
(attack, release) lands between the sampled points (10.5 ms shown as 10.49, 110 as 109.8). A
Channel EQ's seven live slots went into a Pro-Q 4's first seven bands (the off low shelf left
out, its cuts at 12 dB/oct for want of the table's slope), band 8 Unused, every value shown as
written; a band without a slope of its own gets 12 dB/oct — `None` in the slope list means
brickwall.

A multiband compressor crosses as bands by frequency range (`services/translate/translate_mb`).
Pro-MB's state is 151 id/value pairs: a band is 22 from id 22(n-1) — state (0 disabled, 1 enabled,
2 unused), low and high crossover as log2 Hz (4.907 = 30 Hz, 14.873 = 30 kHz), slopes, dynamics
mode (0 compress, 1 expand), threshold normalized on a sampled curve (-90 dB at 0, -48 at 0.2,
0 at 1), range ±30 dB (the limit on the gain change; negative is downward), ratio normalized
(1:1 at 0, 4:1 at 0.6, 100:1 at 1), attack and release as percentages of a program-dependent
time, knee dB, lookahead ms, level dB — read off the AU host, 2026-09-23; mix ×100, input and
output level 36 dB per unit with -1 silent. Multipressor holds four bands between three
crossovers in its measured table, each a compressor and a downward expander, `Band N Monitor`
its on/off. Across the two the spectrum is segmented into at most the target's count of bands
(a stretch no band covers is a band turned off, a stretch under two thirds of an octave joins
its neighbour, past the count the narrowest merges with a note); Pro-MB's expand mode lands in
the expander, its range and percentage times are reported, and the other way a band's expander
beside its compressor is reported and Pro-MB's range set to its widest (-30 dB). Logic-confirmed
2026-09-23 (`mb-*`): three bands dialled on a Pro-MB read as its window showed; the Multipressor
written from them came back with thresholds, make-up, lookahead, output and the off band as
written and its ratios and top crossover on its knobs' positions (4.0 shown as 3.675, 4000 Hz as
3900 — where the writer now puts them itself, `slider.snap`); that re-save carried back into a
Pro-MB read as written, its crossovers from 30 Hz.

### Per-instance ids — measure, never assume

Two instances of the same plugin differ in a few trailer bytes carrying a per-instance id.
**Their absolute position is plugin-specific**: Channel EQ (432 B payload) uses 414, 415,
420-427, while Enveloper (248 B) uses 228-231, 236-243. Applying one plugin's offsets to another
overwrites live parameter data — that is what makes a project fail to open.

Counted from the payload's end they share one window: the last 20 bytes but the final four.
Across every Logic-written `ProjectData` under `resources/` and `in/` (2026-09-21), the pairs
of same-plugin, same-length instances that agree everywhere else differ only at −20..−5, never
in the last four — Channel EQ, Compressor, Enveloper, Gain, Auto-Align 2, Neural DSP, FabFilter
and Waves among them. Other pairs are identical outright, so Logic itself sometimes saves
two instances with one id. The window is **not** always an id: a quarter of all slots carry
zeros or parameter floats there, which is why the bytes are still measured, not assumed.

`instance_offsets()` derives them by diffing real instances of that exact plugin; with fewer
than two available it returns nothing and the clone is copied verbatim. `transplant.id_offsets`
diffs only inside the window, so two instances saved with different settings are not mistaken
for an id; `transplant` uses it only when one source is fanned out onto several channels. A
one-to-one move copies the id with the slot, which is what apply-template's chains op relies
on to converge and what Logic re-saved byte for byte.

### The slot key range grows with the longest chain (every save under `tests/corpus` and `resources/experiments`, 2026-09-21)

One key layout serves every channel of a project: sends from 0, slots from the base, then
**two keys** that hold the non-slot satellites (the 200-byte recording record at reference −2
or −1, the 68-byte aux record at −1), the `.cst` reference, an empty key, and the two
keyed-archive records at reference +2 and +3 (`slots.archive_index`). In the blank-born
public saves, which carry no reference, the archives sit at base + highest slot index + 5 and
+6 on every save (the reference's place, highest key + 3); Logic's own appends on
Audio 1 (`master-track-*`) moved the archives of every channel up one key per plug-in. The
headroom depends on the project's origin — the owner's base-4 sessions put the reference at
highest key + 6, base-2 sessions with references at + 5 — and **Logic sets it on every
save**: its re-save of a fan-out that shortened every chain moved the references from 13 to
11 (`transplant-fanout-logic`), and its re-save of a copy left at 10 moved them to 13 with no
chain change (`songb-drums-to-midi-logic`). That re-layout drops what lands past the channel
records' flag words: a write that grew a base-4 session by three keys instead of its six came
back with every channel's second archive gone (2026-09-21). So a writer grows the
range to the project's own headroom, measured from the input: `add_plugin.headroom` and
`grow_range` move everything from reference −2 up by the deficit, and `property_key_base`
reads the reference's place from the archive pair when no channel names a strip, or from one
archive alone: a new instrument channel carries only its second (`tracks-instrument-logic`,
`addtrack-inst-stereo-logic`), which Logic's own New Software Instrument Track keyed at slot
base + shown slots + 4 at four layouts (`addtrack-inst-shown-{3,4,5}-logic`,
`addtrack-inst-base-3-logic`). With no archive either, the place is **slot base + shown slots
+ 1** (channel record `+28` and `+30`): 340 of the public corpus's 340 Logic saves that carry
an archive and no record at that key fit it (2026-10-03). The saves that do not are this tool's own writes,
which Logic re-lays on its next save (an archive written at 13 came back at 8,
`addtrack-inst-stereo-*`), and projects with a reference at the base, a strip's or a loaded
patch's (192 bytes: `patch-built-loaded-logic`, the Session Player saves, a project made from
a MIDI file), which keep one to three keys more.

**The two archives are the channel's Smart Controls**: the first an `NSMutableDictionary` of
knob number → `NSMutableArray` of `MAPlugInParameterMapping`, each naming the plug-in it
reads by **slot index** (`slot`) and parameter (`parameterIndex_1`); the second holds the
layout name (`contentTagLayoutName`). Payload `+16` is the bplist's size, the bplist from
`+20`, then a 16-byte tail. A plug-in moved to another slot without its mappings made Logic
reset the channel to an unused stub on load (2026-09-21); `smart_controls.shift_mapping_slots`
moves them with the slots, and Logic re-saved that archive byte for byte
(`addplugin-mid-logic`). A slot's payload `+76` u16 is a per-plug-in token Logic recomputes
on load (the same value for the same plug-in on two channels of one save; the owner's
library donor's stale value came back as 0, the packaged donor's unchanged). The other field
Logic may rewrite on a new slot is its preset label
at payload `+14`: a third-party donor saved with an empty label came back reading `Untitled`
on one re-save (`addplugin-front-logic`) and empty on another (`transplant-fanout-logic`).

**Channel record `+30`** is the number of insert slots the mixer shows — the longest chain
plus one empty slot, highest slot key − base + 2 — one value on every channel record of the
project, the 201-byte stubs included (5 on a tracked song whose longest chain is 4; 6, 7 and 9
on the `master-track-*` saves as Audio 1 grew to slot 5, 6 and 8). Logic recomputes it on
save too (5 → 3 on the shortened fan-out, a stale 2 → 5 on the drums-to-midi copy);
`add_plugin.show_slots` raises it to what the new chain needs, which is what makes the
reproduced append match Logic's channel record byte for byte. It is one of six u16 words every
channel record of a project carries alike — `+28` the slot base, `+30`, and `+34 +36 +38 +42`,
unnamed — on all 467 corpus saves and the owner's; Logic's re-save rewrote a fresh record that
disagreed (`addtrack-fresh-*`), so a fresh channel takes them from the project, not its template
(`channel_alloc.project_words`).

### Parameter tables from the Controls view (2026-09-22)

A plug-in window's Controls view lists every parameter in Logic's order — rows of label,
display value and slider — but the float block is not that list: the Compressor's 27 rows
hold popups with no slider (Peak/RMS, Circuit Type, Side Chain Detection), divider gaps, and
floats the rows skip, so "float = row + 1" holds only up to the first popup. What pins a
table is one save at defaults and one after **every** slider row was moved one unit (and
every checkbox pressed): each changed float then matches its row by value — 25 of 25 on the
Dynamics group, none left to order. The tables live in `data/logic/params-<type>.json`
(`services/mixer/plugin_params`); popup rows stay unmapped until measured another way, and a
parameter whose display is not its float (the Vintage Graphic EQ's bands, mostly) carries
`"evidence": "order"` — its row, not a value match, and only when one row and one float were
left (a wider leftover is a guess and stays unmapped). Repeated labels take their section
header or nearest `Band N` as a prefix. Measured so far (`stockfx-dynamics*`, `stockfx-eq-*`,
`stockfx-dr-*`): Compressor 14 of 27 rows, DeEsser 2 4/7, Expander 7/9, Adaptive Limiter 6/9,
Channel EQ 38/47, Linear Phase EQ 37/46, Single Band EQ 2/4, Vintage Console EQ 13/15,
Vintage Graphic EQ 14/16, Vintage Tube EQ 18/23, Multipressor 54/59, Enveloper 7/7, Tru-Tape
Delay 7/9, Delay Designer 5/28 (the taps are not in the float block), Space Designer 30/88
(nor are the envelope handles' displayed values), Echo 4/7, ChromaVerb 51/62, SilverVerb 12/12,
EnVerb 14/14, Tape Delay 13/21, Stereo Delay 12/31, Match EQ 9/24, Noise Gate 11/13
(`stockfx-dr2-*`), Quantec Room Simulator 10/21, Sample Delay 3/4 (`stockfx-dr3-*`; Logic's
own Sample Delay is type 259 and sits under Apple's AUSampleDelay in the menu's search),
Chorus 4/4, Ensemble 14/14, Flanger 5/5, Microphaser 3/4, Modulation Delay 15/18, Phaser
15/18, Ringshifter 20/30, Scanner Vibrato 4/5, Spreader 4/4, Tremolo 6/7 (`stockfx-mod-*`),
Bitcrusher 5/6, Clip Distortion 10/10, Distortion 4/4, Distortion II 6/7, Overdrive 4/4, Phase
Distortion 7/7, AutoFilter 23/30, EVOC 20 Filterbank 35/61, Fuzz-Wah 13/17, Spectral Gate
11/11, Rotor Cabinet 5/14 (`stockfx-dist-*`), Amp Designer 13/25, Bass Amp Designer 27/46,
Pedalboard 8/63 (its 2001 floats hold every pedal's parameters), Pitch Correction 7/36, Pitch
Shifter 4/8, Vocal Transformer 7/10, Exciter 3/4, SubBass 9/9 (`stockfx-amp-*`; Denoiser and
Speech Enhancer are no longer in Logic 12.3.1's menu), Direction Mixer 3/4, Stereo Spread 5/5,
Level Meter 1/8, Loudness Meter 1/7, MultiMeter 9/20, Tuner 2/4, Gain 2/6, Test Oscillator
7/13 (`stockfx-util-*`; BPM Counter and Correlation Meter have no slider to move, and Down
Mixer no row on an audio track). BPM Counter's never-opened mono record carries two parameter
blocks (440 B) against its stereo one's single block (316 B), so the library files both. The
multi-FX carry pattern data — Step FX 29019 floats, Remix FX 4102, Beat Breaker 452, Phat FX
245 — and one slider moves many of them, so their tables hold what matched by value: Beat
Breaker 14 of 174 rows, Step FX 49/276, Remix FX 7/54, Phat FX 16/76 (`stockfx-mfx-*`);
Binaural Post-Processing has no slider, and I/O's row the OCR never read. A save
made after a plug-in's window was opened and a parameter moved carries its record with a
second `GAMETSPP` block appended (the compare state), so the `-spots` and `-mono` saves' edited
records are longer than the `-defaults` save's.

Logic 12.4 saved each of those bundles again without opening a plug-in (`stockfx-*-12-4`,
2026-10-04): every slot keeps its length and its block type, so the tables' offsets hold. Bit
0x10 of a slot payload's `+151` is set while the plug-in's window has been open and cleared in
those saves. Past that byte seven plug-ins differ. Five values Logic restated: Pedalboard's
five macro values (0.001 to 0), ChromaVerb's Freeze (1 to 0) and Damping Low Shelf Ratio (1.01
to 1.0), Tuner's Reference (440.1 to 440.0) and Output Mute (1 to 0). Space Designer's `+198`
went from 3 to 5, and Remix FX, Beat Breaker and one third-party slot changed bytes no table
names. The Controls views were not read again under 12.4, so whether a restated value is 12.4's
slider grid or a reset on load is not known.

**A block type is not always one plug-in.** The word after `GAMETSPP` is shared by Tape Delay
and Echo (147), by Pedalboard and its Tru-Tape Delay stompbox (273) and by Phaser and
Microphaser (152); what tells them apart
is the slot's variant id at `+116`, a per-plug-in base plus the config index at `+81`. The
base is the same for the mono and stereo builds and, over 429 goldens, the same in every Logic
version that writes it (class v2/v3 records carry none). `slot_width.plugin_variant` reads it,
`plugin_names.PLUGIN_VARIANTS` names the shared types' members, a table names its `variant`
(`plugin_params.table_for`) and a donor of a shared type files as `<type>v<variant>-v<ver>`.
Bases seen: Chorus 94, Flanger 147 (type 146), Tape Delay 200, Echo 216, Stereo Delay 232,
SilverVerb 249, Phaser 283, Microphaser 336, Compressor 389, Fuzz-Wah 405, Expander 421,
Enveloper 437, Klopfgeist 453, Pitch Shifter 454, Ensemble 486, AutoFilter 517, Bitcrusher 534,
Distortion 550, Overdrive 566, EnVerb 582, Spectral Gate 615, Noise Gate 728, Modulation Delay
760, Direction Mixer 813, Gain 815, Tremolo 832, SubBass 885, Clip Distortion 905, Adaptive
Limiter 938, Multipressor 954, Phase Distortion 986, Exciter 1002, Stereo Spread 1018, Limiter
1020, EVOC 20 Filterbank 1074, Distortion II 1088, Scanner Vibrato 1104, Rotor Cabinet 1121,
Space Designer 1123, Pitch Correction 1173, Channel EQ 1189, Tuner 1208, MultiMeter 1222,
Correlation Meter 1231, BPM Counter 1232, Linear Phase EQ 1234, Match EQ 1266, Delay Designer
1310, Vocal Transformer 1348, Ringshifter 1380, Test Oscillator 1397, Level Meter 1415, Spreader
1444, Sample Delay 1461, Binaural Post-Processing 1590, Pedalboard 1623, Tru-Tape Delay 2050,
Amp Designer 2212, Vintage Tube EQ 2231, Vintage Graphic EQ 2247, Vintage Console EQ 2263,
ChromaVerb 2279, Phat FX 2296, Step FX 2313, DeEsser 2 2331, Bass Amp Designer 2349, Quantec
Room Simulator 2365, Beat Breaker 2419, Single Band EQ 2442, Remix FX 2466, Loudness Meter 2480.
The type's `PLUGIN_NAMES` entry marks the member that keeps the plain table and donor
keys; the others file by variant.

### Donor rules

A plug-in's mono and stereo records are the same length on every plug-in measured (eighteen,
`stockfx-*-defaults` against `-mono`, 2026-09-22): the width is in the fields above, and
re-stamping them is how a donor of one width goes onto a channel of the other (Logic has
accepted that for the Compressor, `chains`). The records that read longer were edited ones — a
save made after a plug-in's window was opened carries the record with a compare block
appended — which is why `bin/regen_data.py` harvests each group's never-opened strip only.
Should a plug-in's records ever differ in length by width, `harvest_donors` files a real
record per width (`<type>-stereo-v5`, `fixed_width` in the manifest) and `add-plugin` takes
the channel's.

Space Designer's record names its impulse response by path — twice, once beside a file
bookmark that carries the volume name — so the public saves and the donor cut from them have
that path replaced in place at the same length (`tools/stage_public.py`, counted under
`scrubbed` in the manifest); a strip given the donor loads with no IR until one is chosen.

A slot record can only be cloned into a project when:

1. **The class version matches.** Logic upgrades records on save — a project opened in a newer
   Logic rewrites `UCuA` v4 as v5 — so re-read the target before sourcing a donor.
2. **The width is set to the target channel's**, per above.
3. **The plugin type already exists somewhere reachable.** In-project donors are safest; plugins
   that appear in no session (Enveloper, Gain, ChromaVerb) are declared in the chain config and
   pulled from a saved `.cst`.

### Labels and provenance

Slot preset labels (`"<name>.pst"`) and a strip's self-identifying name/category (at `UCuA+52`,
two 64-byte fields) are null-padded fixed-width — rewritable in place with no length change. A
clone inherits the donor's, so both are re-stamped or the file misdescribes itself.

### Latency

Logic's Low Latency Monitoring mode works *by bypassing* plugins, so **a bypassed plugin sheds
its latency**. Hovering a plugin slot shows its exact latency in samples and ms. Watch for
lookahead: the Enveloper's is a real delay, and a dialled transient setting can carry tens of
milliseconds of it.

## `graft` — build a chain shape no saved strip has

A `.cst` is two independent layers: the **OCuA header** (routing — output bus, sends, fader,
channel identity) and the **slot region** (the plugin chain). Neither can be synthesised, but both
can be *transplanted*. Grafting takes a target channel's header and a donor's slots:

```
target_header[:seam] + donor[seam:]        seam = w7 + 0x24
```

Header words (uint32 LE): `w7` @0x1c = header length; `w10` @0x28 = channel number (high bytes)
plus a type flag in the low byte — **0x40 track · 0x42 bus · 0x43 instrument · 0x4C output**
(verified against every strip in the library; the folder is ground truth).

Confirmed in Logic — a grafted vox strip (vox header + overhead EQ→Comp slots) loaded and
re-serialised correctly.

**What a graft does and does not carry.** The header half gives the target's channel identity and
type. It does **not** give the target's *sends*: those are child records that live **after** the
seam, so a graft inherits the **donor's** sends. (`Vox - Lead.cst` carries three 44-byte send
records — Slapback/Plate/Hall — and a graft off an overhead donor has none of them.) Where sends
matter, either re-add them after loading, or skip the strip entirely and apply `.pst` plugin
settings to the existing channel (see below), which disturbs no routing at all.

Use it from a spec — a preset takes either a `template` or a `graft` pair:

```jsonc
"Vox Tracking": {
  "graft": { "routing_from": "…/Vocals/Vox - Lead.cst",   // keeps vox routing
             "chain_from":   "…/Drums/OH L.cst" },        // gives EQ -> Compressor
  "label": "Vox Tracking",                                 // else the donor's labels persist
  "eq":   { "hpf": {"freq": 90} },
  "comp": { "circuit": "VintageOpto", "threshold": -21, "ratio": 2, "attack": 18, "release": 120 }
}
```

`label` matters: slot preset labels (`"<name>.pst"`) live in fixed **67-byte null-padded fields**,
so they are rewritable in place — without it a grafted strip keeps the donor's names and shows up in
Logic as e.g. "Clean Up Snare" on a vocal.

`build` also re-stamps each strip's **provenance** record — the 64-byte name + 64-byte category at
`UCuA+52` that says which `.cst` this is. A clone or graft inherits the donor's, so without this the
built file claims to be its donor (and `diff --library` compares against the wrong strip).

## ⚠️ References are labels, not loaders

A channel's `.cst` reference sets what Logic shows on the **Setting** button. It does **not**
load the chain: Logic renders the plugin-slot records stored in the project, and a channel with
a reference but no slot records shows an empty Audio FX column. Verified against Logic's own
save-time `WindowImage.jpg`. Changing a chain means replacing the slot records (see the Surgery
Test note), not repointing the reference.

## The track list, stacks and channel levels

Three record types describe a project's tracks, and none is self-describing.

### `karT` — the track list

Runs are separated by zero-size marker records; the run holding `NumberOfTracks + 1` entries is
the **arrange list**, and a record's `key` is its display position. 58 bytes at Logic 12,
**57 at Logic 11**.

| offset | meaning |
|---|---|
| `+0` | u32 flags; `0x1` base, bit `0x04000000` = hidden, bit `0x20000000` = **track off** (the power button; switching one on in Logic cleared it and nothing else), bit `0x10000` on the selected row when it is an instrument |
| `+4` | u32, 0 on a fresh row; a word on rows inside some stacks — not the group, which never changes it |
| `+8` | object id in the Environment's space |
| `+14` | **1 = this row sits inside the stack above it**, 0 = header or top level. Holds on every row measured, including the Click and trigger-aux rows inside Drums MIDI that carry no stack index on their channel; a dragged-in track goes 0 -> 1 |
| `+24..39` | the row's own UUID |
| `+40` | bit `0x80` = expanded (stack headers, and every fresh top-level row; no member row); bit `0x20` = selected |
| `+43` | `0x40` on the selected row |

The second long run (76 rows here) is a flat list of every track object in mixer order — it
is not the arrange hierarchy.

### `ivnE` — the Environment objects

| offset | meaning |
|---|---|
| `+0` | channel-object type in the low 16 bits, the build's: **1800** at class 12 from Logic 12, **1760** at class 12 from Logic 11.2, **1728** at class 11; mixed projects set flag bits `0x4040` in the high half on some tracks (ten of 69 in one mix), so mask before comparing |
| `+16` | object id — what `karT+8` points at |
| `+24` | u32 **group bitmask** (bit N−1 = group N; 0 = none; a channel in groups 1 and 4 reads 9) — see Groups below |
| `+38` | u32 **parent**: the object id of the stack this track was dragged into (0 if never dragged). Ids reach 500, so all four bytes matter |
| `+45` | state: 0 on a fresh object, 1 after its first save, 3 after the next |
| `+80` | 1 on the selected object only |
| `+82` | u32 per-object stamp: a fresh object gets its pattern's plus the pattern's `+86` (64 or 66); a channel insert moves every object above the pattern's up by 66 |
| `+86` | u16, `0x42` on a fresh object (`0x40` on older ones) |
| `+154` | kind; **0** marks a grouping object — folder stacks, plus Logic's own Preview/Click/Master |
| `+158` | u16-length-prefixed name, immediately following, padded to an even length; UTF-8, the length in bytes (`names-non-ascii-logic`); written the same way, 1 to 127 bytes: Logic 12.4 kept names of 64, 96 and 127 bytes as written (`names-long-*`, 2026-10-02), and no longer one was tried |
| name end | u16 = the bound channel's owner + 1, kept live when owners shift; +3 on a stack object holds its Sub number |
| last 16 bytes | the object's instance **UUID** (v1, `94 c0 11 ef` in the middle) |

### Which channel an object is, and where it routes — `OCuA` tail

The channel record's payload length varies per session (257, 265, 269 bytes at one class
version), so these are addressed from the end. At class 7 (Logic 12):

| offset | meaning |
|---|---|
| `[len-48 : len-32]` | the bound Environment object's instance UUID — the link from a channel to its object |
| `[len-32 : len-16]` | the **output destination**: the UUID of the channel it feeds (drums -> `Bus 1`, guitars -> `Bus 5`, returns -> `Output 1-2`); all-zero on Sub/Master/Output strips |
| `[len-16 : len]` | the **input**: the UUID of the `Input N` channel record an audio track records from (Audio 1 and a fresh track on Input 1 both point at `Input 1`); zero on everything else |
| `+110` | the **Sub number of the stack** the channel sits in (drums 1, bass 2 … Drums MIDI 7), 0 otherwise |
| `+24, +25` | `01 01` once bound |
| `+60` | NUL-padded label with a leading space: ` Audio 1`, ` Sub 1`, ` Bus 15` |

Holds on every in-use channel of the sessions measured and the template. **Folder stacks bind to
the `Sub 1-7` strips**, which is where a stack's fader lives; the three kind-0 objects bound to
Aux strips (Room, Drum FX, Vox Verb) are input-less auxes, not stacks. `services/mixer/binding.py`.

A class-6 record as Logic 11.2 writes it is the class-7 record without its last 32 bytes: the
bound object's UUID is the last 16, and it carries no destination or input UUID. Every in-use
channel on two Logic 11.2 saves binds there, at payloads of 205 to 233 bytes; Logic 12's
re-save of the same song grew every channel record by 32. Writing a route there is refused:
`routing` and the track adds refuse such records, and the commands refuse the format before them.

A class-6 channel routes by index words, which a class-7 record keeps beside its UUIDs:

| offset | meaning |
|---|---|
| `+92` | u16 **output**: `0xFFFF` none; below half the device's input count the pair `Output 2w+1-2w+2`; from there `Bus w − half + 1` |
| `+94` | u16 **input**: `0xFFFF` none; on an audio channel `Input w+1`, or the pair starting there when `+86` is 1; on an aux `Bus w − base + 1`, where the base is half the device's input count when `+86` is 1 and the whole count when 0; a value past the 256 buses is another kind of source and is not read |
| `+86` | input format: 0 mono, 1 stereo |

The device's input count is the count record's `+36`. On the Logic 12 saves on hand the words
name what the UUIDs name — every output, every audio input, every aux fed by a bus — but for
backups that each caught one aux a save after its input turned stereo: `+86` read 1 and the
word still counted from the mono base (Bus 26 for Bus 10), and the next save rewrote it. A
writer here sets the words with the UUIDs (`route_words`, `stack_place`). Every audio track fed
by an input pair on those saves has `+86` at 1, and none with `+86` at 1 takes one input, so
`set_input` refuses either mix; the width writer sets `+86`. On two Logic 11.2
saves they name what Logic 12.4 bound by UUID when it converted each, every in-use channel
(`logic-11-2-a-converted`, `-b-converted`, 2026-10-02). `binding.output_labels` and
`input_labels` read either; a channel neither can read is left out, never called unrouted.

| file header word (u16 at +4) | `ivnE` class | channel-object type | `OCuA` class | written by |
|---|---|---|---|---|
| 2513, 2512 | 12 | 1800 | 7 | Logic 12 |
| 2511 | 12 | 1760 | 6 | Logic 11.2 |
| 2510, 2509 | 11 | 1728 (1736 and 1752 occur, unread) | 6 | before 11.2; no channel binds by UUID |

### Instrument outputs — an aux fed by a software instrument's extra output

Measured on two saves (2026-09-05) against the projects of the template's lineage: the aux's
channel carries `+95` = 1 and at `+94` a source id Logic hands out in order, starting at the
project's mono input count (Logic renumbers them on load, so a written id only has to be
unique); the input UUID in the tail stays zero. Under the aux sits one 68-byte `UCuA` at the key
just below the channel's 192-byte state record (12 in the template):

| offset | meaning |
|---|---|
| `+0` | u32 72, the class word sends carry too |
| `+15` | the output's index in the plugin's list (Addictive Drums: 3 = "D 5", 11 = "13-14", 12 = "15-16") |
| `+22` | u16 the instrument's number less one (Inst 9 -> 8) |
| `+24` | three reversed fourccs: manufacturer, type, subtype (`xlnA` `aumu` `xAD2`) |
| `+36` | the output's name, NUL-padded to 16 bytes |
| `+52` | a fresh v1 UUID |

The instrument's own records do not change. A stereo output made Logic widen the aux (`+78`,
`+123`); a mono one did not. `services/mixer/instout.py` reads, binds and unbinds; `apply-template`
carries the template's bindings onto the paired instrument (`instout` op). Logic's re-save
kept all three bindings with the row list unchanged.

Bus-fed auxes carry a source id at `+94` as well (`+95` = 0), and Logic restores the bus from it
when only the tail UUID is cleared; **No Input** on an aux is `+94` = `+95` = 0xFF (measured
2026-09-05) — zeroes read back as `Input 1-2`, the live input pair. `set_input(owner, None)`
writes the No Input bytes on an aux, and the `return` op that silences a legacy return goes
through it.

### Strip references, per channel

`logic retrack PROJECT --out DIR --channel 'Audio 5=Rack 1.cst'` (repeatable) repoints one
channel's reference and keeps its folder; `--map` stays the project-wide name-to-name form,
which refuses when one name would have to become two strips. Confirmed 2026-09-06: seven
references repointed on the Tracking template showed on the mixer's Setting buttons and Logic's
re-save kept them byte for byte.

### Sends — `UCuA` keys 0-2

76-byte payload, sitting right after the channel's `OCuA` in key order, before the plugin
slots (key 4+). 78 sends across three Logic 12.3.1 saves:

| offset | meaning |
|---|---|
| `+0` | u32 class word, 72 at `UCuA` v5 (the only version on hand) |
| `+4` | slot: `key << 16` |
| `+8` | u16, 0 or 4 — not decoded |
| `+16` | 1 in **Post Pan** mode (Logic's default), 0 in the other two |
| `+17` | the send level's 0-127 position (a new send is 0; Logic's knob dragged twice on a blank project: 0 → 11 → 34, 2026-09-12) |
| `+18` | 1 in **Pre Fader** mode; Post Fader is `+16` and `+18` both 0 |
| `+19` | 1 when the send is **bypassed** |
| `+22` | u16, 4 with **Independent Pan** on |
| `+24..27` | the exact level, u32 LE in 8.24 fixed point — the same word the channel fader keeps at `+116`; its top byte is `+17` again |
| `+20` | u16 destination as **bus number + the project's mono input count - 1** (32 inputs: 46 -> Bus 15, the B 15 the mixer shows; a 20-input song writes Bus 10 as 29) |
| `+44` | the send's own instance UUID (v1), distinct on all 78 |
| `+60` | the destination **`Bus N` channel's own UUID** (78/78) — the bus is named twice |

**The level in dB.** `dB = 40 · log10(position / 90)`: position 0 is −∞, 90 is 0 dB and the
top, 127, is 5.98, which Logic shows as 6.0. Logic's send knob reports the level word as its
accessibility value and the dB beside it; walked one stop at a time it gave 265 stops, every one
on that law within the display's rounding (2026-10-02). Logic shows a send's level rounded
*down* to the tenth, and the knob's own stops sit about 200 units above each mark — 0 dB is
saved as position 90 plus 256 units (`send-level-0db-logic`). A send written exactly on a mark
read 0.1 dB low in Logic (−10.1 for −10.0); written 256 units above, Logic's knobs showed −10.0
and 3.0 and its save kept both records byte for byte (`send-set-ours`, `-resave-logic`). The
mode, bypass and pan bytes are one save each on one send (`send-mode-*`, `send-bypass-logic`,
`send-independent-pan-logic`). `+8` is still not decoded: it is 4 on half the sends in the
mixes on hand and 0 on every send of a blank-born project, whatever its mode.

The channel's own `OCuA` mirrors every satellite: from `+132`, one u32 per record key (sends
0-2 at `+132/+136/+140`, plugin slots from key 4 at `+148`, the reference and the rest after),
1 exactly when a `UCuA` with that key exists under the owner — every word on the Logic files
measured, no exception. **`+26` is the flag-word count and sizes the record**: payload = 201 +
4 x `+26` on every version-7 channel record on hand (a 201-byte stub has no flag
words; the 20 zero bytes, one byte and three UUIDs after the flags never move). A flag left
set for a missing record is a file Logic refuses to open (measured 2026-09-04: slots removed
without their flags), and so is a record shorter than its `+26` says (measured the same day:
chains landed on 201-byte stubs grown the wrong way); a record without its flag it
tolerates. `services/stream/keyflags.py` syncs the flags at the end of every satellite write and
grows a stub in front of its tail when a key needs it.

Two Logic re-saves (`02 -> 03`, `02 -> 07`) left every send byte-identical. `services/mixer/sends.py`
reads them; `services/mixer/sends_write.py` adds, copies and removes them — a new send is a clone of
one the project already carries (`+8` copied, never synthesised), with a fresh `+44` and the
target bus's UUID at `+60`; `logic send --add/--copy/--remove` drives it. An added send's level,
mode, bypass and Independent Pan (`+16..+19`, `+22` bit 2, `+24`) are the ones asked for, else
those of the send Logic adds: its second send, beside one at -16.8 dB, came in at -∞, post pan
and on (`send-two-base-3-logic`), the packaged blank-project send's values. A copy keeps its
source's.
**Confirmed in Logic 12.3.1 on 2026-09-02:** the added send showed on the strip.

### Row selection marks — `karT`, measured 2026-09-13

Logic's own saves mark the selected arrange row twice: `+76` bit 5 (0x20) and `+79` bit 6
(0x40) of the 94-byte row; a fresh project's three tracks all carry both ("3 selected"), and a
header click moves both to the clicked row. Logic clears the `+79` mark on any row it loads
from one of our files and keeps `+76`, so a written selection does not survive a load: what
Logic reads it from is still open.

### MIDI regions — the region entry and its events (`logic midi`, measured 2026-09-13/15)

A region is an 80-byte entry in the song container's `qSvE` (`regions.py` has the row and
object fields): `+4` its start tick with bar 1 at 34560 (the automation root folders sit at
34560; a one-bar region placed at 3 1 1 1 reads 42240), `+12` bit 0 Mute, `+13` bit 1 Loop
(bit 0 marks the entry Logic last edited and clears when another is edited; bit 2 is set on
every MIDI entry), `+15` bit 4 flex / bit 7 selected, `+28` the loop length — `0x3fffffff`
unlooped, the region's length in ticks when looped (an audio entry read 960000 for a one-beat
region: ticks times 1000, one measurement), `+32` the slot of its own sequence triple. The
triple's `qeSM` carries the region name at `+16` (u16 byte length, UTF-8, padded to even —
`Pad — é` as Logic wrote it), and past the padded name: `+60` the length in ticks, `+76` bit 1
the loop flag again, `+224` the start in ticks from bar 1 (11520 at bar 4), and `+4` the offset
in ticks the region plays its sequence from, with bit 7 of `+8` set: a split's second piece
keeps every event of the parent and starts at the cut (A10: 960). A start trim rewrites every
event's tick instead and keeps the notes' absolute time. The region's `qSvE` is an event list
(`events.py`), ticks relative to the sequence with 38400 at the region's start less that offset:

| line | layout |
|---|---|
| note `0x9c` | `+11` velocity, `+12` pitch; a `0x89` continuation follows with `+12` u32 length in ticks |
| controller `0xBc` | `+11` value, `+12` number; a `0xBB` continuation follows |
| program change `0xCc` | `+12` program |
| pitch bend `0xEc` | `+12` LSB, `+11` MSB (0x40 at centre) |

`c` is the channel less one. `+15` bit 7 marks the selected event on every sequence — sections,
notes, region entries alike — set on the one just made and cleared by a click elsewhere.
Logic files events by tick, and at one tick program change, controller, notes, pitch bend.
A MIDI split (Logic's, A10) adds the piece's triple right after the parent's with the next free
slot and id, the parent's length cut to the split and the piece's to the rest.

### `.patch` bundles (`logic patch`)

A Library patch is a folder: `nodes.plistZ` names the nodes, and each node folder holds
`base.plistZ` (the channel's settings — name, strip file, volume, pan, mute, solo, width, input
and output — as `Channel_*` keys), `mappings.plistZ` and `uidata.plistZ` (Smart Controls) and the
channel's `.cst`. Each `.plistZ` is a zlib-compressed `NSKeyedArchiver` plist (`$top` keys point
into `$objects` by `CF$UID`). The older shape is a plain `data.plist` with the same channel keys
beside `#Root.cst`. Read on Logic's own default patches, 2026-09-13; `--build` writes the older
shape from a `.cst`.

One change per Library save on the eight-insert project (2026-09-16, `patch-c14…c18`): a fader step
changes only the channel record's fader bytes in `#Root.cst` (the same offsets as a project's
`OCuA`, so the reader now reports the fader and pan bytes); an insert adds the slot record and grows
the channel record by four bytes; a send adds a key-0 record like a project's. Saving with a summing
stack's header selected writes the Aux strip as `#Root.cst`, one `.cst` per member and four channels
in `data.plist`. A Library save also renames the track and its strip to the patch's name.

### Audio files and regions (`logic regions`, measured 2026-09-13/15)

An import adds an `lFuA` file record and a `gRuA` region record directly before the first `lytS`,
both carrying the same slot word in their header (`+10`, four times the import's ordinal), and a
type-0x24 entry in the song container whose `+44` word is that slot. A split (A04) adds a second
`gRuA` right after the parent's with the same slot and the piece's number in the header owner
(`+14`), and an entry with that number at `+40`: entry `(+44, +40)` pairs with record `(slot,
owner)` and the file is the record with the entry's slot, on every project on hand with audio
(earlier the entries were ranked onto the records by counter order, which mispaired every region
after a split). The file record: `+8` u16 the name's length in UTF-16 units, `+10` the name in
UTF-16 LE (`v040-é.wav` in the NFD form the file system keeps, `🥁` as a surrogate pair), then
`LFUA`; from that magic `+7` u8 1 on the newest import only, `+138` the Media folder's path in a
256-byte NUL-padded buffer, `+400` u8 channels, `+406` u32 file size, `+456` the format as a
reversed four-CC (`EVAW`), `+464` u32 data offset, `+468` u32 frames, `+476` u32 sample rate, `+480`
u16 channels, `+482` u16 bits, `+508` u32 the number of region records on the file (every file
record on hand but one agrees; Logic loads that many, so a split's second piece with the count left
at 1 was dropped), `+512` u32 ord (1-based), `+518` u32 link — the next file's word, `0xFFFFFFFF` on
the last — the file as Logic stored it, converted to the project's rate on import. The region
record: `+5` bit 1 Mute (mirrored by the entry's `+12` bit 0), `+6` u32 the region's first frame
within the file (22050 after a one-beat start trim at 120 bpm), `+22` u32 its length in frames,
`+38` u8 1 on the record Logic last touched, `+42` u64 a time in 100 ns on the clock of the region's
UUID, `+74` the name (u16 byte length, UTF-8 — `Snare 🥁` — padded to an even length), a v1 UUID 47
bytes before its end followed by `ffffffff`. An import clears the selected bit (`+15` bit 7) on
every other song-container entry. Logic's first import writes one kind-0x0b entry directly before
the 0x0c run in each `gnoS` stride (24- and 16-byte); each later import appends one after it, valued
four times the ordinal. Measured on Logic's first, second and third imports onto one blank-born
project (2026-09-13) and its move, trim, split, mute, rename, loop, fade and further imports on the
`regions-a*` goldens (2026-09-15). Logic's own mixes and legacy saves hold more `gRuA` records than
type-0x24 entries and more `gRuA` than `lFuA`: records no entry names are kept, never paired. A
split also gave the registry a blank kind-0x17 pair for the next free sequence slot (the next MIDI
region took the slot after it) and a blank kind-0x1e pair keyed by the parent's slot, which Logic
dropped on its next load; the parent's `+208` word read `ffffffff` and the piece's `+210` byte 1 for
a few saves. `regions --split` writes all of that; Logic's re-save kept the piece once the file's
region count was raised, and dropped it when the count alone was left at 1.

**Fades** live in the entry's last sixteen bytes (`fades.py`): `+65` u8 Fade-In type (0 In, 1 Speed
Up), `+67` u8 Fade-Out type (0 or 3 Out, 4 X, 5 EqP, 6 X S — Logic wrote 3 for Out on a region that
had a crossfade), `+72` u16 Fade-Out ms, `+75` u8 its curve, `+76` u16 Fade-In ms, `+79` u8 its
curve (-99..99 as the inspector shows). A **crossfade** is the underneath region's fade-out: a drag
under Drag: X-Fade that overlapped two regions wrote 0x20 at `+66` of the region underneath (the
fade-out side) and 0x80 at `+66` of the one dragged over it, the overlap in ms at `+72`, the type at
`+67` and the curve reset at `+75`; dragging the crossfade's edge changed `+72` (500 -> 563) and
`+68` (f9 -> da -> c1 across edits, no formula found: kept as found), and the regions moved apart
keep every byte. **The inspector's parameters** (`region_params.py`, 2026-09-15, the `regions-b*`
goldens): Gain in dB as a tens byte `+52` i8 and a signed five-bit remainder in `+48` bits 0-4 (-17
is -1 and -7), Reverse `+48` bit 5, Fine Tune `+50` i8 cents, Transpose `+53` i8 semitones, Delay
`+60` i32 ticks. Transpose on an unflexed region made Logic switch the track to Flex Pitch (two 0xAA
blocks after the entry, `+48` bit 7, `+15` bit 5 on every audio entry, the channel's flex bytes);
the Reverse row is disabled on a flexed region. **Colour** is a palette index, the `gRuA` payload
`+3` for an audio region and the ninth byte past the padded name of a MIDI region's `qeSM`; a region
born on a track carries the track's index, and the Color window's swatch k writes 24 + k (12 -> 36,
40 -> 64).

### Marker track (`logic markers`, measured 2026-09-15)

The marker track is a sequence triple every blank-born project carries empty: the triple right
after the one whose events are type 0x11, its `qeSM` a copy of the arrangement section
sequence's named for the Marker Set (`Untitled`), slot 4. A marker is a 48-byte 0x12 event
exactly like a section's (`markers.py`): head tick, data line with its `qSxT` text slot at +0
(the lowest free multiple of 4 among the text records, 12 and 16 after two sections), 0 at +8,
the length at +12 — 1 on every marker Logic made, shown as ∞ (to the next marker) — and a third
`0x88` line. Names are RTF text records (`Marker ##` numbers itself). A rename rewrites the
RTF, a move the head tick, a delete removes the event and its record; Logic's first marker also
rewrote 4.6 KB of the registry and added an empty triple after the marker track, which ours does
not. `arrangement --add` and `markers --add` share the pieces (`arrangement_write.py`).

### Track automation (`logic automation`, measured 2026-09-16)

Under the `Track Automation Root Folder` sequence (its `qSvE` at tick 34560 holds one 0x20 reference
per channel, the referenced table slot at data +0) sits one `*Automation` folder per channel: its
`qeSM` carries the name `*Automation` at `+18`, the track's object at `+234` and its own sequence id
at `+8`, the owner of the `qSvE` that holds the points. An event's head +2 is the sub-tick fraction
(u16, 0x8000 half a tick): Logic's region-border point sits at 38399 + 0x8000. A fader point is a
0x50 event — tick at head +4, fader id at head +12 (Volume 7, Pan 10), the fader byte at head +11
(unity 90); a plug-in parameter point is 0x51 to 0x5F — the type's low byte less 0x50 is the insert,
1 to 15 (Logic wrote 0x52 for a point it made on insert 2, 2026-09-23) — with the value at head
+8..+11 and the parameter index at +12: one of Logic's own numbers its parameters by float index
less one (the Compressor's Threshold is 0, its Knee 5), a third-party by AU parameter id; a number
past the plug-in's count names nothing in the Event List. The value is the u32 at +8 over 2^31 (its
top byte the Event List's val, 0..127). Logic lays it on the parameter's Controls slider: units =
floor(value × per), a rate per row — 128 for most, 201.5 for the Compressor's Mix and the Noise
Gate's Release (0..200 units), 483.75 for the Channel EQ's gains (0..480), 1058 for its frequencies
(0..1050), 161.25 for the Multipressor's compression thresholds (0..160) — clamped at the slider's
top (the Compressor's Threshold 100, Ratio 85, Knee 10, so Knee's automation reaches only 10/128 — a
lane carried onto such a short slider, four times shorter than its automation reaches, gets a note:
nearly a switch); the slider's own scale then gives the value, read at up to 44 positions into each
native map's `automation` table (Compressor, Noise Gate, Channel EQ and Multipressor, 2026-09-23;
the rates from every row read at eleven automation values, `auto_value_probe.py`; a switch is on
from one unit; a written point aims at the middle of its unit so no rounding tips it down).
`automation --set "TRACK:slot N NAME=V@BAR,…"` writes such a lane from the parameter's own values:
one of Logic's own by its table name onto the slider unit nearest each value, a third-party by its
AU table's parameter name or id, or its map's vocabulary name, as the fraction of its range.
Logic-confirmed 2026-09-23 (`autoset-*`): the Event List named four lanes so written — a
Compressor's threshold on units 40, 52 and 76, its Auto Release 127 and 0, a Noise Gate's hold 25
and 20, a Pro-C 2's threshold 85 and 106 of 128 — and the Controls view showed a Multipressor's band
1 expander threshold, reduction and response on the written units, the points kept as written. The
same tables give the settings writers their grid: a native value is put on the nearer of the two
sampled slider positions around it before it is written (`slider.snap`; a tie goes down — Logic's
own choice at a midpoint depends on the knob), so the re-save keeps it as written — the knob-shaped
rows are sampled at every unit for that (ratios, times, Q, the Channel EQ's frequencies at all 1051
positions), the linear dB rows every few. The Multipressor's expander threshold, reduction and
response rows carry no band name in the Controls view or the Event List (Logic's own parameter names
lack one); the view lists them band 4 first, and a lane on each band's row found them (`mbx` probe,
2026-09-23): the thresholds run 161.25 per 1.0 like the compression thresholds, the other two 128,
every band alike. Logic-confirmed 2026-09-23 (`snap-*`): raw floats between positions came back on
the positions the snap picks — a Compressor ratio 4.0 as 3.9, attack 20.5 as 20, release 115 as 110;
the Noise Gate's hold 205 as 210, a midpoint Logic took up where the snap takes it down — and a copy
written through the snap came back with every float as written. The Noise Gate's release positions
are not round numbers (351 came back 350.99: the display's tenth hides the rest), so there the snap
is exact to a hundredth. A third-party's value spans its AU parameter's range (`raw` in its map:
Pro-C 2's threshold -60..0 dB). Bit 14 of the type word (0x4051) is set on some of a real song's
parameter points and read as `flagged`; meaning unknown. Logic-confirmed 2026-09-23
(`auto-lanes-*`): four lanes written on a Pro-C 2 and carried into a Compressor by `replace-plugin
--translate` came back from Logic's Event List by name with the written units (40, 52, 76 on
Threshold), and the Compressor's Controls view followed them in Read (-30, -24, -12 dB); a band's
lanes the same way, a Pro-Q 4's onto the Channel EQ slots the plan placed its bands in and a
Pro-MB's onto the Multipressor's (`auto-eqlanes-*`, `auto-mblanes-*`: 1/0/1, -4/0/+6 dB, 1000/2000
Hz; -20/-12/-30 dB, 3.675/1.977, +1 dB). Head +15 is the Event List's selection state on a point it
just made (1, 0x81 on the anchor), rewritten on save. Every folder keeps its points in (tick,
fraction, type, fader, relative) order. Logic's Automation Event List (read for every automation
golden, 2026-09-17) shows a fader point at the tick and value the reader reads, the half-tick point
as the display tick before it, a relative point as `± Volume`, and a plug-in parameter point by its
index with a 0-127 Val (63 for High Shelf Gain's float 1.0; that mapping is unmeasured). `Create 1/2
Automation Point(s) for Visible Parameter` writes at the selected regions' borders (on a track
without a region it writes nothing). Convert Visible Track Automation to Region Automation adds an
unreferenced sequence naming the track at `+234` with the region's copy of the points. The arrange
row's byte at +84 is the lane the header shows (a fader id). A Pan lane chosen in the header popup
wrote no point through the region-border command; unmeasured.

### Session Player regions (`logic sessionplayer`, measured 2026-09-13)

The settings are JSON in a `MneG` record: `+0` u32 the payload size, `+28` u32 the JSON's
length, the document at `+36`. Its top-level scalars are the editor: `rComp` Complexity,
`fillsAmount` Fill Amount, `swing` Swing (one move per save), `fillsComp`, `humanize`,
`dynamics`, `ghostNotes`, `pushPull`, the enable flags, `CharacterIdentifier` the drummer,
`Preset.Name` the preset, `PresetDirty` once anything moved. `GeneratorMemento` is the
generator's bookkeeping; the performance is the notes in the region's own sequence, whose
`qeSM` names it "Drummer - …". One region measured; records pair with drummer sequences in
file order.

### Plug-in identity (`logic plugins`)

A native slot carries its type id in the `GAMETSPP` block (`insert.find_blocks`); a third-party
slot embeds an AU preset plist whose `type`, `subtype` and `manufacturer` integers are the
component's four-character codes (`au.services.embed`). The name string a slot may carry is a
preset name, not the plug-in's.

### Hidden

`karT +0` bit `0x04000000`. The values seen are `0x24000001`, `0x241c0001`, `0x24080001`
and `0x4000001`; testing for one value misses the rest (the template's Rack 1 is hidden).

### Groups (`logic group`) — measured, 2026-09-05

Twenty-eight single-change saves in Logic 12.3.1 (a group made on one track, a second
member, a second group, a rename, then every box in Group Settings toggled once) pin the
whole structure. A group is a **sequence triple of its own** — `qeSM` / zero-size `karT` /
`qSvE`, header `+6` = `0x11` — placed after the last `rpyH` record and before the first
`ivnE`, one per group in slot order (`+10` = 0, 4, 8 …; group N sits in slot 4(N-1)).

| where | meaning |
|---|---|
| `qeSM +8` | the triple id, repeated as the `qSvE`'s owner; any unused id (Logic gave 82, then 43) |
| `qeSM +16` | u16 name length; the name follows, padded to an even length |
| `qeSM +70` + padded name | u32 **settings**, one bit per box: 0 Volume, 1 Pan, 2 Mute, 3 Solo, 8-15 Send 1-8, 16 Editing (Selection), 17 Track Zoom, 18 Color, 20 Record, 21 Hide, 22 Quantize-Locked (Audio) **inverted** (set while the box is off), 23 Track Alternatives, 24 Automation Mode, 26 Input. A fresh group is `0x81400005`; bit 31 is the table's **On** box (clear on a switched-off group; two groups switched off, 2026-09-13) |
| `qSvE` | one 32-byte **event per member per linked fader** — Volume, Mute, Solo, Pan; every other box is flag-only — then a 16-byte tail. `+4` = the member's object id × 2; `+12` the fader as Logic numbers them (7 Volume, 9 Mute, 3 Solo, 10 Pan); `+8` u32 the member's value for it as its channel stores it (the fader's fixed-point word, `0x5a000000` at unity; the pan byte in the top byte, 64 = centre; 0 for Mute and Solo), its halves repeated at `+20` and `+30`. A fresh group writes Mute then Volume per member; Solo then Pan |
| `ivnE +24` | the member's **groups as a bitmask**, bit N−1 = group N (measured on a Create Group that put overhead tracks already in group 1 into group 4: they read 9) |
| `gnoS` | a `<0x11><slot>` entry per group in both runs, directly before the object entries |

Nothing else moves: the row's `+4` and the channel's `+92`, both candidates before the saves, stay
put. `services/arrange/groups.py` reads and writes all of it; the writer reproduces six of the saves byte
for byte in the triple, the numbers and the registry pair. Create Group sets the new bit and leaves
a member's other groups and their events alone; leaving a group is composed (events out, bit
cleared), not measured. `apply-template` carries the template's groups by name — made in the session
when missing, paired rows put in them, a row grouped where its template row is not taken out — as
its last step, so the events carry the fader the template set. Confirmed: the migrated song opened
in Logic with `1: OH` / `2: Room` in the mixer's Group row, and Logic's re-save kept both group
records byte for byte and the row list unchanged.

The events are not always all there, and that is Logic's doing. A switched-off group carries
none (`songb-bars-9-12-logic`). Logic 12.4, re-saving sessions it had only opened, kept every
group's settings, members and Mute events and dropped every Volume event
(`tracking-template-12-4`, `mix-01-12-4`, 2026-10-04), while two other 12.4 saves of a session
kept them (`tracking-convert-after-logic`, `tracking-convert-resave-logic`); and Logic 12.3.1
wrote missing Volume events back when it saved a copy that lacked them (`width-tracking-logic`).
What decides it is not known. So a missing event is no fault: `group_errors` reports an event
for a track or fader the group does not link, or a repeated one, and nothing else about them.
`missing_group_events` counts the missing ones apart, and `integrity.regressions` refuses a write
that leaves more missing than its input had.
On Logic's blank-born project the sequence create, assign, add, assign keeps one event per
member per fader (`tests/goldens/test_groups.py`, 2026-09-13).

Leaving a group was composed until 2026-09-12: Logic's own No Group on one member of a group
made by `logic group` on a blank project (Logic re-saved that group intact first) changed the
group record, the object's group bit and nothing else the leave owns — `assign(…, 0)`
reproduces it; the bytes that differ are the selection made by clicking the track.

### Flex and audio quantize (one tracking project, eleven single-change saves, 2026-09-13)

The owner's live-drum quantize procedure, saved after every step, then re-saved after a flex
mode change and after each of four Quantize values. Everything below is from those saves; the
project is private, so the facts are pinned here and in synthetic tests.

- **Region entries live in the song container's `qSvE`** (the sequence named after the project,
  head `70 03 01 00`), 80 bytes each; `+44` is four times a **counter that keeps counting past
  deleted regions**, so neither the counter nor its distance from the smallest is a record
  index; `regions.py` ranks the counters of every sequence.
- **Enabling flex on a region** (Quantize-Locked (Audio) does it for every group member) sets
  the entry's `+15` bit 4 (bit 7 there is *selected*) and appends two 80-byte **marker blocks**:
  byte 7 = `0xAA` on every block; `+6` = `07` start anchor, `03` end anchor, `01` transient;
  `+0` i32 **source** in samples, `+12` i32 **target** in ticks (960 per quarter, 3840 per 4/4
  bar; the region start is 0), `+8..11` the target's fraction, `0x88` at `+23`, `+39`, `+55`,
  `+71`. The start anchor sits one beat before the region (`-13230` samples at 200 BPM, 44.1
  kHz; target `-960`); the end anchor sits 1024 samples past the region's last frame while it
  is only flexed and **at the last frame once quantized** (target = frames in ticks, with the
  fraction). A written anchor left at +1024 comes back as kind `04` with Logic's own `03`
  before it; two hits snapping to one grid target come back as the one nearest it; with
  Quantize Off the hits are kind `05` with their unmoved, fractional targets.
  `regions.entry_offsets` steps over the blocks.
- **Quantize** on a flexed region: `+13` = 1, `+48` bit 7, `+32` = the slot of a new sequence
  triple per region named **RBA Sequence** (309-byte `qeSM`, empty `qSvE`, a registry pair):
  `+8` its id, `+88` the region length in ticks with fraction, **`+102` i16 the Quantize value**
  — 0 Off, `-2·(7 − log2 d)` for 1/d (1/4 = -10, 1/8 = -8, 1/16 = -6, 1/32 = -4). Logic then
  writes one transient marker per detected hit with the target on the grid; on the first
  quantize only the first Q-Reference region carried them (the markers for every region), a later
  value change wrote the full list on every member. **Logic does not rebuild the markers on
  load**: a save with the markers stripped and the parameter kept came back with two anchors
  per region. The markers are the quantize; a writer has to make them.
- **Across every Logic-written `ProjectData` under `resources/` (2026-09-14)** neither bit marks
  a region reliably: Logic writes marker blocks on entries without `+15` bit 4 and sets the bit
  on entries with none, and `+48` bit 7 is on many entries that name no sequence. What holds on
  every one: a chunk carries `0xAA` at byte 7 exactly when it carries `0x88` at `+23/+39/+55/+71`,
  no block precedes the first entry, and blocks need not start `07` or end `03`. Every entry
  whose `+32` is not `0xFFFFFFFF` names a sequence triple whose `<0x17><slot>` pair is in both
  `gnoS` stride runs; an audio entry with no sequence carries `0xFFFFFFFF`. Hit targets rise
  strictly within every marker list. Nearly every entry naming an RBA Sequence has `+48` bit 7
  clear; many saves carry RBA Sequences no entry names; many audio entries name a 309-byte empty
  sequence called **MIDI Region**, not RBA Sequence.
- **Per channel object** (`ivnE`): `+80` = 1 while the track is selected (many at once);
  `+154` bit 4 = **Q-Reference off** (`0x80` → `0x90`), bit 5 = flex mode other than Slicing;
  three bytes at the padded name's end + 402 − 18 hold the **flex mode**: `02 03 02` Slicing,
  `05 00 05` Monophonic (the Q-locked group takes one member's mode for all).
- **Writing it** (`services/regions/quantize_drums.py`, `logic quantize-drums`): `onsets.py` finds the hits
  in the reference mics (peak envelope, a 24 dB rise over the quietest 30 ms before — for a file's
  first hop, the track's quietest hop — at most 21 dB under the track's peak). Tuned against the
  union of the transients Logic marked on the take at 1/16, 1/8, 1/4 and 1/32 (310; the later lists'
  sources are mostly the raw positions, a minority re-detected a few ms early on the rendered
  audio): 78% of them found within 10 ms, 88% of ours among them, 0.5 ms median position error on
  the exact subset, `flexmarkers.py` writes the blocks and the RBA triple, `flexmode.py` the
  object's Q-Reference and mode bytes; the region's first frame in its file (`gRuA +6`) is taken off
  every hit.
- **The audio file** grows too: Logic appends `LGBM` (a beat-marker cache, 8.6 KB for 212
  markers, pointer-like words, unread here) once flex is on, and `EAPD`/`EAFP` (pitch analysis,
  ~500 KB) for Monophonic; every recorded file already carries `ResU` (zlib JSON, the Smart
  Tempo recording context) and `LGWV`. RIFF chunks after `data` are byte-padded; `data` is not.

### What a track add writes (two clean saves, 2026-09-01, Logic 12.3.1)

**A mono audio track** (`02-baseline -> 03-add-audio-track`, +40 bytes of gnoS, everything
else accounted for):

- `NumberOfTracks` +1; one `ivnE` object cloned in shape from any track object — new id,
  name, fresh tail UUID, colour byte, `+148` icon word; one arrange `karT` row (58 B, `+14 = 0`,
  fresh row UUID, `+51 = 0x07` for an audio track / `0x85` for an instrument track), inserted at
  the position with every later key renumbered; one row in the flat all-tracks list; and one
  **sequence triple** — `qeSM` (345 B, contains the lane name `*Automation`), a zero-size
  `karT` marker, `qSvE` (16 B) — inserted in slot order (below). That `qSvE` is the closing
  event alone, `f1000000ffffff3f0000000000000000`, even beside tracks that carry lanes (Logic
  12.4, `addtrack-lanes-after-logic`); every automation folder on hand ends in it. The writers
  clone the pattern's triple and keep only that event.
- **Binding**: a pre-allocated `Audio N` stub (253 B, already labelled) flips `+24/+25` to
  `01 01`, gets the width triple (mono 211/0/1), its own UUID = the new object's tail UUID,
  and its input UUID = `Input 1`'s. Its destination UUID already pointed at Stereo Out.
- **`gnoS`**: two object entries in the id-ordered registries — 24-byte `<u32 0x14><u32 id>
  <UUID>` and 16-byte `<0x14><id><v1 time fields>` — right after the highest id's; the pair
  keyed by the new index-table slot word (`<0x17><slot>`, same two shapes) filled with a fresh
  UUID and its time; the 16-byte `<0x17><4>` and `<0x17><8>` stamps (the arrange and flat
  lists) refreshed; and the selection fields (`+94`, `+210`, `+214`). Everything else in gnoS
  that moves also moves on a no-op save — per-save nonces.
- The index table — the `qSvE` with one entry per track object (not the largest: a mixed project
  holds a far larger region table repeating track ids) — 80-byte entries, then a 16-byte tail —
  gains one entry **before the tail**: the object id at `+16`, the sequence index at `+20`, and at
  `+32` the lowest slot word (multiples of 4 from 20) no other entry uses. Every entry whose
  sequence index is at or past the new one moves up by one.

The real-file goldens run on a re-saved Mix template staged by `tests/_paths.py`, and check the
invariants above rather than bytes.

`logic add-track` reproduces all of that (`services/arrange/addtrack.py`): against Logic's own add it yields
the same record set at the same positions, the index table and count record byte for byte, and the
registry entries at the same offsets; what differs is minted values (UUIDs, the `qeSM +8` ids Logic
renumbers) and per-save nonces. **Confirmed in Logic 12.3.1 on 2026-09-01:** the project opened, the
new track was there, the source track was intact, nothing else changed.

**A software instrument track** allocates a channel differently: Logic **inserts a new `OCuA`
record** right after the pattern track's channel (265 B payload, Logic's default instrument-slot
record and one property record — kept in `inst-track-12.3.1.json` under the data root, instance
UUIDs re-minted), **renumbers the owner field of every record after it**, relabels the following
`Inst N` channels (`+6`, `+66` and the label all move up one) bumps the channel index of every
object bound above it and the stamp of every object above the pattern's, and adds one to the
channel-count record `nCuA`: a 132-byte head over one u32 per channel record, `+26` the total, then
a u16 per strip class — `+28` Audio, `+32` Aux, `+34` Inst (the one a save moved), `+38` Bus, `+40`
Master and Sub together (these counted from the file, not measured by a save). Audio tracks never do
this because `Audio 1-35` stubs pre-exist. `logic add-track --instrument` does all of it; the index
table and count record it writes are byte-identical to Logic's. **Confirmed in Logic 12.3.1 on
2026-09-01** (both tracks present, the click still plays).

**Where a fresh channel record goes, and its keys.** Every Logic save keeps the mixer records in
owner order (every golden). A fresh channel takes an owner, every channel from it moves up
one, and its record goes after the highest owner below it; placed after the channel records'
trailing 14-byte shells instead, Logic's re-save dropped every plug-in in the project
(`addtrack-order-*`, 2026-09-23). The default instrument records in `inst-track-12.3.1.json` were
measured at slot base 4, property base 12 (keys 4 and 15): the instrument sits at slot index 0,
the keyed archive at the property base + 3, so in another project they take that project's keys.
Left at 4 and 15 in a base-2 project, Logic refused to open a migration ("The operation could not
be completed.") — and opened the same file once only those two records' fresh ids were changed
(`legacy-migrate-keyed-mine`, `-idswap-mine`, 2026-09-24). `validate_project` refuses both
shapes: a plug-in whose +6 index disagrees with its key, a keyed archive off its key.

**The default instrument slot's id and its closing word.** The 656-byte instrument-slot record
keeps its instance id at `[len-20 : len-4]`, followed by a u32 that is 0 in every such record of
the public corpus (131 of 131) and that Logic 12.4 writes back as 0; the keyed archive's id is
its last 16 bytes. An id minted over the slot's last 16 bytes leaves random bytes in that word,
and with a large value there Logic 12.4 refuses the project ("The operation could not be
completed."): three values near 2^24 were refused, and the same file opened with 0, 1 and a
negative value (2026-10-01). The 2026-09-24 refusal above cleared the same way — by re-minting
those ids — so it may have been this word and not the keys.

**A stereo instrument channel takes its width from the instrument slot.** Written with the
channel bytes alone (`+78 +81 +86 +123` = 247 8 1 2) over the default mono slot, Logic 12.4
saved the channel back as mono (243 8 0 1). `+84` and `+119` are 2 on Logic's own stereo
instrument slot (`sessionplayer-track-logic`, another plug-in's); with those two set, Logic
12.4 kept the channel stereo and itself wrote `+81` 2 and `+116` 255 (mono 1 and 254). Neither
that save nor the mono one was kept. With all four written, Logic 12.4 kept the slot record
byte for byte (`addtrack-inst-stereo-mine`, `-logic`, 2026-10-01).

**The sequence triple and the index table are linked by slot.** The three records of a
triple share a header slot (`+10`); the table entry with that slot word at `+32` names the
object (`+16`) and its index (`+20`), and the `qeSM` repeats both: `+234`
the object id, `+242` the index negated, plus `+300 = 382` on a fresh track and a kind byte at
`+39` (9 track, 20 stack). A new track takes the lowest free slot word and goes into the stream
in slot order; no other triple moves. `qeSM +8` (repeated
as the `qSvE` owner) is a per-triple id Logic renumbers on its own saves — any unused value
serves. Measured on both adds; `services/stream/sequence.py`.

**The index is the object's place in the mixer-order track list**, counted from 1: on every
Logic save on hand, the public corpus and the owner's sessions alike (2026-10-03). Logic
re-lays an entry that is off its place on the next open, and where the object has no arrange
row it gives the sequence to whichever object holds that place (an aux in use with no track
came back as `Preview`'s). `table_index.sync_indices` sets every entry, and its own triple's `+242`,
after a writer adds a channel or a row; with that Logic re-saved a written route, send, stack
and convert with the table as written (`route-bus-*`, `send-bus-*`, `stack-summing-*-resave-logic`,
`stack-convert-*-resave-logic`), and `integrity.regressions` counts the entries off their place.

**Three more things a row add must keep straight** — get any of them wrong and Logic's
re-save drops or misplaces rows (measured 2026-09-04; `services/regions/regions.py`,
`services/stream/registry.py`):

- **The song container's row count.** The `qeSM` of the triple that holds the arrange rows
  carries `rows x 60` as a u32 269 bytes before its end (its name is variable-length, so the
  field is addressed from the end; every file on hand). Logic reads that many rows and silently
  drops the rest on its next save — a migration came back as its first 11 rows plus Master.
- **Region placement.** The same container's `qSvE` is an event list of 80-byte entries and
  a 16-byte tail; an entry placing a region carries the track's object id at `+16`, the
  track's 1-based arrange row at `+20` (the object's first row when a channel has two) and the
  region's slot at `+32`. Logic renumbers `+20` when a row moves (`37 -> 38`); every entry
  on hand agrees. Left stale, a region shows on whatever track now sits at that row.
- **Registry slot entries.** gnoS's two `0x17` runs hold one entry per multiple of 4 from 0
  to the highest sequence slot in use; a slot past their end gets appended, with every
  skipped word, the way Logic's re-save extends them.

**The track name is the user's only when `ivnE +45` bit 0 is set**: clear, the arrange shows
the channel-strip setting's name instead (`Rack 2` read `Rack`, the vocal tracks read `Vox -
Lead`). Every named track on hand sets it; Logic's own fresh adds, auto-named `Audio N`,
do not. `rename_track` sets it; `add-track` sets it unless the name is the strip's own label.

**Selection** lives in four places Logic moves together — the row (`+40` bit `0x20`, `+43`
= `0x40`, `+0` bit `0x10000` on an instrument row), the object (`ivnE +80`), and gnoS (`+94`
object id, `+210`/`+214` the 1-based row) — and the previous holder is cleared. Every writer
that adds or moves a row ends by selecting it (`services/arrange/selection.py`).

**Reorder** (`06 -> 07`, Ride dragged above Hi Hat): the two rows swap keys; no table moves.
`logic reorder` reproduces it — the only remaining difference from Logic's file is selection
state. **Save Channel Strip Setting** copies the channel's records out (see `stripsave.py`)
and rewrites the channel's `.cst` reference label to the new strip name.

**Colour** is `ivnE +155`, a palette index (`08-colour-kick`: Kick In 96 -> 64, nothing else
moved); `logic colour` writes it. `+45` is a state flag a fresh object clears.

**A stale index-table entry is not a pattern.** Logic's own files keep a few entries whose
triple carries object 0 and reads as a group's (`link_errors` lists them).
A track cloned from one comes back as a group with no registry entry and the
write gate refuses the copy. The add path takes a pattern only when its entry leads to a track
triple carrying the object itself (`addtrack._sound_entry`, 2026-09-08).

### Summing stacks (Logic's own, 2026-09-12; written 2026-10-02)

Logic's Create Track Stack of each kind over three audio tracks on a blank project: a folder
stack's header row is a grouping object bound to a `Sub N` strip; a summing stack's header is
a grouping object bound to an `Aux N` strip (named `Sum N`, stereo), and every member's output
is re-routed to that aux's bus. The grouping flag alone is not the tell — plain aux, instrument
and output tracks carry it too — so the reader takes an Aux-bound grouping row as a summing
header only when the row under it sits one level deeper (an aux inside a folder stack is
followed by its sibling, at its own depth). A track dragged into a summing stack (Logic 12.4,
`stack-summing-dragged-in-logic`) takes the bus as its output, by UUID and by word, with its row
one level in; its parent pointer and stack index stay as they were, and dragged back out
(`stack-summing-dragged-out-logic`) it keeps the bus. `move_to_stack` writes the same — Logic
re-saved one with every row, route and stack kept (`stack-summing-move-resave-logic`). Only a
direct member takes the bus. A track dragged into a folder inside a summing stack keeps its
output and takes the folder's stack index (`stack-drag-into-folder-after-logic`); a folder
stack dragged into a summing stack moves its rows and nothing else, its tracks still on their
outputs (`stack-folder-into-summing-after-logic`); a summing stack dragged in has its aux
output to the outer bus while its members stay on its own
(`stack-summing-into-summing-after-logic`). `stack_place` writes each, and a track added
beside a summing stack's members is routed the same way; a row moving within its summing stack
keeps its output, as Logic's own saves keep some subtracks routed elsewhere. Logic's manual has
any track added to a summing stack take its bus, and a track dragged out go to Stereo Out; the
drags above and Logic 12.4's own drag out, which kept the bus, are the file, and the file wins.
A track dragged out of an inner stack to a direct place in the summing stack around it takes
that stack's bus, out of a folder (`stack-out-of-folder-after-logic`: output word, destination
UUID, stack index cleared) and out of a summing stack (`stack-out-of-inner-summing-after-logic`)
alike; Flatten Stack on a folder inside a summing stack changes no channel record, so a track
on another output stays there (`stack-flatten-in-summing-after-logic`). A summing stack dragged
out to the top level keeps its aux on the outer bus (`stack-loop-out-logic`), and the outer
stack dragged into it then has its own aux sent to the inner bus: the two auxes feed each
other, saved with no alert (`stack-loop-after-logic`). `routing_loops` names such a loop.
Create Track Stack over a stack's header makes a stack around it. A folder around a summing
stack (`stack-folder-around-summing-after-logic`) and around a folder
(`nest-stack-in-stack-logic`) changes no routing: the rows go one level in and the inner
header's strip takes the new folder's index. A summing stack around a folder
(`stack-summing-around-folder-after-logic`) routes the folder's tracks to the new bus and makes
the new header the parent of the folder and of each of those tracks, their stack index still the
folder's. The folder has no output of its own, so that stack outputs to Output 1-2 and takes
no bus's aux as its main track, whatever its tracks fed: over a folder whose three tracks were
all Bus 1 had, Logic made a new aux on Bus 2, moved the tracks onto it and left Bus 1's aux as
it was, a track or not (`stack-summing-busfolder-after-logic`, `-track-after-logic`,
`tracking-sum-busfolder-after-logic`). The new header takes its first member's colour, the
folder's there. A summing stack around a summing stack
(`stack-summing-around-summing-after-logic`) routes the inner aux to the new bus and parents
its header to the new one; the inner members stay on their bus. Logic 12.4 re-saved a written
copy of each move and each wrap with every row, route, parent, table entry and channel record
as written (`stack-*-ours`, `stack-*-resave-logic`, 2026-10-04). A new folder stack's strip is
the lowest `Sub` out of use, as a convert leaves one: Logic sets `+24`/`+25` and the strip's
own UUID to the new header's and changes nothing else of it, adds no channel record, and keeps
the `Sub` rows of the mixer-order list in strip order (`stack-sub-gap-after-logic`,
`stack-sub-after-convert-after-logic`). A strip the convert left with the folder's level or mute
is put back at its defaults: `+85` to 90, the fixed word at `+116` to `00 00 00 5a`, bit 0 of
`+90` cleared (`stack-sub-level-after-logic`, `stack-sub-muted-after-logic`). In those two saves
the new header also took the object id of the header the convert removed, whose registry entry
and mixer-order row were still there, so the row left the head of the list and no id was added;
`create_stack` takes a new id and leaves that row, and Logic re-saved the copy with every row,
strip and table entry as written, setting the new header's parent to the stack around it. With none out of use the strip is a new one numbered
after the highest `Sub`, one a flattened stack left in use included
(`stack-sub-after-flatten-after-logic`). Stacks nest two deep: with a stack inside a stack, Logic's
Create Track Stack is disabled for the outer header, for the inner header and for the tracks
inside it (read with the Track menu open, 2026-10-04), and a third level is not written
(`stacks.require_two_levels`). Logic's Convert Folder Stack to Summing Stack on a folder that
holds a folder makes no summing stack: the save has no stack, and a first row bound to no object
that Logic shows as Not Assigned (`stack-convert-holding-folder-after-logic`); `stacks
--convert` refuses such a folder. A member's stack index is not a
reliable folder tell around summing stacks: Logic's Flatten then Create Summing leaves members at
the old Sub number (`stack-summing-logic`), and top-level summing members on hand carry one more
often than not. The project word at `+42` is 0 on Logic 12.3.1's saves and 3 on 12.4's, which
rewrites it on every channel record. Flatten Stack takes out the header's arrange row alone
(`stack-folder-flattened-logic`, `stack-summing-flattened-logic`, against the saves before
them): the members' rows come up a level with their parent pointer cleared and all of them
selected (`+80` on each object, the first in the registry), the header object, its flat row,
its strip (in use), its table entry and triple stay, and so do the members' channel stack
indices and routing. Inside another stack the members' parent is cleared to 0 too, not set to
the outer header, and their stack index stays the inner `Sub`'s (`nest-flatten-after-logic`).
`stacks --flatten` (`stack_moves.flatten_stack`) writes the same, and Logic
12.4 re-saved a written flatten of each kind as written (`stack-*-flatten-*`).

Logic 12.4's Convert Folder Stack to Summing Stack (`stack-converted-to-summing-logic`, against
`stack-folder-logic`) is that flatten and then its summing creation over the same members: a new
header object (unnamed `Sum 1`) on the lowest free `Aux`, fed from the lowest free bus, the
members routed to it with the new header as parent and their stack index set to 0; the folder's
header object is gone while its flat row and table entry stay, the row moved up the
mixer-order list to just before the first row of a live channel object — first on a blank-born
project, after the rows of gone objects a tracking session's list already opens with
(`tracking-convert-after-logic`) — and its `Sub`
strip is left out of use (`+24`/`+25` cleared). The two `UCuA` records that save gained are
not the convert's: they are the Click instrument channel's Smart Controls archives, which any
Logic open-and-save adds to a project that lacked them (`stack-convert-lane-before-logic`,
saved untouched, has them). The folder track's Volume lane moves byte for byte into the new header's
automation folder, the old folder's left with its closing event (`stack-convert-lane-after-logic`),
and so do its Mute and Solo lanes (`stack-convert-mutelane-after-logic`,
`stack-convert-sololane-after-logic`);
a folder level off unity stays on the out-of-use `Sub` strip and the aux comes up at 0 dB
(`stack-convert-level-after-logic`), and a muted folder's mute stays there too, the aux
playing (`stack-convert-muted-after-logic`). `stacks --convert`
(`stack_convert.convert_to_summing`) composes the two writers, moves the lane and puts that
row where Logic does; Logic 12.4 re-saved a written convert with every row, object, route,
strip and table entry as written (`stack-convert-reuse-*`, `stack-convert-differ-*`,
2026-10-03; a copy with the row last and its entries off their place came back with the table
re-laid and the orphan entry dropped, `stack-convert-resave-logic`). It refuses a lane other
than those three, or an insert, on the folder's strip. Inside another folder Logic's convert
does the same: the new header's row and object sit under the outer folder, and the members and
the new `Aux` go to stack index 0 whether the inner strip carried the outer stack's number
(below) or 0 (`nest-convert-wrapped-after-logic`, `nest-convert-inner-after-logic`); ours
matches both channel for channel.

Logic's creation, against the save before it: the lowest free `Aux` stub comes into use —
in-use flags, stereo width, output word 0 and `Output 1-2`'s UUID, the bus's index in the input
word and its UUID as the input — with 90 at `+85` and `+119`, which a plain new aux has 0 in;
the bus's own UUID is minted in place of the placeholder an unused bus carries
(`ee0000000000800080…`); each member's output word and destination UUID name the bus; the
members' rows go one level deeper with the header object as their parent, and their `+110` is
left alone (0 on a fresh track). That header object carries 2 and 250 at 10 and 12 bytes past its
name — bytes many track objects carry as 0, or as 2 with 250, 113 or 11, and whose meaning is not
decoded; Logic wrote 0 in both when it saved a header written with them, so they are written 0.
`stack-create --summing`
(`services/arrange/stack_summing.py`) writes the same through an aux track add that binds the lowest
free `Aux` stub (`channel_alloc.free_aux_stub`; a fresh `Aux` strip after the highest when none
is free), and its header's record reads as Logic's own, strip for strip; Logic 12.4 opened two
written stacks whose headers were fresh strips, showed the members under their headers, and
re-saved them with no channel record and neither header object changed (`stack-summing-ours`,
`stack-summing-resave-logic`), and re-saved two stub-bound ones, and one inside a folder, with
every row, route and stack as written (`stack-summing-stub-*`, `nest-inner-stub-*`, 2026-10-02).

**Where a summing stack's aux outputs, and when Logic makes none (Logic 12.4, 2026-10-03).**
Create Track Stack… (Summing) and Convert Folder Stack to Summing Stack read the members'
outputs. Members that share one output get a new aux that outputs there
(`stack-summing-shared-after-logic`: two of three tracks on Bus 1, `Aux 2` fed from Bus 2 and
sent to Bus 1), inside a summing stack as at the top level
(`nest-summing-in-summing-after-logic`); members on different outputs get one sent to Output
1-2, inside a summing stack too (`stack-summing-differ-logic`, `stack-convert-differ-*`,
`nest-summing-in-summing-differ-*`), so position never decides it. `stack_summing` writes both,
each changed channel record as Logic's but for the minted ids. When the members are all that
outputs to a bus and one aux is fed from it, Logic makes no aux: that bus's own aux becomes the
main track, with no output changed, its track moved to the header's place when it had one and
the folder's name gone (`stack-summing-reuse-logic`, `stack-summing-reuse-track-logic`,
`stack-convert-reuse-*`). Against the save before, that is one arrange row for the aux's own
object (a fresh row, the old one gone), the members' rows one deeper with that object as parent,
the object's colour its members' (16 from 5 and from 40 over tracks coloured 16,
`stack-summing-reuse-colour-*`; a tracking session's aux kept the colour it shared with its
members), and no channel record changed.
Its kind byte stays what it was — 0 on a blank-born aux, 128 on a tracking session's aux track
(`tracking-convert-after-logic`) — so a summing header is told by the rows under it, not by
being a grouping object; an aux in use has its object, its flat
row and its index-table entry already (Mixer > Options > Create Tracks for Selected Channel
Strips adds the row alone, `tracks-aux-track-logic`). `stack_reuse` writes it, at the top level
with the aux's own row at the top level; elsewhere it is refused. The gnoS bytes `+137`, `+222`
and `+232` and the song container's `+177` and `+218` also differ across these pairs and across
unrelated saves alike: view state, left alone. A
bus counts as shared only with a UUID of its own: Logic's output change to an unused bus gives
it one and brings the lowest free `Aux` into use fed from it (`route-out-bus-logic`), and so do
its sends (`send-bus-1-logic`, one aux per bus on `send-two-base-3-logic`). Over two members
on a bus still on its placeholder Logic sent the new aux to Output 1-2
(`stack-summing-placeholder-*`). `bus_return.use_bus` writes Logic's version: the bus's
own UUID, every output, input and send that named the placeholder moved to it, and the aux
through `add_track(arrange=False)` — the stub bound stereo, an object (unselected, stamp step
0x42), a flat row, a sequence triple and its index-table entry, no arrange row. On the
placeholder save it gives Logic's own (`route-out-bus-second-logic`): the same records by tag,
both track lists, the table's objects, and the four changed channel records byte for byte but
for the ids.

### Creating a stack (`logic stack-create`) — composed, not sampled

Logic's own Create Track Stack has not been saved and diffed; `services/arrange/stack_create.py` composes
the measured pieces instead. A folder stack is a kind-0 object bound to a `Sub N` strip, so a new
one gets: the highest folder stack's object cloned (a summing stack is never the pattern) (new id,
name, colour, its Sub number after the name, the channel index of `Sub N+1`, a minted stamp, fresh
UUID, the pattern's icon kept), a `Sub N+1` strip cloned from `Sub N` right after it (`+6 = N+1` —
Subs count from 1 there, Audio and Inst from 0 — the label, the object's UUID at `len-48`, no
destination or input), every later channel owner moved up by one and the count record's `+40` class
counted up; a header row where the first member sat, expanded, the member rows behind it with `+14 =
1`, their objects' `+38` parent and their channels' `+110` stack index set as a drag sets them; and
the flat row, sequence triple, index-table entry and two `gnoS` entries exactly as a track add
writes them; the header ends up selected. **Confirmed in Logic 12.3.1 on 2026-09-02:** a stack made
from two aux tracks on a copy of the Mix template opened as a folder holding both.

**A stack inside a stack** (Logic 12.4's own Create Track Stack over two of a folder's three
members, 2026-10-02, `nest-inner-folder-logic` and `nest-inner-summing-logic`): the header's row
takes the members' depth and theirs go one deeper. A folder's new `Sub` strip keeps stack index
0 and its members take the new Sub number; no parent pointer is set. A summing header's object
takes the enclosing stack's object as its parent, its `Aux` strip keeps stack index 0, and the
members keep the enclosing Sub's number and take the header as parent. `stack-create` writes
both from direct members of one stack; Logic showed an outer folder holding a written summing
stack and a written folder, and re-saved every row, route and stack as written
(`nest-inner-ours`, `nest-inner-ours-resave-logic`). With the Sub header itself selected Logic
wraps the stack in a new one (`nest-stack-in-stack-logic`), which is not written. There the inner
`Sub` strip takes the outer stack's number at `+110` and its members keep the inner one; a folder
made inside a folder (`nest-inner-folder-logic`) leaves its strip at 0.

**The pattern.** The structures come from the session's highest-numbered folder stack; a
session with none takes Logic's own first stack, packaged (`stack-folder-12.3.1.json`,
`stack-summing-12.3.1.json`). A new `Sub` strip carries the project's own words (`+28` to
`+42`): Logic rewrote `+42` on two strips written with the pattern's.

### The writers — atomic pieces, and the commands over them

Every write is one function on `bytes` that validates its input and output, so an
orchestrator can chain them in any order. The pieces a new track or stack is made of:

| module | what it owns |
|---|---|
| `recbuild.py` | a record header over a new payload; owner/key/slot restamps; UUID minting |
| `tracklist.py` | `karT` runs, the arrange and flat lists, a new row, renumbering |
| `sequence.py` | the `qeSM`/marker/`qSvE` triple and the index table (`plan_sequence`) |
| `table_index.py` | each table entry's index as its object's place in mixer order (`sync_indices`, `index_errors`) |
| `registry.py` | the two `gnoS` entries and the selection fields |
| `channel_alloc.py` | binding an `Audio N` stub; a new `Inst`/`Sub` channel; owner shifts; the count record |
| `environment.py` | object cloning, the next object id, parent and colour |

The capabilities over them, one command each: `addtrack.py` (`add-track`), `stack_create.py`
(`stack-create`), `reorder.py` (`reorder`), `environment.set_colour` (`colour`),
`environment.rename_track` (`rename`), `stacks.set_hidden` (`hide`), `routing.py` (`route`),
`sends_write.py` (`send`), `transplant.py` (`transplant`, `bypass`), `stripsave.py`
(`strip-save`), `transplant.remove_slots` (`clear-slots`), `levels.py` (`levels`),
`stacks.move_to_stack` (`stacks --move`). Rename and
hide are decoded from reads only — no Logic save of either has been measured. The CLI
side is `_apply.py` (channels) and `_apply_tracks.py` (tracks) over `_edit.edit_copy`, which
copies the project — the whole folder when the bundle has an `Audio Files` sibling, so the
recordings come along, and without `Alternatives/*/Autosave`, which Logic would offer on open
in place of the edit — and runs one step over every ProjectData; the input is never written.

### Track header components — `DisplayState.plist`, not ProjectData

The arrange window's header configuration (the `Track Header Components` submenu / Configure
Track Header popover) lives in the 312-byte `ArrangeCLgUserData` blob under
`screensetDictArray[0]/layoutDictArray[0]/docwWindowState/udataArrange` in
`Alternatives/NNN/DisplayState.plist`, and again as the same blob inside `DisplayStateArchive`.
Measured on seventeen Logic 12.3.1 saves of one project, one component toggled per save
(2026-09-04), and again on seventeen saves of a blank project (2026-09-12): every bit the same
on both, the width formula corrected by the second set. Each save changes exactly one bit and
the width:

| offset | meaning |
|---|---|
| `+38` | u16 header width in pixels: the name column's width plus the shown components' widths (On/Off, Mute, Solo, Protect, Freeze, Input Monitoring 22 each; Record Enable 26; Volume 128; Pan/Send 25; Control Surface Bars 5; Track Numbers 12; Track Icons 30; the rest 0), never below 180. The name column is per project — 109 on the first project measured, 33 on a blank one — and is stored nowhere else, so the writer takes it from the file's own width |
| `+58` | bit 3 = Track Numbers **hidden** |
| `+68` | bit 1 Volume, bit 2 Pan/Send, bit 3 On/Off, bit 4 Groove Track, bit 5 Track Alternatives (set = shown) |
| `+70` | bit 0 Mute, bit 1 Record Enable, bit 2 Solo, bit 3 Track Icons, bit 5 Additional Name Column, bit 7 Input Monitoring, bit 8 Track Protect, bit 10 Freeze, bit 12 Color Bars (set = shown); bit 14 Control Surface Bars **hidden** |

ProjectData does not change with a toggle. `services/stream/header.py` reads and writes the set
(both files, width recomputed); `logic header PROJECT` prints it, `--show/--hide NAME` and
`--from OTHER` write a copy. The writer reproduces Logic's words and width on all sixteen
toggles, and a written set opened in Logic showing every component as set (2026-09-04).

### Control bar and display — `DisplayState.plist`, not ProjectData

The set the main window's control bar shows (Customize Control Bar and Display…) lives in
each alternative's `DisplayState.plist` under `screensetDictArray/layoutDictArray/
docwWindowState/transportLayoutDict`, mirrored in `DisplayStateArchive`. Five lists of
button ids, one per column of the popover; a control that draws two buttons carries two ids. A
list keeps the order it was stored in, and a newly ticked id lands after the last present id
of lower canonical rank (at the front when none is lower) — so two projects can hold the same
set in different orders and both draw the same. Measured on fifty Logic 12.3.1 saves of one
project (2026-09-04) and fifty of a blank project (2026-09-12), one control per save; the
second set corrected MIDI Activity's rank, which the first project had stored out of order:

| List | ids |
|---|---|
| `CLgTransportBtnsViewLeft` | 100 Library, 101 Inspector, 102 Quick Help, 103 Toolbar, 104 Smart Controls, 105 Mixer, 106 Editors |
| `CLgTransportBtnsViewRight` | 107 List Editors, 108 Note Pad, 109 Apple Loops, 110 Browsers |
| `CLgTransportBtnsTransport` | 6-10 Go to Beginning / Position / Left Locator / Right Locator / Selection Start, 1-5 Play from Beginning / Left Window Edge / Left Locator / Right Locator / Selection, 11 Rewind, 12 Forward, 13 Stop, 14 Play, 15 Pause, 16 Record, 50 Free Tempo Recording, 17 Flashback Capture, 35 Skip Cycle, 38 Cycle |
| `CLgTransportBtnsDisplay` | 18 Positions, 19 Locators, 21 Tempo, 22 Time Signature, 23 MIDI Activity, 24 Performance Meter, 20 Sample Rate / Buffer Size, 46 Varispeed, 51 Key Signature, 52 the Left/Length radio (absent = Left/Right) |
| `CLgTransportBtnsModus` | 30 Master Volume box, 53 with it = its popup on Output Meter, 44 Sync, 42 Replace, 39 Autopunch, 40+41 Set Punch In/Out by Playhead, 25 Software Monitoring, 26 Auto Input Monitoring, 28 Pre Fader Metering, 29 Low Latency Monitoring, 31+32 Set L/R by Playhead, 33+34 Set L/R Numerically, 36+37 Move Locators by Cycle Length, 46 Varispeed (again), 47 Tuner, 43 Solo, 48 Count In, 45 Metronome Click |

The LCD's own mode (the chevron menu, or the popover's Display popup) is
`udataTransport/DisplayMode`: 0 Custom, 1 Time, 2 Beats, 3 Beats & Time (Large), 4 Beats &
Project (Large), 7 Beats & Project, 8 Beats & Time; `CLgTransportDisplayMode` is the popover's
copy of it, synced when the popover opens. `UseSMPTEViewOffset` sits beside it. The toolbar's
own set is the separate `actionBarLayoutDict`, below.

`logic controlbar PROJECT` reads it; `--out DIR --from OTHER` copies the whole bar and LCD
mode onto a copy, `--show/--hide NAME` switches controls by name (`services/song/controlbar.py`
writes both files, lists re-sorted the way Logic keeps them). **Confirmed in Logic 12.3.1 on
2026-09-04:** a bar copied from the fifty-first save onto the base project came up with that
set.

### Toolbar — `DisplayState.plist`, beside the control bar

The row under the control bar (Customize Toolbar…) is `docwWindowState/actionBarLayoutDict/
CLgActionBarBtns`, one list of button ids, mirrored in `DisplayStateArchive`; whether the row
shows at all is `docwWindowState/transportBarRows` (1 = control bar alone, 2 = with the
toolbar). Every id was pinned on seven Logic 12.3.1 saves of one project (2026-09-07 — one
with every button on, one with the fourteen a template never shows, and five with the boxes
whose position down the popover's columns has bit N set): in the order Logic writes them, 8 Bounce,
21 Move to Track, 13 Export, 29 Move to Playhead, 7 Import Audio, 52 Nudge Value, 14 Groups,
30 Lock/Unlock SMPTE, 44 Group Clutch, 33 Repeat Section, 40 Automation Quick Access, 34 Cut
Section, 36 Learn, 35 Insert Section, 63 Articulation, 22 Insert Silence, 4 Track Zoom, 61 Note
Repeat, 58 Shuffle, 62 Spot Erase, 46 Previous/Next Marker, 16 Split by Playhead, 15 Set
Locators, 17 Split by Locators, 45 Zoom, 38 Crop, 6 Colors, 20 Stretch to Locators, 18 Remove
Silence, 19 Join, 39 Bounce Regions. The order is the popover's reading order, not the row's:
a template's own list came in another order and drew the same. **Confirmed on 2026-09-08:**
a set written by `logic toolbar --out DIR --show Crop --show Bounce --hide Colors` came up in
Logic as those eighteen and was re-saved with the list unchanged. `--from OTHER`
copies another project's set and row flag; `--row show|hide` is the flag alone;
`apply-template` copies the template's along with the control bar.

### Logic's own settings — `com.apple.logic10.plist`, not the project

Some of what a template seems to carry is not in it at all. The pointer becoming a marquee
over the lower half of a region and a fade tool at its edges is Logic Pro > Settings >
General > Editing (*Fade tool click zones*, *Marquee tool click zones*), one setting for the
whole machine, stored in `~/Library/Preferences/com.apple.logic10.plist` as
`FadeToolClickZones` / `MarqueeToolClickZones` (with `TakeClickZones` for Quick Swipe). Every
project on the Mac behaves the same; nothing in the bundle changes with them (checked: the
Mix template's files hold no such key).

`logic prefs` reads the settings `services/song/prefs_table.py` names, key by key through
`defaults` (the whole-file XML export needs its control characters stripped first);
`--pane View` lists one pane, `--set 'Marquee tool click zones=on'`, `--apply FILE` and
`--export FILE` write and carry a set, and `--controlbar-from PROJECT` makes a project's
control bar the default for new ones (`CLgTransportDefaultConfiguration`, the same five lists
a project carries). Writes go through `defaults write` and are refused while Logic runs,
since Logic writes its own copy back on quit; a copy of the file is taken first.
`LOGICXKIT_LOGIC_PREFS` points the file reads at a copy instead of Logic's own.

The table holds 150 settings over every pane of the window, each pinned by changing that one
control and closing the window — the close is when Logic flushes — then diffing the
preferences (General > Editing on 2026-09-05, the rest on 2026-09-08, driven through the
accessibility tree). What the keys look like, by kind:

| Kind | Example | Stored as |
|---|---|---|
| bool | `FadeToolClickZones` | a boolean; keys ending `_n`, `Disabled`, `Hide…`, `Lock…` hold the box *unticked* |
| int, float, str | `UndoSteps`, `DimLevel`, `MyInfoComposerName` | the number or text; `GlobalMIDIDelay` is in microseconds, `VideoToSongAdjust` 16 per frame |
| choice | `RightButtonFunction` | the item's index — or its own value where measured: `MaxAutoBackups` the count, `SampleAccurateAuto` -1/0/1, `RecOptMidiCycle` 1/2/8/4/5/9, `LevelMeterReturnSpeed` the dB/s as a negative float, `NSRecentDocumentsLimit` absent for System Default |
| bit | `MIDIResetExternalInstruments` | one byte of flags (0x01 Control 123 … 0x80 Pitch Bend), sign-extended, so all-but-two reads -4 |
| databit | `Automation.WriteBits` | a 16-byte blob; byte 1 holds Volume 1, Pan 2, Mute 4, Send 8, Plug-in 16, Solo 32 |

Two popups are pairs of booleans rather than one key: what happens to the open project when
another opens (`AlwaysCloseDocumentWhenOpeningAnotherOne_n` + `AskToCloseDocument_n`) and
the track and marker colour modes (`AutoColorCST24`/`96`, `AutoColorMarker24`/`96`). Not
carried: Audio > Devices (never touched), Plug-in Delay Compensation (Logic asks "Are you
sure?" first), Software monitoring and MIDI Sync's two "All" boxes (the close flushed
nothing), the sliders that would not move, and every Control Surfaces control — those live in
`~/Library/Preferences/com.apple.logic.pro.cs`, Logic's own binary file, not a preference
domain. The crossfade sliders write `CrossfadeSettings.LeftTime`/`.LeftCurve` with a derived
`.TotalSamples` beside them, so the table leaves all three to Logic.

### `apply-template` — the orchestrator over the writers

`logic apply-template TEMPLATE SESSION --out DIR` (`--plan` to only print) pairs the
template's tracks with the session's (`services/mixer/pairing.py`: the Environment object id first —
sessions cut from a template keep them — then the mixer label, then a unique name), plans the
difference as ops, and runs them in order through the atomic writers, each validated:
structure (tracks to add, stacks to make, rows to move into stacks, arrange order), then the
track fields (name, colour, hidden), then the channel fields (width, plugin chain, strip
reference, output, input, sends, fader and pan). What no writer can do — remove a track or
its slots or sends, move a row out of a stack, add an aux — is listed as refused, not
guessed. `--keep-levels` leaves faders alone; `--skip chains,refs,...` leaves out kinds;
`--track NAME` / `--stack NAME` restrict it to those rows (a stack's members), which is how a
mix template lands on the drums alone. Where the template channel carries no slots the
session's are removed (`clear-slots` does the same by hand). On
the sessions on hand the plan is fields only: every one was cut from the Recording
template and still pairs every row by object id (`orchestrators/apply_template.py`).

**Old projects and alternatives.** A project saved by Logic Pro X reads with no track names (its
Environment objects are not found); opening a copy in Logic and saving rewrites only the *active*
alternative in the current layout — switch to each other alternative and save it too, or remove the
stale ones in Edit Alternatives. Such a save has no `ArrangeCLgUserData`, so the header copy is
skipped with a note. One map serves every alternative of a project: it is drafted from the first
alternative, which must fit or nothing is written, and a later alternative whose tracks the map does
not name is left as it was, byte for byte, with a note. Converted 2026-09-08: a 10.4.4 project and a
12.3.1 one carrying a 10.4-era alternative.

A project of another lineage is refused (across lineages the label rule pairs whatever shares an
`Audio N`) unless a **map file** says how its tracks pair: `--propose-map FILE` drafts one from the
names — same name, then a numbered prefix with the DI preferred (`Guitar 1` -> `Gtr 1 DI`), then
shared words, kinds never crossing — with a confidence per line for a person to correct; `--map
FILE` applies it, pairing only by the map, object id and exact name. The map's keys are resolved to
object ids once, against the session as given, so a `Name (Sub N)` key still pairs after the run's
own stacks renumber the Sub strips. Session tracks mapped to `(none)` are left alone — no rule may
claim them, not even a matching object id; template tracks nobody maps to are added where a writer
can, and the rows an earlier structural round made stay paired with the template row they stand for
(object id, not name — a new `Drums` aux beside a legacy `Drums` aux would otherwise be added again
every round). A session stack counts as the template stack its header pairs with, whatever it is
called.

**Confirmed on the legacy songs (2026-09-04):** each migrated onto the Mix template — the drum,
MIDI, bass, guitar and vocal stacks made, every template track added, chains, references, routing,
sends, levels, colours and hidden rows applied — and Logic's own re-save of each returned the
identical row list. What stays refused: sends the legacy session has and the template lacks (never
removed), and inputs past the session's count. Groups follow the template (see Groups). Three things
a legacy migration has to get right: **slot keys** — some projects start their plugin slots at key
2, not 4, and the 2020 song did so with a channel carrying three sends, so key 2 was a send and a
slot at once; `apply-template` first moves every key from the slot base up by two on that collision,
as Logic's own re-save of that song did (`services/mixer/slotkeys.py`). A project born in Logic 12.3.1
also sits at base 2, with no collision, and Logic keeps it there — it undid a rebase forced on a
blank project (2026-09-12), so the move is never applied without the collision. Every slot writer
reads the project's own base (`slot_index_base`, a majority vote over its native chunks and XML AU
states), so a transplanted chain replaces the old one instead of sitting behind it (Logic loaded
both: two amp sims in series, two drum instruments on one channel, prompts for plugins the old chain
used). The rebase also stamps the base into every channel record: the u16 at +28 of a channel's
`OCuA` is the slot base it was written with, 2 or 4 to match the slot keys, and left at 2 under keys
that sit at 4 Logic drops the plugin at slot 0 on any channel that also carries three sends. Stamped
4, the same file keeps them, and the 2020 song migrates in one pass (2026-09-06). A third send
written into a base-2 project collides the same way — Logic dropped the Channel EQ in slot 1 of four
channels apply-template gave a third send — so the send writers move the project to base 4 first,
each send ahead of the slots (`legacy-migrate-fixed-*`, 2026-09-24); **send destinations** — a
send's `+20` counts from the project's device input count, not from 31 (`sends.send_base`);
**mixer-only returns** — a legacy song returns its buses through auxes that have no arrange track,
and once a template aux track returns the same bus the old return is silenced (`return` op: input
cleared, slots removed), or every bus plays twice; **unfed auxes** — a template aux with no input
(the instrument-fed Drums MIDI outputs) now clears the input of its session twin instead of leaving
the aux-add default of `Input 1-2`, a live hardware input; **instrument outputs** — the Drums MIDI
auxes take the drum instrument's hi-hat, overhead and room outputs (see "Instrument outputs" below),
and a legacy aux taking the same output is unbound. The map file also takes `+`/`-` lines: template
tracks nobody maps to are listed with `+` (added) and a `-` leaves one out — the MIDI-drum songs
leave the seventeen drum audio tracks out and alias their legacy Drums stack to the template's Drums
MIDI stack. A send is a 76-byte record; a project whose plugin slots start at key 2 carries kilobyte
slot records under the send keys, and `read_sends` leaves those alone.

### Stack membership is positional, and the pointer confirms it

A stack owns the tracks that **follow it in the arrange list**, up to the next stack — or up
to the first aux/output row with stack index 0 that is not switched off (`0x20000000`; the trigger
auxes inside Drums MIDI carry that bit; the aux tracks after Vox do not). Dragging a track in
does three things, all of which `move_to_stack` reproduces:

1. the arrange row moves into that stack's span (measured: a guitar track went position 33 -> 22,
   landing among the overheads; a room mic 24 -> 27, landing among the bass tracks)
2. `ivnE+38` is stamped with the stack's object id (u32) — 192 for a Drums folder whose own
   object id is 192, 196 for Bass
3. the track's mixer channel gets the stack's Sub number at `+110`

What it does not reproduce: a real drag also bumps index tables in two `qSvE` records —
unmeasured, so a moved copy is verified in Logic before it is trusted. Tracks that were never
dragged read 0 at `+38`, so the pointer confirms membership without establishing it.

**Adding a track is solved** (`logic add-track`, audio; see "What a track add writes"). A track
is far more than its two records: the flat-list row, the sequence triple, the index-table entry
and the two `gnoS` registry entries all have to exist and agree.

### Channel fader, pan, mute and solo — `OCuA`

| offset | meaning |
|---|---|
| `+6` | the channel's own number (`0` is "Audio 1"); label at `+60`, NUL-padded |
| `+116..119` | fader as u32, **8.24 fixed point**; `+85` and `+119` repeat its integer part (0-127) and all three must agree, and do on every record measured. `levels` copies the exact value |
| `+89` | pan 0-127, 64 centre; Logic displays it as `byte - 64` |
| `+90` | bit 0 mute (`mute-audio-1-logic`); bit 1 on every channel a solo elsewhere silences, a muted one included |
| `+88` | bit 0 solo (`solo-audio-2-logic`); bit 2 on Master and Output 1-2 while a solo is on; bit 1 unread, set on two channels of a blank project |

Verified against Logic's mixer, byte -> dB: 47 -> -11.3 · 60 -> -7.1 · 90 -> 0.0 · 92 -> 0.4 · 94 ->
0.8 · 99 -> 1.8 · 110 -> +3.4. The taper is the send knob's law, `dB = 40 · log10(position / 90)` on
the 8.24 word at `+116`: Logic 12.4 saved fader steps showing −16.6, −6.4, −5.3 and 2.7 dB as
exactly the law's words (`fader-step-*`, 2026-10-02). The fader moves in 234 steps and its readout
works on them: where a step sits between marks the label is the mark below — the step shown as −6.0
stores −5.98 dB — and a level written between steps, which Logic keeps as written, reads up to 0.1
dB low (an exact −6.0 reads −6.1; −5.3, a step, reads −5.3). A folder stack's fader is its `Sub N`
strip's — confirmed in Logic on 2026-09-01 (Drums at 60 read -7.1, Guitar at 110 read +3.4, nothing
else moved). Some channels — Auxes, Insts, Output — carry an **all-zero UUID sentinel** instead of a
real one, so a clone must leave it alone.

## `strip-save` — export a channel as a `.cst`

```bash
bin/run logic strip-save "Song.logicx" --channel "Audio 1" -o "/path/to/Kick.cst"
```

Logic's own *Save Channel Strip Setting as…* is the channel's `OCuA` record plus every `UCuA`
satellite (slots, sends, properties), owners zeroed, `+8..9` set to the marker `0x1235`,
`+112..113` a value Logic mints, then a constant 14-byte `OCuA` stub with owner 1. Measured
against a strip Logic saved from the same channel at the same moment: byte-identical once
the minted id and the provenance name (Logic writes the label from *before* the save renamed
it) are supplied. Plugin slots were identical without help. Never writes into the library.

## `pst` — single-plugin settings, no routing attached

```bash
bin/run logic pst config/example-psts.json      # add --overwrite to replace existing
```

A `.pst` is exactly **one GAMETSPP chunk at offset 0** — no `OCuA` header, no sends, no output bus.
That makes it the surgical alternative to a `.cst`: loading a channel strip setting replaces the
channel's whole routing, while loading a `.pst` into a plugin slot changes only that plugin. For
applying tracking values to an existing mixer (buses especially, where no donor strip exists at all)
this is the safe path. Presets are built by patching Logic's own factory `#default.pst`, so length
and trailing internal state stay exactly as Logic writes them.

Spec: `{"output_dir": …, "presets": {"<name>": {"eq": {…}, "comp": {…}, "limiter": {…}}}}` — each
plugin lands in its own Logic folder (`Channel EQ/<name>.pst`, `Compressor/…`, `Limiter/…`).
Existing files are never overwritten unless you pass `--overwrite`.

**Limiter** parameters (index == Apple's own `parameterID`, from Logic's `Limiter.plist`):
`[1]` Gain dB · `[2]` Lookahead ms · `[3]` Softknee · `[4]` Release ms · `[5]` Output Level dB ·
`[6]` Gain Reduction · `[7]` True Peak Detection · `[8]` Mode (0 Legacy, 1 Precision).

## Usage

```bash
# build all strips defined in a spec into its output_dir
bin/run logic build  config/example-strips.json

# replace .cst files that already exist (without this they are kept)
bin/run logic build  config/example-strips.json --overwrite

# round-trip check a spec without writing files
bin/run logic verify config/example-strips.json

# dump a strip's EQ/Comp params (human readable)
bin/run logic decode "/path/to/Some Strip.cst"

# emit a JSON spec entry from an existing strip (for editing + rebuild)
bin/run logic decode "/path/to/Some Strip.cst" --json
```

⚠️ **`build` writes into Logic's own library by default.** A spec's `output_dir` is never
resolved against the process's working directory: an absolute (or `~`-prefixed) path wins, and a
**relative** one hangs off the strip root, which defaults to `~/Music/Audio Music Apps/Channel
Strip Settings` — Logic's live channel-strip library. Give an absolute `output_dir`, or set the
spec's `strip_root` (or `LOGICXKIT_STRIP_ROOT`), to write anywhere else. An existing `.cst` is
kept and reported as skipped unless you pass `--overwrite`, which replaces it. `pst` resolves
the same way against `output_root` / `LOGICXKIT_AUDIO_MUSIC_APPS`.

Then in Logic: right-click a channel strip → **Load Channel Strip Setting…**

## `chains` — apply native tracking chains to a project

```bash
bin/run logic chains <project> --out <dir> --config config/example-chains.json
```

When the chains to copy live in a mix session rather than in saved strips, `tracking-chains
PROJECT --out DIR` derives them in place: each third-party slot becomes Logic's own of the same
family through the translation maps, with its settings, side chain and lanes carried; a
plug-in with no native analogue is removed and a native carrying lookahead is bypassed. What
comes out is a project, so Logic can save it as the tracking template.

Copies a project (APFS clone, so a multi-GB song folder with its `Audio Files` sibling is
instant and costs no disk) and gives its channels native low-latency chains. **This is the
command that actually changes what a channel sounds like** — see "References are labels, not
loaders" above for why repointing a `.cst` reference does not.

Channels are matched by the channel-strip **reference** they carry (`Kick In.cst`), so one
config works across every session regardless of channel numbering. Donors are cloned from the
target project itself wherever possible, which keeps the class version right automatically.

### Where values come from

A chain naming a `strip` takes **every parameter float** from that saved `.cst`, verbatim.
A strip built only from native plugins already *is* a low-latency chain, so the tracking-specific
change is bypassing whichever of its plugins carries lookahead. Deriving a curve from a JSON
description instead gives audibly different EQ: a description rounds a surgical narrow cut into a
generic one and widens the Q, so the built chain does not match the strip it names.

A JSON `eq`/`comp` block is the fallback for a channel with no native source anywhere — one whose
strip is entirely third-party, or a bus carrying no native dynamics. Setting both on one chain is
refused as ambiguous.

The whole float array is copied, not the 33/14-float prefix `build_eq`/`build_comp` emit: the
per-instance id lives past the chunk, so every float in it is a parameter.

Donor and strip play different roles — the donor supplies a record of the project's own class
version, the strip supplies the values. Take a donor verbatim and a **factory** plugin lands in
the project instead of the strip's, with every slot count and structural check still passing.

Config shape:

```jsonc
{
  "strip_root": "~/Music/Audio Music Apps/Channel Strip Settings",
  "donors": {                                  // plugins present in no session
    "gain_invert": { "cst": "…/Snare Down.cst", "type": 183 }
  },
  "chains": {
    "Snare Down.cst": {                        // keyed by the reference the channel carries
      "label": "Snare Btm",
      "strip": "Track/Tracking/Drums/Snare Down.cst",   // values, verbatim
      "pre":   ["gain_invert"],                // slots ahead of the EQ
      "env":   true,                           // Enveloper between EQ and compressor
      "bypass": ["env"],                       // inserted, but off — lookahead is latency
      "post":  []                              // slots after the compressor
    },
    "Vox - Lead.cst": {                        // no native source exists for this one
      "label": "Vox",
      "eq":   { "hpf": {"freq": 90} },
      "comp": { "circuit": "VintageVCA", "threshold": -19, "ratio": 2.5,
                "attack": 22, "release": 140 },
      "_invented": "this channel's strip is entirely third-party — this chain is derived"
    }
  }
}
```

A `pre`/`post` slot whose plugin the strip also has takes the strip's values; one the strip
does not have (an FX-return reverb) keeps the donor's dialed values. Adding a plugin is a
config edit, not a code change.

### Class-version retargeting (derived — verify before trusting)

No v3 project on disk holds a native algorithmic reverb, so v3 sessions could not be given one.
`donors.retarget_version` derives a v3 record from a v5 one. The schema delta is exactly three
things, measured by diffing the library's own v3/v5 pairs:

| | v3 | v5 |
|---|---|---|
| payload `+0` schema constant | 464 | 424 |
| payload `+116` plugin-variant id | absent (0) | present |
| trailing bytes after the parameter chunk | *n* | *n* + 4 |

Downgrading reproduced every real v3 donor with **no unexplained structural bytes**. Two limits
are enforced:

- **Upgrading is refused.** v3→v5 would have to invent the plugin-variant id, which selects the
  mono/stereo build; a wrong one is worse than no donor.
- **A plugin whose float count changed between versions is refused.** Klopfgeist has 14 floats
  at v3 and 15 at v5 with no trailer, so its 4-byte delta is a *parameter*, not schema slack —
  dropping it would truncate the chunk while its count word still claimed the old length. The
  guard requires ≥4 bytes of trailer after the chunk.

It stays an inference for any plugin with no v3 counterpart to check against, so the run prints
a warning naming every derived donor and such a project must be opened in Logic before it is
trusted. Re-saving the session in Logic (which migrates it to v5) is the certain alternative.

### Two checks that run on every build

- **shape** — a strip-sourced chain must reproduce that strip's plugin order, so a config that
  silently omits a plugin the strip carries is caught.
- **values** — after the records are written, `verify_strip_values` reads the result back and
  compares every strip-sourced float to its strip. A mismatch aborts the write. Slot counts
  and structural validation can both pass on a project that carries a factory plugin, so
  success is measured by reading the artifact, not by the report.

A shorter source chunk than the donor holds (the guitar bus EQ on hand is 51 floats where the
drum strips are 52) is reported rather than silently written as a partial copy.

The run reports which references matched, which are configured but absent from this project,
and which wanted a plugin with no donor available, so a silent no-op is impossible.

## `project` — read-only `.logicx` analyzer

```bash
# inventory a whole song/template: per-channel chains, AU preset names, native params
bin/run logic project "/path/to/Song.logicx"
bin/run logic project "/path/to/Song.logicx" --json
```

Walks the channel-strip (`OCuA`) blocks inside `Alternatives/000/ProjectData` and prints,
per channel, the **insert chain** with **AU preset names**, **decoded native (Channel EQ /
Compressor) params**, and the **`.cst` reference** (`⟨loads Kick In.cst⟩` — which saved
strip the channel loads; clean-save templates carry refs with no embedded state, so this IS
their wiring map), plus project metadata and the track-name table. Channels are labelled by
strip type — `Audio N`, `Aux N` (the bus chains — Logic's raw `Bus` objects carry no
inserts), `Inst`, `Input`, `Output`, `Master`.

**Read-only.** The writing commands (`chains`, `levels --to`, `stacks --move`, `retrack`) work
on a copy under `--out`; every service validates its own result. Capability by layer:

| Layer | Read |
|---|---|
| Insert chain (plugin order) · AU preset names · track names · project metadata | ✅ |
| Native (Channel EQ / Compressor / Gain) param values | ✅ — but finished 3rd-party mixes use almost none |
| 3rd-party knob values (FabFilter / iZotope / Neural / Ampeg / …) | ✅ via `logicxkit au strip` (AU-host decode); here: preset *name* only. sonible/Waves partial — see `au` README |
| Sends / output bus / fader / pan | ✅ `logic manifest` — fader in dB and pan (`+116` u32, `+89`), output (tail UUID), sends with their level in dB, mode and bypass |

```bash
bin/run logic manifest "Song.logicx" [--json]        # tracks, stacks, channels from decoded fields
bin/run logic recdiff A B [--baseline X Y] [--json]  # positional record diff of two saves
```

## `arrangement` and `tempo` — the arrangement track and the tempo track

Both are sequence triples near the head of ProjectData whose `qSvE` payload is 16-byte
lines (`services/song/events.py`): a line whose byte 7 has its top bit clear starts an event
(type u32 at +0, tick u32 at +4; 960 ticks per quarter, bar 1 at tick 38400), a line whose
byte 7 has the top bit set continues the event before it (0x88 is the data line; 0xb4 and
0xb1 carry a tempo curve), and type 0xf1 at tick 0x3fffffff ends the sequence.

**Arrangement** (`services/song/arrangement.py`): events of type 0x12, one per section. The data
line holds the slot of the section's `qSxT` text record at +0, the section kind at +8
(0 custom or intro, 1 verse, 2 chorus, 3 bridge, 4 outro) and the length in ticks at +12.
The text record's name is NUL-terminated UTF-8 at +98, or an RTF document whose text is the
name: the form Logic's own rename writes (a marker's in the Marker List, a section's through
Rename…), with `\'hh` for a cp1252 byte and `\uN` for a UTF-16 unit, two for a character past
the BMP (`services/song/rtf.py`). Logic showed a plain UTF-8 name written here and re-saved the
record byte for byte (`names-text-*`, 2026-10-02).
Every section of one song, with quarter-bar lengths, reproduced Logic's display exactly.

**Tempo** (`services/song/tempo.py`): `gnoS +110` is `bpm × 10000` — the tempo the LCD showed
when the song was saved — and +114 the tempo at bar 1 (+198 repeats it). Events of type
0x60 carry `bpm × 10000` at data +0; a head flag 0x40 marks a point Logic generated for a
ramp (one every 480 ticks); data +8 is the point's time in 1/2000 s from Logic's SMPTE origin
(01:00:00:00 = 7 200 000 at bar 1), which Logic's own list points and curve runs carry to the
digit. A step Logic draws from the tempo track is two events one tick
apart with 0xb4/0xb1 lines; one added from the Tempo List is a single bare event. Matched on
every song on hand, ramps and steps included. The 0xb4 line's four fields are
undecoded. The event type is the u16 at +0: a change Logic added carried a nonzero word at +2.

Edits (`--out` required, on a copy): `arrangement --rename N=NAME`, `--move N=BAR`, `--length
N=BARS`, `--delete N`, `--add BAR:BARS:NAME[:KIND]` (N as the listing numbers the sections), `tempo
--set BPM` (the bar-1 event and every `gnoS` word that held its old value) and `tempo --add
BAR=BPM`. A renamed section's text record is rebuilt plain (`arrangement_write.py`); Logic's re-save
of a rename plus a resize kept both byte for byte (2026-09-06), a move plus a delete came back from
Logic's re-save event for event (2026-09-07), and `tempo --set 180` showed on Logic's LCD and
survived its re-save. `--add BAR:BARS:NAME[:KIND]` makes a section the way Logic's own add did: the
name record takes the lowest free multiple-of-4 slot among the `qSxT` records — their own slot
space, the registry is untouched — with the head Logic writes for a fresh one
(`section-text-12.3.1.json` under the data root, form word 0x14), sits in slot order among them, and
the event joins the sequence in tick order. Ours reproduced Logic's add record for record, and
Logic's re-save of a section and a tempo change we added kept both. `tempo --add BAR=BPM` writes
what Logic's own added change was: one bare 32-byte event — no curve lines — with the bpm word, `40
88` at +22 of the data line and the point's time word at +8, the same word Logic's Tempo List wrote
for its own point on the blank project (2026-09-14). The word at head +2 is 27511 (0x6b77) on the
three points the Tempo List added to the owner's song (bars 118, 111 and 103, 2026-09-16) and 0 on
the two it created on the blank, on ramp points and on bar 1 — so it is not the mark of a created
point; meaning unknown. Ours writes zero, which Logic accepted. Head +15 bit 0 is set once the list
edits a point; cleared by hand and re-saved, Logic left it cleared (2026-09-17), so it is edit
state, not something Logic reads back. `tempo --ramp BAR=BPM:BAR=BPM [--density N]` writes what
Logic's Tempo Operations "Create Tempo Curve" writes (linear, 1/8, continue with the new tempo): one
plain event per division from the start bar to the end bar, each holding the tempo at the middle of
its division, the last one the end tempo exactly, no curve lines. Logic's re-save of ours kept all
sixty-six events and rewrote only their time words, then still a guess. A curve drawn by hand on the
tempo track is the other shape — ramp points flagged 0x40 with a 0xb4 curve line on the first — and
is read only. Adding a section needs an index-table slot for its text record, and adding a tempo
change the 0xb4 curve line — both unmeasured, so neither is offered.

**Signature track and project settings** (`services/song/signature.py`, `settings.py`,
`signature_write.py`; `logic signature PROJECT [--out DIR --time N/D --key KEY --division N]`).
The first sequence triple is the signature track. Type 0x30 events are time signatures:
numerator at head +12, denominator's log2 at +11, the bar index as i16 at data +8 (bar 1 = 0,
negative before it) and bar 1's tick at data +12; the first one sits on the earliest bar line
before bar 1 (tick 0 for 4/4, 960 for 3/4). Type 0x32 events are key signatures: head +12 is 7
plus the number of sharps, with bit 0x10 set for a minor key (C major 7, G major 8, A minor
0x17, E minor 0x18); the song record's root at +179 is the key's own tonic (A minor 9). Bit 7 of
head +15 marks the event Logic last edited. In the song record, `gnoS +192` is the LCD's
division as the popup's index (/16 = 7, /32 = 9, /48 = 10), +480 the ticks per division, +179
the key's root in semitones above C; each repeats 700 bytes on. Measured 2026-09-06 on Logic's
own edits of a 5/4 song: 5/4 to 3/4 at bar 1 (Logic re-snapped a later 4/4 change to the next
bar line of the new meter, so `--time` refuses songs with later changes), C to G major, /32 to
/48; A minor and E minor (2026-09-07). `--key-at BAR=KEY` and `--time-at BAR=N/D` add changes
after bar 1 the way Logic's Signature List does: a key change is a bare 0x32 event with its own
tick at data +12, a meter change a 0x30 event with the bar index at data +8 and one empty
continuation line; Logic's re-save of ours kept all four events byte for byte. Logic's own
Signature List on the blank project (2026-09-14, `signature-meter-created-logic` …
`signature-key-a-minor-logic`): Create with the playhead at bar 5 beat 3 made a 5/4 on the next
bar line, bar 6, and with the type set to Key an F major at the playhead itself; a Tempo List
Create made a point at the playhead. Those events match ours byte for byte but for two words:
head +15 is 0x80 on the event just created and gains bit 0 once the list edits it (ours write
0x01), and data +12 holds the playhead's tick on a created meter change and 0 on a created key
change, where ours write the event's tick. A meter change made equal to its predecessor is
dropped by Logic on the next edit.

**Channel records past a session's count** (`services/mixer/channel_alloc.py`,
`services/arrange/inputs_create.py`; `add-track` and `apply-template` use them). When no `Audio N` stub
is free, a fresh 201-byte channel (`audio-channel-12.3.1.json` under the data root) goes where
Logic puts one: at the first bare stub's place, or after the last `Audio`, numbered by position;
the `Audio` strips behind it are renumbered, every later channel owner and every object bound
above it moves up one, and the count record gains one Audio. Measured on Logic's own three adds
to an upgraded Logic 11 song (goldens `upgraded-baseline-logic` ->
`upgraded-three-audio-logic`); ours came back from Logic's re-save byte for byte. An `Input N`
past the count is the same insert after the last mono input, copied from one with its own UUID
and the count record's input word (+30) bumped; six made on a 20-input legacy song survived
Logic's re-save with their routing intact. Sends address buses as `bus + device inputs - 1`,
where the device input count is the count record's +36 word, which Logic keeps at the project's
original value — not the number of `Input` records (`sends.device_inputs`).

**Nudge value is not project data.** The toolbar's Nudge Value popup lives in Logic's own
preferences (`com.apple.logic10`, key `NudgeIncrement`), flushed when Logic quits. Five
saves of one project that differed only in the popup left ProjectData, `DisplayState.plist`
and `DisplayStateArchive` unchanged beyond save churn (2026-09-06). Measured numbers: Tick 0,
Bar 3, Sample 6 (the rest of the popup unmeasured). Nothing here reads or writes it;
`defaults read com.apple.logic10 NudgeIncrement` does, once Logic has quit.

## `modes` — the transport modes and the count-in

What the control bar shows lit lives in the `gnoS` song record (payload offsets; each byte
repeats 700 on and Logic moves both copies): +187 Replace, +188 Solo, +194 Cycle, +195
Autopunch, one byte each with 1 = on; +224 bit 0 Metronome Click; +137 bit 4 Use Musical
Grid; +240 the count-in length as the Record menu orders it — 0 off, 1-6 that many bars,
7-15 one to nine beats (the Count In button turns 0 into 1 Bar). Pinned on Logic 12.3.1 saves
of one project with one press each (2026-09-08); our write of two presses over the base
matched Logic's save of the same presses but for three bytes Logic churns on any press
(record offsets 173, 258, 2504). **Confirmed 2026-09-08:** a copy with Cycle, Metronome Click,
Use Musical Grid and a 3/4 count-in written by `logic modes` came up in Logic with those lit
and was re-saved with every one intact; Solo alone came back off — Logic clears it on load,
so `copy_modes` leaves it out. Software Monitoring, Auto Input Monitoring, Pre Fader
Metering, Low Latency Monitoring and Allow Quick Punch-In left the project untouched — they
are Logic's own settings (`prefs`). Skip Cycle is the two cycle locators swapped, not a flag.

`logic modes PROJECT` reads them; `--out DIR --set Cycle=on --set 'Count-in=2 Bars'` writes
a copy, `--from OTHER` copies another project's set. `apply-template` copies the template's
after the display state (`--skip modes` leaves them).

## `metronome` — the Metronome and Recording project settings

The two panes of File > Project Settings that a tracking template carries. In the `gnoS` song record
(payload offsets): +224 is the click byte — bit 0 Click while playing (the bar's Metronome button,
which also flips bit 2 of +2468), bit 1 set = Click while recording *off*, bit 3 Simple mode, bit 7
set = Polyphonic clicks *off*; +223 bit 1 Automatically colorize takes; +227 bit 1 Automatically
erase duplicates, bit 5 Allow tempo change recording, bit 6 set = MIDI data reduction *off*; +284
the Pre-roll/Count-in radio (1 = pre-roll); +122 a u32 pre-roll time in 1/10000 s; the count-in
length is `modes`' +240. The Audio Click (Klopfgeist) rows are four 32-byte blocks from +516 — Bar,
Beat, Group, Division — velocity at +11 and note at +12 of each. The MIDI click rows are in the
Environment's click object, the one `ivnE` of 414 bytes whose payload opens 0xe8 0x03: four 48-byte
rows from +180 — Bar, Beat, Division, Group — note-on status (0x90 + channel - 1) at +6, bit 7 of
+13 set when the row is off, velocity at +17, note at +18. Only the +224 byte has its copy 700 on
kept in step by Logic; the rest of this block's copy is stale and left alone. Pinned on Logic 12.3.1
saves of one change each (2026-09-08); our write of each box over the save before it matched Logic's
save of it but for the churn bytes. **Confirmed 2026-09-08:** a copy with six boxes and a 2 s
pre-roll written by `logic metronome`, and one with another save's rows copied in, each opened in
Logic showing the pane as written and were re-saved intact. Not carried: "Only during count-in"
(disabled while measuring), the Klopfgeist on/off box (wrote nothing), and the click's output and
Klopfgeist tone, which are the click channel's own plugin state.

`logic metronome PROJECT` reads it all; `--out DIR --set 'Simple mode=on' --set 'Pre-roll
seconds=2'` writes a copy, `--from OTHER` copies the panes whole. `apply-template` copies the
template's after the modes (`--skip metronome` leaves them).

The pane's Volume slider is the Click channel's fader (`OCuA` owner of the `Inst … Click`
channel, the same two fader bytes `levels` reads: 127 → 120 → 121 followed the slider on a blank
project, 2026-09-12); its Tone slider writes three bytes at +248 of that channel's key-2 record,
the Klopfgeist instrument's own state — located, not decoded. The Bar / Group / Beat / Division
row boxes are shared by the Klopfgeist and MIDI click sections: a row that is off greys both.

## `diff` — project↔project and project↔strip-library drift

```bash
# what changed between two projects (chains per channel label + metadata)
bin/run logic diff "A.logicx" "B.logicx"

# does each channel still match the saved .cst it references? (the Snare Down catch)
bin/run logic diff "Song.logicx" --library            # default: Channel Strip Settings
bin/run logic diff "Song.logicx" --library "/path"    # custom library root
```

`--library` with no path falls back to `LOGICXKIT_STRIP_ROOT`, else to Logic's own
`~/Music/Audio Music Apps/Channel Strip Settings`.

Exit 0 = identical / all match, 1 = differences or drift. Library mode compares **plugin
sequences** (preset names ignored) for channels that embed a chain; statuses `match` /
`drift` / `missing`. Drift is normal on a mature template: a saved bus strip often holds an
older chain than the project that references it. Name collisions resolve to the first sorted
path (check `path` in `--json`).

## `image` — extract the auto-saved window screenshot

```bash
bin/run logic image "Song.logicx" [-o out.jpg]
```

Copies `Alternatives/<first>/WindowImage.jpg` out of the bundle — Logic saves one
automatically on every save. **It shows whatever view was open at save** (often partial);
levels/sends/routing are recoverable only visually, so a save made with the full mixer
zoomed out turns this into a free whole-board reference.

## `ocr` — read the WindowImage programmatically

```bash
bin/run logic ocr "Song.logicx"        # fader row + text-item count
bin/run logic ocr mixer.jpg --json     # every token with normalized positions
```

Apple Vision OCR (`src/logicxkit/native/vision_ocr.swift`, compiled and run on demand by the
`swift` toolchain — this, like the rest of the module, is macOS-only and wants Logic Pro
installed) reads Logic's UI text essentially verbatim — validated digit-for-digit against the
hand-read fader table for the Recording template. The default view extracts the **fader row**
(the dominant horizontal band of dB-looking tokens, left→right); pairing values with channel
names is deliberately left manual, since the image shows whatever view was open at save. This
closes most of the "levels are visual-only" gap.

## `neural` — decode Neural DSP knob values

```bash
bin/run logic neural "/path/to/Guitar SLO.cst"          # every Neural instance + params
bin/run logic neural "/path/to/Song.logicx" --json      # whole project, structured
```

The one third party whose state is machine-readable. Logic embeds 3rd-party AU state
as an XML plist (identically in `.cst` and `.logicx` `ProjectData`); for JUCE plugins
the `jucePluginState` key holds the state, and Neural DSP ships two decodable
generations of it:

| Format | Found in | Shape |
|---|---|---|
| **`VC2!` XML container** | current X-edition plugins (SLO X, Nolly, Gojira X) | `<appModel>` XML — every knob a named attribute, grouped by section (`amp`, `soldanoEQ`, pedals, cab mics) |
| **binary ValueTree** | the original Soldano SLO-100 | `PARAM` id/value (float64) children + `presetNameProp` / `plugin_name` props |

Neural instances are identified by AU manufacturer fourcc `NDSP`; in a `.logicx` each
state is attributed to its mixer channel (`Audio N`). Amp knobs are normalized 0–1
(0.5 = noon); gate thresholds / delay times / mic levels are real units. Read-only —
writing 3rd-party state back is out of scope by design.

## Recommended workflow for a new set

1. In Logic, build **one** strip by hand with the exact plugin chain you want
   (e.g. Channel EQ → Compressor). Save it as a `.cst`.
2. `decode --json` that strip to get a starting spec entry.
3. Duplicate the entry per source, edit the numbers, point `template` at your
   hand-built `.cst` and `output_dir` at a new folder.
4. `verify`, then `build`.

## Spec format

Every path a spec names resolves the same way: absolute (or `~`-prefixed) wins; otherwise it
hangs off a root, and never off the process's working directory. `services/mixer/library.py` is the
one resolver, shared with chain configs (`strip_root` + `strip`).

Which root depends on what is being written, because Logic keeps `Channel Strip Settings` and
`Plug-In Settings` as **siblings** under `~/Music/Audio Music Apps`:

| Spec paths | Root | Override |
|---|---|---|
| `.cst`: `template`, `output_dir`, `graft`/`reslot` donors, a chain's `strip`/`cst` | the strip library | spec's `strip_root`, else `LOGICXKIT_STRIP_ROOT` |
| `.pst`: a pst spec's `output_dir` | Logic's user folder | spec's `output_root`, else `LOGICXKIT_AUDIO_MUSIC_APPS` |

```jsonc
{
  "strip_root": "~/Music/Audio Music Apps/Channel Strip Settings",  // optional root for the relative paths below
  "template":   "Track/Lib/template.cst",      // global default chain (optional if every preset sets its own)
  "output_dir": "Track/Lib/output",            // .cst files written here
  "presets": {
    "Strip Name": {
      "template": "Track/Lib/other.cst",        // optional — overrides the global template for THIS strip
                                                 //   (use one template per chain shape: EQ-only / EQ+Comp / EQ+Env+Comp)
      "eq": {
        "hpf":        {"freq": 30},                          // filter: freq (+ optional slope)
        "peak1":      {"freq": 65, "gain": 3.0, "q": 1.0},   // peak/shelf: freq, gain, q
        "high_shelf": {"freq": 10000, "gain": 2.0, "q": 0.71}
        // omitted bands stay flat/off; optional "master_gain"
      },
      "comp": {
        "circuit": "StudioFET", "threshold": -20, "ratio": 3,
        "attack": 15, "release": 75, "gain": 4, "knee": 0.5
        // optional: peak_rms (0=peak,1=rms), auto_gain, auto_release, limiter…
      }
    }
  }
}
```

Both `eq` and `comp` are optional per preset — omit one to leave that plugin as
the template has it.

## Caveat on thresholds

Compressor thresholds are absolute dB and depend on your incoming track levels.
Treat a spec's thresholds as starting points and nudge ±4 dB
once you hear real takes.

**Making the track** (Logic's own first section on a song without one, 2026-09-13): after the
last `tSxT` Logic inserts the section sequence triple (`qeSM` 341, `karT` 36, `qSvE` with the
section event), a second triple with an empty `qSvE`, and a `snrT` (504 bytes); it replaces the
68-byte `OgnS` before the first `rpyH` with a 774-byte one, appends a 734-byte `MneG` (a bplist)
and two `qSxT` — an empty text at slot 0, the section's name at slot 4. `arrangement --add`
writes the same from `arrangement-track-12.3.1.json`, and Logic re-saved one with the section
intact. The time signature line (`0x30`) carries the denominator's log2 at `+11` and the
numerator at `+12`; the key line (`0x32`) the key's index in the circle of fifths at `+12`
(C major 7) — read since 2026-09-06, the field offsets confirmed on the blank project's meter
edits.

