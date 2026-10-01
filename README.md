# logicxkit

[![PyPI](https://img.shields.io/pypi/v/logicxkit)](https://pypi.org/project/logicxkit/)

Read and change Logic Pro projects from the command line without opening Logic: tracks, regions,
the mixer, plug-in settings and MIDI, in one project or across a batch.

## Why logicxkit

While working in Logic sessions, sound engineers continually make improvements, innovations, workflow tweaks, etc. Maybe 7 songs into mixing an album, you discover that bussing the vocal reverbs to their own bus, then applying an EQ with a side chain that knocks out some of the overlapping frequencies on the reverbs from the main vocals increases clarity. But now that has to be applied to every previous song. Through the Logic Pro interface, this is tedious work, especially if the bus numbers differ or inputs are different.

Or maybe between projects, you've really enhanced your workflow. Your track colors, transport preferences and preferred track headers have changed, and maybe you've added aux channels to send different portions of a MIDI instrument to.

Or maybe the hi hat is too loud when open but too quiet when closed.

I built this project to assist me with all of that. Reading my high-latency mix templates and applying plugins and parameters to create low-latency stock logic versions for tracking. Then taking a whole batch of projects and converting them back to the mix template in seconds, driven by an AI coding agent.

Along the way I started [groovebin][groovebin] to assist with MIDI drums (and later MIDI instruments).

New capability requests are welcome as [issues](https://github.com/phierceweb/logicxkit/issues).

## Description

A `.logicx` project and a `.cst` channel strip setting are opaque binary containers. Everything
about a session — which plugin sits in which slot, what that plugin's saved state actually
contains, the fader, the pan, the routing, the track list, the groups, the arrangement, the
control bar — is reachable only by opening Logic and looking at it. There is no way to diff two
sessions, script one change across twenty of them, or read what a third-party plugin stored
inside a strip you saved last year.

logicxkit reads those containers directly. With it you can take a read-only inventory of a
project, diff two projects (or one project against your channel-strip library), decode a
FabFilter or iZotope state that Logic itself only shows you as a preset name, read fader and pan
across a whole session, copy a control bar or a set of mixer groups from one project onto
another, add and rename and reorder tracks, repoint strip references after a library rename,
migrate an old session onto a newer template, and build native Channel EQ / Compressor strips
from a JSON spec.

If what you want is to drive a *running* Logic — press a button, arm a track, move the
playhead — that is a different job, and [logic-pro-mcp](https://github.com/MongLong0214/logic-pro-mcp)
does it through Accessibility, AppleScript and control-surface protocols. logicxkit never talks
to Logic. It works on closed project files, in batch, and the two are complements: one changes
what Logic is doing, the other changes what a session *is* before Logic opens it.

None of these formats are documented, so everything here came out of measurement: one
deliberate change per Logic save, then a byte diff against the save before it. The control bar
is the tidiest example — every button id was pinned on fifty single-toggle saves (2026-09-04),
and a control bar written by this tool and copied whole onto another project came up in Logic
with that exact set. That standard is not uniform across the tool. Some commands have been
opened in Logic and confirmed, some are reasoned from diffs and never opened, and a defect
reproduced on a real project is recorded until a regression test closes it. **[`docs/CAPABILITIES.md`][caps]
carries the level and the evidence for every command, and `bin/run logic capabilities` prints
the same table.** Read it before you point a writer at a session you care about.

## Requirements

- **macOS.** There is no Linux or Windows path. CI runs on a macOS runner with the public golden
  corpus tracked in the repo, so the synthetic layer and every public golden run there; the owner's goldens
  (real sessions) and `tests/rig` (a physical console's scene) skip.
- **Logic Pro 12.3.1 or 12.4** — the tool reads and writes their file format, and confirming any
  change means opening the result in Logic; every confirmation so far was made in 12.3.1. The
  writers take a project in the format both save (2513) and refuse any other, naming the format
  they found: open an older project in Logic and save it first. The readers run on older saves,
  where tracks may read unnamed.
- **Python 3.12 or newer.** `bin/run setup` builds the venv with `python3.12`; set
  `PYTHON=python3.13` (or any 3.12+) to use another interpreter.
- **A Swift toolchain** (`swift`) — the headless AU host and the Apple Vision OCR are Swift
  scripts run JIT at call time. Without it, `au` falls back to static parameter tables and
  `logic ocr` is unavailable.

Two runtime dependencies, installed automatically: [pf-core][pf-core], which supplies the
atomic-write helpers and the logging and exception types used at the CLI boundary, and
[groovebin][groovebin], the general-MIDI library — Standard MIDI Files, note maps, transforms
and the pattern library — that the MIDI editors and `logic beats` build on.

## Getting it

```bash
pip install logicxkit
logicxkit logic project ~/Music/Logic/Song.logicx    # read-only, to see it working
```

That gets you the `logicxkit` command, and with it the record templates and native plug-in
donors the writers need — Logic's own, taken from its saves of a blank project. To work on it instead, clone it and let `bin/run` build
the venv — every command below is written that way, and `bin/run logic …` and
`logicxkit logic …` are the same thing:

```bash
git clone https://github.com/phierceweb/logicxkit.git
cd logicxkit
bin/run setup                        # .venv (python3.12) + editable install + dev extra
bin/run pytest                       # the suite
```

In a checkout, `bin/run` is the only entry point you need: `setup | pytest | python | pip |
ruff | lint | logic | au`. It sources a local `.env` if you have one (see `.env.example`), so
commands run bare.

```bash
bin/run logic project "<song.logicx>"                    # read-only inventory
bin/run logic diff "<a.logicx>" "<b.logicx>"             # what differs between two sessions
bin/run logic levels "<song.logicx>"                     # channel fader + pan
bin/run logic stacks "<song.logicx>" [--tracks]          # track stacks / arrange list
bin/run logic ocr "<song.logicx>"                        # OCR the auto-saved WindowImage
bin/run logic neural "<strip.cst | song.logicx>"         # Neural DSP knob values
bin/run logic midi "<song.logicx>" [--export out.mid]      # MIDI regions, or a .mid of them
bin/run logic midi "<song.logicx>" N --out DIR --humanize   # Logic's Transform window on region N
bin/run logic beats place "<song.logicx>" ID --out DIR --track NAME --bar N  # a groovebin pattern as a region
bin/run logic beats compose "<song.logicx>" --out DIR --track NAME --group TEXT  # a region per section
bin/run logic beats generate "<song.logicx>" --out DIR --track NAME --bar N --meter 4/4 --bars 8  # a phrase from library bars
bin/run logic migrate "<song.logicx>" --template "<t.logicx>" --out DIR  # a song onto a template
bin/run logic plugins "<song.logicx | folder>"            # plug-ins referenced, and which are missing
bin/run logic settings "<song.logicx>"                    # each slot's settings in one vocabulary
bin/run logic add-plugin "<song.logicx>" --channel "Audio 1" --plugin Compressor --out DIR  # a plug-in into a slot
bin/run logic swap-plugin "<song.logicx>" --from "Pro-C 2" --to Compressor --out DIR  # every slot, settings carried
bin/run logic tracking-chains "<song.logicx>" --out DIR   # Logic's own plug-ins for tracking, lookahead bypassed
bin/run logic patch "<name.patch | folder>"               # a Library patch: channels, strips, plug-ins
bin/run logic regions "<song.logicx>"                     # every MIDI and audio region, with files
bin/run logic markers "<song.logicx>"                     # the marker track
bin/run logic sessionplayer "<song.logicx>"               # Session Player drummer, preset, settings
bin/run logic quantize-drums "<song.logicx>" --out DIR    # quantize a drum take to the grid, no Logic
bin/run logic drums-to-midi "<song.logicx>" --out DIR --hit "Kick In=kick" --track NAME  # hits to notes
bin/run au strip "<strip.cst | song.logicx>"             # every embedded 3rd-party state
bin/run au preset "<preset.aupreset | .ffp>"             # a preset file, named, in real units
bin/run logic capabilities -v                            # what each writer is trusted for
```

## The packages

- **`logicxkit.logic`** — Logic Pro channel-strip (`.cst`) build and decode; a read-only
  `.logicx` project analyzer (typed strip labels, per-channel `.cst` wiring refs); **`logic
  diff`** (project↔project and project↔strip-library drift detection); **`logic image`**
  (extract the auto-saved WindowImage) and **`logic ocr`** (Apple-Vision OCR of it — reads the
  mixer as Logic drew it); **`logic levels`** (fader + pan, read and copy between projects);
  **`logic stacks`** (folder stacks and the arrange track list, and `--move` to put a track into
  a stack); **`logic midi`** (MIDI regions, their export as a `.mid`, edits and Logic's Transform window — a selection with operations, or a preset — by region number); **`logic plugins`**
  (every referenced plug-in, and which this Mac lacks — a check that runs Apple's `auval -a`
  scan and can take 25 seconds or more); **`logic patch`** (a Library patch
  bundle's channels, strips and plug-ins, and `--build` to make one); **`logic regions`** (MIDI and audio regions with their files, mutes, loops and fades; `--audio` imports a WAV and `--move`, `--trim`, `--split`, `--loop`, `--mute`, `--rename`, `--fade-in`, `--fade-out` edit one by its number); **`logic markers`** (the marker track, with add, rename, move and delete); **`logic sessionplayer`**
  (a Session Player region's settings and generated notes); **`logic beats`** (patterns from a
  [groovebin][groovebin] library placed, composed or generated as regions); **`logic
  drums-to-midi`** (drum hits in audio tracks as MIDI notes); **Neural DSP state decode** (`logic
  neural`); and the project editors — MIDI regions, notes and edits by region number, drum-map
  remaps, track
  header, control bar, toolbar, transport modes, metronome, channel width, mixer groups,
  arrangement sections, tempo, time signature and key, track add/rename/colour/hide/reorder,
  sends, routing, `apply-template` to move a session onto another project's layout, and
  `migrate` to do that in one run with an optional Logic re-save check. The plug-in editors
  change one slot without touching the rest of the chain: **`logic add-plugin`**,
  **`remove-plugin`** and **`replace-plugin`** insert, take out or swap a plug-in from the donor
  library, and `--side-chain` points a slot at a track, bus or aux by name. **`logic settings`**
  reads a compressor's, gate's, EQ's or multiband's settings in one vocabulary whichever plug-in
  holds them, so `replace-plugin --translate` can move a Pro-C 2's settings into Logic's
  Compressor, or a Channel EQ's bands into Pro-Q 4, along with the slot's automation lanes.
  **`logic swap-plugin`** makes that swap on every slot holding one plug-in across a project.
  **`logic tracking-chains`** makes a copy for recording, where plug-in latency gets in the way:
  each third-party plug-in with a translation map becomes Logic's own of its family with its
  settings carried, and the natives that carry lookahead are bypassed. See
  [`src/logicxkit/logic/README.md`][logic-fmt].
- **`logicxkit.au`** — Audio Unit preset/state decoder: FabFilter `.ffp` +
  `.aupreset` parsing, Waves XPst, **TR5 chain XML** (module chain + per-module params from the
  ValueTree `Chain` prop), **sonible protobuf field walk** (values by field number), **iZotope
  Neutron 5 state** (zlib JSON in real units), a writer that patches a FabFilter state in place
  (Pro-C 2 and Pro-MB by parameter id, Pro-Q 4 by band), and a **headless
  AU host** (`src/logicxkit/native/auprobe.swift`) that loads any installed plugin's state and
  dumps every parameter with real names and UI-formatted values. `au strip` decodes the
  3rd-party states **embedded in `.cst` strips and `.logicx` projects** — the layer Logic
  reports as a preset name and nothing more (FabFilter, Ozone, Nectar, Neutron, Ampeg SVT). AU
  parameter tables live in the data root for offline decode when the host is unavailable. See
  [`src/logicxkit/au/README.md`][au-fmt].
- **`logicxkit.logicx`** — the `.logicx` container format itself: alternatives, `ProjectData`,
  `OCuA` channel blocks. A leaf that both `logic` and `au` read projects through.
- **`logicxkit.utils`** — helpers at least two domains share: the Swift runner behind the AU
  host and OCR, the data-root resolver, and environment lookup.

## Safety

Every command that changes a project takes `--out`, copies the project there, and edits the
copy. **The input project is never modified.**

Most of those writers go through `_edit.edit_copy`, which holds the result against its input
with `services/integrity.py` and refuses on any structural regression — new record-level
problems, more sequence link errors, objects whose mixer index stopped matching their channel,
channels whose send flags stopped matching their sends — then reads the file back to confirm the
bytes that landed are the bytes that passed. A refused run discards the whole copy rather than
leaving a bundle that disagrees with its own metadata.

A write by a command that has not been confirmed in Logic prints a one-line notice naming its
level before it runs, so you get the warning without having to have read
[`docs/CAPABILITIES.md`][caps] first. `LOGICXKIT_NO_NOTICE=1` silences it.

And the gate covers structure, not sound. It cannot tell you a chain landed on the wrong
channel. **Open every output in Logic before trusting it** — that, not a green run, is what
confirms a write.

Three more things write outside `--out`, and one warning:

- **`logic build`, `logic pst` and `logic strip-save` can write your channel-strip and plug-in settings library,
  but only if you ask.** A relative `output_dir` in a spec resolves under
  `~/Music/Audio Music Apps` — Logic's own live library, not a scratch directory — so a write
  that lands there is **refused unless you pass `--install`**, and a spec cannot reach your
  library by leaving a key out. `--overwrite` is still separately required to replace an
  existing file. To write elsewhere, set `output_root` (which moves only the output;
  `strip_root` / `LOGICXKIT_STRIP_ROOT` moves where sources are read from too), or give an
  absolute `output_dir`. The shipped `config/example-*.json` set `output_root` to `out/`, so
  running an example as-is reads your library but never writes to it.
- **`logic prefs` writes Logic's own settings** through `defaults`. It refuses while Logic is
  running and takes a backup first.
- **`logic donors` writes into the data root** (`LOGICXKIT_DATA`) unless you pass `--library`.
- **`logic transplant` refuses a move it cannot make safely.** A channel holds a fixed run of
  slot keys, ending at its `.cst` reference record; a clone that overruns that run deletes the
  reference, and `validate_project` cannot see the loss. A clone across record class versions
  cannot be legalised either. Both stop the run and say what to do instead; `--force` writes
  anyway. Any open defect is listed in
  [`docs/CAPABILITIES.md`][caps].

## Layout

```
logicxkit/
  bin/run                  venv wrapper: setup|pytest|python|pip|ruff|lint|logic|au
  config/example-*.json    neutral example specs (strips, psts, chains, retrack)
  docs/CAPABILITIES.md     what each writer is trusted for, and the evidence behind it
  src/logicxkit/
    cli.py                 unified entry point: logicxkit logic|au …
    logicx/                the .logicx container: alternatives, ProjectData, OCuA channel
                           blocks. A leaf — logic and au both read projects through it
    logic/
      _binary.py           the GAMETSPP float-block model
      cli.py               and the _*.py command groups beside it
      services/            strip build/decode, project analysis, the editors, integrity
      orchestrators/       multi-step workflows (apply-template)
    au/
      cli.py _views.py
      services/            ffp, aupreset, embed, waves, sonible, tr5, juce, host,
                           tables, report
    native/                auprobe.swift, aulatency.swift, vision_ocr.swift — run by
                           `swift` at call time, shipped as package data
    utils/                 helpers ≥2 domains share (swiftrun, data root, env)
  tests/logic tests/au     synthetic records — green on any macOS checkout
  tests/corpus             the public corpus: Logic's saves of a blank project, one change each
  tests/goldens            real-file goldens, reached by manifest key — the owner's skip elsewhere
  tests/rig                a mixing-console preflight golden — skips without its scene
```

The package graph is a DAG and `tests/test_package_layering.py` enforces it: `au` must never
import `logic`. Both read Logic containers through `logicx`.

## What is not in the repo

Two corpora stand behind the goldens. The **public corpus** is Logic's own saves of a blank
project — one deliberate change per save, so a diff isolates the bytes — and it is in the
repo under `tests/corpus/`, so a golden ships in the commit that adds its test.
`tests/goldens/manifest.json` names each save by a neutral key with the facts a test may
assert. The **owner's corpus** — controlled saves cut
from real sessions, project templates, finished mixes, a channel-strip library snapshot — is
Logic-authored material containing real music and **is not here**. The record templates and
native plug-in donors the writers need ship inside the package (`src/logicxkit/data`, Logic's
own from the public corpus); a data root (`LOGICXKIT_DATA`) adds third-party donors and AU
parameter tables, which are not ours to publish.

The consequence for a fresh clone: **`bin/run pytest` runs every public golden**, and the keys
only the owner's corpus has skip. The run prints `goldens: N of M keys found` on its last line so you can see how much actually ran;
`LOGICXKIT_REQUIRE_GOLDENS=1` turns a missing golden into a failure, and
`LOGICXKIT_GOLDENS=owner` prefers the owner's files where both corpora have a key.

[`resources/README.md`][corpus] describes the shape of the owner's corpus and how the
controlled saves are made; [`resources/data/README.md`][data-root] describes the
data root and how to regenerate each part of it (`logic donors`, `logic recdiff`, and
`auprobe.swift list` for the AU tables).
Point `LOGICXKIT_RESOURCES` and `LOGICXKIT_DATA` at your own copies.

`tests/rig` is a separate opt-in: it checks a mixing-console scene against a preflight config
using the public [`x32scene`](https://pypi.org/project/x32scene/) package, which plain
`bin/run setup` does not install. `bin/run setup rig` adds it; without both the package and the
scene, those tests self-skip.

## Development

```bash
bin/run lint     # ruff + the pf-core structural gate
bin/run pytest   # the suite; ends with the goldens line
```

Both must pass before a change lands. **[`docs/`][docs] is the documentation index** —
installation, the command groups and their rules, and the format references.
CI ([`.github/workflows/ci.yml`][ci])
runs the same two on a macOS runner with the public corpus fetched, but the owner's goldens skip
there, so a green check is not a substitute for running the suite on a machine that has those
files. [`CONTRIBUTING.md`][contributing] has the full loop; the house rules are:

- File size target 300 lines, hard limit 500, one concern per file. The limit is enforced by
  pf-core's `pf_core.guards` gate inside `bin/run lint`; there is no baseline file and none
  should be added — split an oversize file instead.
- src-layout, no `sys.path` hacks. `X | None` types.
- The library imports the standard library and [groovebin][groovebin]; [pf-core][pf-core] is
  used for foundation helpers (atomic writes) and adopted for logging and exceptions at the CLI
  boundary only.
- **Decoding claims need evidence from a real file.** `None` beats a guess, and a command
  appearing in `--help` is not evidence of anything. If you add or change a writer, declare its
  level in `src/logicxkit/logic/_capabilities_table.py`; `tests/logic/test_capabilities.py` fails when
  a subcommand is undeclared or the doc drifts from the code.

## License

Apache License 2.0. See [`LICENSE`][license] and [`NOTICE`][notice].

[caps]: https://github.com/phierceweb/logicxkit/blob/main/docs/CAPABILITIES.md
[logic-fmt]: https://github.com/phierceweb/logicxkit/blob/main/src/logicxkit/logic/README.md
[au-fmt]: https://github.com/phierceweb/logicxkit/blob/main/src/logicxkit/au/README.md
[corpus]: https://github.com/phierceweb/logicxkit/blob/main/resources/README.md
[data-root]: https://github.com/phierceweb/logicxkit/blob/main/resources/data/README.md
[docs]: https://github.com/phierceweb/logicxkit/blob/main/docs/README.md
[ci]: https://github.com/phierceweb/logicxkit/blob/main/.github/workflows/ci.yml
[contributing]: https://github.com/phierceweb/logicxkit/blob/main/CONTRIBUTING.md
[pf-core]: https://pypi.org/project/pf-core/
[groovebin]: https://github.com/phierceweb/groovebin
[license]: https://github.com/phierceweb/logicxkit/blob/main/LICENSE
[notice]: https://github.com/phierceweb/logicxkit/blob/main/NOTICE
