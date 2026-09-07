"""`modes`: read a project's transport modes and count-in, set them on a copy, or copy them
from another project."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, edit_copy, first_project_data
from .services.modes import COUNT_IN, COUNT_INS, MODES, copy_modes, read_modes, set_modes
from .services.retrack import find_project


def _match(name: str) -> str:
    wanted = name.strip().lower()
    names = list(MODES) + [COUNT_IN]
    hits = [m for m in names if m.lower() == wanted] or [m for m in names if wanted in m.lower()]
    if len(hits) != 1:
        raise ValueError(f"{name!r}: {'no' if not hits else 'more than one'} mode matches; choose from {', '.join(names)}")
    return hits[0]


def _print(state: dict) -> None:
    for name, value in state.items():
        shown = value if isinstance(value, str) else ("on" if value else "off")
        print(f"  {name:16} {shown}")


def cmd_modes(args) -> int:
    project = find_project(Path(args.project))
    if not (args.set or args.src):
        print(project.name)
        _print(read_modes(first_project_data(project)))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2
    try:
        want: dict = {}
        for spec in args.set or []:
            if "=" not in spec:
                raise ValueError(f"{spec!r}: write NAME=on, NAME=off or 'Count-in=2 Bars'")
            name, _eq, text = spec.partition("=")
            key = _match(name)
            if key == COUNT_IN:
                want[key] = text.strip()
            elif text.strip().lower() in ("on", "yes", "1", "true"):
                want[key] = True
            elif text.strip().lower() in ("off", "no", "0", "false"):
                want[key] = False
            else:
                raise ValueError(f"{spec!r}: use on or off")
        src = find_project(Path(args.src)) if args.src else None
    except ValueError as e:
        print(f"  {e}")
        return 2
    def step(data, count, data_file):
        if src is not None:
            data, _copied = copy_modes(first_project_data(src), data)
        if want:
            data = set_modes(data, want)
        print(f"  {data_file.parent.name}:")
        _print(read_modes(data))
        return data

    try:
        edit_copy(project, Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print("\nUnverified until opened in Logic.")
    return 0


def register(sub) -> None:
    md = sub.add_parser("modes", help="read or set the transport modes and count-in on a copy, or copy them from another project")
    md.add_argument("project")
    md.add_argument("--out", help="output directory (needed to write)")
    md.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help=f"e.g. Cycle=on, 'Metronome Click=off', 'Count-in=2 Bars' ({', '.join(COUNT_INS[:3])} ...)")
    md.add_argument("--from", dest="src", metavar="PROJECT", help="copy the modes and count-in from this project or template")
    md.set_defaults(func=cmd_modes)
