# logicxkit

[![PyPI](https://img.shields.io/pypi/v/logicxkit)](https://pypi.org/project/logicxkit/)

Read and edit Logic Pro projects, channel strips and Audio Unit plugin state from the command
line.

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

None of these formats are documented, so everything here came out of measurement: one
deliberate change per Logic save, then a byte diff against the save before it. The control bar
is the tidiest example — every button id was pinned on fifty single-toggle saves (2026-09-04),
and a control bar written by this tool and copied whole onto another project came up in Logic
with that exact set. That standard is not uniform across the tool. Some commands have been
opened in Logic and confirmed, some are reasoned from diffs and never opened, and a few carry
defects reproduced on real projects. **[`docs/CAPABILITIES.md`][caps]
carries the level and the evidence for every command, and `bin/run logic capabilities` prints
the same table.** Read it before you point a writer at a session you care about.

## Requirements

- **macOS.** There is no Linux or Windows path. CI runs the synthetic layer on a macOS runner,
  which is all a runner can do: the goldens need a reference corpus that is not distributable
  and `tests/rig` needs a physical console's scene, so both skip there.
- **Logic Pro** — the tool reads and writes its file formats, and confirming any change means
  opening the result in Logic.
- **Python 3.12 or newer.** `bin/run setup` builds the venv with `python3.12`; set
  `PYTHON=python3.13` (or any 3.12+) to use another interpreter.
- **A Swift toolchain** (`swift`) — the headless AU host and the Apple Vision OCR are Swift
  scripts run JIT at call time. Without it, `au` falls back to static parameter tables and
  `logic ocr` is unavailable.

The only runtime dependency is [pf-core][pf-core], installed automatically, which supplies the
atomic-write helpers and the logging and exception types used at the CLI boundary. The library
itself stays pure-stdlib.

## Getting it

```bash
pip install logicxkit
logicxkit logic project ~/Music/Logic/Song.logicx    # read-only, to see it working
```

That gets you the `logicxkit` command. To work on it instead, clone it and let `bin/run` build
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
  a stack); **Neural DSP state decode** (`logic neural`); and the project editors — track
  header, control bar, toolbar, transport modes, metronome, channel width, mixer groups,
  arrangement sections, tempo, time signature and key, track add/rename/colour/hide/reorder,
  sends, routing, and `apply-template` to move a session onto another project's layout. See
  [`src/logicxkit/logic/README.md`][logic-fmt].
- **`logicxkit.au`** — Audio Unit preset/state decoder (read-only): FabFilter `.ffp` +
  `.aupreset` parsing, Waves XPst, **TR5 chain XML** (module chain + per-module params from the
  ValueTree `Chain` prop), **sonible protobuf field walk** (values, unnamed), and a **headless
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

**Two writers are not gated.** `logic stacks --move` and `logic levels --to` write their copy
directly, so nothing checks the result before it lands. They still never touch the input.

A write by a command that has not been confirmed in Logic prints a one-line notice naming its
level before it runs, so you get the warning without having to have read
[`docs/CAPABILITIES.md`][caps] first. `LOGICXKIT_NO_NOTICE=1` silences it.

And the gate covers structure, not sound. It cannot tell you a chain landed on the wrong
channel. **Open every output in Logic before trusting it** — that, not a green run, is what
confirms a write.

Three more things write outside `--out`, and one warning:

- **`logic build` and `logic pst` can write your channel-strip and plug-in settings library,
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
  anyway. The remaining open defects are listed in
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
  tests/goldens            real-file goldens, reached by manifest key — skip without the corpus
  tests/rig                a mixing-console preflight golden — skips without its scene
```

The package graph is a DAG and `tests/test_package_layering.py` enforces it: `au` must never
import `logic`. Both read Logic containers through `logicx`.

## What is not in the repo

The reference corpus this was built against is **not distributable and is not here**: Logic's
own controlled saves (one deliberate change per save, so a diff isolates the bytes), project
templates, finished sessions, a channel-strip library snapshot. Those are Logic-authored project
files containing real music. The same goes for the data root the tools load — record templates
Logic wrote, plugin-slot donor records, and AU parameter tables dumped from installed plugins,
none of which are ours to publish.

The consequence for a fresh clone: **`bin/run pytest` runs green, but the goldens under
`tests/goldens/` all skip**, so a green suite there proves the synthetic layer and nothing about
real files. The run prints `goldens: N of M keys found` on its last line so you can see how much
actually ran, and `LOGICXKIT_REQUIRE_GOLDENS=1` turns a missing golden into a failure.

[`resources/README.md`][corpus] describes the shape of the corpus and how the
controlled saves are made; [`resources/data/README.md`][data-root] describes the
data root and how to regenerate each part of it (`logic donors`, `logic recdiff`, `au params`).
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
runs the same two on a macOS runner, but with no corpus staged it proves the synthetic layer
only — a green check there is not a substitute for running the suite on a machine that has the
files. [`CONTRIBUTING.md`][contributing] has the full loop; the house rules are:

- File size target 300 lines, hard limit 500, one concern per file. The limit is enforced by
  pf-core's `pf_core.guards` gate inside `bin/run lint`; there is no baseline file and none
  should be added — split an oversize file instead.
- src-layout, no `sys.path` hacks. `X | None` types.
- The library stays pure-stdlib and portable; [pf-core][pf-core] is
  used for foundation helpers (atomic writes) and adopted for logging and exceptions at the CLI
  boundary only.
- **Decoding claims need evidence from a real file.** `None` beats a guess, and a command
  appearing in `--help` is not evidence of anything. If you add or change a writer, declare its
  level in `src/logicxkit/logic/_capabilities.py`; `tests/logic/test_capabilities.py` fails when
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
[license]: https://github.com/phierceweb/logicxkit/blob/main/LICENSE
[notice]: https://github.com/phierceweb/logicxkit/blob/main/NOTICE
