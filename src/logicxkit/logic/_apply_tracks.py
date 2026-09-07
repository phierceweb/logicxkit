"""Track-level apply commands: reorder · colour · rename · hide · add-track · stack-create.
Each writes a copy and never the input; each is one step an orchestrator can chain."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, bump_track_count, edit_copy, object_by_name

UNVERIFIED = "\nUnverified until opened in Logic."


def cmd_reorder(args) -> int:
    """Move a track before or after another one under the same parent."""
    from .services.reorder import move_track

    def step(data, count, _file):
        for spec in args.move:
            track, _, rest = spec.partition(":")
            where, _, target = rest.partition(":")
            if where not in ("before", "after") or not target:
                raise CommandError(f"bad --move {spec!r}: use TRACK:before:OTHER or TRACK:after:OTHER")
            kw = {where: object_by_name(data, target, count)}
            data = move_track(data, object_by_name(data, track, count), track_count=count, **kw)
            print(f"  {track} -> {where} {target}")
        return data
    return _run(args, step)


def cmd_colour(args) -> int:
    """Set track colours by palette index."""
    from .services.environment import set_colour
    from .services.validate import require_full_walk, require_valid

    def step(data, count, _file):
        require_full_walk(data)
        for spec in args.track:
            name, _, value = spec.rpartition("=")
            data = set_colour(data, object_by_name(data, name, count), int(value))
            print(f"  {name} -> colour {value}")
        require_valid(data)
        return data
    return _run(args, step)


def cmd_rename(args) -> int:
    """Rename tracks."""
    from .services.environment import rename_track
    from .services.validate import require_full_walk, require_valid

    def step(data, count, _file):
        require_full_walk(data)
        for spec in args.track:
            old, _, new = spec.partition("=")
            if not new:
                raise CommandError(f"bad --track {spec!r}: use OLD=NEW")
            data = rename_track(data, object_by_name(data, old.strip(), count), new.strip())
            print(f"  {old.strip()} -> {new.strip()}")
        require_valid(data)
        return data
    return _run(args, step, note=UNVERIFIED)


def cmd_hide(args) -> int:
    """Hide (or --show) tracks in the arrange window."""
    from .services.stacks import set_hidden

    def step(data, count, _file):
        for name in args.track:
            data = set_hidden(data, object_by_name(data, name, count), not args.show, track_count=count)
            print(f"  {name} {'shown' if args.show else 'hidden'}")
        return data
    return _run(args, step, note=UNVERIFIED)


def cmd_add_track(args) -> int:
    """Add an audio or instrument track after a named track; bumps NumberOfTracks."""
    from .services.addtrack import add_track

    def step(data, count, data_file):
        data, report = add_track(
            data, name=args.name, after=object_by_name(data, args.after, count),
            kind="instrument" if args.instrument else "audio",
            input_number=args.input, stereo=args.stereo, track_count=count)
        tracks = bump_track_count(data_file)
        print(f"  {args.name!r} after {args.after!r}: object {report['object_id']}, bound "
              f"{report['label']} (owner {report['owner']}), sequence {report['sequence']}, "
              f"input {report['input']}; NumberOfTracks -> {tracks}")
        return data
    return _run(args, step)


def cmd_stack_create(args) -> int:
    """Make a folder stack from existing top-level tracks; bumps NumberOfTracks."""
    from .services.stack_create import create_stack

    def step(data, count, data_file):
        members = [object_by_name(data, name, count) for name in args.track]
        data, report = create_stack(data, name=args.name, members=members, track_count=count,
                                    colour=args.colour)
        tracks = bump_track_count(data_file)
        print(f"  {args.name!r}: {report['label']} (owner {report['owner']}), object "
              f"{report['object_id']}, sequence {report['sequence']}, "
              f"{len(report['members'])} member(s); NumberOfTracks -> {tracks}")
        return data
    return _run(args, step)


def _run(args, step, note: str = "") -> int:
    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    if note:
        print(note)
    return 0


def register(sub) -> None:
    ro = sub.add_parser("reorder", help="move a track before/after another (writes a copy)")
    ro.add_argument("project")
    ro.add_argument("--out", required=True)
    ro.add_argument("--move", action="append", required=True, metavar="TRACK:before|after:OTHER")
    ro.set_defaults(func=cmd_reorder)
    co = sub.add_parser("colour", help="set track colours by palette index (writes a copy)")
    co.add_argument("project")
    co.add_argument("--out", required=True)
    co.add_argument("--track", action="append", required=True, metavar="NAME=INDEX")
    co.set_defaults(func=cmd_colour)
    rn = sub.add_parser("rename", help="rename tracks (writes a copy)")
    rn.add_argument("project")
    rn.add_argument("--out", required=True)
    rn.add_argument("--track", action="append", required=True, metavar="OLD=NEW")
    rn.set_defaults(func=cmd_rename)
    hd = sub.add_parser("hide", help="hide tracks in the arrange window (writes a copy)")
    hd.add_argument("project")
    hd.add_argument("--out", required=True)
    hd.add_argument("--track", action="append", required=True, metavar="NAME")
    hd.add_argument("--show", action="store_true", help="unhide instead")
    hd.set_defaults(func=cmd_hide)
    at = sub.add_parser("add-track", help="add a track after another (writes a copy)")
    at.add_argument("project")
    at.add_argument("--out", required=True)
    at.add_argument("--name", required=True)
    at.add_argument("--after", required=True, metavar="TRACK", help="an existing track")
    at.add_argument("--input", type=int, default=1, metavar="N", help="Input N (default 1)")
    at.add_argument("--stereo", action="store_true")
    at.add_argument("--instrument", action="store_true", help="a software instrument track")
    at.set_defaults(func=cmd_add_track)
    sc = sub.add_parser("stack-create", help="make a folder stack from tracks (writes a copy)")
    sc.add_argument("project")
    sc.add_argument("--out", required=True)
    sc.add_argument("--name", required=True, help="the stack's name")
    sc.add_argument("--track", action="append", required=True, metavar="NAME",
                    help="a top-level track to put inside (repeatable)")
    sc.add_argument("--colour", type=int, default=16, metavar="INDEX")
    sc.set_defaults(func=cmd_stack_create)
