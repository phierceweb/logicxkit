# Documentation

The navigational index for logicxkit. Every doc in the tree is listed here.

This file describes what each doc is for, not what is in it. Two documents own knowledge that
lives outside this directory, and they are listed too — see
[Format references](#format-references) for why they live where they do.

---

## Table of Contents

- [Start here](#start-here)
- [Format references](#format-references)
- [Reference material](#reference-material)
- [Adding a new doc](#adding-a-new-doc)

---

## Start here

| Doc | Read it when |
|---|---|
| [INSTALLATION.md](INSTALLATION.md) | Installing, or pointing the tools at files that are not in the repo |
| [commands.md](commands.md) | Working out which command to use and what rules govern it |
| [CAPABILITIES.md](CAPABILITIES.md) | **Before pointing any writer at a session you care about** |

`CAPABILITIES.md` is generated from `src/logicxkit/logic/_capabilities.py` and enforced by
`tests/logic/test_capabilities.py`. Change a confidence level in the code, never in the doc.

## Format references

None of Logic's formats are documented by Apple. Everything logicxkit knows about them came out
of measurement — one deliberate change per Logic save, then a byte diff against the save
before it. That knowledge is the most valuable thing in the repo, and it lives beside the code
that depends on it so the two move together:

| Doc | Covers |
|---|---|
| [`src/logicxkit/logic/README.md`](../src/logicxkit/logic/README.md) | The `.logicx` project and `.cst` strip formats: the `GAMETSPP` float block, the record container, `karT` track lists, `ivnE` Environment objects, `OCuA` channel blocks, sends, groups, `DisplayState.plist`, and Logic's own settings plist |
| [`src/logicxkit/au/README.md`](../src/logicxkit/au/README.md) | Audio Unit preset and state formats: FabFilter `.ffp` and `.aupreset`, Waves XPst, TR5 chain XML, sonible protobuf, and the headless AU host |

Do not move these into `docs/`. `CLAUDE.md` designates them as the home of format knowledge,
and a format note is only trustworthy while it sits next to the parser it describes.

**Provenance, strongest first: the file, then a person who was there, then the vendor manual
(authoritative for meaning, never for byte layout), then inference.** Mark inference as
inference. `None` beats a guess.

## Reference material

| Doc | Covers |
|---|---|
| [`resources/README.md`](../resources/README.md) | The reference corpus — what it contains, and how the controlled Logic saves are made |
| [`resources/data/README.md`](../resources/data/README.md) | The data root, and how to regenerate each part of it |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | The development loop, house rules, and the evidence standard |
| [`CHANGELOG.md`](../CHANGELOG.md) | What shipped in each release |

Neither the corpus nor the data root ships. Both are Logic-authored or vendor-authored
material that is not ours to redistribute, which is why a fresh clone's goldens all skip.

## Adding a new doc

1. Put user-facing and cross-cutting docs in `docs/`. Put a format reference beside its parser,
   as above.
2. Follow the house structure: H1, a one-sentence purpose, `---`, a table of contents, then
   content. End with an "Adding a new X" section if the thing gets extended.
3. **Add it to the table above.** An index that silently omits a file is worse than no index,
   because readers treat it as complete.
4. Write prescriptively — "use X", "never do Y" — not descriptively.
5. Do not write exhaustive tables of flags, environment variables or commands. They go stale
   on the next edit. State the rule and point at `--help`, `.env.example`, or the generated
   table instead.
