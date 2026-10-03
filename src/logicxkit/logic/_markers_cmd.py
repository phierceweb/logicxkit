"""`logic markers` — the marker track: every marker with its bar and name; on a copy, `--add`,
`--rename`, `--move` and `--delete` (`markers.py`, `markers_write.py`)."""

from __future__ import annotations

import json
from pathlib import Path

from ._edit import CommandError, edit_copy, first_project_data
from .services.song.markers import TO_NEXT, marker_number, read_markers
from .services.song.markers_write import add_marker, delete_marker, move_marker, rename_marker
from .services.arrange.retrack import find_project
from .services.song.signature import meter


def _bar(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise CommandError(f"bad bar {text!r}: a bar number, fractions allowed") from None


def _index(text: str, flag: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise CommandError(f"bad --{flag} {text!r}: N is a marker's number in the listing")
    return int(text)


def _number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def parse_add(spec: str) -> tuple[str, str, str]:
    """``BAR[:BARS]:NAME`` -> (bar, bars, name); a name may hold colons, so BARS is only a number."""
    bar, sep, rest = spec.partition(":")
    if not sep or not _number(bar) or not rest:
        raise CommandError(f"bad --add {spec!r}: BAR[:BARS]:NAME")
    bars, sep, name = rest.partition(":")
    if sep and _number(bars) and name:
        return bar, bars, name
    return bar, "", rest


def _targets(args, data: bytes) -> dict:
    """Each edit's marker as the listed alternative numbers it: (name, tick), the same marker in
    every alternative."""
    markers = read_markers(data)
    out = {}
    for flag, spec in args.edits:
        if flag == "add":
            continue
        n, sep, _rest = spec.partition("=")
        if flag != "delete" and not sep:
            raise CommandError(f"bad --{flag} {spec!r}: N=" + ("NAME" if flag == "rename" else "BAR"))
        n = _index(n, flag)
        if n > len(markers):
            raise CommandError(f"marker {n}: the song has {len(markers)} marker(s)")
        out[(flag, spec)] = (markers[n - 1].name, markers[n - 1].tick)
    return out


def _edits(args, data: bytes, targets: dict, alternative: str) -> bytes:
    """The edits in command-line order, each on the marker its number named in the listing; a
    marker deleted by an earlier edit takes no later one (an add may reuse its name record)."""
    m = meter(data)
    markers = read_markers(data)
    slots, deleted = {}, set()
    for (flag, spec), (name, tick) in targets.items():
        hits = [k for k in markers if (k.name, k.tick) == (name, tick)]
        if len(hits) != 1:
            has = f"{len(hits)} markers" if hits else "no marker"
            raise CommandError(f"--{flag} {spec}: alternative {alternative} has {has} {name!r} at bar {m.bar(tick):g}")
        slots[(flag, spec)] = hits[0].text_slot
    for flag, spec in args.edits:
        if flag == "add":
            bar, bars, name = parse_add(spec)
            start = m.tick(_bar(bar))
            length = TO_NEXT if not bars else m.tick(_bar(bar) + _bar(bars)) - start
            data = add_marker(data, name, tick=start, length=length)
            continue
        if slots[(flag, spec)] in deleted:
            raise CommandError(f"--{flag} {spec}: marker {spec.partition('=')[0]} was deleted by an earlier edit")
        n = marker_number(data, slots[(flag, spec)])
        if flag == "delete":
            data = delete_marker(data, n)
            deleted.add(slots[(flag, spec)])
        else:
            rest = spec.partition("=")[2]
            data = rename_marker(data, n, rest) if flag == "rename" else move_marker(data, n, m.tick(_bar(rest)))
    return data


def cmd_markers(args) -> int:
    project = find_project(Path(args.project))
    args.edits = list(args.edits or ())
    if args.edits:
        if not args.out:
            print("  --out is needed to write")
            return 2
        try:
            targets = _targets(args, first_project_data(project))
            edit_copy(project, Path(args.out), lambda data, _count, data_file: _edits(args, data, targets, data_file.parent.name))
        except (ValueError, CommandError) as e:
            print(f"  {e}")
            return 1
        for flag, spec in args.edits:
            print(f"  --{flag} {spec}")
        return 0
    data = first_project_data(project)
    markers, m = read_markers(data), meter(data)
    if args.json:
        print(json.dumps([{"number": n, "name": k.name, "tick": k.tick, "bar": k.bar(m), "length": k.length}
                          for n, k in enumerate(markers, 1)], indent=1))
        return 0
    print(f"{project.name}: {len(markers)} marker(s)")
    for n, k in enumerate(markers, 1):
        length = "to the next" if k.length == TO_NEXT else f"{m.bar(k.tick + k.length) - k.bar(m):g} bar(s)"
        print(f"  {n:3d} bar {k.bar(m):7.2f}  {k.name!r:24s} {length}")
    return 0


def register(sub) -> None:
    ap = sub.add_parser("markers", help="the marker track; add, rename, move or delete on a copy")
    ap.add_argument("project")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="output directory (needed to write)")
    for flag, shape, text in (("add", "BAR[:BARS]:NAME", "a marker at BAR, to the next marker or for BARS"),
                              ("rename", "N=NAME", "rename marker N"),
                              ("move", "N=BAR", "move marker N to BAR"),
                              ("delete", "N", "delete marker N and its name")):
        ap.add_argument(f"--{flag}", dest="edits", action="append", type=lambda s, f=flag: (f, s), metavar=shape, help=text)
    ap.set_defaults(func=cmd_markers)
