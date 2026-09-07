"""`toolbar`: read a project's toolbar button set, or set it on a copy — by name, or copied
whole from another project."""

from __future__ import annotations

from pathlib import Path

from .services.retrack import copy_project, find_project
from .services.toolbar import (BUTTONS, alternative_dirs, buttons_of, copy_toolbar, read_toolbar, set_buttons,
                               show_toolbar, toolbar_shown)


def _match(name: str) -> str:
    wanted = name.strip().lower()
    hits = [b for b in BUTTONS if b.lower() == wanted] or [b for b in BUTTONS if wanted in b.lower()]
    if len(hits) != 1:
        raise ValueError(f"{name!r}: {'no' if not hits else 'more than one'} button matches; "
                         f"choose from {', '.join(BUTTONS)}")
    return hits[0]


def _print(alt: Path, state: dict[str, bool]) -> None:
    print(f"  row {'shown' if toolbar_shown(alt) else 'hidden'}")
    for name, shown in state.items():
        print(f"  [{'x' if shown else ' '}] {name}")


def cmd_toolbar(args) -> int:
    project = find_project(Path(args.project))
    if not (args.show or args.hide or args.src or args.row):
        for alt in alternative_dirs(project):
            print(f"{project.name} / {alt.name}")
            _print(alt, buttons_of(read_toolbar(alt)))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2
    try:
        want = {_match(n): True for n in args.show or []}
        want.update({_match(n): False for n in args.hide or []})
        src = find_project(Path(args.src)) if args.src else None
    except ValueError as e:
        print(f"  {e}")
        return 2
    dest = copy_project(project, Path(args.out))["dest"]
    print(f"into : {dest}\n")
    for alt in alternative_dirs(dest):
        if src is not None:
            copy_toolbar(alternative_dirs(src)[0], alt)
        if args.row:
            show_toolbar(alt, args.row == "show")
        state = set_buttons(alt, want) if want else buttons_of(read_toolbar(alt))
        print(f"  {alt.name}:")
        _print(alt, state)
    print("\nUnverified until opened in Logic.")
    return 0


def register(sub) -> None:
    tb = sub.add_parser("toolbar", help="read or set the toolbar's buttons on a copy, or copy them from another project")
    tb.add_argument("project")
    tb.add_argument("--out", help="output directory (needed to write)")
    tb.add_argument("--show", action="append", metavar="BUTTON", help="e.g. Crop, 'Nudge Value'")
    tb.add_argument("--hide", action="append", metavar="BUTTON")
    tb.add_argument("--from", dest="src", metavar="PROJECT", help="copy the whole toolbar from this project or template")
    tb.add_argument("--row", choices=("show", "hide"), help="show or hide the toolbar row itself")
    tb.set_defaults(func=cmd_toolbar)
