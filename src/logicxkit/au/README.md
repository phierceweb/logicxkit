# logicxkit.au — Audio Unit preset/state decoder (read-only)

Decodes 3rd-party plugin settings wherever they live: standalone preset files
(`.ffp`, `.aupreset`, `.pst`) and the AU states **embedded in `.cst` channel
strips and `.logicx` ProjectData** — the layer `logicxkit.logic` reports as
"preset name only". Everything here is read-only.

macOS only: the AU host loads the plugins you actually have installed, through
Audio Unit APIs and a `swift` toolchain. The static paths below parse files and
need neither.

## The two decode paths

1. **AU host (preferred)** — `src/logicxkit/native/auprobe.swift` instantiates
   the installed Audio Unit headless, restores the state via
   `kAudioUnitProperty_ClassInfo`, and dumps every parameter: real name, unit,
   min/max/default, current value, and the plugin's own display string
   (`ParameterStringFromValue` — "2.00:1", "101.62 Hz", "24 dB/oct"). Works for
   any AU that instantiates headless; needs the `swift` toolchain (JIT, no
   build step).
2. **Static tables** — parse the file/blob directly and name values via the
   AU parameter tables under the data root (`LOGICXKIT_DATA`), one
   `au/<Manu>_<Subtype>.json` per plugin, generated from the installed AUs via
   `auprobe list`; regenerate on plugin updates. The tables are vendor-authored
   data and are not shipped — `resources/data/README.md` says how to make them.
   Used when the host is unavailable (`--no-host`) or the AU is denylisted.

Per-state ladder in `au strip`: **NDSP** → the `juce` JUCE decoders ·
**Waves** → static XPst · everything else → AU host, falling back to tables.

## Format intelligence (verified against real files)

- **FabFilter `.ffp`** — 4CC magic (`FC2p`, `FQ4p`, `FPMb`, `FPLr`, …) + u32 LE
  version + u32 LE count + count × float32 LE. **Param position i == AU
  parameter id i** for the same plugin, so one table names both families.
- **`.aupreset` / embedded ClassInfo plists** — identity fourccs
  (`type`/`subtype`/`manufacturer`) + preset `name` + state. Classic plugins
  (Pro-C 2, Pro-MB, iZotope, Ampeg) use the AU-standard `data` key: 12B header
  (8 reserved + u32 BE pair count) + (u32 BE id, f32 BE value) pairs. Newer
  FabFilter (Pro-Q 4) uses a `FabFilterPluginState` blob (`FFBS`, 24 bands ×
  24 floats + 75 globals) — opaque statically, fully readable via the host.
- **Waves `Waves_XPst`** — binary head + `<PresetChunkXMLTree>` XML whose
  `RealWorld` parameter text is positional real-unit values (`*` = unset).
  WaveShell AUs crash headless (objc class collision), so XPst is the only
  Waves path.
- **sonible `jucePluginState`** — protobuf, no published schema. Decoded via a
  schema-less wire walk (`services/sonible.py`): message 3 = the parameter
  block, values legible but keyed by field number, not name (the AU crashes
  headless, so no name source). Naming needs a one-knob-at-a-time calibration
  against the UI. The big trailing field is learned/NN state, summarized.
- **TR5 Suite** — the AU exposes only 16 shallow params; the real state is a
  JUCE ValueTree whose binary `Chain` prop holds a plain `<Session>` XML:
  A/B/C/D snapshots, module GUIDs + bypass, and every module parameter as
  named attributes (`services/tr5.py` decodes it, incl. the source preset path).
- **Kemper `.rigpack` / `.presetpack`** — bare SQLite, but only store-catalog
  stubs (descriptions/branding), no rig payloads; rigs land in the normal
  library DBs on import. Not worth tooling.

## Usage

```bash
bin/run au preset "~/Library/Audio/Presets/FabFilter/Pro-C 2/Drum Bus.aupreset"
bin/run au strip  "…/Channel Strip Settings/Track/<library>/Drums/Kick In.cst"
bin/run au strip  "…/Song.logicx"          # every 3rd-party state, per mixer channel
bin/run au params aumf FQ4p FabF           # live parameter table (needs swift)
bin/run au tables                          # list the tables in the data root
# --all shows unchanged params too; --json for structured output; --no-host forces static
```

## Latency

`src/logicxkit/native/aulatency.swift <type> <subtype> <manu> [sampleRate]` reports an
installed AU's `kAudioUnitProperty_LatencySamples` after initialisation at that rate — the
figure a host compensates for, so what a player feels while monitoring. Run it with `swift`
directly; there is no CLI wrapper.

## Denylist

`Soni` (sonible) and `ksWV` (Waves) crash when instantiated without a UI host —
`is_headless_safe()` routes them to the static paths. Extend the set in
`services/host.py` if another AU takes the process down.
