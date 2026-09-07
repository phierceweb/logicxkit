"""`controlbar`: read a project's control bar and display set, or set it on a copy — by
name, or copied whole from another project."""

from __future__ import annotations

from pathlib import Path

from .services.controlbar import (
    CONTROLS, LCD_MODES, alternative_dirs, controls_of, copy_layout, read_layout, write_controls,
)
from .services.retrack import copy_project, find_project


def _match(name: str) -> str:
    wanted = name.strip().lower().replace("_", " ")
    hits = [c for c in CONTROLS if c.lower() == wanted or c.lower().replace("/", " ") == wanted]
    if not hits:
        hits = [c for c in CONTROLS if wanted in c.lower()]
    if len(hits) != 1:
        raise ValueError(f"{name!r}: {'no' if not hits else 'more than one'} control matches; "
                         f"choose from {', '.join(CONTROLS)}")
    return hits[0]


def _print_state(state: dict[str, bool], transport: dict | None = None) -> None:
    if transport:
        mode = transport.get("DisplayMode")
        print(f"  LCD: {LCD_MODES.get(mode, f'mode {mode}')}"
              + (", SMPTE view offset" if transport.get("UseSMPTEViewOffset") else ""))
    for name, shown in state.items():
        print(f"  [{'x' if shown else ' '}] {name}")


def cmd_controlbar(args) -> int:
    project = find_project(Path(args.project))
    if not (args.show or args.hide or args.src):
        for alt in alternative_dirs(project):
            layout, transport = read_layout(alt)
            print(f"{project.name} / {alt.name}")
            _print_state(controls_of(layout), transport)
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2
    try:
        want = {_match(n): True for n in args.show or []}
        want.update({_match(n): False for n in args.hide or []})
        src = find_project(Path(args.src)) if args.src else None
        if src is not None and not alternative_dirs(src):
            raise ValueError(f"{src}: no alternative carries a DisplayState.plist")
    except ValueError as e:
        print(f"  {e}")
        return 2
    dest = copy_project(project, Path(args.out))["dest"]
    if src is not None:
        print(f"from : {src}")
    print(f"into : {dest}\n")
    for alt in alternative_dirs(dest):
        if src is not None:
            copy_layout(alternative_dirs(src)[0], alt)
        state = write_controls(alt, want) if want else controls_of(read_layout(alt)[0])
        print(f"  {alt.name}:")
        _print_state(state, read_layout(alt)[1])
    print("\nUnverified until opened in Logic.")
    return 0


def register(sub) -> None:
    cb = sub.add_parser("controlbar", help="read or set the control bar and display (Views, "
                        "Transport, Display, Modes) on a copy, or copy it from another project")
    cb.add_argument("project")
    cb.add_argument("--out", help="output directory (needed to write)")
    cb.add_argument("--show", action="append", metavar="CONTROL", help="e.g. Pause, 'Go to Beginning', Tuner")
    cb.add_argument("--hide", action="append", metavar="CONTROL")
    cb.add_argument("--from", dest="src", metavar="PROJECT",
                    help="copy the whole control bar and LCD mode from this project or template")
    cb.set_defaults(func=cmd_controlbar)
