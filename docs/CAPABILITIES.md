# What the Logic writers can actually do

The question this file exists to answer without a survey: **can I point this command at a real
Logic project today?**

Read the table, then the defect list, for anything you plan to run. Each row says what it was
measured against and when. All of it is macOS-only: the writers target Logic Pro's own project
format, and "confirmed" means the output was opened in Logic Pro itself. The measurements
are on projects Logic 12.3.1 saved (file format 2513), but for `names-non-ascii-logic`,
`addtrack-inst-stereo-logic`, `names-write-resave-logic` and `names-long-resave-logic`, which are
Logic 12.4's, in the same format. Logic 12.4 re-saved each of the 61 public copies a writer made, with the record list
12.3.1's re-save has and the goldens that hold that one (2026-10-01). Every writer refuses a
project in any other format.

The table is **generated from `src/logicxkit/logic/_capabilities.py`**, its rows declared in
`_capabilities_table.py` — change a level there, not here. `bin/run logic capabilities -v`
prints it with the catch per command, and `tests/logic/test_capabilities.py` fails when a
subcommand has no entry or the two drift apart.

## Confidence levels

| Level | Means |
|---|---|
| **CONFIRMED** | Output was opened in Logic and the change was there. The save that proves it still exists. |
| **CLAIMED** | A doc says it was confirmed, but the save is gone or the code has changed since. |
| **DERIVED** | Byte layout reasoned from reads and diffs. Never opened in Logic. |
| **BROKEN** | Has a defect reproduced on a real Logic project. |

A command being in `--help` is not evidence of anything.

The controlled Logic saves these confirmations were measured against are Logic-authored project
files and are not redistributable, so a clone carries none of them; `resources/README.md` says
how to stage your own.

## The table

<!-- generated from src/logicxkit/logic/_capabilities.py — edit there, not here -->

| Command | Level | Safe on a real song? |
|---|---|---|
| `project` `manifest` `diff` `decode` `neural` `recdiff` | — | yes, read-only |
| `plugins` | — | yes, read-only |
| `regions` | **CONFIRMED** | read yes; `--audio` and the edits on a copy |
| `markers` | **CONFIRMED** | yes, on a copy |
| `quantize-drums` | **CONFIRMED** | yes, on a copy |
| `drums-to-midi` | **CONFIRMED** | yes, on a copy |
| `sessionplayer` | — | yes, read-only |
| `automation` | **CONFIRMED** | read-only until `--set`, `--copy` or `--clear`, which need `--out` |
| `patch` | **CONFIRMED** | read yes; `--build` writes outside Logic's library unless `--install` |
| `midi` | **CONFIRMED** | read, `--export` and `--map` yes; `--region`, `--note`, the edits by region number and `--remap` on a copy |
| `beats` | **CONFIRMED** | yes, on a copy |
| `stacks` | **CONFIRMED** | read-only until `--move` or `--move-out`, which need `--out` |
| `levels` | **CONFIRMED** | read-only until `--fader`, `--pan` or `--to`, which need `--out` |
| `build` `verify` `pst` `donors` `image` `ocr` | — | never touches a project; `build`/`pst` reach Logic's own library only with `--install` |
| `chains` | **CONFIRMED** | yes, after reading `--plan` |
| `retrack` | **CONFIRMED** | yes |
| `strip-save` | **CONFIRMED** | yes |
| `send` | **CONFIRMED** | yes |
| `stack-create` | **CONFIRMED** | yes; not around a stack |
| `add-track` | **CONFIRMED** | yes |
| `reorder` | **CONFIRMED** | yes |
| `route` | **CONFIRMED** | yes |
| `arrangement` | **CONFIRMED** | yes, on a copy |
| `signature` | **CONFIRMED** | yes, on a copy |
| `toolbar` | **CONFIRMED** | yes, on a copy |
| `modes` | **CONFIRMED** | yes, on a copy |
| `metronome` | **CONFIRMED** | yes, on a copy |
| `width` | **CONFIRMED** | yes, on a copy |
| `tempo` | **CONFIRMED** | yes, on a copy |
| `rename` `colour` `hide` | **CONFIRMED** | yes |
| `settings` | **CONFIRMED** | yes; `--set` writes a copy |
| `transplant` | **CONFIRMED** | yes, within the channel's key range |
| `bypass` | **CONFIRMED** | yes |
| `add-plugin` | **CONFIRMED** | yes, on a copy |
| `tracking-chains` | **CONFIRMED** | yes, on a copy |
| `swap-plugin` | **CONFIRMED** | yes, on a copy |
| `remove-plugin` `replace-plugin` | **CONFIRMED** | yes, on a copy |
| `clear-slots` | **CONFIRMED** | yes |
| `header` | **CONFIRMED** | yes |
| `prefs` | **CONFIRMED** | yes, with Logic closed |
| `controlbar` | **CONFIRMED** | yes |
| `group` | **CONFIRMED** | yes |
| `apply-template` | **CONFIRMED** | yes, with a map across lineages |
| `migrate` | **CONFIRMED** | yes, on a renamed copy; across lineages only with `--map` or `--force` |

## The catch, per command

<!-- generated from src/logicxkit/logic/_capabilities.py — edit there, not here -->

