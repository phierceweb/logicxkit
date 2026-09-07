# logicxkit.logic — build Logic channel strips from JSON

A small, self-contained tool that builds Logic Pro **channel strip settings**
(`.cst`) for Logic's *native* **Channel EQ** and **Compressor** from a
human-readable JSON spec — and decodes existing strips back into that JSON.

`config/example-strips.json` is the neutral shape of that spec.

## Why it's template-based (and what it can't do)

A `.cst` is a proprietary binary file. Three layers:

1. **Binary header** (`OCuA` magic) — fader, pan, I/O bus, channel name. Not documented.
2. **Plugin-slot table** — which plugins load in which slots. Not documented.
3. **Plugin state** — for Logic native plugins, stored in `GAMETSPP` float blocks. **This is what we read/write.**

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

**Compressor** — `float[1]`=threshold dB, `[2]`=ratio, `[3]`=attack ms,
`[4]`=release ms, `[5]`=makeup gain dB, `[6]`=knee, `[7]`=peak/RMS,
`[8]`=auto-gain, `[9]`=output distortion, `[10]`=circuit type,
`[11]`=limiter threshold, `[12]`=limiter, `[13]`=auto-release.
Circuit types: `Platinum 0, ClassicVCA 1, VintageVCA 2, VintageFET 3,
VintageOpto 4, FET 5, StudioFET 6, StudioVCA 7, StudioOpto 8`.

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
   symptom — Logic loads the stale copy.
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
+4   2  class version  bumps when Logic upgrades the file (see "Schema versions" below)
+14  2  owner          which channel this record belongs to
+18  2  key            the record's role within that channel
+28  4  payload size   next record starts at pos + 36 + size
```

A `.cst` starts with the channel record at offset 0. `ProjectData` has a **24-byte file header**
first, and a total at **0x10 == filesize - 24** that must be rewritten after any length change.
There is no offset table, record count or checksum anywhere, which is what makes writing into
a project possible at all.

Keys: **0-2 sends**, **4+ plugin slots**, higher keys per-channel properties (the `.cst`
reference sits at a key that moves with the Logic build — 9, 10, 12 and 13 all occur, so never
hardcode it). Gaps are normal; Logic writes sparse keys itself.

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

Rebase the variant id rather than incrementing it: `new = old - old_cfg + new_cfg`. The config
index is **not** always the channel count — Gain's stereo index is 3. Leave `+82`/`+83` (bus
counts) alone, and only follow `+157` to `+156` when the two already agreed, or you destroy a
legitimately mono side chain on a stereo compressor.

`logic width PROJECT` prints every channel's width; `--out DIR --stereo 'Aux 13' --mono 'Aux 1'`
writes a copy through `widen_channels`, which moves the channel's three width bytes and
re-stamps each slot on it. **Confirmed 2026-09-08:** two drum-MIDI auxes made stereo on both
templates came back from Logic's re-save with the channels and their slots still stereo.

### Per-instance ids — measure, never assume

Two instances of the same plugin differ in a few trailer bytes carrying a per-instance id.
**Their position is plugin-specific**: Channel EQ (432 B payload) uses 414, 415, 420-427, while
Enveloper (248 B) uses 228-231, 236-243. Applying one plugin's offsets to another overwrites
live parameter data — that is what makes a project fail to open.

`instance_offsets()` derives them by diffing real instances of that exact plugin; with fewer
than two available it returns nothing and the clone is copied verbatim.

### Donor rules

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
(verified against all 94 strips in the library; the folder is ground truth).

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
| `+14` | **1 = this row sits inside the stack above it**, 0 = header or top level. 113/113 rows on two files, including the Click and trigger-aux rows inside Drums MIDI that carry no stack index on their channel; a dragged-in track goes 0 -> 1 |
| `+24..39` | the row's own UUID |
| `+40` | bit `0x80` = expanded (stack headers, and every fresh top-level row; no member row); bit `0x20` = selected |
| `+43` | `0x40` on the selected row |

The second long run (76 rows here) is a flat list of every track object in mixer order — it
is not the arrange hierarchy.

### `ivnE` — the Environment objects

| offset | meaning |
|---|---|
| `+0` | channel-object type in the low 16 bits: **1800** at Logic 12, **1728** at Logic 11; mixed projects set flag bits `0x4040` in the high half on some tracks (ten of 69 in one mix), so mask before comparing |
| `+16` | object id — what `karT+8` points at |
| `+24` | u32 **group number** (1-based; 0 = none) — see Groups below |
| `+38` | u32 **parent**: the object id of the stack this track was dragged into (0 if never dragged). Ids reach 500, so all four bytes matter |
| `+45` | state: 0 on a fresh object, 1 after its first save, 3 after the next |
| `+80` | 1 on the selected object only |
| `+82` | u32 per-object stamp: a fresh object gets its pattern's plus the pattern's `+86` (64 or 66); a channel insert moves every object above the pattern's up by 66 |
| `+86` | u16, `0x42` on a fresh object (`0x40` on older ones) |
| `+154` | kind; **0** marks a grouping object — folder stacks, plus Logic's own Preview/Click/Master |
| `+158` | u16-length-prefixed name, immediately following, padded to an even length |
| name end | u16 = the bound channel's owner + 1, kept live when owners shift; +3 on a stack object holds its Sub number |
| last 16 bytes | the object's instance **UUID** (v1, `94 c0 11 ef` in the middle) |

### Which channel an object is, and where it routes — `OCuA` tail

The channel record's payload length varies per session (257, 265, 269 bytes at one class
version), so these are addressed from the end:

| offset | meaning |
|---|---|
| `[len-48 : len-32]` | the bound Environment object's instance UUID — the link from a channel to its object |
| `[len-32 : len-16]` | the **output destination**: the UUID of the channel it feeds (drums -> `Bus 1`, guitars -> `Bus 5`, returns -> `Output 1-2`); all-zero on Sub/Master/Output strips |
| `[len-16 : len]` | the **input**: the UUID of the `Input N` channel record an audio track records from (Audio 1 and a fresh track on Input 1 both point at `Input 1`); zero on everything else |
| `+110` | the **Sub number of the stack** the channel sits in (drums 1, bass 2 … Drums MIDI 7), 0 otherwise |
| `+24, +25` | `01 01` once bound |
| `+60` | NUL-padded label with a leading space: ` Audio 1`, ` Sub 1`, ` Bus 15` |

Measured 59/59 in-use channels on seven sessions and the template. **Folder stacks bind to
the `Sub 1-7` strips**, which is where a stack's fader lives; the three kind-0 objects bound to
Aux strips (Room, Drum FX, Vox Verb) are input-less auxes, not stacks. `services/binding.py`.

### Instrument outputs — an aux fed by a software instrument's extra output

Measured on two saves (2026-09-05) against nine projects of the template's lineage: the aux's
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
`+123`); a mono one did not. `services/instout.py` reads, binds and unbinds; `apply-template`
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
| `+16..19`, `+24..27` | the level, not decoded; `+17` and `+27` agree on every send and differ per send |
| `+20` | u16 destination as **bus number + the project's mono input count - 1** (32 inputs: 46 -> Bus 15, the B 15 the mixer shows; a 20-input song writes Bus 10 as 29) |
| `+44` | the send's own instance UUID (v1), distinct on all 78 |
| `+60` | the destination **`Bus N` channel's own UUID** (78/78) — the bus is named twice |

The channel's own `OCuA` mirrors every satellite: from `+132`, one u32 per record key (sends
0-2 at `+132/+136/+140`, plugin slots from key 4 at `+148`, the reference and the rest after),
1 exactly when a `UCuA` with that key exists under the owner — 78,666 words on nineteen Logic
files, no exception. **`+26` is the flag-word count and sizes the record**: payload = 201 +
4 x `+26` on all 21,772 version-7 channel records on hand (a 201-byte stub has no flag
words; the 20 zero bytes, one byte and three UUIDs after the flags never move). A flag left
set for a missing record is a file Logic refuses to open (measured 2026-09-04: slots removed
without their flags), and so is a record shorter than its `+26` says (measured the same day:
chains landed on 201-byte stubs grown the wrong way); a record without its flag it
tolerates. `services/keyflags.py` syncs the flags at the end of every satellite write and
grows a stub in front of its tail when a key needs it.

Two Logic re-saves (`02 -> 03`, `02 -> 07`) left every send byte-identical. `services/sends.py`
reads them; `services/sends_write.py` adds, copies and removes them — a new send is a clone of
one the project already carries (level bytes and `+8` copied, never synthesised), with a fresh
`+44` and the target bus's UUID at `+60`; `logic send --add/--copy/--remove` drives it.
**Confirmed in Logic 12.3.1 on 2026-09-02:** the added send showed on the strip.

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
| `qeSM +70` + padded name | u32 **settings**, one bit per box: 0 Volume, 1 Pan, 2 Mute, 3 Solo, 8-15 Send 1-8, 16 Editing (Selection), 17 Track Zoom, 18 Color, 20 Record, 21 Hide, 22 Quantize-Locked (Audio) **inverted** (set while the box is off), 23 Track Alternatives, 24 Automation Mode, 26 Input. A fresh group is `0x81400005`; bit 31 is set on every group 12.3.1 made and clear on one older template group — unmeasured |
| `qSvE` | one 32-byte **event per member per linked fader** — Volume, Mute, Solo, Pan; every other box is flag-only — then a 16-byte tail. `+4` = the member's object id × 2; `+12` the fader as Logic numbers them (7 Volume, 9 Mute, 3 Solo, 10 Pan); `+8` u32 the member's value for it as its channel stores it (the fader's fixed-point word, `0x5a000000` at unity; the pan byte in the top byte, 64 = centre; 0 for Mute and Solo), its halves repeated at `+20` and `+30`. A fresh group writes Mute then Volume per member; Solo then Pan |
| `ivnE +24` | the member's **group number** |
| `gnoS` | a `<0x11><slot>` entry per group in both runs, directly before the object entries |

Nothing else moves: the row's `+4` and the channel's `+92`, both candidates before the saves,
stay put. `services/groups.py` reads and writes all of it; the writer reproduces six of the
saves byte for byte in the triple, the numbers and the registry pair. Leaving a group is
composed (events out, number cleared), not measured. `apply-template` carries the template's
groups by name — made in the session when missing, paired rows put in them, a row grouped where
its template row is not taken out — as its last step, so the events carry the fader the template
set. Confirmed: the migrated song opened in Logic with `1: OH` / `2: Room` in the mixer's Group
row, and Logic's re-save kept both group records byte for byte and the row list unchanged.

**Open (2026-09-08):** a track added *after* members are assigned leaves the group with fewer
fader events than members ("2 event(s) for 2 member(s), 4 expected"), so `apply-template` runs
over another lineage need `--skip group` until the add re-syncs the events.

### What a track add writes (two clean saves, 2026-09-01, Logic 12.3.1)

**A mono audio track** (`02-baseline -> 03-add-audio-track`, +40 bytes of gnoS, everything
else accounted for):

- `NumberOfTracks` +1; one `ivnE` object cloned in shape from any track object — new id,
  name, fresh tail UUID, colour byte, `+148` icon word; one arrange `karT` row (58 B, `+14 = 0`,
  fresh row UUID, `+51 = 0x07` for an audio track / `0x85` for an instrument track), inserted at
  the position with every later key renumbered; one row in the flat all-tracks list; and one
  **sequence triple** — `qeSM` (345 B, contains the lane name `*Automation`), a zero-size
  `karT` marker, `qSvE` (16 B) — inserted in slot order (below).
- **Binding**: a pre-allocated `Audio N` stub (253 B, already labelled) flips `+24/+25` to
  `01 01`, gets the width triple (mono 211/0/1), its own UUID = the new object's tail UUID,
  and its input UUID = `Input 1`'s. Its destination UUID already pointed at Stereo Out.
- **`gnoS`**: two object entries in the id-ordered registries — 24-byte `<u32 0x14><u32 id>
  <UUID>` and 16-byte `<0x14><id><v1 time fields>` — right after the highest id's; the pair
  keyed by the new index-table slot word (`<0x17><slot>`, same two shapes) filled with a fresh
  UUID and its time; the 16-byte `<0x17><4>` and `<0x17><8>` stamps (the arrange and flat
  lists) refreshed; and the selection fields (`+94`, `+210`, `+214`). Everything else in gnoS
  that moves also moves on a no-op save — per-save nonces.
- The index table — the `qSvE` with one entry per track object (not the largest: a mixed project holds a region table of 21,000 entries repeating track ids) — 80-byte entries, then a 16-byte tail — gains one
  entry **before the tail**: the object id at `+16`, the sequence index at `+20`, and at
  `+32` the lowest slot word (multiples of 4 from 20) no other entry uses. Every entry whose
  sequence index is at or past the new one moves up by one.

The real-file goldens run on a re-saved Mix template staged by `tests/_paths.py`, and check the
invariants above rather than bytes.

`logic add-track` reproduces all of that (`services/addtrack.py`): against Logic's own add it
yields the same record set at the same positions, the index table and count record byte for
byte, and the registry entries at the same offsets; what differs is minted values (UUIDs,
the `qeSM +8` ids Logic renumbers) and per-save nonces. **Confirmed in Logic 12.3.1 on 2026-09-01:** the project opened, the new track was there, the source track was intact, nothing else changed.

**A software instrument track** allocates a channel differently: Logic **inserts a new
`OCuA` record** right after the pattern track's channel (265 B payload, Logic's default
instrument-slot record and one property record — kept in `inst-track-12.3.1.json` under the data root,
instance UUIDs re-minted), **renumbers the owner field of every record after it**, relabels
the following `Inst N` channels (`+6`, `+66` and the label all move up one) bumps the channel index of every
object bound above it and the stamp of every object above the pattern's, and adds one to the
channel-count record `nCuA`: a 132-byte head over one u32 per channel record, `+26` the total,
then a u16 per strip class — `+28` Audio, `+32` Aux, `+34` Inst (the one a save moved), `+38`
Bus, `+40` Master and Sub together (these counted from the file, not measured by a save).
Audio tracks never do this because `Audio 1-35` stubs pre-exist. `logic add-track --instrument`
does all of it; the index table and count record it writes are byte-identical to Logic's.
**Confirmed in Logic 12.3.1 on 2026-09-01** (both tracks present, the click still plays).

**The sequence triple and the index table are linked by slot.** The three records of a
triple share a header slot (`+10`); the table entry with that slot word at `+32` names the
object (`+16`) and its index (`+20`, 17 + mixer rank), and the `qeSM` repeats both: `+234`
the object id, `+242` the index negated, plus `+300 = 382` on a fresh track and a kind byte at
`+39` (9 track, 20 stack). A new track takes the lowest free slot word, the index after its
pattern's, and goes into the stream in slot order; every entry at or past its index moves up
one and that entry's triple has `+242` decremented; no other triple moves. `qeSM +8` (repeated
as the `qSvE` owner) is a per-triple id Logic renumbers on its own saves — any unused value
serves. Measured on both adds; `services/sequence.py`.

**Three more things a row add must keep straight** — get any of them wrong and Logic's
re-save drops or misplaces rows (measured 2026-09-04; `services/regions.py`,
`services/registry.py`):

- **The song container's row count.** The `qeSM` of the triple that holds the arrange rows
  carries `rows x 60` as a u32 269 bytes before its end (its name is variable-length, so the
  field is addressed from the end; 39/39 files). Logic reads that many rows and silently
  drops the rest on its next save — a 57-row migration came back as the first 11 plus Master.
- **Region placement.** The same container's `qSvE` is an event list of 80-byte entries and
  a 16-byte tail; an entry placing a region carries the track's object id at `+16`, the
  track's 1-based arrange row at `+20` (the object's first row when a channel has two) and the
  region's slot at `+32`. Logic renumbers `+20` when a row moves (`37 -> 38`); 1,055 entries
  agree. Left stale, a region shows on whatever track now sits at that row.
- **Registry slot entries.** gnoS's two `0x17` runs hold one entry per multiple of 4 from 0
  to the highest sequence slot in use; a slot past their end gets appended, with every
  skipped word, the way Logic's re-save extends them.

**The track name is the user's only when `ivnE +45` bit 0 is set**: clear, the arrange shows
the channel-strip setting's name instead (`Rack 2` read `Rack`, four vocal tracks read `Vox -
Lead`). 1,327 named tracks on 39 files set it; Logic's own fresh adds, auto-named `Audio N`,
do not. `rename_track` sets it; `add-track` sets it unless the name is the strip's own label.

**Selection** lives in four places Logic moves together — the row (`+40` bit `0x20`, `+43`
= `0x40`, `+0` bit `0x10000` on an instrument row), the object (`ivnE +80`), and gnoS (`+94`
object id, `+210`/`+214` the 1-based row) — and the previous holder is cleared. Every writer
that adds or moves a row ends by selecting it (`services/selection.py`).

**Reorder** (`06 -> 07`, Ride dragged above Hi Hat): the two rows swap keys; no table moves.
`logic reorder` reproduces it — the only remaining difference from Logic's file is selection
state. **Save Channel Strip Setting** copies the channel's records out (see `stripsave.py`)
and rewrites the channel's `.cst` reference label to the new strip name.

**Colour** is `ivnE +155`, a palette index (`08-colour-kick`: Kick In 96 -> 64, nothing else
moved); `logic colour` writes it. `+45` is a state flag a fresh object clears.

**A stale index-table entry is not a pattern.** Logic's own files keep a few entries whose
triple carries object 0 and reads as a group's (`link_errors` lists them; 8 in one project, 13
in another). A track cloned from one comes back as a group with no registry entry and the
write gate refuses the copy. The add path takes a pattern only when its entry leads to a track
triple carrying the object itself (`addtrack._sound_entry`, 2026-09-08).

### Creating a stack (`logic stack-create`) — composed, not sampled

Logic's own Create Track Stack has not been saved and diffed; `services/stack_create.py`
composes the measured pieces instead. A folder stack is a kind-0 object bound to a `Sub N`
strip, so a new one gets: the highest stack's object cloned (new id, name, colour, its Sub number after the name, the
channel index of `Sub N+1`, a minted stamp, fresh UUID, the pattern's icon kept), a `Sub N+1` strip cloned from `Sub N` right after it (`+6 = N+1`
— Subs count from 1 there, Audio and Inst from 0 — the label, the object's UUID at `len-48`,
no destination or input), every later channel owner moved up by one and the count record's
`+40` class counted up; a header row where the first member sat, expanded, the member rows
behind it with `+14 = 1`, their objects' `+38` parent and their channels' `+110` stack index
set as a drag sets them; and the flat row, sequence triple, index-table entry and two `gnoS`
entries exactly as a track add writes them; the header ends up selected. Members already
inside a stack are refused. **Confirmed in Logic 12.3.1 on 2026-09-02:** a stack made from two
aux tracks on a copy of the Mix template opened as a folder holding both.

**Needs a stack to clone.** The structures come from the session's highest-numbered stack, so
a session with none is refused and a template's tracks land flat there; a donor (the
template's stack) has not been tried (2026-09-08).

### The writers — atomic pieces, and the commands over them

Every write is one function on `bytes` that validates its input and output, so an
orchestrator can chain them in any order. The pieces a new track or stack is made of:

| module | what it owns |
|---|---|
| `recbuild.py` | a record header over a new payload; owner/key/slot restamps; UUID minting |
| `tracklist.py` | `karT` runs, the arrange and flat lists, a new row, renumbering |
| `sequence.py` | the `qeSM`/marker/`qSvE` triple and the index table (`plan_sequence`) |
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
recordings come along — and runs one step over every ProjectData; the input is never written.

### Track header components — `DisplayState.plist`, not ProjectData

The arrange window's header configuration (the `Track Header Components` submenu / Configure
Track Header popover) lives in the 312-byte `ArrangeCLgUserData` blob under
`screensetDictArray[0]/layoutDictArray[0]/docwWindowState/udataArrange` in
`Alternatives/NNN/DisplayState.plist`, and again as the same blob inside `DisplayStateArchive`.
Measured on seventeen Logic 12.3.1 saves of one project, one component toggled per save
(2026-09-04), each save changing exactly one bit and the width:

| offset | meaning |
|---|---|
| `+38` | u16 header width in pixels: 109 plus the shown components' widths (On/Off, Mute, Solo, Protect, Freeze, Input Monitoring 22 each; Record Enable 26; Volume 128; Pan/Send 25; Control Surface Bars 5; Track Numbers 12; Track Icons 30; the rest 0) |
| `+58` | bit 3 = Track Numbers **hidden** |
| `+68` | bit 1 Volume, bit 2 Pan/Send, bit 3 On/Off, bit 4 Groove Track, bit 5 Track Alternatives (set = shown) |
| `+70` | bit 0 Mute, bit 1 Record Enable, bit 2 Solo, bit 3 Track Icons, bit 5 Additional Name Column, bit 7 Input Monitoring, bit 8 Track Protect, bit 10 Freeze, bit 12 Color Bars (set = shown); bit 14 Control Surface Bars **hidden** |

ProjectData does not change with a toggle. `services/header.py` reads and writes the set
(both files, width recomputed); `logic header PROJECT` prints it, `--show/--hide NAME` and
`--from OTHER` write a copy. The writer reproduces Logic's words and width on all sixteen
toggles, and a written set opened in Logic showing every component as set (2026-09-04).

### Control bar and display — `DisplayState.plist`, not ProjectData

The set the main window's control bar shows (Customize Control Bar and Display…) lives in
each alternative's `DisplayState.plist` under `screensetDictArray/layoutDictArray/
docwWindowState/transportLayoutDict`, mirrored in `DisplayStateArchive`. Five lists of
button ids, one per column of the popover, kept in one fixed order whatever order the boxes
were ticked; a control that draws two buttons carries two ids. Measured on fifty Logic 12.3.1
saves of one project, one control per save (2026-09-04, the `controlbar-saves` golden):

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
mode onto a copy, `--show/--hide NAME` switches controls by name (`services/controlbar.py`
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
Mix template's four files hold no such key).

`logic prefs` reads the settings `services/prefs_table.py` names, key by key through
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
template's tracks with the session's (`services/pairing.py`: the Environment object id first —
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
the seven sessions on hand the plan is fields only: every one was cut from the Recording
template and still pairs 56/56 by object id (`orchestrators/apply_template.py`).

**Old projects and alternatives.** A project saved by Logic Pro X reads with no track names
(its Environment objects are not found); opening a copy in Logic and saving rewrites only the
*active* alternative in the current layout — switch to each other alternative and save it too,
or remove the stale ones in Edit Alternatives. Such a save has no `ArrangeCLgUserData`, so the
header copy is skipped with a note. One map serves every alternative of a project; an
alternative whose tracks the map does not name is left as it was, with a note. Converted
2026-09-08: a 10.4.4 project and a 12.3.1 one carrying a 10.4-era alternative.

A project of another lineage is refused (across lineages the label rule pairs whatever shares
an `Audio N`) unless a **map file** says how its tracks pair: `--propose-map FILE` drafts one
from the names — same name, then a numbered prefix with the DI preferred (`Guitar 1` ->
`Gtr 1 DI`), then shared words, kinds never crossing — with a confidence per line for a
person to correct; `--map FILE` applies it, pairing only by the map, object id and exact
name. Session tracks mapped to `(none)` are left alone — no rule may claim them, not even a
matching object id; template tracks nobody maps to are added where a writer can, and the
rows an earlier structural round made stay paired with the template row they stand for
(object id, not name — a new `Drums` aux beside a legacy `Drums` aux would otherwise be
added again every round). A session stack counts as the template stack its header pairs
with, whatever it is called.

**Confirmed on three legacy songs (2026-09-04):** all three migrated onto the Mix template —
248-306 ops each, the drum, MIDI, bass, guitar and vocal stacks made, every template track
added, chains, references, routing, sends, levels, colours and hidden rows applied — and Logic's
own re-save of each returned the identical row list. What stays refused: sends the legacy
session has and the template lacks (never removed), and inputs past the session's count. Groups
follow the template (see Groups). Three things a legacy migration has to get right: **slot
keys** — a project made before Logic 11.2 starts its plugin slots at key 2, not 4;
`apply-template` first moves every key from the slot base up by two, as Logic's own re-save of
such a project does (`services/slotkeys.py`), and every slot writer reads the project's own base
(`slot_index_base`, a majority vote over its native chunks and XML AU states), so a transplanted
chain replaces the old one instead of sitting behind it (Logic loaded both: two amp sims in
series, two drum instruments on one channel, prompts for plugins the old chain used). The rebase
also stamps the base into every channel record: the u16 at +28 of a channel's `OCuA` is the slot
base it was written with, 2 in such a project and 4 in everything Logic 12 writes or converts,
and left at 2 under keys that sit at 4 Logic drops the plugin at slot 0 on any channel that also
carries three sends. Stamped 4, the same file keeps them, and the 2020 song migrates in one pass
(2026-09-06); **send destinations** — a send's `+20` counts from the project's device input
count, not from 31 (`sends.send_base`); **mixer-only returns** — a legacy song returns its buses
through auxes that have no arrange track, and once a template aux track returns the same bus the
old return is silenced (`return` op: input cleared, slots removed), or every bus plays twice;
**unfed auxes** — a template aux with no input (the instrument-fed Drums MIDI outputs) now
clears the input of its session twin instead of leaving the aux-add default of `Input 1-2`, a
live hardware input; **instrument outputs** — the Drums MIDI auxes take the drum instrument's
hi-hat, overhead and room outputs (see "Instrument outputs" below), and a legacy aux taking the
same output is unbound. The map file also takes `+`/`-` lines: template tracks nobody maps to
are listed with `+` (added) and a `-` leaves one out — the MIDI-drum songs leave the seventeen
drum audio tracks out and alias their legacy Drums stack to the template's Drums MIDI stack. A
send is a 76-byte record; a project whose plugin slots start at key 2 carries kilobyte slot
records under the send keys, and `read_sends` leaves those alone.

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

### Channel fader and pan — `OCuA`

| offset | meaning |
|---|---|
| `+6` | the channel's own number (`0` is "Audio 1"); label at `+60`, NUL-padded |
| `+116..119` | fader as u32, **8.24 fixed point**; `+85` and `+119` repeat its integer part (0-127) and all three must agree — 532/532 records on nine files. `levels` copies the exact value |
| `+89` | pan 0-127, 64 centre; Logic displays it as `byte - 64` |

Verified against Logic's mixer, byte -> dB: 47 -> -11.3 · 60 -> -7.1 · 90 -> 0.0 · 92 -> 0.4 ·
94 -> 0.8 · 99 -> 1.8 · 110 -> +3.4. About 0.2 dB per step near unity, steepening below. The
taper is deliberately not modelled; copying levels never needs it. A folder stack's fader is
its `Sub N` strip's — confirmed in Logic on 2026-09-01 (Drums at 60 read -7.1, Guitar at 110
read +3.4, nothing else moved). Some channels — Auxes, Insts, Output — carry an **all-zero UUID
sentinel** instead of a real one, so a clone must leave it alone.

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
| Sends / output bus / fader / pan | ✅ `logic manifest` — fader/pan (`+116` u32, `+89`), output (tail UUID), sends (bus). Send level is still undecoded |

```bash
bin/run logic manifest "Song.logicx" [--json]        # tracks, stacks, channels from decoded fields
bin/run logic recdiff A B [--baseline X Y] [--json]  # positional record diff of two saves
```

## `arrangement` and `tempo` — the arrangement track and the tempo track

Both are sequence triples near the head of ProjectData whose `qSvE` payload is 16-byte
lines (`services/events.py`): a line whose byte 7 has its top bit clear starts an event
(type u32 at +0, tick u32 at +4; 960 ticks per quarter, bar 1 at tick 38400), a line whose
byte 7 has the top bit set continues the event before it (0x88 is the data line; 0xb4 and
0xb1 carry a tempo curve), and type 0xf1 at tick 0x3fffffff ends the sequence.

**Arrangement** (`services/arrangement.py`): events of type 0x12, one per section. The data
line holds the slot of the section's `qSxT` text record at +0, the section kind at +8
(0 custom or intro, 1 verse, 2 chorus, 3 bridge, 4 outro) and the length in ticks at +12.
The text record's name is NUL-terminated at +98, or an RTF document whose text is the name.
Twelve sections of one song, with quarter-bar lengths, reproduced Logic's display exactly.

**Tempo** (`services/tempo.py`): `gnoS +110` is `bpm × 10000` — the tempo the LCD showed
when the song was saved — and +114 the tempo at bar 1 (+198 repeats it). Events of type
0x60 carry `bpm × 10000` at data +0; a head flag 0x40 marks a point Logic generated for a
ramp (one every 480 ticks). A step Logic draws from the tempo track is two events one tick
apart with 0xb4/0xb1 lines; one added from the Tempo List is a single bare event. Matched on
every song on hand, a ramp and two step songs included. The 0xb4 line's four fields are
undecoded. The event type is the u16 at +0: a change Logic added carried a nonzero word at +2.

Edits (`--out` required, on a copy): `arrangement --rename N=NAME`, `--move N=BAR`,
`--length N=BARS`, `--delete N`, `--add BAR:BARS:NAME[:KIND]` (N as the listing numbers the
sections), `tempo --set BPM` (the bar-1 event and every `gnoS` word that held its old value)
and `tempo --add BAR=BPM`. A renamed section's text
record is rebuilt plain (`arrangement_write.py`); Logic's re-save of a rename plus a resize
kept both byte for byte (2026-09-06), a move plus a delete came back from Logic's re-save
event for event (2026-09-07), and `tempo --set 180` showed on Logic's LCD and survived its
re-save.
`--add BAR:BARS:NAME[:KIND]` makes a section the way Logic's own add did:
the name record takes the lowest free multiple-of-4 slot among the `qSxT` records — their own
slot space, the registry is untouched — with the head Logic writes for a fresh one
(`section-text-12.3.1.json` under the data root, form word 0x14), sits in slot order among them, and the
event joins the sequence in tick order. Ours reproduced Logic's add record for record, and
Logic's re-save of a section and a tempo change we added kept both. `tempo --add BAR=BPM`
writes what Logic's own added change was: one bare 32-byte event — no curve lines — with the
bpm word, `40 88` at +22 of the data line and an ascending stamp at +8;
the word Logic put at head +2 is undecoded and written as zero, which Logic accepted.
`tempo --ramp BAR=BPM:BAR=BPM [--density N]` writes what Logic's Tempo Operations "Create Tempo
Curve" writes (linear, 1/8, continue with the new tempo): one plain event per division from
the start bar to the end bar, each holding the tempo at the middle of its division, the
last one the end tempo exactly, no curve lines. Logic's re-save of ours kept all sixty-six
events and rewrote only their stamps. A curve drawn by hand on the tempo track is the
other shape — ramp points flagged 0x40 with a 0xb4 curve line on the first — and is read only. Adding a
section needs an index-table slot for its text record, and adding a tempo change the 0xb4
curve line — both unmeasured, so neither is offered.

**Signature track and project settings** (`services/signature.py`, `settings.py`,
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
continuation line; Logic's re-save of ours kept all four events byte for byte.

**Channel records past a session's count** (`services/channel_alloc.py`,
`services/inputs_create.py`; `add-track` and `apply-template` use them). When no `Audio N` stub
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

The two panes of File > Project Settings that a tracking template carries. In the `gnoS` song
record (payload offsets): +224 is the click byte — bit 0 Click while playing (the bar's
Metronome button, which also flips bit 2 of +2468), bit 1 set = Click while recording *off*,
bit 3 Simple mode, bit 7 set = Polyphonic clicks *off*; +223 bit 1 Automatically colorize
takes; +227 bit 1 Automatically erase duplicates, bit 5 Allow tempo change recording, bit 6
set = MIDI data reduction *off*; +284 the Pre-roll/Count-in radio (1 = pre-roll); +122 a u32
pre-roll time in 1/10000 s; the count-in length is `modes`' +240. The Audio Click
(Klopfgeist) rows are four 32-byte blocks from +516 — Bar, Beat, Group, Division — velocity
at +11 and note at +12 of each. The MIDI click rows are in the Environment's click object,
the one `ivnE` of 414 bytes whose payload opens 0xe8 0x03: four 48-byte rows from +180 —
Bar, Beat, Division, Group — note-on status (0x90 + channel - 1) at +6, bit 7 of +13 set
when the row is off, velocity at +17, note at +18. Only the +224 byte has its copy 700 on
kept in step by Logic; the rest of this block's copy is stale and left alone. Pinned on
Logic 12.3.1 saves of one change each (2026-09-08); our write of each box over the save
before it matched Logic's save of it but for the churn bytes.
**Confirmed 2026-09-08:** a copy with six boxes and a 2 s pre-roll written by `logic metronome`,
and one with another save's rows copied in, each opened in Logic showing the pane as written
and were re-saved intact. Not carried: "Only during count-in" (disabled while measuring), the Klopfgeist on/off box
(wrote nothing), and the click's output and Klopfgeist tone, which are the click channel's
own plugin state.

`logic metronome PROJECT` reads it all; `--out DIR --set 'Simple mode=on' --set 'Pre-roll
seconds=2'` writes a copy, `--from OTHER` copies the panes whole. `apply-template` copies the
template's after the modes (`--skip metronome` leaves them).

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
hangs off a root, and never off the process's working directory. `services/library.py` is the
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
