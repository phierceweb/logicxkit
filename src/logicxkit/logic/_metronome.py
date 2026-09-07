"""`metronome`: read a project's Metronome and Recording settings, set the boxes on a copy,
or copy the lot — flags, pre-roll, Klopfgeist rows, MIDI click rows — from another project."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, edit_copy, first_project_data
from .services.metronome import BITS, PREROLL, copy_metronome, read_metronome, set_metronome
from .services.retrack import find_project


def _match(name: str) -> str:
    wanted = name.strip().lower()
    names = list(BITS) + [PREROLL]
    hits = [m for m in names if m.lower() == wanted] or [m for m in names if wanted in m.lower()]
    if len(hits) != 1:
        raise ValueError(f"{name!r}: {'no' if not hits else 'more than one'} setting matches; choose from {', '.join(names)}")
    return hits[0]


def _print(state: dict) -> None:
    for name, value in state.items():
        if isinstance(value, bool):
            print(f"  {name:32} {'on' if value else 'off'}")
        elif isinstance(value, float):
            print(f"  {name:32} {value:g}")
    for section in ("Klopfgeist", "MIDI click"):
        print(f"  {section}:")
        for row, fields in state[section].items():
            print(f"    {row:9} " + "  ".join(("on" if v else "off") if isinstance(v, bool) else f"{k} {v}"
                                             for k, v in fields.items()))


def cmd_metronome(args) -> int:
    project = find_project(Path(args.project))
    if not (args.set or args.src):
        print(project.name)
        _print(read_metronome(first_project_data(project)))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2
    try:
        want: dict = {}
        for spec in args.set or []:
            if "=" not in spec:
                raise ValueError(f"{spec!r}: write NAME=on, NAME=off or 'Pre-roll seconds=2'")
            name, _eq, text = spec.partition("=")
            key = _match(name)
            t = text.strip().lower()
            if key == PREROLL:
                want[key] = float(t)
            elif t in ("on", "yes", "1", "true"):
                want[key] = True
            elif t in ("off", "no", "0", "false"):
                want[key] = False
            else:
                raise ValueError(f"{spec!r}: use on or off")
        src = find_project(Path(args.src)) if args.src else None
    except ValueError as e:
        print(f"  {e}")
        return 2

    def step(data, count, data_file):
        if src is not None:
            data, _copied = copy_metronome(first_project_data(src), data)
        if want:
            data = set_metronome(data, want)
        print(f"  {data_file.parent.name}:")
        _print(read_metronome(data))
        return data

    try:
        edit_copy(project, Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print("\nUnverified until opened in Logic.")
    return 0


def register(sub) -> None:
    mt = sub.add_parser("metronome", help="read or set the Metronome and Recording project settings on a copy, or copy them from another project")
    mt.add_argument("project")
    mt.add_argument("--out", help="output directory (needed to write)")
    mt.add_argument("--set", action="append", metavar="NAME=VALUE", help="e.g. 'Simple mode=on', 'Click while recording=off', 'Pre-roll seconds=2'")
    mt.add_argument("--from", dest="src", metavar="PROJECT", help="copy every metronome and recording setting from this project or template")
    mt.set_defaults(func=cmd_metronome)
