"""What each command is trusted for, declared next to the code rather than in prose.

`docs/EVIDENCE.md` is generated from this table, and `tests/logic/test_capabilities.py`
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

from ..utils.env import env_str
from ._capabilities_table import CAPABILITIES, Capability  # noqa: F401

LEVELS = ("CONFIRMED", "CLAIMED", "DERIVED", "BROKEN", "—")

NOTICE_LEVELS = ("CLAIMED", "DERIVED", "BROKEN")
NOTICE_ENV = "LOGICXKIT_NO_NOTICE"
LIBRARY_WRITERS = ("build", "pst")


def notice(cmd: str, args=None) -> str | None:
    """The one-line warning a write by `cmd` earns, or None when it earns none."""
    cap = by_command().get(cmd)
    if cap is None:
        return None
    level = "DERIVED" if any(getattr(args, dest, None) for dest in cap.derived) else cap.level
    if level not in NOTICE_LEVELS:
        return None
    return (f"logicxkit: '{cmd}' is {level} — {cap.safe}. Open the result in Logic before "
            f"trusting it; `logic capabilities -v` and docs/EVIDENCE.md say why.")


def emit_notice(args) -> None:
    """Every project-mutating command takes ``--out``, so that flag is the write signal."""
    if env_str(NOTICE_ENV):
        return
    writing = bool(getattr(args, "out", None)) or args.cmd in LIBRARY_WRITERS
    line = notice(args.cmd, args) if writing else None
    if line:
        print(line, file=sys.stderr)


def by_command() -> dict[str, Capability]:
    return {name: cap for cap in CAPABILITIES for name in cap.commands}


def _names(cap: Capability) -> str:
    return " ".join(f"`{n}`" for n in cap.commands)


def table() -> str:
    """The markdown table `docs/EVIDENCE.md` carries, generated: one line per command; the
    catch, prose, goes in `catches()` below it."""
    rows = ["| Command | Level | Safe on a real song? |", "|---|---|---|"]
    for cap in CAPABILITIES:
        level = cap.level if cap.level == "—" else f"**{cap.level}**"
        rows.append(f"| {_names(cap)} | {level} | {cap.safe} |")
    return "\n".join(rows)


def catches() -> str:
    """The catch per command, generated for `docs/EVIDENCE.md`: what each level was measured
    against, and where it stops."""
    out = []
    for cap in CAPABILITIES:
        if cap.catch:
            out.append(f"### {_names(cap)}\n\n{cap.catch}.")
    return "\n\n".join(out)


def cmd_capabilities(args) -> int:
    print("What each command is trusted for. Raising a level needs evidence — see the "
          "module docstring.\n")
    width = max(len(" ".join(c.commands)) for c in CAPABILITIES)
    for cap in CAPABILITIES:
        names = " ".join(cap.commands)
        print(f"  {names:{width}s}  {cap.level:9s}  {cap.safe}")
        if cap.catch and args.verbose:
            print(f"  {'':{width}s}             {cap.catch}")
    print("\nThe catch per command: -v; full detail, including the reproduced defects: docs/EVIDENCE.md")
    return 0


def register(sub) -> None:
    ap = sub.add_parser("capabilities", help="what each command is trusted for")
    ap.add_argument("-v", "--verbose", action="store_true", help="include the catch per command")
    ap.set_defaults(func=cmd_capabilities)
