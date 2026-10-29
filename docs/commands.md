# Commands

What the CLI is organised into and the rules that govern each group.

This file is about shape and safety, not flags. For a command's flags run
`logicxkit logic <command> --help`; for what each command does in plain words read
[CAPABILITIES.md](CAPABILITIES.md), and for whether it is trusted against a real session
[EVIDENCE.md](EVIDENCE.md), which is generated from the code and cannot drift from it.

---

## Table of Contents

- [Two CLIs](#two-clis)
- [Reading a project](#reading-a-project)
- [Editing a project](#editing-a-project)
  - [Tracks, stacks and the mixer](#tracks-stacks-and-the-mixer)
- [Building strips and presets](#building-strips-and-presets)
- [Decoding plugin state](#decoding-plugin-state)
- [Drum patterns](#drum-patterns)
- [Logic's own settings](#logics-own-settings)
- [The four rules that apply everywhere](#the-four-rules-that-apply-everywhere)
- [Adding a new command](#adding-a-new-command)

---

## Two CLIs

`logicxkit logic` works on Logic's own file formats — projects, channel strips, settings.
`logicxkit au` decodes Audio Unit plugin state, wherever it is stored.

They are separate because the dependency graph is: `au` must never import `logic`. Both read
Logic containers through `logicxkit.logicx`. `tests/test_package_layering.py` enforces this —
do not add an import that crosses it.

## Reading a project

Start here. These never write, so point them at anything.

`project` inventories a whole session — channels, chains, AU preset names, native params.
`diff` compares two projects, or one project against your strip library, which is how you find
a channel that has drifted from the `.cst` it claims to reference. `stacks`, `levels`,
`arrangement`, `tempo`, `signature`, `modes`, `metronome`, `group` and `header` each read their
own part of a session and print it. `decode` reads a `.cst` directly. `manifest` and `recdiff`
report on the record layer.

`image` extracts the window screenshot Logic auto-saves into a project, the one exception here:
it writes that JPEG (to the current directory unless `-o` says where) and keeps an existing file
unless `--overwrite` is given. `ocr` reads that screenshot with Apple Vision, which is the only way
to see the mixer as Logic actually drew it.

Several of these turn into writers when given a flag — `stacks --move`, `levels --to`. Read the
next section before using one.

## Editing a project

**Every project-mutating command requires `--out` and works on a copy. The input is never
modified.** There is no in-place mode and none will be added.

**Every writer takes a project in file format 2513** — the u16 at +4 of `ProjectData`, which
Logic 12.3.1 and 12.4 write. Logic moves record layouts between builds, so a field written where
another build keeps something else is damage no later check sees. An alternative an earlier
Logic saved is left as it is, byte for byte, and named in the output, when a current one sits
beside it — Logic keeps such bundles itself. A bundle with no current alternative, or one holding
an alternative a later Logic saved, is refused before anything is copied, naming the alternative
and the format it found: open the project in the current Logic and save it, then run the
command. A bundle with no ProjectData at all is refused the same way. A writer's pre-read (`--plan`, a preview), the listing it prints after the write and
a `--src` or `--from` project it copies from take the current alternatives only, `--plan` naming
the others and refusing the bundles the run refuses. The readers take any save as they find it.

Most editors route through `_edit.edit_copy`, which holds the result against its input using
`logic/services/stream/integrity.py` (region, file and marker checks in `integrity_regions.py`, marker
targets in order and RBA Sequences no entry names among them; the arrange list read by the track
count before and after), refuses on any structural regression,
and then reads the file back to confirm the bytes that landed are the bytes that passed. A refused
run discards the whole copy rather than leaving a bundle that disagrees with its own metadata.

Do not assume that gate covers everything:

- **It checks structure, not sound.** It cannot tell you a chain landed on the wrong channel.
- **`chains` bypasses `edit_copy`** but runs the same regression check and read-back itself.
- **`controlbar`, `header` and `toolbar` bypass it** because they write `DisplayState.plist`
  and never touch `ProjectData`, which is what the gate inspects.
- **`retrack --map` bypasses it**: it rewrites each `ProjectData` in the copy checked only for
  an unchanged length. `retrack --channel` goes through the gate.

A write through `edit_copy` that leaves a channel feeding itself — its output, or a send that is
not bypassed, on a bus whose aux leads back to it — prints `warning: this leaves a routing loop:`
and the channels and buses along it. The copy is still written: Logic's own drags of two
summing stacks into each other leave the same loop without an alert. A loop the project already
had is not named again.

`apply-template` is the orchestrator over the rest: it migrates a session onto another
project's layout, pairing tracks by Environment object id within a lineage and by an explicit
map across lineages. It refuses across lineages without a map. A strip reference the template's
channel lacks stays as it is — clearing one is not written — and the op says so in the plan.
A template stack is the session stack whose header pairs with its own, else the one stack of
its name; with two of that name and neither paired, the move is refused naming both. An output
to a bus the template returns and the session will not (the return was refused) is refused.
A template stack of tracks the plan adds is planned above them, saying how many are added, and
made once they exist. The channel ops are planned again once tracks are added and moved, so a
run can do ops `--plan` did not list; the plan says so when it has any of those.

`migrate` runs that in one pass: it drafts the pairing with `propose-map` (or takes `--map FILE`),
applies it, and writes `CLAUDE migrated - <song>.logicx` into `--out`, never over an existing
output. A song of the template's own lineage pairs by object id and ignores the draft; any other
song is refused unless given `--map` or `--force`, and `--save-map FILE` keeps the draft to edit.
The pairing is drafted from the first alternative, which must fit or nothing is written; a
later alternative the map does not name is left as it was. A folder holding more than one
project is refused (name the song), and a refused run leaves no `--out` behind. It ends with a
checklist of refused and failed ops and session-only tracks. `--verify` is the one
command that drives Logic itself: it opens the copy, has Logic Save As it into `--out` through
`tools/driver`, closes without saving, and compares the two row lists. It needs macOS, Logic Pro
and a checkout, and refuses before writing anything when one is missing.

A slot is its mixer slot: `--at N` and `slot N` count from 1 with empty slots included, the number
automation names an insert by. `add-plugin` puts one plug-in from the donor library into slot N of a
channel (after the last without `--at`): an empty slot takes it where it is, an occupied one moves
it and every later slot down a key. `remove-plugin --at N` takes that slot's plug-in out and moves
the later ones up, and `replace-plugin --at N --plugin NAME` puts another plug-in in its place. All
three take `--channel LABEL` or `--stack NAME` (every member of a folder stack), and keep the
channel's Smart Control mappings and automation lanes on the plug-ins they were made for, dropping a
removed slot's. An instrument channel's slot 1 is its instrument: an effect is refused there, an
append lands at slot 2, and removing the instrument leaves slot 1 empty. One of Logic's own
instruments from the library goes into an empty slot 1 (`add-plugin --at 1`, or `replace-plugin
--at 1` over the one there) at the width it was saved at: the channel's input follows it, and the
channel's width too when no effect comes after it. The track's Smart Controls stay as they were. A
MIDI effect is refused; MIDI FX slots are read, not written. `transplant` replaces a
channel's whole chain from another channel, the destination taking the source channel's width when
the chain has its instrument; `--stack NAME=SRC_LABEL` gives every member of a folder
stack SRC_LABEL's slots, each copy with its own instance id when one source fans out to several
channels (refused when the source holds no second instance to measure the id from). The library
holds Logic's own effects as packaged and whatever `logic donors PROJECT [--as NAME]` has
harvested — Logic's instruments, and third-party plug-ins per width and class version — so one of
those needs a donor project once;
`--refresh` replaces donors the library holds after a plug-in update. Where the package and the data
root hold a donor of one name, the package's is used, and `logic donors` into the data root leaves
those plug-ins to the package. `transplant`, `chains` and `clear-slots` leave the destination's
plug-in automation lanes as they are. `--plugin` takes the library's name for it, a
`Manufacturer/Subtype` code or a native type id. `--side-chain NAME` points the new slot at a track,
bus or aux return by name or mixer label (an aux stands for the bus feeding it); without it the slot
listens to nothing, whatever the donor listened to in the project it came from. An input of the
audio interface is `Input N`, and an instrument track is named like any other. `transplant` and
`apply-template` carry each slot's side chain by its source's *name* — the channel of that name in
the destination, whatever number it has there — and clear it with a line in the report when no
channel of that name exists; `chains` clears a library donor's. `plugins` lists the source beside
every slot that has one.

`swap-plugin --from NAME --to NAME --out DIR` does that for every slot in the project holding
one plug-in — Logic's name (the samplers, Drum Kit Designer, External Instrument, the Studio
instruments and I/O included), a `Manufacturer/Subtype` code, a native type id, a coded plug-in's
four-letter code (`PRRT` for Quick Sampler) or the name in its translation map — on a copy: each
slot goes through the same replace, settings carried through the family vocabulary, side chain
and automation lanes with them, and gets its own report lines. A slot whose settings cannot
cross (a compressor into a gate, a plug-in without a map) or that cannot take the plug-in (an
instrument into an effect slot) is left as it is with the reason. `--channel` and `--stack`
narrow it, `--plan` runs the same swap in memory over every alternative the write edits and
writes nothing, `--no-translate` puts the replacement in at its defaults, `--set` dials a value
into every replacement. A `--from` no slot holds, one naming the `--to` plug-in, or a type id or
code several plug-ins share (`InWr`, the Studio instruments'; `147`, Tape Delay's and Echo's) is
refused before a copy is made.

`tracking-chains PROJECT --out DIR` makes a project's chains low-latency and native on a copy,
the way a tracking template wants them: every third-party slot with a translation map becomes
Logic's own of the same family with its settings carried (Pro-C 2 or smart:comp 2 to a
Compressor, Pro-Q 4 to a Channel EQ, smart:gate to a Noise Gate, Pro-MB to a Multipressor; a
plug-in carrying several families, Neutron 5, becomes one native per live element, added after
the first), a third-party without a native analogue is removed (`--keep-unmapped` leaves it),
and natives that carry lookahead — Linear Phase EQ, Multipressor, Adaptive Limiter, Limiter,
Enveloper — are bypassed, the ones it made from a third-party too (`--keep-lookahead` leaves
them). `--plan` runs the same edit in memory and prints the lines the write would; `--channel`
and `--stack` narrow it.

`settings` reads every slot's settings in its family's vocabulary — a compressor's threshold,
ratio, attack, release, knee, make-up, mix, auto release, input and output gain whichever
compressor it is — through the plug-in's translation map (`data/translate/`: Pro-C 2 from its
AU state's id/value pairs, sonible's smart:comp 2 and smart:gate from their protobuf state,
Logic's Compressor, Noise Gate, Channel EQ and Multipressor from their measured tables; a slot
without a map says so), each slot by its mixer slot. An
EQ's settings are its bands — shape, frequency, gain, Q, slope — and Pro-Q 4's cross into
Channel EQ's one slot per shape, bells by rising frequency, the rest reported. `replace-plugin
--translate` carries the old slot's settings into the replacement through that vocabulary and
prints what each parameter became, what has no analogue in the new plug-in, what was clamped,
what is only approximate (Logic's knee has no dB scale) and what the new plug-in keeps of its
own; the old slot's side chain rides along. The replacement can be one of Logic's own or a
FabFilter plug-in: Pro-C 2 and Pro-MB take their values by parameter id, Pro-Q 4 by band in
its binary state, each patched in place inside the record's plist so nothing else moves.
sonible's protobuf is read, not written; so is iZotope's Neutron 5, which carries a
compressor, a gate and an EQ at once and gets a `settings` line per family.

A multiband compressor's settings are its bands by frequency range, each a compressor or an
expander (Pro-MB by its band layout, Multipressor by its table), beside the globals; across the
two the spectrum is segmented into at most the target's count of bands, a stretch no source band
covers as a live band at ratio 1 (an off band's range goes to the next live one), and the report
names what merged or has no analogue (Pro-MB's range limit and percentage attack and release). A
Multipressor band crosses into a Pro-MB band as one side: its expander when the compressor is
neutral, else its compressor, and the plan names the side; that side's lanes carry and the
other side's stay behind with the reason.

A replaced slot's automation follows the translation: every plug-in parameter lane on that
insert is carried through the two maps — the old plug-in's parameter named through its map, the
points read over its stored range (a third-party) or its measured positions (one of Logic's
own), written onto the new plug-in's parameter index — and a lane with no home in the new
plug-in, or on a parameter whose slider is not measured, is dropped with a report line rather
than left pointing at a wrong parameter. An EQ's or a multiband's lanes cross by band: a band's
frequency, gain, Q and on/off (a multiband's threshold, ratio and make-up) go to the band the
plan placed it in, and a lane on a band that found no place is dropped with a line.
`--keep-automation` leaves the lanes as they are; with neither flag the old plug-in's lanes are
dropped with a line, and so is its side chain.

`settings --set NAME=VALUE --channel LABEL --at N --out DIR` writes into one existing slot on
a copy, by the same vocabulary names `settings` prints (`threshold=-24`, `auto_gain=off`) or,
on an EQ, by band (`"band 2=bell 250 Hz -4 dB Q 2.4"`, `"band 1=low cut 80 Hz 24 dB/oct"`,
`… off`): only the bands named change, a band given no slope keeps its own, one of Logic's own
keeps its slot's shape, and Pro-Q 4 takes a new band past its last.
`add-plugin --set` and `replace-plugin --set` dial the same way on the way in — a table name
for one of Logic's own (held to its slider's measured ends with a note and put on the slider's
grid where the plug-in has a translation map; the instrument, MIDI-effect and re-measured effect
tables carry each slider's measured ends as the parameter's range, a slider ending on a word at one
end (Mute, Off, mono, Fix or Click at the bottom, inf or Paradise at the top) its other end alone,
and a number outside is refused — the word's own side is not checked, and the word cannot be
written by name — within it a finite number goes as given: Logic's load puts a value between slider
positions on one, and derives the next word from an ES2 MM Amount written alone, the one linked
shape measured; the other effect tables carry no ranges), a vocabulary item for a third-party, a
band on any EQ — and after `--translate` they override what was carried. A table name that lives past the float block (Vintage B3's lower
manual and pedals) is written at its payload offset like any other; a plug-in whose state is
text (Alchemy, Sample Alchemy) is read by `project` and refused by `--set`, since writing it
would resize the record. A table name whose word is placed by row order alone (25 rows over 8
tables, Sculpture's 12 the most) is refused by `--set` too, and `project` marks its value `*`:
coded series moved 13 of the 411 such placements they re-tested.

**Open every output in Logic before trusting it.** A green run is not confirmation; a file that
opens is not confirmation either. The way to check a writer is Save As in Logic and diff the
record list against the input.

### Tracks, stacks and the mixer

The track commands take a track by the name the arrange list shows. Where a stack header shares
its name with a channel, add the mixer label in parentheses: `Drums (Sub 1)`. The mixer commands
take a channel by its mixer label (`Audio 5`, `Bus 15`, `Aux 2`).

- `add-track --name NAME --after TRACK` adds an audio track after an existing one, inside that
  track's stack when it has one, recording from `--input N`. `--stereo` records from the pair
  `Input N-(N+1)`, so N is odd. `--instrument` adds a software instrument track instead, and
  `--stereo` then makes its channel stereo.
- `rename --track OLD=NEW` renames a track and marks the name as the user's; without that mark
  the arrange shows the channel-strip setting's name. A track name is 1 to 127 bytes of UTF-8:
  `rename`, `add-track --name` and `stack-create --name` write names outside ASCII as Logic
  stores them, and a track is found by name in either Unicode form. Group, marker and section
  names take UTF-8 too (a group's up to 63 bytes); one Logic renamed, which it stores as RTF, is
  read as Logic shows it. A written name needs a visible character, and a marker or section name
  cannot start `{\rtf`.
- `colour --track NAME=INDEX` sets a track's colour by Logic's palette index.
- `hide --track NAME` hides a track; `--show` brings it back.
- `reorder --move TRACK:before:OTHER` (or `:after:`) moves a row among its siblings, under the
  same parent. A stack header moves with its members.
- `stack-create --name NAME --track NAME` makes a folder stack from tracks; `--track` repeats.
  Its header takes the lowest `Sub` strip that is out of use (a converted stack leaves one), as
  Logic's own does, and a new strip after the highest otherwise; it is coloured 20 unless
  `--colour` names an index, takes the members' parent (the summing stack they sit in), and
  takes the lowest object id a converted or deleted track left behind, else the next id past
  the highest, as Logic's Create Track Stack does; `add-track` takes a deleted track's id the
  same way for a new audio track, whether an audio or an instrument track left it (the adds
  measured), the next id otherwise. A strip the convert left with
  the folder's level or mute comes back at 0 dB and not muted, as in Logic; one carrying a pan,
  a solo, an insert or a send is refused.
  `--summing` makes a summing stack instead: a stereo aux on the lowest free `Aux` stub (a
  fresh strip after the highest when none is free), fed from the lowest bus nothing uses, with
  every member's output sent to that bus. The tracks are all at the top level, or all
  direct members of one stack, and the new stack then sits inside that one. The stack outputs
  where every member did, or to Output 1-2 when their outputs differ, as Logic's own does —
  inside another summing stack too — and the output names each member output it replaced.
  Members that are the only channels on their bus get no new aux: that bus's own aux becomes
  the main track, as in Logic, with no output changed, under its own name (`--name` is not
  applied, and the output says so); `NumberOfTracks` grows only when the aux had no track.
  A stack's header as a `--track` makes a stack around that stack: a folder around any stack
  changes no routing; `--summing` around a folder stack sends the tracks the folder holds to the
  new bus, and around a summing stack sends that stack's aux there, as Logic's own does. Around
  a folder the new stack always outputs to Output 1-2 and no bus's aux is reused: tracks that
  fed a bus of their own leave it for the new one, that bus's aux is left with nothing feeding
  it, and the output names each output replaced. A summing stack's header takes its first
  member's colour unless `--colour` names one.
  Refused: a third level of stack, which Logic does not make either (its Create Track Stack is
  disabled there), and the reuse above inside another stack or with a summing stack among the
  members.
  A track that becomes a direct member of a summing stack — `add-track`, `stacks --move` —
  outputs to that stack's bus; one that goes into a folder inside a summing stack keeps its
  output, as Logic's drag leaves it. `stacks --move STACK:SUMMING` moves a stack with its rows:
  a summing stack's aux then outputs to the outer bus, a folder's tracks keep their outputs. A
  move that would make a third level is refused.
  `stacks --move-out TRACK` takes a track one level out, to just after the stack it
  leaves. One that lands as a direct member of a summing stack outputs to that stack's bus; out
  to the top level it keeps its output, the bus of a summing stack it left included, each as in
  Logic. `stacks
  --flatten STACK` takes a stack apart as Logic's Flatten Stack does: the header's row goes, the
  members come up a level, selected, and keep their routing and their channels' stack index; the
  header object and its strip stay, the strip in use. `stacks --convert STACK` makes a folder
  stack a summing stack as Logic's Track > Convert Folder Stack to Summing Stack does: the
  flatten, then a summing stack over the same members on the lowest free `Aux` fed from the
  lowest free bus, the folder's header object gone and its `Sub` strip out of use, the members
  at stack index 0; the name stays when it was the user's, else the stack is `Sum N`. The
  folder's Volume, Mute and Solo lanes move onto the new header; its level and its mute stay on
  the `Sub` strip with the aux at 0 dB and playing, all as Logic's convert does, and the output
  names a level or a mute left behind. A folder
  inside another folder converts as Logic's does, the new stack inside the outer one. Members
  on other outputs convert by `--summing`'s rule, and members that are the only channels on
  their bus take that bus's own aux as the main track: the header carries the aux's name and
  the track count drops by one when the aux was a track already; the aux keeps its own level
  and lanes, but a folder's Volume lane moves onto it in place of the aux's own, as Logic's
  convert does, and the output says so. Refused, each named: a folder with a lane other than
  those three or with an insert, a reused aux with a lane other than Volume under a folder with
  a Volume lane, a folder's Mute or Solo lane where the aux is reused, and a folder that holds
  a stack (Logic's own convert of one leaves a track assigned to nothing). Where two
  stacks share a name, `--stack`, `stacks --move`, `--flatten` and `--convert` take `NAME (Sub
  1)` or `NAME (Aux 9)`.
- `route --output CHANNEL=DEST` sets where a channel outputs to, and `--input CHANNEL=INPUT`
  what feeds it: an `Input N` for a track, a `Bus N` for an aux. The record's index words are
  set with its UUIDs. A mono audio track takes one input and a stereo one a pair (`Input 1-2`);
  `width` changes which. An output sent to a bus nothing uses puts that bus in use as Logic
  does: the bus takes a UUID of its own and the lowest free `Aux` (a fresh strip when none is
  free) comes into use fed from it, output Output 1-2, with no track; the output says so.
  `NumberOfTracks` does not change. A second output to the same bus adds nothing.
- `send --add CHANNEL=BUS` adds a send in the lowest free of a channel's three slots (`--key`
  picks one), `--remove CHANNEL` drops every send on it, and `--copy LABEL=SRC_LABEL --from
  SRC_PROJECT` replaces a channel's sends with another project's. Buses are not remapped across
  projects: a copied send points at the bus of the same number. `--set CHANNEL=BUS` names a send
  that is already there. `--level DB` (`--level=-inf` to 6), `--mode post-pan|post-fader|pre-fader`
  and `--bypass on|off` apply to every `--add` and `--set` of the call, and need one; an added
  send given none comes in as Logic adds one, at −∞ dB, post pan and on. A second send to a bus
  the channel already sends to is refused: `--set` changes the one there. `--add` to a bus
  nothing uses puts it in use first, as `route --output` does.
- `levels --fader CHANNEL=DB` sets a fader in dB and `--pan CHANNEL=N` a pan from -64 (left) to
  63 (right). A fader is written at exactly that level; Logic's own readout shows its steps as
  labelled and a level between two of them up to 0.1 dB low (an exact -6.0 shows -6.1). Without
  either flag `levels` lists every fader in dB to the hundredth, as written, marking a muted
  and a soloed channel, and `--to OTHER` copies a project's faders and pans onto another.
- `width --stereo LABEL` (or `--mono`) changes a channel's width and the build of every plug-in
  on it. With neither flag it lists the widths and writes nothing.

## Building strips and presets

`build` writes `.cst` channel strips from a JSON spec, `pst` writes single-plugin settings with
no routing attached, and `verify` round-trips a spec without writing anything. `strip-save`
goes the other direction — exports a channel from a project as a `.cst`. A preset in a `build`
spec can name a `graft` instead of a `template`: the routing of one strip with the chain of
another, for a shape no saved strip has.

These are the only commands that write outside `--out`, so they carry their own gate: **a
relative `output_dir` resolves under Logic's own live library, and writing there is refused
unless you pass `--install`.** A spec cannot reach your library by omitting a key. `--overwrite`
is separately required to replace an existing file. To write elsewhere, set `output_root`, or
give an absolute `output_dir`.

`donors` writes into the data root rather than a project; `chains` reads the data root's donors
first and the package's native ones second. `config/example-chains.json` and
`config/example-strips.json` run as shipped from a checkout against the strips under
`tests/corpus/strips/` with `LOGICXKIT_STRIP_ROOT=tests/corpus/strips` (a wheel ships no
corpus), the chains one on a project whose channels carry its reference names. `chains
--verify WRITTEN --config CFG` opens the written copy in Logic Pro, reads each chained channel's
plug-ins in their Controls views and compares every row with what the tables decode from the
file, saving nothing; it runs on macOS from a checkout (`tools/driver/`) and prints one line per
slot, matched or the rows that differ with both values. `retrack` repoints strip references after
a library rename — it changes a label, never a chain.

## Decoding plugin state

`au strip` is the one to reach for: it decodes the third-party plugin states embedded inside
`.cst` strips and `.logicx` projects — the layer Logic reports as a preset name and nothing
more. `au preset` does the same for a standalone preset file.

Decoding runs a ladder per state: Neural DSP and JUCE decoders first, Waves through the static
XPst table, and anything else through the headless AU host, which loads the real plugin and
reads its parameters. `--no-host` forces the static tables instead. Without a `swift` toolchain
the host is unavailable and the ladder falls back on its own.

`au params` dumps a live parameter table from an installed plugin; `au tables` lists the tables
already in the data root. `logic neural` decodes Neural DSP knob values specifically, from either a
strip or a whole project. `logic plugins` stops at identity: every slot's plug-in, and which
third-party components `auval -a` does not list on this Mac. That check is Apple's scan of every
installed Audio Unit, run when a slot holds a third-party plug-in; with many plug-ins installed it
takes 25 seconds or more, so the scan is kept (in `~/Library/Caches/logicxkit/`) and used again
for a day while the two Components folders stay as they are. `--rescan` runs it again, which an
Audio Unit that ships inside an app needs, since it shows in neither folder. auval lists what the
system has registered so far, which right after a start can be part of it: a scan that leaves out
a plug-in a Components folder holds is not kept, and the output says so. `logic midi` reads the
MIDI regions and `--export` writes
what each region plays as a Standard MIDI File with the song's tempo map and time signatures, bar 1
at tick 0 (a split leaves both pieces holding the parent's events; the piece plays its own span, and
the `midi` and `regions` listings say `2 event(s), 1 played` when they differ, `--json` carrying
`played` beside `events`); a song with events before bar 1 is refused. `--region` and `--note` write
a region and notes on a copy through the integrity gate; a note goes into the region on its track
that holds its bar, and is refused when none or several do. The listing numbers regions across the
song (`--json` carries it as `number`), and edits take that number: `--transpose`, `--velocity`,
`--move`, `--delete` and `--quantize` change a region in place, `--copy-region` copies one elsewhere
— the whole sequence, as Logic's own copy does, so a split piece's copy holds the parent's events
too — and `--copy-notes` only the notes it plays, and `--remap [N=]SRC:DST` translates drum note
numbers between [groovebin](https://github.com/phierceweb/groovebin)'s note maps (`gm`,
`addictive-drums-2`, `drum-kit-designer`) in region N or every region on `--track`, counting the
notes with no counterpart. In-place edits run in command-line order, then `--region`/`--note`, then
the copies; a bad spec exits before anything is copied. A region number means the same region
(track, start and name) in every alternative, and is refused where an alternative lacks it. An edit
that moves an event out of its region is refused, a MIDI region goes only onto a software instrument
track, and notes at one tick are written low to high. `--remap` keeps the pitch of chokes and stick
clicks, which GM has no stroke for, and refuses a region holding polyphonic aftertouch. `--map NAME`
names each note's stroke in the listing. The transforms are Logic's Transform window: `logic midi
SONG N … --out DIR` (regions by listing number) or `--track NAME` (every region on it) with
`--select COND[,COND…]` — `position` in song bars as the signature track numbers them, a meter
change and all (a whole number is the whole bar), `pitch`, `velocity`, `length` (ticks or `1/16`),
`channel`, each `=VALUE`, `=LO-HI` or `<`, `<=`, `>`, `>=`, `!=` a value — and the operations
`--set`, `--add`, `--mul`, `--min`, `--max`, `--random`, `--flip`, `--quantize position=|length=`,
`--crescendo`, `--exp` and `--reverse` (`FIELD=VALUE`), or the presets `--humanize`,
`--fixed-velocity`, `--velocity-limit`, `--random-velocity`, `--crescendo LO..HI`,
`--reverse-position`, `--reverse-pitch`, `--exp-velocity`, `--fixed-length`, `--max-length`,
`--min-length`, `--half-speed`, `--double-speed`, `--legato`, `--staccato` and `--swing`.
Consecutive operations apply in one pass reading each note as it was; each preset is its own pass,
and `--select` picks the notes once for the whole run, so a later pass works on the ones the
selection picked rather than re-picking against what an earlier pass changed. Notes outside the
selection keep their bytes, and so do the region's controller, bend and program events — half and
double speed alone move them, rescaled with the notes. A note pushed out of its region is refused as
any edit is; so is any step that moves a note's position on a region holding those events, since
they would stay behind: `position=` under `--set`, `--add`, `--mul`, `--min`, `--max`, `--random`,
`--flip`, `--crescendo` and `--quantize`, `--reverse position`, `--reverse-position`, `--swing`, and
`--humanize` unless its `pos` is 0. A region holding polyphonic aftertouch is refused as `--remap`
refuses one, half and double speed and swing take the whole region, and `--seed N` repeats the
random moves (`random` prints the seed it chose; each alternative gets the same draws). Region
numbers go before the transform flags — `--staccato 3` hands the 3 to `--staccato`, which is refused
when it leaves no region named. The arithmetic is groovebin's (`groovebin transform` does the same
to a `.mid`). `logic regions` lists every region, numbered, with its mute, loop, fades and audio
file (a split's pieces with their first frame), and `--audio` imports a PCM WAV at the project's
sample rate — other rates are refused, since Logic converts on import and this does not. It writes
onto a project with no audio regions or with the ones Logic's own imports and splits leave, and
refuses any other layout and a WAV whose name the project already holds, before anything is copied.
Names outside ASCII are written as Logic writes them (UTF-8 region names, UTF-16 file names). The
edits take the listing number, in command-line order on a copy: `--move N=BAR`, `--to-track N=TRACK` (onto
another audio track, where it is in time; a MIDI region, the region's own track and a track that is
not an audio track are refused), `--trim N=BAR:BARS`
(the start with its content kept in place, the length, or both), `--split N=BAR`, `--loop
N[=on|off]`, `--mute N[=on|off]`, `--rename N=NAME`, `--fade-in N=MS[:CURVE[:speed-up]]`,
`--fade-out N=MS[:CURVE[:TYPE]]` (type `out`, `x`, `eqp` or `xs`), `--crossfade
N=[MS][:CURVE[:TYPE]]` (from region N into the one that starts inside it on its track — exactly one
must; MS is the overlap when empty, the type `eqp` by default), the inspector's `--gain N=DB`,
`--delay N=TICKS`, `--transpose N=SEMITONES`, `--fine-tune N=CENTS` and `--reverse N[=on|off]`, and
`--colour N=INDEX` (a palette index; the Color window's swatch k is 24 + k); the listing shows the
parameters that are set and a colour that differs from the track's. A split leaves the fade-in on the
region and gives its fade-out to the new piece, which takes the region's selection, as Logic's own split
does. A looping region and a crossfaded one are not split, a
quantized region (flex markers that are hits) is neither trimmed nor split — one carrying the two
anchors of an identity map, as a region bounced in place on a flexed track does, and at most the
file's own markers after them, is cut, each piece re-anchored for its length with those markers
shifted to its start — a trim past the file is refused, a MIDI
region has no fades or parameters, and Transpose is written as the entry's field alone (Logic flexes
the track itself when it transposes an unflexed region). Each edit names a region by its number in
the input's listing, whatever the imports and edits before it moved; regions playing one sequence
(aliases) take a mute each and no other edit. A number means the same region (track, name and start)
in every alternative, and is refused where an alternative lacks it — as is a marker number (name and
bar) for `logic markers`. `logic markers` lists the marker track and edits it on a copy: `--add
BAR[:BARS]:NAME`, `--rename N=NAME`, `--move N=BAR`, `--delete N`. Logic's re-save of copies
carrying every region edit and every marker edit kept all of them. `logic chains` also takes a chain
keyed by a channel name instead of a strip reference — `Stereo Out` for the main output — listing
its plug-ins in slot order as declared donors with parameters named as `services/mixer/output_params.py`
names them, or by an index inside the donor's block; every configured value, a strip-referenced chain's
`pre`/`post` donors' too, is held to the table's measured range and, where the plug-in's map measures
the slider, goes to the nearer sampled position, as `--set` writes it; outside either it is refused.
`config/example-mastering.json` is the shape. A
label two channels carry, a channel keyed both by strip and by name, or an index past the block is
refused before anything is written, and every configured value is read back afterwards. `logic
plugins --validate` opens each listed third-party component with `auval -v`, since the registry
keeps a component whose bundle has gone bad and Logic's own launch trusts that registry.

`logic strip-silence PROJECT --track NAME [--track NAME …]` cuts the silent stretches out of the
named audio tracks' regions and fades the cuts, on a copy with `--out`; without it the plan is printed
and nothing written. Each audio file is read once into a peak per 10 ms; a stretch is silent while it
sits under the file's own loud level, its 95th-percentile peak, by more than the `--threshold`
figure (default -30 dB, given at or below 0) for at least `--min-gap` seconds (default 2: a rest between phrases is shorter, a gap between
songs far longer), and a sound shorter than `--min-keep` seconds (default 0.5) between two such
stretches is silence too, so a bump between songs is not a song. `--pad` takes one figure or
`BEFORE:AFTER` in ms, since a drum rings on after its hit. A
gap's edges then crop outward over sound under the loud level by more than the `--edge` figure
(default -20 dB, or the threshold when that is higher; at or above the threshold) — hum, string noise and room between songs — stepping
over a click of under 50 ms, and a sound the crop leaves shorter than `--min-keep` is silence too.
The crop walks as far as the sound stays under that figure, so a quiet outro that decays into a gap
is cropped with the hum; an `--edge` nearer the threshold (-28) keeps it. Each kept
span is widened by `--pad` ms (default 500) before the first sound and after the last; the
region is split at the end of one kept span and the new piece's start trimmed to the next, a region
that begins or ends in a gap is trimmed, and `--fade` ms (default 20) goes in and out on every edge
this run cut, with no curve or type, the region's own fade-in and fade-out kept on its first and last
piece and shortened to fit a piece they outlast (the longer yielding first, the rest shared); a region
the plan would cut that is crossfaded into or from another on its track is refused, since a cut would leave
half a crossfade (a crossfaded pair the plan leaves whole is no bar); two kept spans that touch, the pad
having reached half the gap, are one; the pieces are named `<stem>.N`, the stem a piece's name less its
trailing `.N` and N the piece's number in its file — or the next past the highest `.N` already on a
piece of that file, since Logic's own split numbers names from a counter that runs ahead of the piece
number (`take.7` may be piece 2), so no name repeats; a cut of `take.7` gives `take.N`, never
`take.7.1`. A kept span's edge within half a tick of the region's own is the region's, since no trim
can move it; a kept span shorter than a tick cannot be written and is dropped; a region whose every kept span is that
short is left as it is, and the plan says so. A region silent throughout is muted, since there is no
region delete; with `--ref`, so is a mic never heard over its bleed floor, and the plan names that floor. When no region changes, the plan says `nothing to cut; no copy written`, `--out`
writes nothing and the exit is 0. The plan lists every kept span in minutes from bar 1 and in bars, with
the loud level and the limit per region; a track with no audio regions, an unknown track, a track
named as its own reference, a reference named twice, a file whose rate or frame count disagrees with
its record, a file at another rate than the project, a changing tempo, a band reaching half the sample rate, and a figure past a day of
seconds, an hour of ms (a fade past 65535 ms) or 200 dB are refused. Audio is found
as `quantize-drums` finds it (`--audio DIR`).

A mic that is never silent while the band plays — a vocal mic full of drum and amp bleed — takes
`--ref NAME` (repeatable): the reference track's playing, by the same loud-level rule, says when
the band plays (a reference whose file is silent never does); the mic's bleed floor is its
25th-percentile nonzero level over those moments within the region, and it is
heard wherever it rises more than `--above` dB (default 9) over that floor, on a running median
over `--window` ms (default 300, long enough that a drum hit in the bleed does not count; a drum
mic wants 50, short enough to keep its own hits) — and, since bleed rises with whatever is
playing, only where it is also `--above` dB over the bleed the references predict: each reference
scaled by the mic's usual ratio to it (the 25th percentile of mic over reference while that
reference plays) and summed as power, so a loud chorus's bleed stays silence, and a backing mic given
the lead mics as references too hears the lead's bleed, far under the lead's own mic, as silence while
its own singer is heard. `--gate DB` sets the floor rule's margin apart from the bleed rule's (default
`--above`): a singer who stands off the mic clears the bleed by a wide margin while sitting only a
little over the floor, and a lower gate keeps them. The plan names each reference's usual
ratio, the bleed floor and the heard-over level per region; a region beside which no reference
plays is left unchanged, since its floor cannot be read. `--band LOW:HIGH` measures within that
band in Hz, as an RMS (without `--band` the RMS is of the whole band), and `--ref` or `--band` switches
the envelope from the top-16-bit peak to an RMS read through the `bandrms.swift` helper (so this needs the swift toolchain, as `ocr` does). The
reference's hops are aligned to the mic's file by song time, so the two regions may sit at
different offsets in their files. `--against-band LOW:HIGH` reads the mic in a second band of its own, and each sound is then kept
only if, at its peak, it is `--tilt` dB (default 0) louder in `--tilt-band` (default `--band`) than
there: a tom's fundamental against 400:2000 drops the snare hits a level rule lets through, since a
snare in a tom mic has more above 400 Hz than at the tom's note, while the level rule itself stays
on the wide band, where the kick and the snare shell do not reach into the tom's note. For a voice
over drums and amps: `--ref Overheads --band 300:3000`; for a tom mic full of snare and kick:
`--ref Snare --ref Kick --band 60:400 --tilt-band auto --against-band 400:2000 --window 50
--above 12 --min-gap 0.5 --min-keep 0.05 --pad 50:600`. `--tilt-band auto` reads each file's
fundamental itself — the frequency with the most power at the mic's loudest moments, searched in
5 Hz steps from 50 to 350 Hz (a floor tom near 80 Hz, a rack near 120) — and takes the band from
0.7 to 1.4 times it; the plan names the note it found, and a file whose loudest moments peak at the
search's edge is refused. `--above`, `--gate`, `--window` and
`--against-band` are refused without `--ref`, and `--tilt` and `--tilt-band` without `--against-band`.

`--spec FILE.json` does every group of tracks in one run on one copy: `{"groups": [{"tracks":
[...], ...}]}`, each group's settings under the flags' names with underscores (`min_gap`,
`against_band`, `tilt_band`), the rest the defaults; `config/example-strip-silence.json` is the
shape. A spec is instead of `--track` and the flags, a track belongs to one group, and the groups
are cut in order on one copy, so the plan and the copy hold them all. A file's pieces are
numbered in two bytes of the entry, so a file the cuts would take past 65535 pieces is refused, in
the plan and before any write.

`logic songs PROJECT SETLIST --track NAME [--track NAME …]` finds a live set's songs where the named
tracks all stop and writes one arrangement section per song on a copy with `--out`; without it the
plan is printed. The setlist is a text file, one song per line in playing order, a line reading
`break` (any case) after a song the band stopped on, blank lines and lines starting with `#` skipped (so no song
starts with `#` or is named `break`); a break before the first song, two in a row, a control character
in a name, a file that is not UTF-8 or a setlist naming no song is refused. Name the tracks that go
quiet between songs — a bass DI, the kick, the snare; a vocal or an amp full of hum is not one. Each
file is read once into a peak per 10 ms as `strip-silence` reads it; a track is quiet while it stays
under its file's loud level by more than the `--threshold` figure (default -30 dB, given at or below 0), and wherever no region of it plays;
a run of `--min-gap` s (default 0.5) with every named track quiet is a gap, a sound under `--min-keep` s
(default 0.3) between two gaps silence too; gaps less than `--merge` s (default 15) of playing apart are
one stop, since a band that has stopped noodles and talks; a stop of `--min-stop` s (default 10) separates
songs, and playing shorter than `--min-song` s (default 45) is listed and left out. The plan lists every
stop, every stretch of playing with its bars and the song laid over it, the bits left out and, for each
`break` on the setlist, the stop that follows the song before it. When the setlist and the stretches
differ in number nothing is written and the plan says so: a song that runs straight into the next has no
stop to find, so lower `--min-stop` and `--merge` for a set with short stops, or split that song by hand
with `arrangement`. Each section runs from the stretch's first hop for its length; the stops stay
unclaimed, and Logic keeps such gaps between sections — but its own section edits misbehave around
them, so `--breaks NAME` also writes a section NAME over every stop, from the set's start to the first
song and after the last to the end of the last region on any track, and the sections run contiguous. A
section already on the arrangement where a song plays — a second run on a copy that has the songs — is
named in the plan and nothing is written. `logic arrangement PROJECT --fill
NAME --out DIR` does the same on any project's existing sections: a section NAME over every gap from
bar 1 to the first section, between two, and after the last to the end of the last region. Audio is
found as `quantize-drums` finds it (`--audio DIR`); a changing tempo, an unknown track, a track with no
audio regions and a file at another rate than the project are refused.

`logic split-sections PROJECT --section NAME --track NAME [--track NAME …] [--to NAME …]` cuts the named
audio tracks' regions at the edges of every arrangement section called NAME and, with `--to`, puts the
pieces inside those sections on another track, where they are in time, on a copy with `--out`; without
it the plan is printed — the talk between a live set's songs off the lead vocal track and onto a talking
track, once the breaks are sections (`songs --breaks`, `arrangement --fill`). `--to` names one track per
`--track`, in order; without it the regions are cut and stay. The section edges inside a region cut it
into stretches inside and outside those sections; a stretch shorter than `--min-piece` seconds (default
1) stays with its neighbour, uncut, so a cut made by hand a beat off a section's edge is left alone, and
the plan names it. The pieces are named `<stem>.N` as `strip-silence` names them, by the piece's number
in the file or past the highest `.N` already on one of its pieces (a piece of `Vocal.8` gives `Vocal.N`,
never `Vocal.8.1`), keep the region's fade-in on its first piece and its fade-out on its last, each shortened
to fit a piece it outlasts, with the cuts unfaded, and are `regions`' own split and `--to-track`. A
region the plan would cut or move that is crossfaded into or from another on its track is refused. A piece that would land over a
region already on the destination or over another piece this run moves there, a destination that is not
an audio track or is the track itself, `--to` naming fewer or more tracks than `--track`, a
`--min-piece` under 0 or past a day, an unknown section and a changing tempo are refused before
anything is copied. A destination's regions count until a run moves them, so swapping two tracks'
pieces takes two runs. When no region changes, the plan says `nothing to cut; no copy written`,
`--out` writes nothing and the exit is 0.

`logic automation` lists each track's automation lanes and points. A plug-in lane is listed as
`--set` takes it, `slot N NAME`, with its plug-in, its parameter index and each point in the
parameter's own unit; one no table names stays `insert N parameter M` (`--json` for the raw ticks
and values; `--all` includes tracks with an empty folder). `--set "TRACK:LANE=V@BAR,..."` replaces a
lane's points on a copy (`--out`), `--copy "TRACK:LANE->TRACK"` copies a lane onto another track and
`--clear "TRACK:LANE"` empties one, the three applied in command-line order; lanes are Volume, Pan,
Mute, Solo and ±Volume (the relative lane), values 0-127 with Volume 90 and Pan 64 at unity. A
plug-in parameter lane is `slot N NAME` — `--set "Audio 2:slot 1 Threshold=-30@1,-12@9"` — N the
mixer slot and TRACK the track's name or its mixer label, with values in the parameter's own unit
(`on`/`off` for a switch): for one of Logic's own with a translation map (Compressor, Noise Gate,
Channel EQ, Multipressor), NAME is a name from its measured table and each value lands on the nearer
position of its slider, which the report names (a value past the slider's end is held there and the
report gives the slider's range); the other natives are refused, their sliders unmeasured; for a
third-party, NAME is a parameter name or id from its AU table (the value within the table's range)
or a vocabulary name from its translation map (`threshold`, in the vocabulary's unit); a bare id
with neither takes 0..1. A value or bar that is not a finite number is refused. `--clear` takes the
same form. A parameter point whose type word carries bit 14 is listed with a `?`: read, not decoded.

`logic sessionplayer` reads a Session Player region's settings and generated notes. `logic patch`
reads a Library patch bundle; `--build` writes one from a `.cst`, refuses a file that does not read
as a channel strip before writing anything, replaces an existing bundle with `--overwrite` only once
the new one is complete, and like `build` refuses to write into Logic's own library without
`--install`. `logic quantize-drums` quantizes a multitrack drum take on a copy without Logic: the
members of a folder stack (or `--track`s) go into a Drums group with Editing (Selection) and
Quantize-Locked (Audio), the groups named by `--off` are switched off, Q-Reference stays on the
`--ref` tracks, every member is on flex Slicing, and each member region gets one flex marker per hit
found in the reference tracks' audio with its target on the `--grid` (4, 8, 16 or 32, the measured
values; 1/16 by default). The audio is read from `--audio DIR` first, then the bundle's Media,
`Audio Files` beside the project, or where the file record says unless that is another
project's audio (a copy's records still name the project it was copied from, so a copy reads only
its own); it may be 16/24/32-bit PCM or 32/64-bit float WAV. A song whose tempo changes, and reference audio with no hits, are refused and
nothing is written. `--bars FIRST-LAST` re-quantizes only the hits in those song bars, on `--grid`
or each region's own Quantize value, and keeps every other marker block's bytes; regions outside the
range are untouched. It refuses a region that does not start on a line of the song's grid (quantize
it whole instead), a hit whose new target would cross a kept hit's, and an entry whose slot names a
sequence other than an RBA Sequence; a region already quantized keeps its one RBA Sequence. On a
project Logic quantized itself, whose first quantize writes the hits on the first Q-Reference region
alone, a member whose list holds only the two anchors takes that region's hits as its own (the
regions must start together with the same first frame and length), and the group is reused when
every member that has audio regions is in it. Logic's re-save of a `--bars` copy kept every marker
list.

## Drum patterns

The pattern library is [groovebin](https://github.com/phierceweb/groovebin)'s:
`groovebin index FOLDER --map NAME` builds an sqlite index of any folder of `.mid` files (or of
an Addictive Drums 2 `MidiDb.csv` with `--csv`), labelled from their paths, and
`groovebin search` and `groovebin show` read it. `logic beats` writes patterns
from that index into a copy of a project; `--db` names the index (default: groovebin's own, under
the user cache).

`beats place`, `compose` and `generate` write MIDI regions into a copy through the integrity gate,
each on a software instrument track only. Each tries the whole write on the
first alternative before copying, so a refusal leaves no copy. `beats place PROJECT ID --out DIR
--track NAME --bar N` lays one pattern as a region from bar N, `--repeat` times back to back,
refused at the first bar whose meter is not the pattern's; `--map NAME` translates its notes from
the map it was indexed in and `--velocity` scales every velocity. A region never grows to hold a
note: one at or past its copy's end is dropped and counted. `beats compose PROJECT --out DIR
--track NAME --group TEXT` writes one region per arrangement section whose name says Intro, Verse,
Pre-Chorus, Chorus, Bridge or Outro, from the group's patterns of that role in the section's meter
(the second verse takes the second Verse pattern, cycling), repeated to the section's length;
`--fills` puts a fill pattern's fill bar on each section's last bar. Every other section is
skipped with its reason. `beats generate PROJECT --out DIR --track NAME --bar N --meter N/D
--bars N` picks a phrase bar by bar from the index's real bars: the first starts a pattern, each
next has the kick and snare onsets nearest those of the bar that followed the last pick in its
own pattern, and timing and velocity move slightly. `--category`, `--role`, `--intensity` and
`--tempo` filter as `groovebin search` does, `--fills` puts a fill bar on every fourth bar,
`--seed` repeats a phrase (the seed used is printed) and `--map` writes it in another map;
`groovebin generate -o FILE.mid` writes the same phrase as a file for listening.

`drums-to-midi PROJECT --out DIR --hit TRACK=TERM --track TARGET` turns drum hits in audio tracks
into notes in one new MIDI region on a software instrument track, on a copy; Logic's re-save of one
kept the region and every note. Each `--hit` names an audio track and the drum-map term its hits
play (`kick`, `snare`, `hihat closed` …) in `--map NAME` (default `addictive-drums-2`); each hit
becomes a sixteenth on that key, cut at the next note on that key, its velocity from the hit's peak
scaled from the track's quietest to its loudest. `--threshold DB` sets how far under the track's
loudest hit a hit may be (lower finds quieter hits). `--grid N` quantizes the notes first, and the
region spans the whole bars holding the quantized notes. Audio is found as `quantize-drums` finds it
(`--audio DIR`); a song whose tempo changes, an unknown term, two tracks on one key, a track with no
audio regions, and a WAV whose sample rate or own frame count disagrees with its file record are
refused.

## Logic's own settings

`prefs` reads and writes Logic's application settings, which live in a plist outside any
project. It refuses to write while Logic is running and takes a backup first. This is the only
command that changes state Logic owns globally rather than per-session.

## The four rules that apply everywhere

1. **Writers take `--out` and copy first.** The input project is never modified.
2. **Logic's own library is opt-in.** `--install` to write there, `--overwrite` to replace.
3. **A command's confidence level is printed before it writes**, if that level is `CLAIMED`,
   `DERIVED` or `BROKEN`. `LOGICXKIT_NO_NOTICE=1` silences the line but not the risk.
4. **Confirmation means Logic opened it.** Not that the command exited zero.

## Adding a new command

1. Register it in the relevant `_*.py` group beside `logic/cli.py`, or in `au/cli.py`.
2. Declare its confidence level in `src/logicxkit/logic/_capabilities_table.py`.
   `tests/logic/test_capabilities.py` fails when a subcommand has no entry, so this is not
   optional.
3. Start at `DERIVED` unless you have opened the output in Logic. Raising a level needs
   evidence the level itself names — see [EVIDENCE.md](EVIDENCE.md).
4. If it writes a project, route it through `_edit.edit_copy` unless there is a reason not to,
   and state that reason in the capability entry's catch.
5. Add it to the right group above only if it opens a new category. A new editor does not need
   its own paragraph here; the rules already cover it.
