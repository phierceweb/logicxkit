# Contributing

## Requirements

macOS with Logic Pro, Python 3.12, and a `swift` toolchain. There is no Linux path. CI runs
lint and the suite on a macOS runner with the public corpus fetched, so the synthetic layer and
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

Tests that read real Logic files skip when those files are absent. Run `bin/run fetch-corpus`
once to get the public corpus (Logic's saves of a blank project); the keys only the owner's
corpus has — real sessions and templates — skip everywhere else, and a change to one of those
readers needs the owner to run the suite. Every run ends with a `goldens: N of M keys found`
line; without the corpus it reads `0 of M` and the suite is still green. Set
`LOGICXKIT_REQUIRE_GOLDENS=1` to make a missing golden fail instead. See `resources/README.md`
and `resources/data/README.md` for what the corpora are and how to build your own.

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

## Licensing of contributions

logicxkit is Apache-2.0. Under section 5 of that licence, anything you deliberately submit for
inclusion is contributed under the same terms. There is no separate CLA.
