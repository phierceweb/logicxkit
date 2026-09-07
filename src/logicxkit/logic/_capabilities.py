"""What each command is trusted for, declared next to the code rather than in prose.

`docs/CAPABILITIES.md` is generated from this table, and `tests/logic/test_capabilities.py`
fails when the two disagree or when a subcommand has no entry, so "can I point this at a real
song?" is answered by one command rather than by reading the code.

Raising a level needs evidence, and the levels say what evidence:

    CONFIRMED  output was opened in Logic and the change was there, and the save proving it
               is staged under resources/, which the tools never write
    CLAIMED    a doc says it was confirmed, but the save is gone or the code changed since
    DERIVED    byte layout reasoned from reads and diffs; never opened in Logic
    BROKEN     has a defect reproduced on a real Logic project

The saves themselves are Logic-authored project files and are not redistributable, so a clone
carries none of them; `resources/README.md` says how to make your own. Producing any of that
evidence needs Logic Pro on macOS.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from ..utils.env import env_str

LEVELS = ("CONFIRMED", "CLAIMED", "DERIVED", "BROKEN", "—")


@dataclass(frozen=True)
class Capability:
    commands: tuple[str, ...]
    level: str
    safe: str
    catch: str = ""


CAPABILITIES = (
    Capability(("project", "manifest", "diff", "decode", "neural", "recdiff"), "—",
               "yes, read-only",
               "`project`'s \"channels with inserts\" counts `.cst` labels, not loaded plugins"),
    Capability(("stacks",), "CONFIRMED", "read-only until `--move`, which needs `--out`",
               "Reads folder stacks and the arrange list. `--move TRACK:STACK --out DIR` writes "
               "a copy whose rows match Logic's own drag saves (2026-09-04). It writes directly "
               "rather than through `_edit.edit_copy`, so `integrity.py` does NOT gate it — open "
               "the result in Logic"),
    Capability(("levels",), "DERIVED", "read-only until `--to`, which needs `--out`",
               "Reads fader and pan. `--to OTHER --out DIR` copies them onto another project; no "
               "Logic-confirmed artifact stands behind that write, and like `stacks --move` it "
               "bypasses `integrity.py` — open the result in Logic"),
    Capability(("build", "verify", "pst", "donors", "image", "ocr"), "—",
               "never touches a project; `build`/`pst` reach Logic's own library only with "
               "`--install`",
               "A relative `output_dir` resolves under `~/Music/Audio Music Apps` — Logic's own "
               "library — and writing there is refused without `--install`. `--overwrite` is "
               "separately required to replace a file. Elsewhere: `output_root` (or `strip_root` "
               "/ `LOGICXKIT_STRIP_ROOT`, which moves `build`'s sources too), or an absolute "
               "`output_dir`"),
    Capability(("chains",), "CLAIMED", "yes, after reading `--plan`",
               "Replaces a channel's whole chain. `--plan` names every chain it would "
               "take off; `--strict` refuses on shape drift"),
    Capability(("retrack",), "CONFIRMED", "yes",
               "Changes a label, never a chain; basename-only library match. `--channel` repoints one "
               "channel at a time, so channels sharing a name can part ways: seven repointed on a "
               "tracking template showed on the Setting buttons and survived Logic's re-save "
               "byte for byte (2026-09-06)"),
    Capability(("strip-save",), "CONFIRMED", "yes"),
    Capability(("send",), "CONFIRMED", "yes",
               "Writes to buses the caller declared missing; no cross-project bus remap"),
    Capability(("stack-create",), "CONFIRMED", "on a folder stack only",
               "Summing stacks unimplemented"),
    Capability(("add-track",), "CONFIRMED", "yes",
               "Audio, instrument and aux adds; 46 in one migration survived Logic's own re-save "
               "row for row (2026-09-04). With no audio stub free a fresh channel is made where "
               "Logic makes one, and Logic's re-save kept three such byte for byte (2026-09-06). "
               "Keeps the song container's row count, the region placements and the registry's "
               "slot entries in step"),
    Capability(("reorder", "route"), "DERIVED", "with care"),
    Capability(("arrangement",), "CONFIRMED", "yes, on a copy",
               "Reads matched Logic's display on every project tested; a rename plus a resize "
               "survived Logic's re-save byte for byte (2026-09-06), `--add` reproduces Logic's own "
               "add record for record and survived its re-save, and a move plus a delete came back "
               "from Logic's re-save event for event"),
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
               "A channel's width and the build of every plug-in on it, measured across ten sessions "
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
    Capability(("transplant",), "DERIVED", "yes, within the channel's key range",
               "Refuses a move that overruns the slot key range — which deletes the channel's "
               "`.cst` reference record, a loss `validate_project` cannot see — and one that "
               "crosses a record class version; `--force` writes anyway. Clones take the "
               "destination's own slot keys (2 in pre-11.2 projects)"),
    Capability(("bypass",), "DERIVED", "yes",
               "Flips the bypass bit on the slots a channel already carries; adds nothing and "
               "removes nothing"),
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
               "identical group records and row list. Leaving a group is composed, not measured"),
    Capability(("apply-template",), "CONFIRMED", "yes, with a map across lineages",
               "Same lineage pairs by object id; across lineages `--map FILE` says how tracks pair "
               "(`--propose-map` drafts it, `(none)` leaves a track alone). Three legacy songs "
               "migrated onto a mixing template opened in Logic and re-saved with the identical "
               "row list (2026-09-04). Never removes a send; inputs past the session's count are made "
               "before planning (Logic re-saved six); the template's groups are made and joined by "
               "name (2026-09-05, confirmed on the same song). Legacy bus returns the template "
               "duplicates are silenced; `-` lines in the map leave template tracks out. A song made "
               "before Logic 11.2 migrates in one pass: the slot base is stamped into every channel "
               "record (`logic/README.md`: slot keys). Also carries the track power state, icons, "
               "header components and the control bar; not the project's own tempo, meter or key, "
               "which stay the song's"),
)


NOTICE_LEVELS = ("CLAIMED", "DERIVED", "BROKEN")
NOTICE_ENV = "LOGICXKIT_NO_NOTICE"
LIBRARY_WRITERS = ("build", "pst")


def notice(cmd: str) -> str | None:
    """The one-line warning a write by `cmd` earns, or None when it earns none."""
    cap = by_command().get(cmd)
    if cap is None or cap.level not in NOTICE_LEVELS:
        return None
    return (f"logicxkit: '{cmd}' is {cap.level} — {cap.safe}. Open the result in Logic before "
            f"trusting it; `logic capabilities -v` and docs/CAPABILITIES.md say why.")


def emit_notice(args) -> None:
    """Every project-mutating command takes ``--out``, so that flag is the write signal."""
    if env_str(NOTICE_ENV):
        return
    writing = bool(getattr(args, "out", None)) or args.cmd in LIBRARY_WRITERS
    line = notice(args.cmd) if writing else None
    if line:
        print(line, file=sys.stderr)


def by_command() -> dict[str, Capability]:
    return {name: cap for cap in CAPABILITIES for name in cap.commands}


def table() -> str:
    """The markdown table `docs/CAPABILITIES.md` carries, generated."""
    rows = ["| Command | Level | Safe on a real song? | The catch |", "|---|---|---|---|"]
    for cap in CAPABILITIES:
        names = " ".join(f"`{n}`" for n in cap.commands)
        level = cap.level if cap.level == "—" else f"**{cap.level}**"
        rows.append(f"| {names} | {level} | {cap.safe} | {cap.catch} |")
    return "\n".join(rows)


def cmd_capabilities(args) -> int:
    print("What each command is trusted for. Raising a level needs evidence — see the "
          "module docstring.\n")
    width = max(len(" ".join(c.commands)) for c in CAPABILITIES)
    for cap in CAPABILITIES:
        names = " ".join(cap.commands)
        print(f"  {names:{width}s}  {cap.level:9s}  {cap.safe}")
        if cap.catch and args.verbose:
            print(f"  {'':{width}s}             {cap.catch}")
    print("\nFull detail, including the reproduced defects: docs/CAPABILITIES.md")
    return 0


def register(sub) -> None:
    ap = sub.add_parser("capabilities", help="what each command is trusted for")
    ap.add_argument("-v", "--verbose", action="store_true", help="include the catch per command")
    ap.set_defaults(func=cmd_capabilities)
