"""`width`: read every channel's width, or make channels mono or stereo on a copy."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, edit_copy, first_project_data
from .services.binding import channels
from .services.insert import MONO, STEREO, channel_formats, widen_channels
from .services.retrack import find_project

WORDS = {MONO: "mono", STEREO: "stereo"}


def _owners(data: bytes, labels: list[str]) -> dict[int, str]:
    chans = channels(data)
    out = {}
    for label in labels:
        wanted = label.strip().lower()
        hits = [o for o, c in chans.items() if c.label.lower() == wanted]
        if len(hits) != 1:
            raise ValueError(f"{label!r}: {'no' if not hits else 'more than one'} channel has that label")
        out[hits[0]] = chans[hits[0]].label
    return out


def _print(data: bytes, only: set[int] | None = None) -> None:
    chans, fmts = channels(data), channel_formats(data)
    for owner in sorted(chans):
        if only is not None and owner not in only:
            continue
        print(f"  {chans[owner].label:12} {WORDS.get(fmts.get(owner), '?')}")


def cmd_width(args) -> int:
    project = find_project(Path(args.project))
    if not (args.stereo or args.mono):
        print(project.name)
        _print(first_project_data(project))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2

    def step(data, count, data_file):
        try:
            want = {o: STEREO for o in _owners(data, args.stereo or [])}
            want.update({o: MONO for o in _owners(data, args.mono or [])})
        except ValueError as e:
            raise CommandError(str(e)) from None
        out, changed = widen_channels(data, want)
        print(f"  {data_file.parent.name}: {len(changed)} channel(s) changed")
        _print(out, set(want))
        return out

    try:
        edit_copy(project, Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print("\nUnverified until opened in Logic.")
    return 0


def register(sub) -> None:
    wd = sub.add_parser("width", help="read every channel's width, or make channels mono or stereo on a copy")
    wd.add_argument("project")
    wd.add_argument("--out", help="output directory (needed to write)")
    wd.add_argument("--stereo", action="append", metavar="LABEL", help="a channel to make stereo, e.g. 'Aux 13'")
    wd.add_argument("--mono", action="append", metavar="LABEL", help="a channel to make mono")
    wd.set_defaults(func=cmd_width)
