"""The rows `_capabilities.py` serves: what each command is trusted for, and the evidence."""

from __future__ import annotations

from ._capabilities_content import CONTENT_ROWS
from ._capability import Capability


CAPABILITIES = (
    Capability(("project", "manifest", "diff", "decode", "neural", "recdiff"), "—",
               "yes, read-only",
               "`project`'s \"channels with inserts\" counts `.cst` labels, not loaded plugins"),
    Capability(("plugins",), "—", "yes, read-only",
               "Names every slot's plug-in — Apple's by type id, a third-party one by the AU component "
               "identity in its embedded preset — and checks the third-party ones against `auval -a`. "
               "A missing verdict has not yet been compared with Logic's own missing-plug-in dialog. A component whose bundle has gone bad stays in the "
               "registry, and Logic itself opened such a project without an alert (FabFilter Pro-C 2 "
               "disabled by hand, 2026-09-16); `--validate` opens each listed component with auval -v "
               "and reports it broken"),
    *CONTENT_ROWS,
    Capability(("stacks",), "CONFIRMED", "read-only until `--move`, which needs `--out`",
               "Reads folder stacks and the arrange list, nested stacks included (the member byte is "
               "the depth). `--move TRACK:STACK --out DIR` writes a copy whose rows match Logic's own drag "
               "saves (2026-09-04; into and out of a nested stack 2026-09-16, the `nest-*` goldens, and "
               "Logic re-saved a nested move as written, `nest-ours-resave-logic`), through the same "
               "integrity gate as every other writer"),
    Capability(("levels",), "CONFIRMED", "read-only until `--to`, which needs `--out`",
               "Reads fader and pan. `--to OTHER --out DIR` copies them onto another project "
               "through the integrity gate; a copy written onto a blank project came back from "
               "Logic's re-save with every fader and pan as written (2026-09-12)"),
    Capability(("build", "verify", "pst", "donors", "image", "ocr"), "—",
               "never touches a project; `build`/`pst` reach Logic's own library only with "
               "`--install`",
               "A relative `output_dir` resolves under `~/Music/Audio Music Apps` — Logic's own "
               "library — and writing there is refused without `--install`. `--overwrite` is "
               "separately required to replace a file. Elsewhere: `output_root` (or `strip_root` "
               "/ `LOGICXKIT_STRIP_ROOT`, which moves `build`'s sources too), or an absolute "
               "`output_dir`"),
    Capability(("chains",), "CONFIRMED", "yes, after reading `--plan`",
               "Replaces a channel's whole chain. `--plan` names every chain it would "
               "take off; `--strict` refuses on shape drift. The real tracking chains written "
               "onto the tracking template came back from Logic's re-save with all 46 "
               "channels' chains identical (2026-09-12). A chain keyed by a channel name puts declared "
               "donors on the Stereo Out with parameters named as measured; the example mastering chain "
               "opened in Logic with every value shown as written and re-saved intact "
               "(2026-09-16, `master-ours-resave-logic`)"),
    Capability(("retrack",), "CONFIRMED", "yes",
               "Changes a label, never a chain; basename-only library match. `--channel` repoints one "
               "channel at a time, so channels sharing a name can part ways: seven repointed on a "
               "tracking template showed on the Setting buttons and survived Logic's re-save "
               "byte for byte (2026-09-06)"),
    Capability(("strip-save",), "CONFIRMED", "yes",
               "A path under Logic's own library is refused without `--install` (2026-09-27)"),
    Capability(("send",), "CONFIRMED", "yes",
               "Writes to buses the caller declared missing; no cross-project bus remap. A project "
               "with no send to clone gets Logic's own from a blank project (packaged), and Logic "
               "re-saved one such add byte for byte (2026-09-13). A third send in a project whose slots "
               "start at key 2 moves the project to base 4 first, as Logic's own re-save does; left at 2 it "
               "shares slot 1's key and Logic drops the plug-in there (`legacy-migrate-fixed-*`, 2026-09-24)"),
    Capability(("stack-create",), "CONFIRMED", "on a folder stack only",
               "Summing stacks unimplemented. A session with no stack patterns on Logic's own first "
               "stack (packaged); Logic re-saved two such stacks with the header, strip and members "
               "as written (2026-09-13)"),
    Capability(("add-track",), "CONFIRMED", "yes",
               "Audio, instrument and aux adds; every add in one migration survived Logic's own re-save "
               "row for row (2026-09-04). With no audio stub free a fresh channel is made where "
               "Logic makes one, and Logic's re-save kept three such byte for byte (2026-09-06). "
               "Keeps the song container's row count, the region placements and the registry's "
               "slot entries in step. `--stereo` binds the pair channel `Input N-(N+1)`, as Logic's own "
               "New Tracks did with an interface attached (2026-09-17); inside a nested stack the row "
               "takes the depth of its place. A fresh channel record goes after the highest owner below "
               "it and carries the project's slot base and shown-slot count; an instrument channel's "
               "default records are keyed to the project's slot and property bases. Logic re-saved ten "
               "chained adds with every plug-in and track (`addtrack-fresh-*`, 2026-09-23); a record out "
               "of owner order lost every plug-in (`addtrack-order-*`), and one instrument channel keyed "
               "for another base made a migration Logic would not open (`legacy-migrate-keyed-mine`). "
               "`--instrument --stereo` writes the width bytes Logic's own stereo instrument channel "
               "carries (`sessionplayer-track-logic`); a track added that way is not yet opened in Logic"),
    Capability(("reorder",), "CONFIRMED", "yes",
               "Moves a row among its siblings; a stack header moves with its members, and that "
               "move reproduces Logic's own drag of a header byte for byte (2026-09-12). A plain-row "
               "move came back from Logic's re-save in the written order, every row byte held but "
               "the moved row's selection mark, which Logic clears on load (2026-09-13)"),
    Capability(("route",), "CONFIRMED", "yes",
               "Sets a channel's input or output by label; an output rerouted to a bus came back "
               "from Logic's re-save with the routing intact and the channel record byte for byte "
               "(2026-09-13)"),
    Capability(("arrangement",), "CONFIRMED", "yes, on a copy",
               "Reads matched Logic's display on every project tested; a rename plus a resize "
               "survived Logic's re-save byte for byte (2026-09-06), `--add` reproduces Logic's own "
               "add record for record and survived its re-save, and a move plus a delete came back "
               "from Logic's re-save event for event. On a song with no arrangement track `--add` "
               "makes the track as Logic's first section does, and Logic re-saved one with the "
               "section intact (2026-09-13)"),
    Capability(("signature",), "CONFIRMED", "yes, on a copy",
               "Reads the signature track and the LCD's division on every project tested. `--time` at "
               "bar 1, `--key` (major and minor) and `--division` reproduce Logic's own edits byte for "
               "byte (2026-09-06/07); `--key-at` and `--time-at` add changes after bar 1 and survived "
               "Logic's re-save byte for byte. `--time` at bar 1 refuses songs with later meter "
               "changes"),
    Capability(("toolbar",), "CONFIRMED", "yes, on a copy",
               "Every button's id measured on seven saves (2026-09-07) and written in Logic's order; "
               "Logic re-saved one of ours unchanged. `--row` shows or hides the toolbar row"),
    Capability(("modes",), "CONFIRMED", "yes, on a copy",
               "Cycle, Replace, Autopunch, Metronome Click, Use Musical Grid and the count-in length in "
               "the song record, pinned on Logic's saves of one press apiece (2026-09-08); a copy "
               "written with four of them came up in Logic so and was re-saved intact. Solo is read "
               "but not copied — Logic clears it on load. "
               "`apply-template` copies them"),
    Capability(("metronome",), "CONFIRMED", "yes, on a copy",
               "The Metronome and Recording panes: nine boxes, the pre-roll time, the four Klopfgeist "
               "rows and the four MIDI click rows in the click object, pinned on Logic's saves of one "
               "change apiece (2026-09-08); a copy with six boxes and the pre-roll written, and one "
               "with changed rows copied in, each came up in Logic's "
               "pane as written and re-saved intact. `apply-template` copies them"),
    Capability(("width",), "CONFIRMED", "yes, on a copy",
               "A channel's width and the build of every plug-in on it, measured across real sessions "
               "and a Logic-written stereo bus; two auxes made stereo on two templates came back "
               "stereo from Logic's re-save, slots included (2026-09-08)"),
    Capability(("tempo",), "CONFIRMED", "yes, on a copy",
               "Reads matched every project's LCD, ramps and steps included; `--set 180` showed 180 on "
               "Logic's LCD and survived its re-save (2026-09-06); "
               "`--add` writes the bare step Logic's Tempo List makes and survived its re-save; "
               "`--ramp` writes the event run Logic's Tempo Operations curve makes and survived "
               "its re-save event for event. Hand-drawn curves (the 0xb4 line) are read only"),
    Capability(("rename", "colour", "hide"), "CONFIRMED", "yes",
               "Applied across three legacy migrations Logic re-saved unchanged (2026-09-04); a "
               "rename marks the name as the user's, else the arrange shows the strip setting's name"),
    Capability(("settings",), "CONFIRMED", "yes; `--set` writes a copy",
               "A slot's settings in its family's vocabulary through the plug-in's map "
               "(`data/translate`): a third-party's from its AU state's id/value pairs (Pro-C 2, "
               "with the normalized ratio, attack and release read off curves the AU host sampled) or "
               "its vendor blob (sonible's smart:comp 2 and smart:gate, real units in their protobuf "
               "block, `sonible-*`), its FabFilter binary state by band (Pro-Q 4) or its zlib JSON state "
               "(iZotope's Neutron 5, real units by module: a compressor, a gate and an EQ at once, a line "
               "per family, `neutron-*`), one of Logic's own from its measured table (Compressor, Noise Gate, "
               "Channel EQ, Multipressor), a multiband's as bands by frequency range (Pro-MB, Multipressor). "
               "A slot without a map says so. `--set` writes the same names into one slot: one of Logic's "
               "own through its table, each value held to its measured slider's ends and put on the nearer sampled "
               "position — the knob rows are sampled at every unit, the dB rows every few, where a value between "
               "samples is written as given with a note (`snap-*`), "
               "FabFilter's pairs or binary state patched in place inside the record's plist at the same "
               "length (sonible's protobuf and iZotope's JSON are read, not written); an EQ takes "
               "`band N=<shape> <freq> …`, rewriting that band and no other. `--at` is the mixer slot. "
               "Three items written into a Pro-C 2 came back from Logic's re-save shown as written, the "
               "other nine and the side chain untouched (`write-proc-*`, 2026-09-23)"),
    Capability(("transplant",), "CONFIRMED", "yes, within the channel's key range",
               "Each slot's side chain follows its source's name into the destination (payload "
               "+144/+145, the `sidechain-*` goldens) or is cleared with a report line. "
               "Refuses a move that overruns the slot key range — which deletes the channel's "
               "`.cst` reference record, a loss `validate_project` cannot see — and one that "
               "crosses a record class version; `--force` writes anyway. Clones take the "
               "destination's own slot keys (2 in projects whose slots start there). Two native "
               "slots moved between blank-born projects came back from Logic's re-save byte for "
               "byte (2026-09-13). One source fanned out to several channels gives each copy its "
               "own instance id, measured from a second instance of that plug-in in the source; "
               "without one the fan-out is refused. So is a third-party slot onto an audio channel of the "
               "other width (Logic's own are re-stamped; an instrument channel's width byte says "
               "nothing about its plug-in). `--stack NAME=SRC` targets a folder stack's "
               "members. One Auto-Align 2 fanned out onto a tracking song's seventeen drum channels "
               "came back from Logic's re-save with every slot byte for byte, the seventeen "
               "stamped ids included (2026-09-21, `transplant-fanout-*`). The destination's plug-in "
               "automation lanes are left as they are"),
    Capability(("bypass",), "CONFIRMED", "yes",
               "Flips the bypass bit on the slots a channel already carries; adds nothing and "
               "removes nothing. Two bypassed slots came back from Logic's re-save with the bits "
               "as written (2026-09-13)"),
    Capability(("add-plugin",), "CONFIRMED", "yes, on a copy",
               "A library plug-in into mixer slot N (from 1, empty slots counted — the insert automation "
               "names), the end without: an empty slot takes it where it is, an occupied one moves it "
               "and every later slot down a key with their automation lanes (`slots-front-*`: Logic's "
               "Event List named every lane's plug-in, 2026-09-23). An instrument channel's slot 1 is its "
               "instrument; an effect is refused there and an append lands at 2 (`slots-inst-*`). "
               "`--set` on one of Logic's own holds a value to its slider's measured ends with a note and "
               "puts it on the slider's grid. The donor is stamped as `transplant` "
               "stamps one (owner, key, index, width for Logic's own, id, bypass, the side chain "
               "`--side-chain NAME` asks for by name, none otherwise — Logic showed a written one "
               "in the plug-in header and re-saved it as written, `sidechain-ours-resave-logic`), "
               "the slots from "
               "that position on move down a key, header key and +6 index both, and the "
               "channel's Smart Control mappings move with them (without that Logic reset the "
               "channel). A chain reaching the two keys under the reference record moves the "
               "reference, the records under it and the archives above it up on every channel, "
               "and every channel record's shown-slot count follows. Logic's own appends on the "
               "`master-track-*` saves are reproduced slot for slot and the channel record byte "
               "for byte; Logic re-saved a mid-chain insert and an append with every slot, "
               "archive and channel record as written but a per-plug-in token on the new slot "
               "(2026-09-21, `addplugin-mid-*`, `addplugin-end-*`), and Auto-Align 2 into slot 1 "
               "of a tracked song's seventeen drum channels in front of their chains, the range "
               "grown by the project's own headroom (`addplugin-front-*`). Third-party plug-ins "
               "come from `logic donors PROJECT [--as NAME] [--refresh]`, one donor per width. A side "
               "chain may also be an input of the interface or an instrument track "
               "(`sidechain-input2-logic`, `sidechain-inst-*`)"),
    Capability(("tracking-chains",), "CONFIRMED", "yes, on a copy",
               "Every third-party slot with a translation map replaced by Logic's own of its family with the "
               "settings carried (the `replace-plugin --translate` path; Neutron 5 one native per live element, "
               "the extras added after the first), a third-party without a map removed, the natives that carry "
               "lookahead bypassed, one it made from a third-party too (a Pro-MB's Multipressor, `mb-promb`). "
               "Logic-confirmed 2026-09-24 (`trk-*`): a Neutron 5 read back as the Channel "
               "EQ and Compressor it became, both Controls views on the carried values, and a re-save kept every "
               "swap and every bypass on two channels and the output. An instrument channel keeps its "
               "instrument, whatever it is (2026-09-27)"),
    Capability(("swap-plugin",), "CONFIRMED", "yes, on a copy",
               "Every slot holding one plug-in replaced by another across the project, each through the "
               "`replace-plugin --translate` path: settings through the family vocabulary, side chains and "
               "automation lanes carried, a slot whose settings cannot cross left as it is with the reason; a "
               "`--from` no slot holds, or one naming the `--to` plug-in, refused before a copy is made. "
               "The replacement and the carry are the Logic-confirmed ones (`slots-replace4-*`, `translate-*`, "
               "`auto-lanes-*`); the loop itself Logic-confirmed on two smart:comp 2 slots into Compressors, "
               "both channels' Controls views reading the carried values (`swap-*`, 2026-09-24), and again "
               "with the packaged donors only (`swap-packaged-*`, 2026-09-25): the same carried values, and "
               "Auto Release reading 1 — the packaged `#default` donor's — where the data root's `Drum Mix` "
               "donor had read 0. The 2026-09-24 copies, and the `translate-*` ones, took a Compressor donor "
               "harvested from a real project — the packaged donor's layout and length, its preset name, "
               "values and instance id aside"),
    Capability(("remove-plugin", "replace-plugin"), "CONFIRMED", "yes, on a copy",
               "The plug-in in mixer slot N out of a channel, the slots after it moved up a key with their "
               "automation lanes and Smart Control mappings, the removed slot's dropped (`slots-remove-*`, "
               "Logic's Event List named the rest on their own plug-ins, 2026-09-23); an instrument "
               "channel's instrument leaves its slot empty. "
               "`replace-plugin` is that removal and an `add-plugin` at the same slot. Logic "
               "re-saved both with every slot as written, the replace's archives and channel "
               "record too (2026-09-22, `addplugin-remove-*`, `addplugin-replace-*`); the key "
               "range is left for Logic to re-lay out on save. "
               "`replace-plugin --translate` carries the old slot's settings through the family "
               "vocabulary: a Pro-C 2 dialled in Logic to -30 dB / 3.06:1 / 10.72 ms / 115 ms / 6 dB "
               "knee / +3 dB / 80 % went into a Compressor that Logic showed as -30 dB, 3.1:1, 10.5 ms, "
               "110 ms, +3 dB, knee 0.1, 80 % and kept so on re-save (`translate-*`, 2026-09-22) — its "
               "own grids, which the map rounds to; attack and release sit on their knobs' positions and "
               "are written as read (a smart:comp 2 into a Compressor and a smart:gate into a Noise Gate "
               "came back the same way, `translate-sonible-resave-logic`). "
               "Knee is approximate (dB/72); Pro-C 2's look-ahead, auto gain, range, hold and style have no "
               "analogue and are reported, not guessed, as is the Compressor's circuit the other way; the "
               "target keeps its own. An EQ crosses as bands: a Pro-Q 4 dialled "
               "to nine bands went into a Channel EQ that Logic showed with the low cut, four bells, "
               "high shelf and high cut as planned and re-saved as written but for its knobs' own "
               "frequency and Q positions (250.01 Hz to 250, Q 2.43 to 2.50; `translate-proq-*`, "
               "2026-09-22); the notch and the fifth bell were reported, not placed. The slot's automation "
               "lanes follow the translation (`automation_remap`): a Pro-C 2's threshold, ratio and attack lanes "
               "landed on the Compressor's indices in its slider units and Logic's Event List listed them by "
               "name, its Controls view following them in Read — -30, -24, -12 dB, 3.9:1 and 2.7:1, 16 ms "
               "(`auto-lanes-*`, 2026-09-23); a lookahead lane with no analogue was dropped with a line. "
               "An EQ's or a multiband's lanes cross by band, onto the band the plan placed each in: a "
               "Pro-Q 4's low-cut on/off, bell gain and bell frequency lanes reached the Channel EQ's Low "
               "Cut, Peak 1 and Peak 3 and read 1/0/1, -4/0/+6 dB and 1000/2000 Hz, a Pro-MB's threshold, "
               "ratio and level lanes the Multipressor's band 1 and 4 and read -20/-12/-30 dB, 3.675 and "
               "1.977 (its ratio knob's grid), +1 dB (`auto-eqlanes-*`, `auto-mblanes-*`, 2026-09-23); "
               "the four natives' sliders are measured for it. `--keep-automation` leaves the lanes; with "
               "neither they are dropped with a line, and so is the side chain. The other way "
               "round, a FabFilter replacement takes the plan into its own state: Logic's Compressor "
               "into a Pro-C 2 that Logic showed as -30 dB, 3.10:1, 10.49 ms, 109.8 ms, +7.20 dB knee, "
               "+3 dB, 80 % (attack and release land between the sampled curve's points; "
               "`write-comp2proc-*`), and a Channel EQ into a Pro-Q 4 whose seven bands Logic showed as "
               "written, the off low shelf left out (`write-eq2proq-*`, 2026-09-23); what the donor keeps "
               "of its own is reported. A multiband compressor crosses as bands by frequency range: a "
               "Pro-MB's three bands went into a Multipressor Logic showed as written but for its ratio "
               "and crossover knobs (4.0 as 3.675, 4 kHz as 3.9), and that re-save came back into a "
               "Pro-MB as written (`mb-*`, 2026-09-23). A stretch no source band covers is a live band "
               "at ratio 1, since an off band's range goes to the next live one (`mb-neutral-*`); Pro-MB's "
               "range limit and percentage times, and a Multipressor band's expander beside its "
               "compressor, are reported, not guessed"),
    Capability(("clear-slots",), "CONFIRMED", "yes",
               "Drops the records and their key flags; the `.cst` reference label stays. Opened in "
               "Logic with the inserts empty (2026-09-04); without the flag sync Logic refuses the file"),
    Capability(("header",), "CONFIRMED", "yes",
               "Every bit measured on seventeen single-toggle saves; a written set opened in Logic "
               "showing all sixteen components as set"),
    Capability(("prefs",), "CONFIRMED", "yes, with Logic closed",
               "Logic's own settings: 150 controls across every Settings pane pinned by single "
               "changes (General > Editing 2026-09-05, the rest 2026-09-08); a box written with Logic "
               "closed came up that way on relaunch. Not carried: Audio > Devices, Plug-in Delay "
               "Compensation, Control Surfaces (Logic's own file). Writes go through `defaults`, are "
               "refused while Logic runs, and take a backup first"),
    Capability(("controlbar",), "CONFIRMED", "yes",
               "Every id measured on fifty single-toggle saves (2026-09-04); a bar copied whole "
               "onto another project came up in Logic with that set. Both display-state files written"),
    Capability(("group",), "CONFIRMED", "yes",
               "Every box and the member events measured on twenty-eight single-change saves "
               "(2026-09-05); the writer reproduces six of Logic's saves byte for byte, and a "
               "migrated song with two groups opened in Logic showing them and re-saved with the "
               "identical group records and row list. Leaving a group: Logic's own No Group on a member (2026-09-12) matches the composed leave outside the selection bytes"),
    Capability(("apply-template",), "CONFIRMED", "yes, with a map across lineages",
               "Same lineage pairs by object id; across lineages `--map FILE` says how tracks pair "
               "(`--propose-map` drafts it, `(none)` leaves a track alone). Legacy songs "
               "migrated onto a mixing template opened in Logic and re-saved with the identical "
               "row list (2026-09-04). Never removes a send; inputs past the session's count are made "
               "before planning (Logic re-saved six); the template's groups are made and joined by "
               "name (2026-09-05, confirmed on the same song). Legacy bus returns the template "
               "duplicates are silenced; `-` lines in the map leave template tracks out. A song "
               "whose slots start at key 2 beside three sends is moved to base 4 in the same pass, as Logic's own re-save does; a project born at base 2 without that collision is left there "
               "(`logic/README.md`: slot keys). Also carries the track power state, icons, "
               "header components and the control bar; not the project's own tempo, meter or key, "
               "which stay the song's. The current tracking template applied onto a tracked song "
               "(2026-09-16) re-saved in Logic with the identical row list and strip references, "
               "two of them repointed per channel"),
    Capability(("migrate",), "CONFIRMED", "yes, on a renamed copy; across lineages only with `--map` or `--force`",
               "Composes `propose-map` (or `--map FILE`) with `apply-template`'s step into "
               "`CLAUDE migrated - <song>.logicx`: the ops are apply-template's CONFIRMED writers, "
               "A session of the template's lineage "
               "pairs by object id and the draft is not applied. `--verify` drives Logic Pro — opens "
               "the copy, Save As through `tools/driver`, closes without saving — and compares the "
               "row lists ignoring only the flag word; it runs from a checkout on macOS with Logic "
               "installed and has not yet been run against Logic. Logic re-saved a migrated legacy session "
               "with every row and plug-in as written (2026-09-24, `legacy-migrate-fixed-*`)"),
)
