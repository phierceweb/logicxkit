"""`add-plugin`: a library plug-in into one slot of a channel, on a copy. No donor strip: the
plug-in comes from the `donors/` library (`logic donors PROJECT` harvests it, third-party ones
included)."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, edit_copy, owner_by_label
from ._plugin_settings import dialled, donor_table, replace_slot, set_specs


def cmd_add_plugin(args) -> int:
    from ..utils.data import data_dirs
    from .services.add_plugin import add_plugin
    from .services.insert import channel_formats
    from .services.plugin_library import load_library
    from .services.transplant import slot_class_version

    if not (args.channel or args.stack):
        print("  name the channels with --channel or --stack")
        return 2
    if args.at is not None and args.at < 1:
        print("  --at counts slots from 1")
        return 2
    libraries = [Path(args.library)] if args.library else data_dirs("donors")
    donors = load_library(libraries)
    if not donors:
        print(f"  no donors under {', '.join(map(str, libraries)) or 'the data root'}; "
              "`logic donors PROJECT` harvests them")
        return 1
    settings = set_specs(args.set)
    total = 0

    def step(data, count, data_file):
        nonlocal total
        alt = data_file.parent.name
        version, formats = slot_class_version(data), channel_formats(data)
        for label in _channels(args, data, count):
            owner = owner_by_label(data, label)
            try:
                donor = _pick(donors, args.plugin, formats.get(owner), version)
                offsets = _offsets(data, donor, libraries)
                raw, by_table, notes = dialled(donor, settings)
                data, report = add_plugin(data, owner, raw, at=args.at, id_offsets=offsets,
                                          type_id=donor.type_id, bypass=args.bypass, force=args.force,
                                          settings=by_table, table=donor_table(donor) if by_table else None,
                                          side_chain=_side_chain(data, args))
            except (LookupError, ValueError) as e:
                raise CommandError(f"{alt}: {label}: {e}") from None
            moved = f", {len(report['moved'])} moved down" if report["moved"] else ""
            lanes = f", {report['lanes_moved']} automation point(s) with them" if report["lanes_moved"] else ""
            ids = "" if offsets else "  id copied"
            keyed = f"  side chain {args.side_chain} ({report['side_chain']})" if report["side_chain"] else ""
            print(f"  {alt}: {label:11s} {donor.label} into slot {report['position']}{moved}{lanes}"
                  f"{'  bypassed' if args.bypass else ''}{ids}{keyed}")
            for note in notes:
                print(f"      {note}")
            total += 1
        return data

    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print(f"\nAdded {total} slot(s). Open the copy in Logic before trusting it.")
    return 0


def cmd_remove_plugin(args) -> int:
    from .services.remove_plugin import remove_plugin

    if not (args.channel or args.stack):
        print("  name the channels with --channel or --stack")
        return 2
    if args.at < 1:
        print("  --at counts slots from 1")
        return 2
    total = 0

    def step(data, count, data_file):
        nonlocal total
        alt = data_file.parent.name
        for label in _channels(args, data, count):
            try:
                data, report = remove_plugin(data, owner_by_label(data, label), args.at)
            except ValueError as e:
                raise CommandError(f"{alt}: {label}: {e}") from None
            moved = f", {len(report['moved'])} moved up" if report["moved"] else ""
            dropped = f", its {report['lanes_dropped']} automation point(s) dropped" if report["lanes_dropped"] else ""
            print(f"  {alt}: {label:11s} slot {args.at} removed, {report['slots']} left{moved}{dropped}")
            total += 1
        return data

    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print(f"\nRemoved {total} slot(s). Open the copy in Logic before trusting it.")
    return 0


def cmd_replace_plugin(args) -> int:
    """A removal and an insert at the same slot, one gate."""
    from ..utils.data import data_dirs
    from .services.insert import channel_formats
    from .services.plugin_library import load_library
    from .services.transplant import slot_class_version

    if not (args.channel or args.stack):
        print("  name the channels with --channel or --stack")
        return 2
    if args.at < 1:
        print("  --at counts slots from 1")
        return 2
    libraries = [Path(args.library)] if args.library else data_dirs("donors")
    donors = load_library(libraries)
    if not donors:
        print("  no donors in the library; `logic donors PROJECT` harvests them")
        return 1
    settings = set_specs(args.set)
    total = 0

    def step(data, count, data_file):
        nonlocal total
        alt = data_file.parent.name
        version, formats = slot_class_version(data), channel_formats(data)
        for label in _channels(args, data, count):
            owner = owner_by_label(data, label)
            try:
                donor = _pick(donors, args.plugin, formats.get(owner), version)
                data, lines = replace_slot(data, owner, args.at, donor, id_offsets=_offsets(data, donor, libraries),
                                           settings=settings, translate=args.translate, keep_automation=args.keep_automation,
                                           bypass=args.bypass, side_chain=args.side_chain, force=args.force)
            except (LookupError, ValueError) as e:
                raise CommandError(f"{alt}: {label}: {e}") from None
            print(f"  {alt}: {label:11s} {lines[0]}")
            for line in lines[1:]:
                print(f"  {line}")
            total += 1
        return data

    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print(f"\nReplaced {total} slot(s). Open the copy in Logic before trusting it.")
    return 0


def _side_chain(data, args):
    """The side chain `--side-chain NAME` asks for, resolved in this alternative."""
    from .services.sidechain import resolve
    return resolve(data, args.side_chain) if getattr(args, "side_chain", None) else None


def _pick(donors, name: str, width: int | None, version: int | None):
    from .services.plugin_library import find_donor
    return find_donor(donors, name, width=width, version=version)


def _offsets(data: bytes, donor, libraries=None) -> tuple[int, ...]:
    """The plug-in's instance-id offsets: measured against the project's own instances when they
    tell the id apart, else the library's measurement, else against another library record of the
    plug-in, else none (the id is copied — Logic gives a second holder a fresh one on load)."""
    from ..utils.data import data_dirs
    from .services.plugin_library import library_offsets
    from .services.transplant import id_offsets
    return (id_offsets(data, donor.raw) or tuple(donor.id_offsets)
            or library_offsets(donor, libraries if libraries is not None else data_dirs("donors")))


def _channels(args, data: bytes, count: int | None) -> list[str]:
    """Every ``--channel`` label and the channel of every ``--stack`` member, each once."""
    from .services.stacks import read_stacks, read_tracks, rows_below

    labels = [c.strip() for c in args.channel or []]
    if args.stack:
        stacks = read_stacks(data, count)
        bound = {r["key"]: r["label"] for r in read_tracks(data, count)}
        for name in args.stack:
            stack = next((s for s in stacks if s.name == name.strip()), None)
            if stack is None:
                raise CommandError(f"no stack named {name!r} (have: {', '.join(sorted(s.name for s in stacks))})")
            labels += [bound[key] for key, _n in rows_below(stacks, stack, headers=False) if bound.get(key)]
    return list(dict.fromkeys(labels))


def register(sub) -> None:
    ap = sub.add_parser("add-plugin", help="a library plug-in into one slot of a channel (writes a copy)")
    ap.add_argument("project")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--plugin", required=True, metavar="NAME",
                    help="a library plug-in: its name, a Manufacturer/Subtype code or a type id")
    ap.add_argument("--channel", action="append", metavar="LABEL", help="mixer label, e.g. 'Audio 5' (repeatable)")
    ap.add_argument("--stack", action="append", metavar="NAME", help="every member of this folder stack (repeatable)")
    ap.add_argument("--at", type=int, metavar="N", help="the mixer slot, from 1, empty slots counted (default: after the last)")
    ap.add_argument("--bypass", action="store_true", help="insert it bypassed")
    ap.add_argument("--side-chain", metavar="NAME", dest="side_chain",
                    help="the track, bus or aux return the plug-in listens to, by name or mixer label")
    ap.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help="a parameter to dial on the way in: a table name for Logic's own, a vocabulary item or "
                         "`band N=<shape> <freq> …` through the map (repeatable)")
    ap.add_argument("--library", help="donor library directory (default: the data root's donors/)")
    ap.add_argument("--force", action="store_true",
                    help="write past a refusal: a donor of another class version, or a third-party "
                         "plug-in of the other width, which loads at its saved width")
    ap.set_defaults(func=cmd_add_plugin)
    rm = sub.add_parser("remove-plugin", help="one slot out of a channel, the rest closed up (writes a copy)")
    rm.add_argument("project")
    rm.add_argument("--out", required=True, help="output directory")
    rm.add_argument("--at", type=int, required=True, metavar="N", help="the mixer slot, from 1, empty slots counted")
    rm.add_argument("--channel", action="append", metavar="LABEL", help="mixer label (repeatable)")
    rm.add_argument("--stack", action="append", metavar="NAME", help="every member of this folder stack (repeatable)")
    rm.set_defaults(func=cmd_remove_plugin)
    rp = sub.add_parser("replace-plugin", help="another library plug-in in a slot's place (writes a copy)")
    rp.add_argument("project")
    rp.add_argument("--out", required=True, help="output directory")
    rp.add_argument("--at", type=int, required=True, metavar="N", help="the mixer slot, from 1, empty slots counted")
    rp.add_argument("--plugin", required=True, metavar="NAME", help="the library plug-in to put there")
    rp.add_argument("--channel", action="append", metavar="LABEL", help="mixer label (repeatable)")
    rp.add_argument("--stack", action="append", metavar="NAME", help="every member of this folder stack (repeatable)")
    rp.add_argument("--bypass", action="store_true", help="insert it bypassed")
    rp.add_argument("--side-chain", metavar="NAME", dest="side_chain",
                    help="the track, bus or aux return the plug-in listens to, by name or mixer label")
    rp.add_argument("--translate", action="store_true",
                    help="carry the old slot's settings (and side chain) into the replacement through the family vocabulary")
    rp.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help="a parameter to dial on the way in: a table name for Logic's own, a vocabulary item or "
                         "`band N=<shape> <freq> …` through the map (repeatable; after --translate)")
    rp.add_argument("--keep-automation", action="store_true", dest="keep_automation",
                    help="keep the old plug-in's automation lanes on the slot as they are; without it they are "
                         "carried through the maps with --translate (a lane without a home dropped with a report "
                         "line) and dropped without")
    rp.add_argument("--library", help="donor library directory (default: the data root's donors/)")
    rp.add_argument("--force", action="store_true", help="write past a version or width refusal")
    rp.set_defaults(func=cmd_replace_plugin)
