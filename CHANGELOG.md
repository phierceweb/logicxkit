# Changelog

Notable changes to logicxkit. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

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
