# Changelog

Notable changes to logicxkit. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

## 0.8.0 — 2026-10-02

### Added

- Projects saved by Logic 11.2 are read: tracks are named, channels bound and routed. One
  serves as an `apply-template` template, its chains aside; every writer still refuses one as
  the project to change.
- `rename`, `add-track --name` and `stack-create --name` take a track name outside ASCII (1 to 127
  bytes of UTF-8, with a visible character), and a track is found by name whether the argument is
  composed or decomposed.
- Send levels in dB, with the send's mode and bypass: `send --set CHANNEL=BUS` and `send --add`
  take `--level DB`, `--mode post-pan|post-fader|pre-fader` and `--bypass on|off` (which need one of
  them), and `manifest` lists each send's level, mode and bypass.
- Faders in dB: `levels --fader CHANNEL=DB` and `--pan CHANNEL=N` set them, and `levels` and
  `manifest` list every fader in dB to the hundredth.
- `automation` lists a plug-in parameter lane by the name `--set` takes (`slot N NAME`) with its
  plug-in and each point in the parameter's own unit; `--json` gains `plugin`, `name`, `unit`
  and each point's `in_unit`.
- `stack-create --summing` makes a summing stack: an aux fed from a free bus, the members routed
  to it. Members that output anywhere but where the aux will are refused.
- `stack-create` makes a stack inside a stack, from tracks that are direct members of one.
- `stacks --move` moves a track into a summing stack, its output sent to the stack's bus, and
  `stacks --move-out TRACK` takes a track one level out of its stack. A track that enters a
  summing stack at any depth, added, moved or stacked there, outputs to its bus; one moving
  within it keeps its output.
- `markers`, `arrangement` and `group` write a name outside ASCII (a group's up to 63 bytes of
  UTF-8); a marker or section name cannot start `{\rtf`.

### Changed

- The write gate refuses an edit that leaves an in-use channel bound to no track.
- `--stack NAME` and `stacks --move` refuse a name two stacks share, and take `NAME (Sub 1)` or
  `NAME (Aux 9)`.
- `route` and `add-track` write a channel's routing index words with its UUIDs.
- `route --input` gives a mono audio track one input and a stereo one a pair, and refuses
  the other way round.
- `send --add` without `--level`, `--mode` or `--bypass` makes the send Logic adds: −∞ dB,
  post pan, on. A second send to a bus the channel already sends to is refused.
- `apply-template --plan` says when the run can do channel ops it did not list.
- For code that imports the library: the record stream (`HEADER`, `project_records`,
  `reassemble`, `ProjRecord`) is `logicxkit.logic.services.stream`, channel-record facts are
  `services.mixer`, slot facts `services.slots` and plug-in names `services.plugin_names`;
  `services.insert` keeps `insert_slots` and the width writers. `logicxkit.logic` exports the
  same names as before.

### Fixed

- `add-track --instrument` no longer writes a copy Logic refuses to open ("The operation could
  not be completed.").
- `add-track --instrument --stereo` makes a channel that stays stereo in Logic.
- A marker or section that Logic renamed to a name outside ASCII, and one whose record carries
  bytes after its text, no longer reads as unnamed; a group's name outside ASCII reads as Logic
  shows it.
- `stacks` and `manifest` no longer list an aux track inside a folder stack as an empty summing
  stack.
- A track name of any length reads.
- `toolbar --from` a project with no `DisplayState.plist` says so instead of failing.
- `apply-template` moves a track into the session stack the template's stack header pairs
  with, not the last stack of that name, and refuses when two share the name and neither pairs.
- `apply-template` no longer routes a track to a bus whose return it could not place.

## 0.7.1 — 2026-09-30

### Changed

- logicxkit depends on `groovebin~=0.4.1` and `pf-core~=0.24.0`. The `rig` extra pins
  `x32scene~=0.6.0`, the first x32scene on that pf-core.

### Fixed

- Track names outside ASCII read as Logic shows them (Logic 12.4's save,
  `names-non-ascii-logic`). 0.7.0 dropped such a track's object, so an `add-track` above its
  channel left its mixer index stale and the write gate did not see it. An object whose name is
  not UTF-8 text stays in the reader with no name. Writing a name outside ASCII is still refused.

## 0.7.0 — 2026-09-29

### Added

- `logic add-plugin --plugin NAME --channel LABEL | --stack NAME [--at N]` puts a plug-in from the
  donor library into mixer slot N of a copy (from 1, empty slots counted; after the last without
  `--at`). An empty slot takes it where it is; an occupied one moves it and every later slot down,
  with their automation lanes and Smart Control mappings. On an instrument channel slot 1 is the
  instrument: an effect is refused there and an append lands at slot 2. `--bypass`,
  `--side-chain NAME` and `--set NAME=VALUE` set the slot up on the way in. Each copy gets its own
  instance id where the plug-in's id bytes are measured; Logic gives the rest one on load. A
  third-party plug-in is refused on an audio channel of the other width unless the library holds
  that width, and so is one of Logic's own whose other width is unmeasured (Binaural
  Post-Processing, Correlation Meter, Direction Mixer, Stereo Spread and Pedalboard's Tru-Tape
  Delay go on stereo channels only); `--force` writes past a width or class-version refusal.
