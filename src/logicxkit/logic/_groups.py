"""`group`: read a project's groups, or on a copy make one, put tracks in or out of one,
rename one or set its boxes."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, edit_copy, object_by_name
from .services.groups import FLAGS


def _print(groups, objs) -> None:
    if not groups:
        print("  no groups")
    for g in groups:
        members = ", ".join(objs[m].name if m in objs else str(m) for m in g.members)
        print(f"  {g.number:2d}  {g.label:16s} {', '.join(g.settings)}")
        print(f"      {members or '(no members)'}")


def cmd_group(args) -> int:
    from .services.environment import channel_objects
    from .services.groups import assign, create_group, read_groups, set_group
    from .services.retrack import find_project
    from logicxkit.logicx import project_data

    writing = bool(args.create or args.assign or args.name or args.setting is not None)
    if not writing:
        project = find_project(Path(args.project))
        data = project_data(project)
        print(project.name)
        _print(read_groups(data), channel_objects(data))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2
    if (args.name or args.setting is not None) and not args.create and not args.group:
        print("  --group N says which group --name / --setting change")
        return 2

    def step(data, count, _file):
        if args.create:
            members = [object_by_name(data, n, count) for n in args.track or []]
            data, g = create_group(data, name=args.create, members=members, settings=args.setting)
            print(f"  group {g.number} {g.label!r}: {', '.join(g.settings)}; {len(members)} member(s)")
        elif args.group:
            data = set_group(data, args.group, name=args.name, settings=args.setting)
            g = read_groups(data)[args.group - 1]
            print(f"  group {g.number} {g.label!r}: {', '.join(g.settings)}")
        for spec in args.assign or []:
            name, _, number = spec.rpartition("=")
            if not name or not number.isdigit():
                raise CommandError(f"bad --assign {spec!r}: use TRACK=N (0 = no group)")
            data = assign(data, object_by_name(data, name.strip(), count), int(number))
            print(f"  {name.strip()} -> group {number}")
        return data

    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    return 0


def register(sub) -> None:
    gp = sub.add_parser("group", help="read the groups, or make one / assign tracks / set its "
                        "boxes on a copy")
    gp.add_argument("project")
    gp.add_argument("--out", help="output directory (needed to write)")
    gp.add_argument("--create", metavar="NAME", help="make a group ('' for an unnamed one)")
    gp.add_argument("--track", action="append", metavar="TRACK", help="a member for --create (repeatable)")
    gp.add_argument("--assign", action="append", metavar="TRACK=N", help="put a track in group N (0 = out)")
    gp.add_argument("--group", type=int, metavar="N", help="the group --name / --setting change")
    gp.add_argument("--name", metavar="NAME", help="rename --group N")
    gp.add_argument("--setting", action="append", metavar="BOX",
                    help=f"a box to tick, repeatable; the rest come off. One of: {', '.join(FLAGS)}")
    gp.set_defaults(func=cmd_group)
