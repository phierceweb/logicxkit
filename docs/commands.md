# Commands

What the CLI is organised into and the rules that govern each group.

This file is about shape and safety, not flags. For a command's flags run
`logicxkit logic <command> --help`; for whether a command is trusted against a real session read
[CAPABILITIES.md](CAPABILITIES.md), which is generated from the code and cannot drift from it.

---

## Table of Contents

- [Two CLIs](#two-clis)
- [Reading a project](#reading-a-project)
- [Editing a project](#editing-a-project)
- [Building strips and presets](#building-strips-and-presets)
- [Decoding plugin state](#decoding-plugin-state)
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

`image` extracts the window screenshot Logic auto-saves into a project; `ocr` reads that
screenshot with Apple Vision, which is the only way to see the mixer as Logic actually drew it.

Several of these turn into writers when given a flag — `stacks --move`, `levels --to`. Read the
next section before using one.

## Editing a project

**Every project-mutating command requires `--out` and works on a copy. The input is never
modified.** There is no in-place mode and none will be added.

Most editors route through `_edit.edit_copy`, which holds the result against its input using
`logic/services/integrity.py`, refuses on any structural regression, and then reads the file
back to confirm the bytes that landed are the bytes that passed. A refused run discards the
whole copy rather than leaving a bundle that disagrees with its own metadata.

Do not assume that gate covers everything:

- **It checks structure, not sound.** It cannot tell you a chain landed on the wrong channel.
- **Two writers bypass it entirely** — `stacks --move` and `levels --to` write their copy
  directly. They still never touch the input.
- **`chains` bypasses `edit_copy`** but runs the same regression check and read-back itself.
- **`controlbar`, `header` and `toolbar` bypass it** because they write `DisplayState.plist`
  and never touch `ProjectData`, which is what the gate inspects.

`apply-template` is the orchestrator over the rest: it migrates a session onto another
project's layout, pairing tracks by Environment object id within a lineage and by an explicit
map across lineages. It refuses across lineages without a map.

**Open every output in Logic before trusting it.** A green run is not confirmation; a file that
opens is not confirmation either. The way to check a writer is Save As in Logic and diff the
record list against the input.

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

`donors` writes into the data root rather than a project. `retrack` repoints strip references
after a library rename — it changes a label, never a chain.

## Decoding plugin state

`au strip` is the one to reach for: it decodes the third-party plugin states embedded inside
`.cst` strips and `.logicx` projects — the layer Logic reports as a preset name and nothing
more. `au preset` does the same for a standalone preset file.

Decoding runs a ladder per state: Neural DSP and JUCE decoders first, Waves through the static
XPst table, and anything else through the headless AU host, which loads the real plugin and
reads its parameters. `--no-host` forces the static tables instead. Without a `swift` toolchain
the host is unavailable and the ladder falls back on its own.

`au params` dumps a live parameter table from an installed plugin; `au tables` lists the tables
already in the data root. `logic neural` decodes Neural DSP knob values specifically, from
either a strip or a whole project.

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
2. Declare its confidence level in `src/logicxkit/logic/_capabilities.py`.
   `tests/logic/test_capabilities.py` fails when a subcommand has no entry, so this is not
   optional.
3. Start at `DERIVED` unless you have opened the output in Logic. Raising a level needs
   evidence the level itself names — see [CAPABILITIES.md](CAPABILITIES.md).
4. If it writes a project, route it through `_edit.edit_copy` unless there is a reason not to,
   and state that reason in the capability entry's catch.
5. Add it to the right group above only if it opens a new category. A new editor does not need
   its own paragraph here; the rules already cover it.
