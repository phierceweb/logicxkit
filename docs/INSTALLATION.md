# Installation

How to install logicxkit, what it needs from the machine, and how to point it at files that
are not in the repo.

---

## Table of Contents

- [Two ways to install](#two-ways-to-install)
- [What the machine must have](#what-the-machine-must-have)
- [Configuration](#configuration)
- [The three things that live outside the repo](#the-three-things-that-live-outside-the-repo)
- [What a green test run does and does not prove](#what-a-green-test-run-does-and-does-not-prove)
- [Adding a new environment variable](#adding-a-new-environment-variable)

---

## Two ways to install

**To use it**, install from PyPI. This gives you the `logicxkit` command:

```bash
pip install logicxkit
logicxkit logic project ~/Music/Logic/Song.logicx
```

**To work on it**, clone it and let `bin/run` build the venv:

```bash
git clone https://github.com/phierceweb/logicxkit.git
cd logicxkit
bin/run setup          # .venv + editable install + dev extra
bin/run pytest
bin/run lint
```

Do not create the venv by hand. `bin/run` is the entry point for every development task —
`setup | pytest | python | pip | ruff | lint | logic | au` — and it sources a local `.env`
before running, so commands work without exported variables. `bin/run logic …` and
`logicxkit logic …` invoke the same CLI.

`bin/run setup rig` additionally installs the `rig` extra, which only `tests/rig` needs. Do not
add it to a normal setup: nothing in `src/` imports it, and the tests that use it self-skip
without a physical console's scene file.

## What the machine must have

- **macOS.** There is no Linux or Windows path, and one is not planned. The tools read and
  write Logic Pro's own file formats, the native helpers run through the `swift` toolchain, and
  `logic ocr` uses Apple Vision.
- **Python 3.12 or newer.** `bin/run setup` builds the venv with `python3.12`; set
  `PYTHON=python3.13` (or any 3.12+) to choose another interpreter.
- **Logic Pro**, to confirm anything. A file that opens is not proof a write was correct — see
  [CAPABILITIES.md](CAPABILITIES.md).
- **A Swift toolchain**, optionally. Without `swift` on `PATH`, `au` falls back to the static
  parameter tables and `logic ocr` is unavailable. Everything else works.

## Configuration

Every setting is an environment variable, every one is optional, and every one has a working
default. Copy `.env.example` to `.env` and edit what you need; `bin/run` sources it.

Treat `.env.example` as the authoritative list — it carries each variable's default and the
consequence of leaving it unset. Do not maintain a second copy of that list here or in the
README; two lists drift.

The variables fall into three groups:

- **Where Logic keeps its own files.** Defaults point at Logic's real locations. Override them
  to read from a staged copy instead of the live library.
- **Where your rig's specs and reference files live.** These point outside the repo (see below).
- **Test behaviour.** Most usefully `LOGICXKIT_REQUIRE_GOLDENS=1`, which turns a missing
  golden into a failure instead of a skip.

## The three things that live outside the repo

None of these ship, and none of them can. Each is Logic-authored or vendor-authored material
that is not ours to redistribute.

**The reference corpus** (`LOGICXKIT_RESOURCES`) — Logic's own controlled saves, project
templates, finished sessions and a channel-strip library snapshot. The goldens read it through
a manifest that maps neutral keys to files, so no test names a real song.
[`resources/README.md`](../resources/README.md) describes its shape and how the controlled
saves are made.

**The data root** (`LOGICXKIT_DATA`) — record templates Logic wrote, plugin-slot donor records,
and AU parameter tables dumped from installed plugins. The tools load these at runtime.
[`resources/data/README.md`](../resources/data/README.md) says how to regenerate each part
(`logic donors`, `logic recdiff`, `au params`).

**Your rig's specs** — the real chain, preset and mapping specs. No variable points at them:
they are files you hand to `build`, `chains` and `apply-template --map`. Keep them in a private
repo so they are versioned and backed up. Do not put real paths, names or values in
`config/example-*.json`: those are the neutral defaults a stranger gets.

`LOGICXKIT_RIG_CONFIG` is test-only despite the name: `tests/rig` reads
`<root>/x32/preflight.json` for one console-preflight golden and skips without it.

## What a green test run does and does not prove

Tests that read real Logic files skip when those files are absent, and they are absent in every
clone. **A green suite on a fresh clone proves the synthetic layer only.**

Every run ends with a line naming how much actually ran:

```
goldens: 0 of 73 keys found; none on this machine
```

Read that line before trusting a run. Set `LOGICXKIT_REQUIRE_GOLDENS=1` to make a missing
golden fail instead of skip. CI is subject to the same limit — it runs on a macOS runner with
no corpus staged, so a green check there is not a substitute for a run on a machine that has
the files.

## Adding a new environment variable

1. Read it through `utils/env.py`, never `os.environ` directly — the helpers apply the
   default and the `~` expansion consistently.
2. Give it a working default. A variable that must be set to make the tool run is a bug.
3. Document it in `.env.example`, in the group it belongs to, with its default and what
   happens when it is absent. That file is the canonical list.
4. If it points at something outside the repo, say so in the section above and explain why
   the target cannot ship.