- `logic remove-plugin --at N` takes the plug-in in mixer slot N out and moves the later slots up
  with their lanes and mappings; the removed slot's lanes and mappings go with it. Removing an
  instrument leaves slot 1 empty.
- `logic replace-plugin --at N --plugin NAME` puts another plug-in in the slot. `--translate`
  carries the old slot's settings, side chain and automation lanes across through the family maps
  and reports what has no analogue, was clamped or is approximate; `--keep-automation` leaves the
  lanes as they are; with neither, the lanes are dropped with a line, and so is the side chain.
- `logic settings PROJECT` lists every slot's settings in its family's terms — compressor, gate,
  EQ by band, multiband by band — by mixer slot. Maps: Logic's Compressor, Noise Gate, Channel EQ
  and Multipressor; FabFilter Pro-C 2, Pro-Q 4 and Pro-MB; sonible smart:comp 2 and smart:gate;
  iZotope Neutron 5 (compressor, gate and EQ). `--set NAME=VALUE` or `--set "band N=<shape>
  <frequency> …" --channel LABEL --at N --out DIR` writes one slot of a copy (Logic's own and the
  FabFilter plug-ins; sonible's and iZotope's are read only); a band edit changes that band only.
- Parameter tables for 66 of Logic's own plug-ins and packaged donors for 71, at both widths where
  Logic has two. `project` names a slot's parameters from them; `add-plugin --set` dials them, each
  value held to the slider's measured ends (with a note) and put on the slider's grid, where Logic
  keeps it on load. Plug-ins that share a block type (Tape Delay and Echo, Phaser and Microphaser,
  Pedalboard and its stompbox) are told apart.
- `logic automation --set "TRACK:slot N NAME=V@BAR,…"` (and `--clear`) writes a plug-in parameter
  lane by mixer slot and parameter name, in the parameter's own unit: Logic's Compressor, Noise
  Gate, Channel EQ and Multipressor through their measured sliders, a third-party plug-in through
  its AU table. TRACK is the track's name or its mixer label. A value past a native slider's end is
  held there with a note; a value or bar that is not a finite number is refused. The listing names a
  plug-in lane `insert N parameter M`, and `--json` carries `slot`.
- `logic swap-plugin --from NAME --to NAME --out DIR`: every slot holding one plug-in replaced
  by another across the project (`--channel`/`--stack` narrow it), settings carried through the
  family vocabulary, side chains and automation lanes with them, a slot whose settings cannot
  cross left as it is with the reason; `--plan` writes nothing. A `--from` no slot holds, or one
  naming the `--to` plug-in, is refused before anything is written. Logic-confirmed (`swap-*`).