### `project` `manifest` `diff` `decode` `neural` `recdiff`

`project`'s "channels with inserts" counts `.cst` labels, not loaded plugins.

### `plugins`

Names every slot's plug-in — Apple's by type id, a third-party one by the AU component identity in its embedded preset — and checks the third-party ones against `auval -a`. A missing verdict has not yet been compared with Logic's own missing-plug-in dialog. A component whose bundle has gone bad stays in the registry, and Logic itself opened such a project without an alert (FabFilter Pro-C 2 disabled by hand, 2026-09-16); `--validate` opens each listed component with auval -v and reports it broken.

### `regions`

Every MIDI and audio region, numbered, with its track, start, mute, loop and fades; an audio region's file record (name, format, frames, rate, channels, bits), its first frame and length in frames. Read from Logic's imports of two WAVs onto a blank-born project (2026-09-13) and Logic's own move, trim, split, mute, rename, loop, fade and import saves of one (2026-09-15, the `regions-a*` goldens): an entry pairs with its region record by slot word and piece number and with its file by slot on every project on hand with audio, so a split's second piece reads its own record. Names are UTF-8 with a byte length (region), UTF-16 LE with a unit count (file): `Snare 🥁`, `Pad — é` and `v040-日本.wav` read back as Logic wrote them. `--audio` copies a PCM WAV at the project's rate into the bundle and writes the file, region and container records held field for field to Logic's own first, second and third imports; Logic re-saved two imports written onto a blank-born project with every region record, entry and registry id as written, rewriting only each file's folder path and size, and one word of the stereo file, on load (2026-09-14). It writes onto a project with no audio regions or one whose regions are laid out as Logic's imports and splits leave them (n file records numbered 0, 4, … 4(n-1) with their region records, an ordinal/link chain in file order, one registry entry each), and refuses any other layout, a WAV whose name the project already holds, and other rates and formats. The track selection is not moved. `--move`, `--trim`, `--split`, `--loop`, `--mute`, `--rename`, `--fade-in` and `--fade-out` write the fields Logic's own edits changed, and Logic re-saved a copy carrying all eight on audio and a move, both trims, a split and loops on MIDI with every region, record, entry and the split pieces' fields as written (2026-09-15, `regions-audio-edits-*` and `regions-midi-edits-*`). A split's second piece needs the file record's region count raised — Logic loads that many — and a MIDI piece plays its sequence from an offset, which the MIDI edits then refuse; an audio region's loop length is one measurement (its length in ticks times 1000). The inspector's Gain, Delay, Transpose, Fine Tune and Reverse, the Fade-Out type, the crossfade with the region over it and a region's colour read what Logic's own edits of one region wrote (2026-09-15, the `regions-b*` goldens; gain is a tens byte plus a signed five-bit remainder); `--gain`, `--delay`, `--transpose`, `--fine-tune`, `--reverse`, `--fade-out N=MS:CURVE:TYPE`, `--crossfade` and `--colour` write those fields the way Logic did, entry for entry on the save before its own, and Logic re-saved a copy carrying all of them with every field as written (`regions-params-*`), setting one more bit beside the crossfade's. Transpose on an unflexed region made Logic flex the track, which the writer does not; Logic kept the value on load, but whether it plays transposed is unheard.

### `markers`

Reads the marker track — a marker's bar, name and length — matching Logic's Marker List on its own create, rename, move, second-marker and delete saves (2026-09-15, the `markers-a2*` goldens): 48-byte events like the arrangement's sections on the triple after the 0x11 one, names in `qSxT` records. `--add`, `--rename`, `--move` and `--delete` write those events and plain name records the way `arrangement --add` does, and Logic re-saved a copy carrying all four with both markers as written (`markers-edits-*`); Logic's own first marker also rewrote part of the registry, which ours leaves alone. A name outside ASCII is written as UTF-8, which Logic's Marker List showed and its re-save kept; Logic's own rename to one, an RTF record, is read (`names-text-*`, 2026-10-02).

### `quantize-drums`

