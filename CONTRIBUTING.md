# Contributing

## Requirements

macOS with Logic Pro, Python 3.12, and a `swift` toolchain. There is no Linux path. CI runs
lint and the suite on a macOS runner with the public corpus from the checkout, so the synthetic layer and
the public goldens run there; the owner's goldens and `tests/rig` skip, because a runner has
neither those sessions nor a console. `bin/run lint && bin/run pytest` on your own machine,
before you open a pull request, is still the gate — and if you have goldens staged beyond the
public corpus, say so in the PR, because that run is worth more than the runner's.

## Setup

```bash
bin/run setup
bin/run pytest
bin/run lint
```

`bin/run setup rig` additionally installs `x32scene`, which only `tests/rig` needs.

## What a green suite does and does not prove

The public corpus (Logic's saves of a blank project, one change per save) is in the repo under
`tests/corpus/`, so its goldens run on every checkout; `tools/stage_public.py` adds a save to
it and to `tests/goldens/manifest.json`. Tests that read the owner's files — real sessions and
templates — skip everywhere else, and a change to one of those readers needs the owner to run
the suite. Every run ends with a `goldens: N of M keys found` line naming what skipped. Set
`LOGICXKIT_REQUIRE_GOLDENS=1` to make a missing golden fail instead (`=public`, which CI runs,
only for a public key). See `resources/README.md` and `resources/data/README.md` for what the
owner's corpus and the data root are.

## Evidence

A claim about byte layout needs a real file behind it. `None` beats a guess, and a command's
confidence level in `logic/_capabilities.py` may only be raised by evidence the level names:

- **CONFIRMED** — the output was opened in Logic and the change was there.
- **DERIVED** — reasoned from reads and diffs; never opened in Logic.
- **CLAIMED** — was confirmed once, but the artifact is gone or the code has changed since.

A file that opens in Logic can still be wrong. The way to check a writer is Save As in Logic and
diff the record list against the input.

## House rules

- File size: 300 lines is the target, 500 is the hard limit enforced by `bin/run lint`. There is
  no baseline file — split the file instead.
- One concern per file. `src/logicxkit/au` must never import `src/logicxkit/logic`; both read
  Logic containers through `src/logicxkit/logicx`. `tests/test_package_layering.py` enforces it.
- `X | None` types, src-layout, no `sys.path` hacks.
- Comments carry the non-obvious why, an invariant, or a trap — not what the code already says,
  and not history.
- Tests travel with the change.
- `bin/run setup` also writes pw-foundation's generic starter rules for AI assistants into a
  gitignored folder. Where they disagree with these rules, these win: below the CLI the library
  uses pw-foundation for atomic writes alone, and `tests/test_framework_boundary.py` enforces it.

## Recording a golden

Every format claim rests on one deliberate change in Logic and a byte diff against the save
before it. `tools/driver/README.md` has the loop and the traps; `tools/driver/drive.py` performs
one action and one Save As per step, `tools/driver/diff.py` diffs two saves, and
`tools/stage_public.py` files the saves under `tests/corpus/` with a manifest key and the
facts a test may assert. Only saves of a project born in Logic on your own machine go into the
public corpus; a session that holds anyone's music or third-party plug-in state stays out.

## Opening a command on another Logic version

Every writer takes Logic 12.3.1's file format (2513, which 12.4 writes too); most take Logic 13.0's
(2514) as well, and the rest refuse it; the readers run on older saves. A command takes another format when its row in
`src/logicxkit/logic/_capabilities_table.py` names it in `formats`, for example
`formats=(2511, 2513)` for Logic 11.2. A pull request that adds one carries:

- the saves, made in that Logic from a blank project, one change each, staged with
  `tools/stage_public.py` — Logic's own version of the edit the command makes, beside the save
  before it;
- the command's output on a copy of the save before, re-saved in that Logic without a change,
  staged too, with a golden that compares the re-save with the output record by record;
- the row's catch naming those saves by manifest key in backticks, the Logic version and the date.
  `tests/logic/test_format_evidence.py` fails on a row that names a format no public save it
  cites is in; `logic capabilities` and `docs/EVIDENCE.md` then list the format under the row.

One command per pull request. A command may still refuse an operation it cannot do on that format
(an instrument add, for one, needs Logic 12's channel records); the refusal is narrowed, not
removed, by the same evidence.

## Licensing of contributions

logicxkit is Apache-2.0. Under section 5 of that licence, anything you deliberately submit for
inclusion is contributed under the same terms. There is no separate CLA.
