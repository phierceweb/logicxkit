# What logicxkit can do

What each logicxkit command does to a Logic Pro project, in the words Logic itself uses, and what
it does not do.

How each command was checked in Logic, and where each one stops, is in [EVIDENCE.md](EVIDENCE.md).
The options are in `logicxkit logic <command> --help`.

---

## Table of Contents

- [How it works](#how-it-works)
- [Look inside a project](#look-inside-a-project)
- [Tracks and track stacks](#tracks-and-track-stacks)
- [Routing and the mixer](#routing-and-the-mixer)
- [Plug-ins](#plug-ins)
- [Templates and batches of songs](#templates-and-batches-of-songs)
- [Regions, MIDI and drums](#regions-midi-and-drums)
- [Project and Logic settings](#project-and-logic-settings)
- [Channel strips and patches](#channel-strips-and-patches)
- [What it does not do](#what-it-does-not-do)
- [How far to trust it](#how-far-to-trust-it)
- [Adding a new command](#adding-a-new-command)

---

## How it works

logicxkit reads and changes saved Logic projects (`.logicx`) without opening Logic. A command
that changes something writes a changed copy into the folder you name with `--out`; the project
you started from is never touched. Open the copy in Logic to use it.

- **A Mac.** It runs on macOS only.
- **A project saved by Logic 12.3.1 or 12.4, to change it.** A project an older Logic saved is
  refused with the reason: open it in the current Logic, save it, and run the command again.
  Reading works on older projects too.
- **The command line.** Every change is a command, such as
  `logicxkit logic rename Song.logicx --track "Audio 1=Rhythm Gtr" --out edited/`. An AI coding
  agent such as Claude Code can run them for you from a plain description of the change.
- **Third-party plug-ins come from a project that already has them.** To put a third-party
  plug-in on a channel, logicxkit copies it from a project where it is loaded: run
  `logicxkit logic donors` on such a project once. Logic's own effects come with logicxkit; its
  instruments are copied the same way, from a project that has the instrument loaded.

## Look inside a project

These only read. Point them at any project.

- **What's in it.** Every track and channel, the plug-ins on each and their preset names, and
  the settings of Logic's own plug-ins by name where measured — most of its effects, instruments
  and MIDI effects (`project`); `manifest` is the short form.
- **What changed.** Compare two projects, or a project against your saved channel strips to find
  a channel that no longer matches the strip it names (`diff`).
- **Plug-ins.** Every plug-in in the project — Logic's own instruments, MIDI effects and
  Pedalboard's pedals by name too — and which third-party ones are not installed on this Mac (`plugins`). A compressor's, gate's, EQ's or multiband's settings in plain units —
  threshold, ratio, EQ bands (`settings`) — for Logic's Compressor, Noise Gate, Channel EQ and
  Multipressor, FabFilter Pro-C 2, Pro-Q 4 and Pro-MB, sonible smart:comp 2 and smart:gate, and
  iZotope Neutron 5.
- **Inside third-party plug-ins.** The settings a third-party plug-in stores, which Logic shows
  only as a preset name (`logicxkit au strip` for a project or a `.cst`, `au preset` for a preset
  file), and Neural DSP amp settings (`neural`).
- **The mixer and the timeline.** Fader, pan, mute and solo (`levels`); track stacks (`stacks`);
  regions (`regions`); markers (`markers`); arrangement sections (`arrangement`); tempo
  (`tempo`); time signature and key (`signature`); groups (`group`); automation (`automation`);
  MIDI notes (`midi`); Session Player settings (`sessionplayer`).
- **The screenshot Logic saves in every project.** Save it as a picture (`image`), or read the
  text in it (`ocr`).
- **Channel strip files and patches.** The EQ and compressor settings in a `.cst` (`decode`); a
  Library patch (`patch`).

`recdiff` lists the raw differences between two saves of a project; it is for working on
logicxkit itself.

Many of these make changes when given an option that asks for one. Those are below.

## Tracks and track stacks

- Add audio and software instrument tracks, mono or stereo, with their input set (`add-track`).
- Rename tracks (`rename`), color them (`colour`), hide and show them (`hide`), and move them up
  or down the track list (`reorder`).
- Make a channel mono or stereo (`width`).
- Choose which controls the track headers show (`header`).
- Make folder and summing stacks from tracks, including a stack inside a stack (`stack-create`).
- Move tracks and stacks into and out of stacks, flatten a stack, and convert a folder stack to a
  summing stack as Logic's Track menu does (`stacks`).

Logic nests stacks two deep, and logicxkit refuses a third level as Logic does.

## Routing and the mixer

- Set a channel's input and output, including sending it to a bus (`route`). A bus nothing used
  before gets its aux, as in Logic.
- Add, change and remove sends — the bus, level, pre or post fader, bypass — or copy a channel's
  sends from another project (`send`).
- Set faders and pans, or copy every fader and pan from another project (`levels`).
- Make groups, choose what each one links, and put channels in or take them out (`group`).
- Write, copy and clear automation: volume, pan, mute and solo, and plug-in parameters on Logic's
  Compressor, Noise Gate, Channel EQ and Multipressor and on third-party plug-ins logicxkit has a
  parameter list for (`automation`).

A change that leaves channels feeding each other in a loop, such as two summing stacks each
routed into the other, is still written, with a warning that names the loop.

## Plug-ins

- Put a plug-in in any insert slot, take one out, or replace one, with its settings dialled in on
  the way (`add-plugin`, `remove-plugin`, `replace-plugin`). Automation and Smart Controls stay
  with the plug-ins they belong to.
- Put one of Logic's own instruments on a software instrument track, or swap the one that is
  there (`add-plugin`, `replace-plugin --at 1`): any of the 27 in the instrument slot's menu, from
  ES2 and Alchemy to Sampler and Drum Kit Designer. The track becomes stereo or mono as the
  instrument is. Its Smart Controls are not set up for most of them the way Logic sets them up
  when you load the instrument yourself. MIDI effects are listed but not added.
- Change the settings of a plug-in already on a channel by name — threshold, ratio, an EQ band
  (`settings --set`) — on Logic's Compressor, Noise Gate, Channel EQ and Multipressor and on
  FabFilter Pro-C 2, Pro-Q 4 and Pro-MB.
- Swap one plug-in for another everywhere in a project, carrying the settings across when both
  do the same job, such as a FabFilter Pro-C 2 into Logic's Compressor (`swap-plugin`). A setting
  with no equivalent is named in the report.
- Make a low-latency copy for recording: third-party plug-ins become Logic's own with their
  settings carried, the ones with no Logic equivalent come out, and plug-ins with lookahead are
  bypassed (`tracking-chains`).
- Bypass every plug-in on a channel (`bypass`), or empty its inserts (`clear-slots`).
- Copy channels' plug-ins from another project, onto one channel or onto every track in a stack
  (`transplant`), or put whole chains on channels from a list you write (`chains`, whose
  `--plan` names every chain it would replace).

## Templates and batches of songs

`apply-template` gives an existing song a template's layout. It adds the tracks the song is
missing and brings each matching track in line with the template: name, color, icon, stack,
order, input and output, mono or stereo, plug-ins, sends, fader and pan, groups, and the channel
strip it names. It also copies the track header settings, the control bar, the transport modes
and the metronome settings. The song keeps its own tempo, time signature and key, and tracks the
template does not have are left as they are. `migrate` does the same in one step per song and
writes a renamed copy.

Songs started from the template match up track by track on their own. A song that was not needs
a list saying which of its tracks is which template track: `--propose-map` drafts one for you to
check, and without one the song is refused.

Smaller pieces copy from one project to another on their own:

- The control bar (`controlbar --from`), the toolbar (`toolbar --from`), the track header
  settings (`header --from`), the transport modes and count-in (`modes --from`), and the
  metronome and recording settings (`metronome --from`).
- Faders and pans (`levels --to`), and a channel's sends (`send --copy`).

## Regions, MIDI and drums

- **Audio and MIDI regions.** Import a WAV; move, trim, split, loop, mute and rename regions; set
  fades and crossfades; set the region inspector's gain, delay, transpose, fine tune and reverse;
  color a region (`regions`).
- **Markers and sections.** Add, rename, move and delete markers (`markers`) and arrangement
  sections (`arrangement`).
- **Tempo and signature.** Set the tempo, and add tempo changes and ramps (`tempo`); set the time
  signature and key, and change them later in the song (`signature`).
- **MIDI.** Add regions and notes; transpose, change velocity, quantize, move, copy and delete;
  run Logic's Transform window operations, such as humanize, swing, legato and fixed velocity;
  export the song's MIDI as a `.mid` file; convert drum parts between the General MIDI, Addictive
  Drums 2 and Drum Kit Designer note layouts (`midi`).
- **Quantize a multitrack drum recording**, every drum track moved together the way Logic's
  quantize-locked drum group with Flex Time does it (`quantize-drums`). It finds the hits itself,
  so the result is close to Logic's, not identical. `--bars` quantizes only part of the song.
- **Turn drum audio into MIDI.** Kick, snare and tom hits become notes in a region on a software
  instrument track (`drums-to-midi`). Hi-hats and cymbals do not convert well.
- **Drum patterns.** Write patterns from a MIDI drum library into a song: one pattern, a pattern
  per arrangement section with fills, or a new phrase put together from real bars (`beats`). The
  library is [groovebin](https://github.com/phierceweb/groovebin)'s.

## Project and Logic settings

- Turn transport modes on and off — Cycle, Replace, Autopunch, the metronome click, Use Musical
  Grid — and set the count-in (`modes`).
- Set the Metronome and Recording project settings (`metronome`).
- Show and hide control bar items (`controlbar`) and toolbar buttons (`toolbar`).
- Change Logic's own settings, the ones in its Settings window, which belong to Logic rather than
  to a project: list them, change them by name, save a set to a file and apply it on another Mac,
  or make a project's control bar the default (`prefs`). It covers every pane except audio
  devices, plug-in delay compensation and control surfaces. Logic has to be closed, and a backup
  is taken first.

## Channel strips and patches

- Build `.cst` channel strips with Logic's Channel EQ and Compressor from a list of settings
  (`build`; `verify` checks the list without writing), and single-plug-in settings files (`pst`).
- Save a channel from a project as a `.cst` (`strip-save`).
- Build a Library patch from a `.cst` (`patch --build`).
- After renaming files in your channel strip library, point a project's channels at the new names
  (`retrack`). Only the name a channel points at changes; its plug-ins stay as they are.

None of these write into Logic's own library folders unless you add `--install`.

## What it does not do

- **It does not control Logic.** It cannot play, record, bounce or press a button in a running
  Logic; it works on saved files. The one exception, `migrate --verify`, opens a copy in Logic and
  saves it again to check it. [logic-pro-mcp](https://github.com/MongLong0214/logic-pro-mcp)
  controls a running Logic.
- **It cannot hear.** It checks that a changed project is put together the way Logic puts one
  together, and refuses to write one that is not. It cannot tell that a plug-in chain landed on
  the wrong channel or that a mix sounds wrong. Open every copy in Logic and listen before you
  use it.
- **It refuses what has not been measured.** Each command refuses the cases it has not been
  measured on and names the reason: a project an older Logic saved, a song with tempo changes for
  the drum commands, a third level of stacks.

## How far to trust it

Every command that changes a project has had its output opened in Logic and checked there.
[EVIDENCE.md](EVIDENCE.md) says, for each command, what was checked, in which Logic version, on
what date, and where it stops; `logicxkit logic capabilities` prints the same list.

Opened in Logic but not yet listened to: drum parts converted between note layouts
(`midi --remap`), a region transposed with `regions --transpose`, and the patterns `beats`
writes. `migrate --verify` has not yet been run against Logic.

## Adding a new command

1. Rate it in `src/logicxkit/logic/_capabilities_table.py`. EVIDENCE.md is generated from it.
2. Add a line for it in the section above where a Logic user would look for it, in Logic's own
   words, naming the command in backticks. `tests/logic/test_capabilities.py` fails when a
   command is missing from this file.
3. Until it is CONFIRMED, name it under [How far to trust it](#how-far-to-trust-it). The same
   test fails when it is missing there.
4. Say what the command does for the person using Logic, not how the file changes.