The drum-quantize procedure as file writes: groups off, the drum group with Editing (Selection) and Quantize-Locked (Audio), Q-Reference on the reference tracks, flex Slicing, and per region the two anchors plus one flex marker per hit found in the reference audio, targets on the grid, with the RBA Sequence carrying the Quantize value. Every layout is from Logic's own saves of one take (2026-09-13). Logic opened a written copy of that take reading Quantize 1/16 Note with Flex on, and its re-save kept every marker list, header, group and object field byte for byte. The hits are ours: the detector finds 78% of the transients Logic marked on that take across four grids and 88% of its own are among them, so the result is a quantize, not Logic's. The reference audio is 16/24/32-bit PCM or 32/64-bit float WAV; `--grid` takes the measured 4, 8, 16 or 32; a song whose tempo changes and reference audio with no hits are refused. `--bars FIRST-LAST` moves only the hits in those song bars onto the grid (each region's own Quantize value unless `--grid`) and keeps every other marker block's bytes, writing a kept Quantize-Off block as a hit block with its target unchanged; it refuses a region off the song's grid, a hit whose target would cross a kept one, and an entry naming a sequence other than an RBA Sequence, and a region already quantized keeps its one RBA Sequence. A member listing only anchors — Logic's first quantize writes the hits on the first Q-Reference region alone — takes that region's hits, and the group is reused when every member with audio regions is in it; on a take Logic itself quantized this wrote one list to every member, and Logic re-saved that `--bars 9-12` copy with every member's marker list and the drum group as written (2026-09-15, `songb-bars-9-12-*`), and those bars listen as tight as Logic's own.

### `drums-to-midi`

Each `--hit TRACK=TERM` audio track's hits, found by `quantize-drums`' detector, become sixteenths on the term's key in the drum map, each cut at the next note on that key, velocity from each hit's peak scaled from the track's quietest to its loudest, quantized to `--grid` when given, in one new region on a software instrument track spanning the bars that hold the quantized notes; `--threshold DB` sets the detector's floor under the track's loudest hit, `--hit TRACK=TERM:THRESHOLD` one track's own, and `--velocity FLOOR..CEILING[:GAMMA]` maps the velocities onto a band. The region is written as `midi --region` writes one and filled through the region edits, and tempo changes are refused. Logic re-saved a copy carrying the region it wrote over a real drum take with all 350 notes as written (2026-09-15, `songb-drums-to-midi-*`). Listened to on that take: the kick and snare lanes are the playing. It is for drums with strong transients — kick, snare, toms; hats and cymbals ring under bleed and are not what this converts (the detector's 24 dB rise, not its floor, is what a hat never gives).

### `sessionplayer`

A Session Player region's settings from the JSON in its MneG record — Complexity (`rComp`), Fill Amount (`fillsAmount`) and Swing pinned by one editor move per save (2026-09-13) — with the drummer, preset and the generated notes' count. One region measured; records pair with drummer sequences in file order.

### `automation`

Reads track automation: the per-channel `*Automation` folders under the Track Automation Root Folder, their fader points (0x50: value byte, fader id) and plug-in parameter points (0x51-0x5F, 0x50 plus the mixer slot with empty slots counted, an instrument channel's instrument insert 1: a u32 over 2^31 and the parameter index; bit 14 of the type word, on some points of a real song, reads as flagged), and a region's own automation as the unreferenced sequence that names the track (2026-09-16, the `automation-*` goldens). Points were made with Create 1/2 Automation Point(s) for Visible Parameter (at the selected regions' borders) and in the Automation Event List, where Pan and the relative Volume lane were measured (the relative lane sets bit 7 of the type word's high byte). `--set`, `--copy` and `--clear` write a lane's points as the Event List does, in Logic's own order, into the track's existing folder; Logic listed three lanes written onto the blank as written and re-saved the folder byte for byte but for head +15, its selection state (`automation-ours-resave-logic`). A point's sub-tick fraction (head +2) is read and kept on a copy; Logic's own Automation Event List, read off the screen for every automation golden (2026-09-17), shows the same ticks and values as the reader, the half-tick point as the display tick before it. `--set "TRACK:slot N NAME=V@BAR"` writes a plug-in lane by mixer slot and parameter name in the parameter's own unit: the four natives with a map through their measured sliders (a value past a slider's end held there with a note), a third-party through its AU table (`autoset-*`); a value or bar that is not a finite number is refused. Logic's Event List named lanes at insert 4 as the Pro-Q 4 there and lanes at insert 1 as nothing (`slots-insert*`, 2026-09-23). The listing names a plug-in lane as `--set` takes it, with each point in the parameter's own unit: every index took the name Logic's Event List gave it and every point the value the Controls view showed, on the three `auto-*-resave-logic` saves.

### `patch`

Reads a Library patch bundle in both shapes Logic writes: its nodes, each channel's settings and the plug-ins on its strip; one Logic saved from the Library reads back with all eight inserts (2026-09-13). `--build` writes the same shape from a `.cst`; a built patch installed in the user library loaded from Logic's Library with all eight inserts on the channel. A file that does not read as a channel strip, including Logic's older-format factory strips, is refused before anything is written, and `--overwrite` replaces a bundle only once the new one is complete.

### `midi`

Notes, controllers, program changes and pitch bends read from Logic's saves of a blank project, one field changed per save (2026-09-13); the .mid is a format-1 file at the song's PPQ with its tempo map and time signatures, one track per region, and Logic imported one and saved the same events; events before bar 1 are refused. `--region` and `--note` write what Logic's Pencil click and Event List Create wrote; a region with two notes came back from Logic's re-save note for note, and so did regions named four and nine bytes long, every word after the name as written. `--note` goes into the region on its track that holds its bar and is refused when none or several do. An un-named instrument track shows its patch's name after any load. `--transpose`, `--velocity`, `--move`, `--delete`, `--quantize`, `--copy-region`, `--copy-notes` and `--remap` rewrite a region's event lines by its listing number through the integrity gate, and Logic's re-save of one copy carrying every one of them (2026-09-14) kept every region and event as written; the number means the same region (track, start, name) in every alternative. An edit that moves an event out of its region is refused, and so is an edit, not a copy, to a sequence two regions play; a MIDI region goes only onto a software instrument track. `--map` and `--remap` use groovebin's note maps (GM percussion, Addictive Drums 2's keymap, Drum Kit Designer); the pairings between them are the tables' own, chokes and stick clicks have no GM counterpart, a region with polyphonic aftertouch is refused, and no remapped pattern has been listened to. A region name outside ASCII is written as UTF-8, as Logic's own rename wrote one. The transforms (`--select` with the operations, and the presets) rewrite the selected notes' fields through the same lines and gate, and Logic re-saved a copy carrying one of every operation and preset on 27 regions with every region and event as written (2026-09-15, `midi-transform-*`); swing's tick is the one Logic's Piano Roll wrote at 60% (`midi-qswing-60-logic`).

### `beats`

The patterns, their index and the picking are groovebin's (`groovebin index`, `search`, `show`, `generate`); this writes them into a project. `place` lays one pattern, `--repeat` times, as a region from a bar whose meter must be the pattern's, `--map` translating from the map it was indexed in; `compose` writes a region per Intro, Verse, Pre-Chorus, Chorus, Bridge or Outro section from one group's patterns, with `--fills` on each section's last bar, and reports every section it skips; `generate` places a seeded phrase picked bar by bar from real library bars by their kick and snare onsets. Each region is written as `midi --region` writes one and filled through the region edits, on a software instrument track only, never lengthened for a note; the loop flag is never written and no output has been opened in Logic or listened to. Logic re-saved a copy holding a placed pattern and a generated phrase, and one holding two composed sections with their fills, with every region and note as written (2026-09-15, `beats-place-generate-*`, `beats-compose-*`).

### `stacks`

Reads folder stacks and the arrange list, nested stacks included (the member byte is the depth). `--move TRACK:STACK --out DIR` writes a copy whose rows match Logic's own drag saves (2026-09-04; into and out of a nested stack 2026-09-16, the `nest-*` goldens, and Logic re-saved a nested move as written, `nest-ours-resave-logic`), through the same integrity gate as every other writer. Into a summing stack the track's output goes to the stack's bus, the row, word and UUID as Logic's own drag left them (`stack-summing-dragged-in-logic`, 2026-10-02), and Logic re-saved a written move with every row, route and stack kept (`stack-summing-move-*`). A track moved into a folder inside a summing stack goes to that stack's bus too, as Logic's manual has a track added to a summing stack do; a stack is not moved into one at any depth. `--move-out TRACK` takes a row one level out as Logic's drags did (the `nest-*` goldens; `stack-folder-dragged-out-logic` to the top level), keeping its bus out of a summing stack (`stack-summing-dragged-out-logic`).

### `levels`

Reads fader and pan, the fader in dB to the hundredth. `--to OTHER --out DIR` copies them onto another project through the integrity gate; a copy written onto a blank project came back from Logic's re-save with every fader and pan as written (2026-09-12). `--fader CHANNEL=DB` and `--pan CHANNEL=N` set them: a fader written at -5.3 dB and a pan at -20 read so in Logic 12.4 and came back from its save as written (`send-set-*`, 2026-10-02). Logic's fader readout shows its own steps as labelled, but a level between two up to 0.1 dB low (an exact -6.0 shows -6.1), so the listing gives the level as written.

### `build` `verify` `pst` `donors` `image` `ocr`

A relative `output_dir` resolves under `~/Music/Audio Music Apps` — Logic's own library — and writing there is refused without `--install`. `--overwrite` is separately required to replace a file. Elsewhere: `output_root` (or `strip_root` / `LOGICXKIT_STRIP_ROOT`, which moves `build`'s sources too), or an absolute `output_dir`.

### `chains`

Replaces a channel's whole chain. `--plan` names every chain it would take off; `--strict` refuses on shape drift. The real tracking chains written onto the tracking template came back from Logic's re-save with all 46 channels' chains identical (2026-09-12). A chain keyed by a channel name puts declared donors on the Stereo Out with parameters named as measured; the example mastering chain opened in Logic with every value shown as written and re-saved intact (2026-09-16, `master-ours-resave-logic`).

### `retrack`

Changes a label, never a chain; basename-only library match. `--channel` repoints one channel at a time, so channels sharing a name can part ways: seven repointed on a tracking template showed on the Setting buttons and survived Logic's re-save byte for byte (2026-09-06).

### `strip-save`

A path under Logic's own library is refused without `--install` (2026-09-27).

### `send`

Writes to buses the caller declared missing; no cross-project bus remap. A project with no send to clone gets Logic's own from a blank project (packaged), and Logic re-saved one such add byte for byte (2026-09-13). A third send in a project whose slots start at key 2 moves the project to base 4 first, as Logic's own re-save does; left at 2 it shares slot 1's key and Logic drops the plug-in there (`legacy-migrate-fixed-*`, 2026-09-24). `--level`, `--mode` and `--bypass` write the send's level in dB, its mode and its bypass box: Logic 12.4's knobs showed -10.0 and 3.0 dB on two written sends and its save kept both records byte for byte (`send-set-*`, 2026-10-02). The level is 40 * log10(position / 90), walked on Logic's knob over 265 stops; Independent Pan is read and not written. An add given none of the three comes in as Logic's own second send beside one at -16.8 dB did, at -inf, post pan and on (`send-two-base-3-logic`); a second send to a bus the channel sends to is refused.

### `stack-create`

A session with no stack patterns on Logic's own first stack (packaged); Logic re-saved two such stacks with the header, strip and members as written (2026-09-13). `--summing` makes the header an aux track fed from a free bus and routes each member to it, by UUID and by index word as Logic's own Create Track Stack (Summing) wrote both; Logic 12.4 showed two written stacks, one with an instrument member, and re-saved them with every row, route and channel record as written (`stack-summing-*`, 2026-10-02). Logic's own binds the lowest free `Aux` stub where this adds a fresh strip. Direct members of one stack make a stack inside it, of either kind, as Logic's own inner Create Track Stack inside a folder wrote them (`nest-inner-*-logic`); Logic showed an outer folder holding a written summing stack and a written folder and re-saved every row, route and stack (`nest-inner-ours*`). Inside a summing stack the new aux outputs to that stack's bus. `--summing` refuses members that output anywhere but where the new aux will (Output 1-2, or the bus of a summing stack around them): Logic's own was measured over tracks already there. A header as a member is refused.

### `add-track`

Audio, instrument and aux adds; every add in one migration survived Logic's own re-save row for row (2026-09-04). With no audio stub free a fresh channel is made where Logic makes one, and Logic's re-save kept three such byte for byte (2026-09-06). Keeps the song container's row count, the region placements and the registry's slot entries in step. `--stereo` binds the pair channel `Input N-(N+1)`, as Logic's own New Tracks did with an interface attached (2026-09-17); inside a nested stack the row takes the depth of its place, and inside a summing stack outputs to its bus, as Logic's manual has a track added to one do. A fresh channel record goes after the highest owner below it and carries the project's slot base and shown-slot count; an instrument channel's default records are keyed to the project's slot and property bases. Logic re-saved ten chained adds with every plug-in and track (`addtrack-fresh-*`, 2026-09-23); a record out of owner order lost every plug-in (`addtrack-order-*`), and one instrument channel keyed for another base made a migration Logic would not open (`legacy-migrate-keyed-mine`). `--instrument --stereo` writes the width bytes Logic's own stereo instrument channel carries (`sessionplayer-track-logic`) and a stereo instrument slot; Logic 12.4 saved one with the channel still stereo and the slot byte for byte (`addtrack-inst-stereo-*`, 2026-10-01). A Logic 11.2 project is refused, as by every writer: an instrument add written to one came back from Logic 12.4 with another instrument track left without its strip (2026-10-01).

### `reorder`

Moves a row among its siblings; a stack header moves with its members, and that move reproduces Logic's own drag of a header byte for byte (2026-09-12). A plain-row move came back from Logic's re-save in the written order, every row byte held but the moved row's selection mark, which Logic clears on load (2026-09-13).

### `route`

Sets a channel's input or output by label, by UUID and by index word; an output rerouted to a bus came back from Logic's re-save with the routing intact, and the channel record written is the one Logic saved but for the word its version sets (`route-*`, 2026-09-13). An audio track takes an input pair only when stereo and one input only when mono, as every audio track on the Logic saves measured does; `width` changes which. A Logic 11.2 project is refused by its format; its class-6 channel records carry no routing uuid.

### `arrangement`

Reads matched Logic's display on every project tested; a rename plus a resize survived Logic's re-save byte for byte (2026-09-06), `--add` reproduces Logic's own add record for record and survived its re-save, and a move plus a delete came back from Logic's re-save event for event. On a song with no arrangement track `--add` makes the track as Logic's first section does, and Logic re-saved one with the section intact (2026-09-13). A name outside ASCII is written as UTF-8, which Logic's arrangement track showed and its re-save kept; Logic's own rename to one, an RTF record, is read (`names-text-*`, 2026-10-02).

### `signature`

Reads the signature track and the LCD's division on every project tested. `--time` at bar 1, `--key` (major and minor) and `--division` reproduce Logic's own edits byte for byte (2026-09-06/07); `--key-at` and `--time-at` add changes after bar 1 and survived Logic's re-save byte for byte. `--time` at bar 1 refuses songs with later meter changes.

### `toolbar`

Every button's id measured on seven saves (2026-09-07) and written in Logic's order; Logic re-saved one of ours unchanged. `--row` shows or hides the toolbar row.

### `modes`

Cycle, Replace, Autopunch, Metronome Click, Use Musical Grid and the count-in length in the song record, pinned on Logic's saves of one press apiece (2026-09-08); a copy written with four of them came up in Logic so and was re-saved intact. Solo is read but not copied — Logic clears it on load. `apply-template` copies them.

### `metronome`

The Metronome and Recording panes: nine boxes, the pre-roll time, the four Klopfgeist rows and the four MIDI click rows in the click object, pinned on Logic's saves of one change apiece (2026-09-08); a copy with six boxes and the pre-roll written, and one with changed rows copied in, each came up in Logic's pane as written and re-saved intact. `apply-template` copies them.

### `width`

A channel's width and the build of every plug-in on it, measured across real sessions and a Logic-written stereo bus; two auxes made stereo on two templates came back stereo from Logic's re-save, slots included (2026-09-08).

### `tempo`

Reads matched every project's LCD, ramps and steps included; `--set 180` showed 180 on Logic's LCD and survived its re-save (2026-09-06); `--add` writes the bare step Logic's Tempo List makes and survived its re-save; `--ramp` writes the event run Logic's Tempo Operations curve makes and survived its re-save event for event. Hand-drawn curves (the 0xb4 line) are read only.

### `rename` `colour` `hide`

Applied across three legacy migrations Logic re-saved unchanged (2026-09-04); a rename marks the name as the user's, else the arrange shows the strip setting's name; a name outside ASCII is written as UTF-8 with its byte length, the object Logic's own rename wrote (`names-non-ascii-logic`), and Logic 12.4 saved a copy carrying three with each as written (`names-write-*`, 2026-10-01) and one with names of 64, 96 and 127 bytes (`names-long-*`).

### `settings`

A slot's settings in its family's vocabulary through the plug-in's map (`data/translate`): a third-party's from its AU state's id/value pairs (Pro-C 2, with the normalized ratio, attack and release read off curves the AU host sampled) or its vendor blob (sonible's smart:comp 2 and smart:gate, real units in their protobuf block, `sonible-*`), its FabFilter binary state by band (Pro-Q 4) or its zlib JSON state (iZotope's Neutron 5, real units by module: a compressor, a gate and an EQ at once, a line per family, `neutron-*`), one of Logic's own from its measured table (Compressor, Noise Gate, Channel EQ, Multipressor), a multiband's as bands by frequency range (Pro-MB, Multipressor). A slot without a map says so. `--set` writes the same names into one slot: one of Logic's own through its table, each value held to its measured slider's ends and put on the nearer sampled position — the knob rows are sampled at every unit, the dB rows every few, where a value between samples is written as given with a note (`snap-*`), FabFilter's pairs or binary state patched in place inside the record's plist at the same length (sonible's protobuf and iZotope's JSON are read, not written); an EQ takes `band N=<shape> <freq> …`, rewriting that band and no other. `--at` is the mixer slot. Three items written into a Pro-C 2 came back from Logic's re-save shown as written, the other nine and the side chain untouched (`write-proc-*`, 2026-09-23).

### `transplant`

Each slot's side chain follows its source's name into the destination (payload +144/+145, the `sidechain-*` goldens) or is cleared with a report line. Refuses a move that overruns the slot key range — which deletes the channel's `.cst` reference record, a loss `validate_project` cannot see — and one that crosses a record class version; `--force` writes anyway. Clones take the destination's own slot keys (2 in projects whose slots start there). Two native slots moved between blank-born projects came back from Logic's re-save byte for byte (2026-09-13). One source fanned out to several channels gives each copy its own instance id, measured from a second instance of that plug-in in the source; without one the fan-out is refused. So is a third-party slot onto an audio channel of the other width (Logic's own are re-stamped; an instrument channel's width byte says nothing about its plug-in). `--stack NAME=SRC` targets a folder stack's members. One Auto-Align 2 fanned out onto a tracking song's seventeen drum channels came back from Logic's re-save with every slot byte for byte, the seventeen stamped ids included (2026-09-21, `transplant-fanout-*`). The destination's plug-in automation lanes are left as they are.

### `bypass`

Flips the bypass bit on the slots a channel already carries; adds nothing and removes nothing. Two bypassed slots came back from Logic's re-save with the bits as written (2026-09-13).

### `add-plugin`

A library plug-in into mixer slot N (from 1, empty slots counted — the insert automation names), the end without: an empty slot takes it where it is, an occupied one moves it and every later slot down a key with their automation lanes (`slots-front-*`: Logic's Event List named every lane's plug-in, 2026-09-23). An instrument channel's slot 1 is its instrument; an effect is refused there and an append lands at 2 (`slots-inst-*`). `--set` on one of Logic's own holds a value to its slider's measured ends with a note and puts it on the slider's grid. The donor is stamped as `transplant` stamps one (owner, key, index, width for Logic's own, id, bypass, the side chain `--side-chain NAME` asks for by name, none otherwise — Logic showed a written one in the plug-in header and re-saved it as written, `sidechain-ours-resave-logic`), the slots from that position on move down a key, header key and +6 index both, and the channel's Smart Control mappings move with them (without that Logic reset the channel). A chain reaching the two keys under the reference record moves the reference, the records under it and the archives above it up on every channel, and every channel record's shown-slot count follows. Logic's own appends on the `master-track-*` saves are reproduced slot for slot and the channel record byte for byte; Logic re-saved a mid-chain insert and an append with every slot, archive and channel record as written but a per-plug-in token on the new slot (2026-09-21, `addplugin-mid-*`, `addplugin-end-*`), and Auto-Align 2 into slot 1 of a tracked song's seventeen drum channels in front of their chains, the range grown by the project's own headroom (`addplugin-front-*`). Third-party plug-ins come from `logic donors PROJECT [--as NAME] [--refresh]`, one donor per width. A side chain may also be an input of the interface or an instrument track (`sidechain-input2-logic`, `sidechain-inst-*`).

### `tracking-chains`

Every third-party slot with a translation map replaced by Logic's own of its family with the settings carried (the `replace-plugin --translate` path; Neutron 5 one native per live element, the extras added after the first), a third-party without a map removed, the natives that carry lookahead bypassed, one it made from a third-party too (a Pro-MB's Multipressor, `mb-promb`). Logic-confirmed 2026-09-24 (`trk-*`): a Neutron 5 read back as the Channel EQ and Compressor it became, both Controls views on the carried values, and a re-save kept every swap and every bypass on two channels and the output. An instrument channel keeps its instrument, whatever it is (2026-09-27).

### `swap-plugin`

Every slot holding one plug-in replaced by another across the project, each through the `replace-plugin --translate` path: settings through the family vocabulary, side chains and automation lanes carried, a slot whose settings cannot cross left as it is with the reason; a `--from` no slot holds, or one naming the `--to` plug-in, refused before a copy is made. The replacement and the carry are the Logic-confirmed ones (`slots-replace4-*`, `translate-*`, `auto-lanes-*`); the loop itself Logic-confirmed on two smart:comp 2 slots into Compressors, both channels' Controls views reading the carried values (`swap-*`, 2026-09-24), and again with the packaged donors only (`swap-packaged-*`, 2026-09-25): the same carried values, and Auto Release reading 1 — the packaged `#default` donor's — where the data root's `Drum Mix` donor had read 0. The 2026-09-24 copies, and the `translate-*` ones, took a Compressor donor harvested from a real project — the packaged donor's layout and length, its preset name, values and instance id aside.

### `remove-plugin` `replace-plugin`

The plug-in in mixer slot N out of a channel, the slots after it moved up a key with their automation lanes and Smart Control mappings, the removed slot's dropped (`slots-remove-*`, Logic's Event List named the rest on their own plug-ins, 2026-09-23); an instrument channel's instrument leaves its slot empty. `replace-plugin` is that removal and an `add-plugin` at the same slot. Logic re-saved both with every slot as written, the replace's archives and channel record too (2026-09-22, `addplugin-remove-*`, `addplugin-replace-*`); the key range is left for Logic to re-lay out on save. `replace-plugin --translate` carries the old slot's settings through the family vocabulary: a Pro-C 2 dialled in Logic to -30 dB / 3.06:1 / 10.72 ms / 115 ms / 6 dB knee / +3 dB / 80 % went into a Compressor that Logic showed as -30 dB, 3.1:1, 10.5 ms, 110 ms, +3 dB, knee 0.1, 80 % and kept so on re-save (`translate-*`, 2026-09-22) — its own grids, which the map rounds to; attack and release sit on their knobs' positions and are written as read (a smart:comp 2 into a Compressor and a smart:gate into a Noise Gate came back the same way, `translate-sonible-resave-logic`). Knee is approximate (dB/72); Pro-C 2's look-ahead, auto gain, range, hold and style have no analogue and are reported, not guessed, as is the Compressor's circuit the other way; the target keeps its own. An EQ crosses as bands: a Pro-Q 4 dialled to nine bands went into a Channel EQ that Logic showed with the low cut, four bells, high shelf and high cut as planned and re-saved as written but for its knobs' own frequency and Q positions (250.01 Hz to 250, Q 2.43 to 2.50; `translate-proq-*`, 2026-09-22); the notch and the fifth bell were reported, not placed. The slot's automation lanes follow the translation (`automation_remap`): a Pro-C 2's threshold, ratio and attack lanes landed on the Compressor's indices in its slider units and Logic's Event List listed them by name, its Controls view following them in Read — -30, -24, -12 dB, 3.9:1 and 2.7:1, 16 ms (`auto-lanes-*`, 2026-09-23); a lookahead lane with no analogue was dropped with a line. An EQ's or a multiband's lanes cross by band, onto the band the plan placed each in: a Pro-Q 4's low-cut on/off, bell gain and bell frequency lanes reached the Channel EQ's Low Cut, Peak 1 and Peak 3 and read 1/0/1, -4/0/+6 dB and 1000/2000 Hz, a Pro-MB's threshold, ratio and level lanes the Multipressor's band 1 and 4 and read -20/-12/-30 dB, 3.675 and 1.977 (its ratio knob's grid), +1 dB (`auto-eqlanes-*`, `auto-mblanes-*`, 2026-09-23); the four natives' sliders are measured for it. `--keep-automation` leaves the lanes; with neither they are dropped with a line, and so is the side chain. The other way round, a FabFilter replacement takes the plan into its own state: Logic's Compressor into a Pro-C 2 that Logic showed as -30 dB, 3.10:1, 10.49 ms, 109.8 ms, +7.20 dB knee, +3 dB, 80 % (attack and release land between the sampled curve's points; `write-comp2proc-*`), and a Channel EQ into a Pro-Q 4 whose seven bands Logic showed as written, the off low shelf left out (`write-eq2proq-*`, 2026-09-23); what the donor keeps of its own is reported. A multiband compressor crosses as bands by frequency range: a Pro-MB's three bands went into a Multipressor Logic showed as written but for its ratio and crossover knobs (4.0 as 3.675, 4 kHz as 3.9), and that re-save came back into a Pro-MB as written (`mb-*`, 2026-09-23). A stretch no source band covers is a live band at ratio 1, since an off band's range goes to the next live one (`mb-neutral-*`); Pro-MB's range limit and percentage times, and a Multipressor band's expander beside its compressor, are reported, not guessed.

### `clear-slots`

Drops the records and their key flags; the `.cst` reference label stays. Opened in Logic with the inserts empty (2026-09-04); without the flag sync Logic refuses the file.

### `header`

Every bit measured on seventeen single-toggle saves; a written set opened in Logic showing all sixteen components as set.

### `prefs`

Logic's own settings: 150 controls across every Settings pane pinned by single changes (General > Editing 2026-09-05, the rest 2026-09-08); a box written with Logic closed came up that way on relaunch. Not carried: Audio > Devices, Plug-in Delay Compensation, Control Surfaces (Logic's own file). Writes go through `defaults`, are refused while Logic runs, and take a backup first.

### `controlbar`

Every id measured on fifty single-toggle saves (2026-09-04); a bar copied whole onto another project came up in Logic with that set. Both display-state files written.

### `group`

Every box and the member events measured on twenty-eight single-change saves (2026-09-05); the writer reproduces six of Logic's saves byte for byte, and a migrated song with two groups opened in Logic showing them and re-saved with the identical group records and row list. Leaving a group: Logic's own No Group on a member (2026-09-12) matches the composed leave outside the selection bytes. A name outside ASCII is UTF-8 by its byte length, as Logic's own rename wrote one; Logic's Groups inspector showed one written here (`names-text-*`, 2026-10-02).

### `apply-template`

Same lineage pairs by object id; across lineages `--map FILE` says how tracks pair (`--propose-map` drafts it, `(none)` leaves a track alone). Legacy songs migrated onto a mixing template opened in Logic and re-saved with the identical row list (2026-09-04). Never removes a send; inputs past the session's count are made before planning (Logic re-saved six); the template's groups are made and joined by name (2026-09-05, confirmed on the same song). Legacy bus returns the template duplicates are silenced; `-` lines in the map leave template tracks out. A song whose slots start at key 2 beside three sends is moved to base 4 in the same pass, as Logic's own re-save does; a project born at base 2 without that collision is left there (`logic/README.md`: slot keys). Also carries the track power state, icons, header components and the control bar; not the project's own tempo, meter or key, which stay the song's. The current tracking template applied onto a tracked song (2026-09-16) re-saved in Logic with the identical row list and strip references, two of them repointed per channel. A template stack is the session stack its header pairs with, else the one stack of its name; two of the name with neither paired refuse the move. An output to a bus the template returns and the session will not is refused. A Logic 11.2 save serves as the template: its routing is read from the channel records' index words (every routed channel as Logic 12.4 converted it, 2026-10-02); its chains are refused, its slot records being another class.

### `migrate`

Composes `propose-map` (or `--map FILE`) with `apply-template`'s step into `CLAUDE migrated - <song>.logicx`: the ops are apply-template's CONFIRMED writers, A session of the template's lineage pairs by object id and the draft is not applied. `--verify` drives Logic Pro — opens the copy, Save As through `tools/driver`, closes without saving — and compares the row lists ignoring only the flag word; it runs from a checkout on macOS with Logic installed and has not yet been run against Logic. Logic re-saved a migrated legacy session with every row and plug-in as written (2026-09-24, `legacy-migrate-fixed-*`).

## The two rules that matter most

**1. `apply-template` pairs by object id within a lineage and by a map across one; without a map it refuses.**
`services/pairing.py` pairs on Environment object id, then mixer label, then name. Two
unrelated projects both have an `Audio 1`, so the label rule pairs them happily: on one legacy song
that meant renaming *Guitar 1* to *Kick In* and *Bass* to *Snare Up*.

`match_quality` scores the share of rows paired by object id, and the command refuses below
`LINEAGE_FLOOR` (0.5). Songs cut from one recording template score 1.00; the legacy
songs score 0.02 and are refused by name, with an example of what would have been
renamed. `--force` overrides, and says so loudly.

A session with a few tracks remade by hand loses only a few points, which is why the floor sits
at 0.5 rather than near 1.

**2. Every write is gated, but a gate is not an audition.** `services/integrity.py` holds
a project against the input it was given and refuses on any regression — new record-level
problems, more sequence link errors, objects whose mixer index stopped matching their channel,
channels whose send flags stopped matching their sends, a strip reference placed outside its
channel's records. It runs in `_edit.edit_copy` — the
path every `ProjectData` writer takes except `retrack --map` — and in `chains`, before the write
and again by reading the file back. A refused run discards the whole copy rather than leaving a bundle that
disagrees with its own metadata.

Proof it works: `apply-template` on a legacy song stops with `sequence link errors 0 -> 5`
rather than writing a corrupted project.

The gate covers structure, not sound. It cannot tell you a chain is on the wrong channel or
that the mix is wrong, so: **open every output in Logic before trusting it.**

## Known defects

Each of these was reproduced on a real Logic project, not inferred.

**Still open:** none. A defect reproduced on a real project goes here, with the command it
names, until a regression test closes it.
