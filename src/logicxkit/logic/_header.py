"""`header`: read a project's track header components, or set them on a copy — by name, or
copied from another project."""

from __future__ import annotations

from pathlib import Path

from .services.header import COMPONENTS, alternative_dirs, read_components, write_components
from .services.retrack import copy_project, find_project


def _match(name: str) -> str:
    wanted = name.strip().lower().replace("_", " ")
    hits = [c for c in COMPONENTS if c.lower() == wanted or c.lower().replace("/", " ") == wanted]
    if not hits:
        hits = [c for c in COMPONENTS if wanted in c.lower()]
    if len(hits) != 1:
        raise ValueError(f"{name!r}: {'no' if not hits else 'more than one'} component matches; "
                         f"choose from {', '.join(COMPONENTS)}")
    return hits[0]


def _print_state(state: dict[str, bool]) -> None:
    for name, shown in state.items():
        print(f"  [{'x' if shown else ' '}] {name}")


def cmd_header(args) -> int:
    project = find_project(Path(args.project))
    if not (args.show or args.hide or args.src):
        for alt in alternative_dirs(project):
            print(f"{project.name} / {alt.name}")
            _print_state(read_components(alt))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2
    try:
        want: dict[str, bool] = {}
        if args.src:
            src = find_project(Path(args.src))
            if not alternative_dirs(src):
                raise ValueError(f"{src}: no alternative carries a DisplayState.plist")
            want.update(read_components(alternative_dirs(src)[0]))
            print(f"from : {src}")
        for name in args.show or []:
            want[_match(name)] = True
        for name in args.hide or []:
            want[_match(name)] = False
    except ValueError as e:
        print(f"  {e}")
        return 2
    dest = copy_project(project, Path(args.out))["dest"]
    print(f"into : {dest}\n")
    for alt in alternative_dirs(dest):
        state = write_components(alt, want)
        print(f"  {alt.name}:")
        _print_state(state)
    print("\nUnverified until opened in Logic.")
    return 0


def register(sub) -> None:
    hd = sub.add_parser("header", help="read or set the track header components (writes a copy)")
    hd.add_argument("project")
    hd.add_argument("--out", help="output directory (needed to write)")
    hd.add_argument("--show", action="append", metavar="COMPONENT", help="e.g. Volume, Mute, 'Track Numbers'")
    hd.add_argument("--hide", action="append", metavar="COMPONENT")
    hd.add_argument("--from", dest="src", metavar="PROJECT", help="copy the set from this project or template")
    hd.set_defaults(func=cmd_header)