- `logic tracking-chains PROJECT --out DIR`: a project's chains made low-latency and native on a
  copy — every third-party slot with a map becomes Logic's own of its family with the settings
  carried (Neutron 5 one native per live element), the rest removed unless `--keep-unmapped`,
  the natives carrying lookahead bypassed unless `--keep-lookahead`, one it made from a
  third-party (a Pro-MB's Multipressor) too; `--plan` writes nothing.
  Logic-confirmed (`trk-*`).
- Side chains: `plugins` shows each slot's source; `add-plugin` and `replace-plugin --side-chain
  NAME` set one by the name of a track (audio or instrument), a bus or an aux return, or as
  `Input N`; `transplant` and `apply-template` carry each slot's side chain to the channel of the
  same name in the destination, or clear it with a report line.
- `logic donors PROJECT [--as NAME]` harvests third-party plug-ins, one donor per plug-in, width
  and class version; `--refresh` replaces the donors the library already holds.
- `logic transplant --stack NAME=SRC_LABEL` puts SRC_LABEL's slots on every member of a folder
  stack.

### Changed

- The write gate (`services/integrity.py`) also refuses a strip reference placed outside its
  channel's records.
- `config/example-chains.json` and `config/example-strips.json` run as shipped from a checkout
  against the strips under `tests/corpus/strips/` (`LOGICXKIT_STRIP_ROOT=tests/corpus/strips`),
  exported by `strip-save` from the public corpus; `build` names a missing strip and the root it
  looked under.
- `logic transplant` from one source to several channels gives each copy its own instance id and
  refuses the fan-out when it cannot; a third-party slot onto an audio channel of the other width
  is refused (`--force` writes anyway). The destination's plug-in automation lanes are left as
  they are.
- `logic donors` in an installed copy refuses until `LOGICXKIT_DATA` or `--library` names a
  folder.
- Every writer refuses a result whose channel records are out of owner order, whose plug-in
  record's slot index disagrees with its key, or whose channel archive sits off its key.
- The packaged Space Designer donor names a neutral impulse-response path: choose the IR again
  after `add-plugin`.
- The package's own data files win over the data root's of the same name: record templates,
  native donors, parameter tables and translation maps. The data root adds what the package lacks,
  and `logic donors` into it leaves the plug-ins the package ships.
- A translation from a Pro-C 2 reports its style, range and hold as not carried, and one from
  Logic's Compressor its circuit type.
- Every writer refuses a project Logic 12.3.1 did not save (file format 2513) before anything is
  copied, naming the alternative and the format it found; a project from an earlier Logic is
  opened and saved in the current one first. The readers run on any save.

### Fixed

- A spec's `auto_release` and `limiter` set the Compressor's Auto Release and Limiter On; 0.6.0
  wrote `auto_release` to Limiter On and `limiter` to Limiter Threshold. A strip or chain 0.6.0
  built from a spec with `auto_release` has the Limiter on and Auto Release as the donor held it:
  rebuild it.
- `add-track`: a fresh channel record goes in owner order and carries the project's mixer-wide
  fields (the slot base, the shown-slot count and four more) instead of its template's, a fresh
  aux the values of Logic's own new aux channel strip, and an instrument track's default records
  are keyed to the project. 0.6.0 could write a project where Logic dropped every plug-in on load,
  or the plug-ins of Audio 1 and the Stereo Out after ten adds, or, with an instrument track, one
  Logic would not open.
- A third send on a channel of a project whose slots start at key 2 (`send`, `apply-template`,
  `migrate`) moves the project to base 4 first; 0.6.0 put it on slot 1's key and Logic dropped the
  plug-in there.
- `apply-template`'s `refs` op onto a channel carrying no strip reference puts the record among
  that channel's own; 0.6.0 put it at the end of the file, on no channel.
- Every writer's copy leaves `Alternatives/*/Autosave` behind. A source open in Logic carried its
  pre-edit autosave into the copy, and Logic offered that version on open.
- `project` listed a slot's second state copy — the one Logic writes after the live block — as
  another plug-in, under its parameter table's names.
- `add-plugin --set`, `chains` and the other slot writers patch a donor's state copies along with
  its block, as `build` does; a two-block donor kept the copy's old values, which Logic may load.
- `tracking-chains` keeps an instrument channel's instrument; a third-party or Apple AU instrument
  in slot 1 was removed as a plug-in with no native analogue.
- `strip-save -o` under Logic's own library is refused without `--install`, as `build` and `pst`
  are; 0.6.0 wrote there.
- A bundle without `MetaData.plist` and an `--out` naming a file are refused in a sentence, not an
  errno.
- `add-track --instrument --stereo` makes the instrument channel stereo; `--stereo` was ignored
  on an instrument track.
- `settings` and the translation notes print a value of 10,000 or more in full (`20000 Hz`, not
  `2e+04 Hz`).
- `add-track` whose pattern track has a stale index-table entry clones the entry from a track of
  the same kind; it could take an aux's or an instrument's.
- `au preset` and `au strip` refuse a missing path in a sentence (`no such file: PATH`), not an
  errno.
- `project`'s listing prints plug-in values without float32 noise (`0.0`, not `5.3e-15`);
  `--json` keeps the stored values.
- The tests run from an unpacked sdist or a git archive: the git-index checks skip there, and the
  cache-path test no longer depends on `HOME`.

## 0.6.0 — 2026-09-17

### Added

- `logic automation` reads track automation: each channel's lanes and points (fader points with the fader
  byte, plug-in parameter points with the 0..1 float and parameter index), and a region's own automation,
  from Logic's `*Automation` folders (the `automation-*` goldens); `--set`, `--copy` and `--clear` write a
  lane's points the way the Automation Event List does, Pan and the relative Volume lane included; Logic
  listed three lanes written onto the blank as written and re-saved them (`automation-ours-resave-logic`).
  A parameter point whose type word carries bit 14 (seen on a real song) reads as flagged rather than
  being dropped. A point's sub-tick fraction (head +2; Logic's region-border points sit half a tick
  off) is read, kept on a copy and written in Logic's own order, so the re-save is our write byte for
  byte but for Logic's selection byte; two points at one position are refused; a tick past the
  32-bit line is refused. The three write flags apply in the order typed.
- `logic stacks` reads a stack inside a stack (the member byte is the depth; a nested header lists among its
  parent's members, `--json` carries `depth` and `parent`), and `--move` puts a track or a whole stack into
  a nested stack, or a member one level out, matching Logic's own drags by membership, depth and stack
  index (the `nest-*` goldens); Logic re-saved a nested move as written (`nest-ours-resave-logic`).
  `reorder` and apply-template's moves carry a header's nested stack along with its members; `add-track`
  places a row inside a nested stack at its depth; a moved header keeps its expanded bit; `--stack` on
  `quantize-drums` and `apply-template` takes a nested stack's rows too; apply-template leaves a nested
  member one level per move.
- The packaged donor library carries Linear Phase EQ, Multipressor, Adaptive Limiter and Limiter
  (`bin/regen_data.py` harvests it from two corpus saves); `services/output_params.py` names the float
  indices Logic's one-knob saves moved, and `chains` names the three new plug-ins.
- `chains` takes a chain keyed by a channel name (`Stereo Out`): its plug-ins in slot order from declared
  donors, parameters by the names `output_params.py` measured or by an index inside the donor's block;
  `config/example-mastering.json`. Logic showed the example chain's values as written and re-saved it
  intact (`master-ours-resave-logic`). The chain is checked before the write — a name two channels carry,
  a channel keyed both by strip reference and by name, an index outside the block, a named parameter on a
  donor with a shorter block — and read back after it; `--plan` names the channel; `stereo` widens it; a
  `pre`/`post` parameter goes by name or index; a dialled parameter wins over a strip's float; any refusal
  discards the copy, and the structure gate compares against the file's own bytes.
- `plugins --validate` opens each listed third-party component with `auval -v` and reports one whose bundle
  has gone bad as broken, a hang past the timeout included; each component is announced as it is checked
  and the verdict read from auval's own failure markers.
- `patch` reads the fader and pan bytes from a patch's `#Root.cst` channel record (`PatchChannel.fader`
  and `.pan_byte`, after its other fields); five Library saves join the corpus (a fader step, an insert,
  a send, a summing stack).
- `add-track --stereo` binds the track's input to the `Input N-(N+1)` pair channel, as Logic's own New
  Tracks does with an interface attached (`tracks-stereo-pair-logic`); an even input number is refused.
- Logic's MIDI import pairs nested same-pitch notes first in, first out (`midi-nested-import-logic`),
  as groovebin's reader does; a tempo point's head +15 bit 0 is list-edit state Logic does not restore
  (`tempo-bit-cleared-resave-logic`).
- `plugins` runs the `auval -a` registry scan only when a slot needs it, and a scan past its timeout
  reads as unknown rather than ending the command.
- `midi` edits write a note's channel (a channel edit on a note read from the file took no effect);
  `--export` says which aftertouch and pressure events the file cannot carry; a note-off line is refused by
  name; the report counts duplicate notes; `--seed` refuses a non-decimal digit.
- Linear Phase EQ's cut bands name their third float `slope` (the order, dB/Oct ÷ 6), not a gain; the band
  stride is pinned by the default frequency ladder.
- 40 public goldens from session C (2026-09-16): the four output plug-ins on the Stereo Out and on a
  track with sixteen parameter saves, stack nesting, automation, a Session Player player change.

### Changed

- The public golden corpus is tracked in the repo under `tests/corpus/`, so a golden ships in the commit
  that adds its test. `bin/run fetch-corpus`, `tests/goldens/corpus.json` and CI's fetch step are gone;
  `LOGICXKIT_RESOURCES` names the owner's corpus only.
- `apply-template` repoints a strip reference per channel, so two session channels that share a reference
  may part ways when the template names them differently. The current template applied onto a tracked
  song re-saved in Logic with the identical row list and references (owner golden).
- `bin/run` no longer lets `.env` override a variable given on the command line.
- groovebin 0.3.0 is required; `logic beats` takes the pattern library's default path from it, so an
  empty `XDG_CACHE_HOME` reads as unset on both sides.
- `logic toolbar` discards its copy when a write fails, like the record editors; the DisplayState writers
  read back what they wrote.
- The sdist names its files: nothing gitignored under `config/` or `docs/`, no corpus, no golden tests;
  `tests/test_sdist.py` builds it and checks. `tools/stage_public.py` refuses a save whose project title
  lacks the neutral prefix or a name, key or note with a private word, and leaves autosaves out; the
  autosaves that had reached the corpus are gone. The sdist test also refuses a file git does not track.
- `header` and `controlbar` discard their copy when a write fails, as `toolbar` does.
- `chains` reports a channel narrowed to mono as narrowed, not widened.
- `plugins --validate` counts a component as passing only on auval's own success line.
- `apply-template --plan` names a strip reference the session carries and the template lacks, as a
  refused op; clearing one is not written.
- `docs/CAPABILITIES.md`: a three-column table, the catch per command under its own heading.
- `stacks` resolves a folder like every other command and reads each alternative with its own track count.
- The tempo word 27511 is on the owner's Tempo List adds only; the blank's created points carry 0, so
  it is read and kept as an unknown, not a create marker.
- `LOG_FILE` and `LOG_LEVEL` are documented in `.env.example`.
- `chains` reports a class v2 Channel EQ strip (51 floats) as an older layout written onto the current
  52-float block, not as a chain that differs from its strip, so `--strict` passes it; class v3 appended
  the one trailing float and indices 0–50 are the same layout.
- The owner's sessions and the stack-move and group saves are reached by manifest key, so the goldens
  line counts them and their facts come from the manifest.
- Every write command names the alternative in each line it reports, so one edit on a project carrying
  more than one no longer reads as several: `automation`, `beats`, `reorder`, `colour`, `rename`,
  `hide`, `add-track`, `stack-create`, `group`, `stacks --move`, `quantize-drums` and `drums-to-midi`
  join the ten that already did.

### Fixed

- The suite gates its own shape: `tests/test_test_layout.py` refuses a test defined below a file's
  `unittest.main()` (26 files had drifted there, so a direct run of one reported OK having collected a
  fraction of it), and `tests/test_declared_dependencies.py` refuses a `pyproject.toml` pin the venv does
  not hold — `pip check` reads installed metadata and cannot see that drift. The stale-bytecode purge
  covers `tests/` as well as `src/`.
- `tests/logic/test_alternative_labels.py` refuses a per-alternative step that reports without naming
  its alternative, whether it prints or appends to a list its caller prints.
- The writer's tick ceiling is pinned to its literal; the test read it from the module it checks, so any
  ceiling passed.

## 0.5.0 — 2026-09-15

### Added

- `logic midi` transforms — Logic's Transform window: `--select` by position (song bars), pitch, velocity,
  length and channel with `--set`, `--add`, `--mul`, `--min`, `--max`, `--random`, `--flip`, `--quantize
  position=|length=`, `--crescendo`, `--exp` and `--reverse`, and the presets `--humanize`, `--fixed-velocity`,
  `--velocity-limit`, `--random-velocity`, `--crescendo`, `--reverse-position`, `--reverse-pitch`,
  `--exp-velocity`, `--fixed-length`, `--max-length`, `--min-length`, `--half-speed`, `--double-speed`,
  `--legato`, `--staccato` and `--swing`, over the regions numbered after the project or every region on
  `--track`; `--seed` repeats the random moves. Swing puts every second grid line late by grid × (2·swing − 1),
  the tick Logic's Piano Roll wrote at 60% (`midi-qswing-60-logic`). A step that moves a note's position
  is refused on a region holding controller, bend or program events, which would stay behind. The
  arithmetic is groovebin 0.2.0's.
- `logic regions` reads and writes an audio region's Gain, Delay, Transpose, Fine Tune and Reverse (`--gain`,
  `--delay`, `--transpose`, `--fine-tune`, `--reverse`), the Fade-Out type (`--fade-out N=MS:CURVE:TYPE`), a
  crossfade into the region over it (`--crossfade`) and a region's colour (`--colour`), as Logic's own edits
  of one region wrote them (the `regions-b*` goldens).
- `logic drums-to-midi --hit TRACK=TERM:THRESHOLD` gives one track its own detector floor and `--velocity
  FLOOR..CEILING[:GAMMA]` maps the velocities onto a band.
- The `midi` and `regions` listings say `2 event(s), 1 played` when a MIDI split leaves a region holding more
  than it plays; `--json` carries `played`.

### Changed

- logicxkit depends on `groovebin~=0.2.0`.

## 0.4.0 — 2026-09-15

### Added

- `logic regions` edits a region by its listing number on a copy: `--move`, `--trim`, `--split`,
  `--loop`, `--mute`, `--rename`, `--fade-in`, `--fade-out`; the listing shows mutes, loops,
  fades and a split piece's first frame. CONFIRMED: Logic's re-save of copies carrying every edit
  kept each region, record, entry and split piece as written.
  A flexed region is neither trimmed nor split, and a MIDI split's second piece — which plays the
  parent's events from an offset — takes no `midi` edit. Regions playing one sequence take a mute each and no
  other edit; `midi --copy-notes` copies the notes a region plays. A region or marker number means the same
  region or marker in every alternative, refused where one lacks it.
- `logic markers`: the marker track, and `--add`, `--rename`, `--move`, `--delete` on a copy.
  CONFIRMED: reading matches Logic's Marker List on its five marker saves, and Logic's re-save of
  a copy carrying all four edits kept both markers as written.
- `logic migrate`: propose-map (or `--map`) and apply-template in one run into
  `CLAUDE migrated - <song>.logicx`, with a checklist; `--save-map` keeps the draft, and
  `--verify` has Logic Pro re-save the copy and compares the row lists. CONFIRMED: Logic's re-save
  of a migrated legacy session kept its rows as written.
- `logic midi` edits a region by its listing number on a copy: `--transpose`, `--velocity`,
  `--move`, `--delete`, `--quantize`, `--copy-region`, `--copy-notes`. CONFIRMED: Logic's re-save
  of a copy carrying every edit kept every region and event as written.
- `logic midi --remap [N=]SRC:DST` translates drum notes between groovebin's note maps (`gm`,
  `addictive-drums-2`, `drum-kit-designer`) and counts the notes left unmapped; `--map NAME` names
  each note's stroke in the listing. CONFIRMED by the same re-save.
- `logic beats place`: one pattern from a groovebin library as a MIDI region on a software
  instrument track from a bar, `--repeat`, `--map` and `--velocity`, on a copy; refused where the
  project's meter is not the pattern's. CONFIRMED by Logic's re-save (`beats-place-generate-*`).
- `logic beats compose`: a region per Intro, Verse, Pre-Chorus, Chorus, Bridge or Outro section
  from one group's patterns, `--fills` on each section's last bar, on a copy. CONFIRMED by Logic's
  re-save (`beats-compose-*`).
- `logic beats generate`: a seeded phrase picked bar by bar from library bars by kick and snare
  onsets, `--fills` every fourth bar, into a copy. CONFIRMED by the same re-save as `place`.
- logicxkit depends on `groovebin`, which owns the general-MIDI code: Standard MIDI File reading
  and writing, the note maps, the note transforms and the pattern library (`groovebin index`,
  `search`, `show`, `generate`); logicxkit keeps what writes Logic projects.
- `logic drums-to-midi`: hits in audio tracks as notes on drum-map keys, velocity from each hit's
  peak, in one new MIDI region on a copy, `--grid` to quantize and `--threshold` for the detector's
  floor; a WAV whose rate or frame count disagrees with its file record is refused. CONFIRMED: Logic's
  re-save of a copy written over a real drum take kept the region and every note.
- `logic quantize-drums --bars FIRST-LAST` re-quantizes only the hits in those bars and keeps
  every other marker block. CONFIRMED: Logic's re-save of a `--bars` copy of a take it had quantized
  itself kept every marker list and the drum group.
- The integrity gate refuses a write that loses a region entry, moves one to another track,
  changes the file an audio region plays, adds region records past the file records or the
  reverse, leaves a region's sequence slot unregistered (a lost registry included), breaks
  marker-block framing, strips a flexed region's markers, puts markers on a MIDI region, writes
  marker targets out of order, or leaves more RBA Sequences that no region names.

### Changed

- `logic midi` numbers regions across the song, keeps the numbers under `--track`, and `--json`
  carries them as `number`.
- A write by a CONFIRMED command prints the DERIVED notice when it uses a flag that is not yet
  confirmed.
- `logic midi --region` puts a MIDI region only on a software instrument track.
- Region, sequence and audio file names outside ASCII are written as Logic writes them (UTF-8
  with a byte length; UTF-16 LE with a unit count), library pattern names included.
- `logic quantize-drums --grid` takes 4, 8, 16 or 32, the measured values, and defaults to each
  region's own Quantize value under `--bars`.

### Fixed

- `logic regions` and `logic midi` read a split's second piece from its own record and file
  (entries pair with records by slot word and piece number), a MIDI split piece's events at the
  time Logic plays them (its sequence offset), the loop flag from the right bit (edited regions
  no longer show as looped), and file names by their UTF-16 unit count.
- `apply-template --map` keeps pairing a `Name (Sub N)` row after the run's own stack creation
  renumbers the Sub strips.
- `apply-template` on a project with several alternatives writes nothing unless the map fits the
  first alternative, and a later alternative the map does not name keeps its bytes.
- A map file round-trips track names with outer spaces or two spaces before `#`.
- Every writer gives each alternative its own track count.
- `stack-create` and `apply-template` keep a later Sub strip's label equal to its number, and
  pattern a new folder stack on the highest folder stack, never a summing stack's Aux.
- The onset detector (`quantize-drums`, `drums-to-midi`) finds a hit in a file's first samples.
- `logic quantize-drums` treats a region whose slot names an RBA Sequence as quantized, so it never
  gives it a second one.
- `logic quantize-drums --bars` on a project Logic quantized itself: a member whose marker list
  holds only the two anchors takes the reference region's hits, and the drum group is reused when
  every member with audio regions is in it, instead of a second group being made.
- The `logic midi` and `logic regions` listings read the project's track count, and print `-` for
  a track name an old project does not carry.

## 0.3.0 — 2026-09-14

### Added

- `logic quantize-drums`: the live-drum quantize on a copy without Logic — the drum group with
  Editing (Selection) and Quantize-Locked (Audio), other groups off, Q-Reference on the
  reference tracks, flex Slicing, and one flex marker per hit found in the reference audio with
  its target on the 1/N grid (`services/onsets.py`, `flexmarkers.py`, `quantize_drums.py`).
  CONFIRMED: Logic re-saved a written take with every marker intact.
- `logic regions` reads a region's first frame within its file.
- `midi --region` and `regions --audio` place their entry correctly on a project whose regions
  carry flex markers.
- `logic regions` maps an entry to its region record by ranking the counters of every audio
  entry in every sequence, take folders included; the earlier base-offset rule mislabelled a
  project with take folders.
- `logic quantize-drums` takes a reference's audio from the file named after its region,
  handles member regions that start at different bars, and names the files it used.
- `logic project` names a native insert from its type id when the slot carries no name string,
  as `plugins` does; a built patch's eight inserts read as eight.
- The drum-quantize onset detector is tuned against the transients Logic marked across four
  grids: 78% of them found, 88% of its own among them (was 55% and 90%).
- The package carries Logic's own record templates and native plug-in donor slots, regenerated
  from the public corpus by `bin/regen_data.py`, so `add-track`, `stack-create`, `send --add`,
  `arrangement --add` and native `chains` work after `pip install` alone; a data root
  (`LOGICXKIT_DATA`) still takes precedence, and `chains` reads both donor libraries.
- `stack-create` works on a session with no stack, patterning on Logic's own first stack;
  `arrangement --add` makes the arrangement track when the song has none; `send --add` works on
  a project with no send to clone.
- `logic midi` reads a song's MIDI regions — notes, controllers, program changes, pitch bends,
  loop flag — and `--export` writes a format-1 Standard MIDI File.
- `logic plugins` names every slot's plug-in and reports which third-party components this Mac
  lacks, for one project or a folder of them.
- `logic patch` reads a Library patch bundle — its nodes, each channel's settings, strip and
  plug-ins — in both shapes Logic writes.
- The group-events loss reported on 2026-09-08 does not reproduce on the blank-born project;
  `tests/goldens/test_groups.py` pins create, assign, add, assign.
- `logic midi --region` and `--note` write an empty MIDI region and notes on a copy; Logic re-saved
  one with its notes intact.
- `logic regions` reads every MIDI and audio region with its file record (name, format, frames,
  rate, channels, bits); `--audio` imports a PCM WAV at the project's rate as a region.
- `logic sessionplayer` reads a Session Player region's drummer, preset and settings (the JSON in
  its record) and its generated notes; Complexity, Fill Amount and Swing pinned by one editor
  move per save.
- `logic patch --build` writes a patch bundle from a `.cst`, into Logic's own library only with
  `--install`; a built patch loaded from the Library with all its inserts.
- Nine more public goldens: a third send and the slot base it moves to 4, the Signature List's
  meter and key creates and edits after bar 1, and a Tempo List point and its edit.
- Sixty-two more public goldens: MIDI region writes and their re-saves, audio region writes and
  a re-save, three audio imports, a Session Player track and three settings, a Library-saved
  patch and a built one loaded.
- `tools/driver` and `tools/stage_public.py`: the accessibility driver that records goldens from
  Logic, with the recipe and the traps; CONTRIBUTING describes recording one.
- Forty-three public goldens: the arrangement track and sections, an instrument track, a track
  header click, eight native inserts, MIDI events one field per save, meter changes, and
  Logic's re-saves of route, transplant, bypass, send, stack-create, arrangement and reorder
  outputs.

### Changed

- `tempo --add` and `--ramp` write each point's time word (data +8, 1/2000 s from the SMPTE
  origin) as Logic computes it; Logic's own points and curve runs match to the digit.
- `route`, `transplant`, `bypass` and `reorder` are CONFIRMED: Logic re-saved one write of each
  with the written bytes intact.
- `logic donors` names Logic's plug-ins that ship without factory presets (Gain, EnVerb).

### Fixed

- `logic regions --audio` numbers an import as Logic's own imports do — entry word, record header
  slots, file ordinal and link chain, registry entry, current and selected marks — and refuses a
  project whose audio regions are in any other layout, or a WAV whose name it already holds,
  before anything is copied. Logic re-saved two such imports with every region record kept.
- `logic midi --note` goes into the region on the named track that holds its bar, never another
  track's region at the same tick, and is refused when no region or several hold it.
- `logic midi --region` writes a region's length and track for a name of any length; Logic
  re-saved regions named four and nine bytes long as written.
- `logic midi --export` writes the song's tempo map and time signatures, and refuses events
  before bar 1 instead of raising.
- `logic quantize-drums` reads 32/64-bit float and extensible WAVs, and refuses a song whose tempo
  changes and reference audio with no hits.
- `logic patch --build` refuses a file that is not a channel strip, leaves nothing behind when it
  fails, and replaces a bundle with `--overwrite` only once the new one is complete, exiting 1
  with the path of a replaced bundle it could not remove.
- A channel's group field is a bitmask, one bit per group: `logic group` reads a channel that
  is in several groups, or in group 3 or higher, as Logic does; `--create` keeps a member's
  other groups, `--assign` moves it out of every other one.
- `logic group` shows a switched-off group and `--group N --on/--off` sets it (flags bit 31).
- `logic regions` reads a recorded project's regions: the entry counter's base, the flex
  marker blocks after a flexed entry, and a flexed audio region's RBA sequence is not a MIDI
  region.

## 0.2.0 — 2026-09-12

### Fixed

- `validate_project` checks third-party plugin slots for duplicate keys and index collisions.
- `apply-template` places each added track after the one added just above it, so a run of new
  tracks lands in template order in one pass.
- `stacks --move` and `levels --to` write through the integrity gate; a refused result is
  discarded.
- A project writer whose step fails part-way discards the whole copy, including alternatives
  it had already written.
- `logic project` reads a channel's inserts from its plugin-slot records at slot base 2, 3 or 4;
  a plugin name in a property record, such as an aux's input source, is not an insert.
- `logic header` computes the header width from the project's own name-column width and never
  below Logic's 180-pixel floor, and says when a width grown from one stored on that floor is
  an estimate.
- `logic controlbar` keeps a project's stored button order and inserts a newly shown control
  where Logic does.
- `logic stacks` reads summing stacks (a grouping header bound to an Aux with members under
  it) as well as folder stacks; `--move` refuses a summing stack.
- `logic reorder` moves a stack header together with its members, and refuses to move a row into
  or out of a summing stack.
- `apply-template` moves a project's slot keys from base 2 to 4 only when a channel carries a
  send at key 2.
- Bar numbers given to `arrangement`, `tempo` and `signature` follow the song's time signatures.
- `logic arrangement` refuses a non-ASCII section name.
- `build` and `pst` refuse Logic's own library without `--install` whatever
  `LOGICXKIT_AUDIO_MUSIC_APPS` is set to, and refuse under the folder it names.
- `build`, `verify` and `pst` refuse a preset name that is not a plain file name.
- `logic pst` marks a failed preset `!!` and exits 1.
- `apply-template` without `--out`, `--plan` or `--propose-map` exits 2 with a message.
- A quoted `~` expands in every path argument, including lists such as `recdiff --baseline`.
- A JUCE plugin state nested past the recursion limit decodes to nothing.
- Scanning a file for embedded plists takes one parse per plist.

### Added

- `apply-template --plan` names the session tracks the template has no counterpart for.
- `chains` and `levels --to` are CONFIRMED.
- Sends read their level (`Send.level`, `Send.level_exact`).
- Leaving a group is measured against Logic's own No Group save.
- The slot base is read from the channel records' own word when they agree, and follows the
  number of sends (2, 3 or 4).
- `bin/run fetch-corpus` downloads the public golden corpus; `LOGICXKIT_REQUIRE_GOLDENS=public`
  and `LOGICXKIT_GOLDENS=owner` steer the goldens between the two corpora.
- `logic image --overwrite`; without it an existing file is kept.

## 0.1.1 — 2026-09-11

### Fixed

- The headless AU host finds `auprobe.swift` inside the installed package, so `au params` and
  state decodes use it.

### Added

- `docs/README.md` (documentation index), `docs/INSTALLATION.md` and `docs/commands.md`.
- `py.typed`: the package is annotated and now says so to type checkers.
- `aulatency.swift` is documented in `src/logicxkit/au/README.md`; it ships in the wheel and
  is run directly with `swift`.

## 0.1.0 — 2026-09-10

First public release.

### Added

- `logicxkit logic` — Logic Pro channel-strip (`.cst`) build and decode, read-only `.logicx`
  project analysis, and writers for the track list, stacks, groups, sends, routing, channel
  levels and width, arrangement, tempo, time and key signatures, transport modes, metronome,
  track headers, control bar, toolbar and Logic's own settings. Every project-mutating command
  requires `--out` and works on a copy.
- `logicxkit logic apply-template` — migrate a session onto a template, pairing by Environment
  object id within a lineage and by an explicit map across lineages.
- `logicxkit logic diff` — project-to-project and project-to-strip-library drift.
- `logicxkit logic image` / `ocr` — extract and OCR the auto-saved WindowImage via Apple Vision.
- `logicxkit au` — Audio Unit preset and state decode: FabFilter `.ffp` and `.aupreset`, Waves
  XPst, TR5 chain XML, sonible protobuf field walk, and the third-party states embedded in
  `.cst` strips and `.logicx` projects.
- Headless AU host (`auprobe.swift`) — loads an installed plugin's state and dumps every
  parameter with real names and UI-formatted values.
- `logicxkit logic capabilities` — what each command is trusted for, generated from
  `logic/_capabilities.py`.
- `logicxkit --version` (`-V`) prints the installed version.
- Write gate (`logic/services/integrity.py`): every project write is held against its input and
  refused on any regression; a refused run discards the copy.
- A write by a command whose capability level is `CLAIMED`, `DERIVED` or `BROKEN` prints a
  one-line notice naming that level (`LOGICXKIT_NO_NOTICE=1` silences it).
- `logic transplant` refuses a clone that overruns the channel's slot key range or crosses a
  record class version; `--force` overrides.
- `logic build` and `logic pst` refuse to write into Logic's own library unless `--install` is
  passed.
- Strip specs take `output_root`, which moves where built strips land without moving where
  their sources are read from.
- CI on a macOS runner; `v*` tags build an sdist + wheel, check the wheel carries the Swift
  helpers and no reference material, and publish to PyPI through a trusted publisher gated on
  reviewer approval.
