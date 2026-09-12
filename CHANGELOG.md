# Changelog

Notable changes to logicxkit. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

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
