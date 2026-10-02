"""`swap-plugin`: every slot holding one plug-in replaced by another across the project (or
the channels named), settings carried through the family vocabulary, side chains and
automation lanes with them, one report line per slot; `--plan` says what would change."""

from __future__ import annotations

from pathlib import Path

from ._add_plugin_cmd import _channels, _offsets, _pick
from ._edit import CommandError, edit_copy, owner_by_label
from ._plugin_settings import replace_slot, set_specs, translation


def slot_names(payload: bytes, maps) -> set[str]:
    """Every name a slot answers to, lowercased: Logic's name for one of its own, its type id,
    a third-party's `Manufacturer/Subtype` code, and the plug-in's name in its translation map."""
    from .services.plugin_names import native_name
    from .services.plugins import plugin_identity
    from .services.translate import map_for
    identity = plugin_identity(payload)
    names: set[str] = set()
    if identity and identity[0] == "native":
        names.add(str(identity[1]))
        if (name := native_name(identity[1], identity[2] if len(identity) > 2 else None)):
            names.add(name)
    elif identity:
        names.add(f"{identity[3]}/{identity[2]}")
    if (m := map_for(payload, maps)) is not None:
        names.add(m.plugin)
    return {n.lower() for n in names}


def matching_slots(data: bytes, owner: int, wanted: str, maps) -> list[int]:
    """The mixer positions (from 1, empty slots counted) on ``owner`` holding ``wanted``."""
    from .services.slots import slot_index_base
    from .services.stream import HEADER
    from .services.transplant import channel_slots
    base = slot_index_base(data)
    return [r.key - base + 1 for r in channel_slots(data, owner) if wanted.strip().lower() in slot_names(r.raw[HEADER:], maps)]


def _labels(args, data: bytes, count) -> list[str]:
    from .services.plugins import slot_payloads
    if args.channel or args.stack:
        return _channels(args, data, count)
    return list(dict.fromkeys(ref.channel for ref, _p in slot_payloads(data)))


def _refusal(project: Path, args, donors, maps) -> str | None:
    """Why nothing would be swapped, read before any copy is made: ``--to`` names the plug-in
    ``--from`` does, or no slot of any alternative holds ``--from``."""
    from .services.stream import HEADER
    from .services.plugins import slot_payloads
    from .services.project import project_metadata
    target = _pick(donors, args.target, None, None)
    if args.source.strip().lower() in slot_names(target.raw[HEADER:], maps):
        return f"--from {args.source} and --to {args.target} name the same plug-in ({target.label})"
    held: set[str] = set()
    for data_file in sorted(project.glob("Alternatives/*/ProjectData")):
        data = data_file.read_bytes()
        count = project_metadata(project, data_file.parent.name).get("tracks")
        if any(matching_slots(data, owner_by_label(data, label), args.source, maps) for label in _labels(args, data, count)):
            return None
        held |= {ref.name for ref, _p in slot_payloads(data)}
    where = " on the channels named" if args.channel or args.stack else ""
    return f"no slot holds {args.source!r}{where}; the project holds: {', '.join(sorted(held)) or 'no plug-in'}"


def _plan_lines(data: bytes, owner: int, at: int, donor, translate: bool) -> list[str]:
    """What the slot would become; a settings crossing that would be refused raises as the write would."""
    if not translate:
        return [f"slot {at}: {donor.label} in, at its defaults"]
    carried = translation(data, owner, at, donor)
    lines = [f"slot {at}: {donor.label} in"]
    lines += [f"    {name} = {value}" for name, value in carried.values.items()]
    lines += [f"    band {band.number}: {band.label()}" for band in carried.bands]
    lines += [f"    {note}" for note in carried.notes]
    return lines


def cmd_swap_plugin(args) -> int:
    from ..utils.data import data_dirs
    from .services.mixer import channel_formats
    from .services.plugin_library import load_library
    from .services.retrack import find_project
    from .services.translate import load_maps
    from .services.transplant import slot_class_version

    if not args.plan and not args.out:
        print("  name the copy's directory with --out, or ask for --plan")
        return 2
    libraries = [Path(args.library)] if args.library else data_dirs("donors")
    donors = load_library(libraries)
    if not donors:
        print("  no donors in the library; `logic donors PROJECT` harvests them")
        return 1
    settings, maps = set_specs(args.set), load_maps()
    swapped, skipped, channels = 0, 0, set()

    def step(data, count, data_file):
        nonlocal swapped, skipped
        alt = data_file.parent.name
        version, formats = slot_class_version(data), channel_formats(data)
        for label in _labels(args, data, count):
            owner = owner_by_label(data, label)
            for at in matching_slots(data, owner, args.source, maps):
                try:
                    donor = _pick(donors, args.target, formats.get(owner), version)
                    if args.plan:
                        lines = _plan_lines(data, owner, at, donor, not args.no_translate)
                    else:
                        data, lines = replace_slot(data, owner, at, donor, id_offsets=_offsets(data, donor, libraries),
                                                   settings=settings, translate=not args.no_translate,
                                                   keep_automation=args.keep_automation, force=args.force)
                except LookupError as e:
                    raise CommandError(f"{alt}: {label}: {e}") from None
                except ValueError as e:
                    skipped += 1
                    print(f"  {alt}: {label:11s} slot {at}: left as it is — {e}")
                    continue
                swapped += 1
                channels.add(label)
                print(f"  {alt}: {label:11s} {lines[0]}")
                for line in lines[1:]:
                    print(f"  {line}")
        return data

    project = find_project(Path(args.project))
    try:
        if (why := _refusal(project, args, donors, maps)):
            raise CommandError(why)
        if args.plan:
            first = sorted(project.glob("Alternatives/*/ProjectData"))[0]
            step(first.read_bytes(), None, first)
        else:
            edit_copy(project, Path(args.out), step)
    except (CommandError, LookupError) as e:
        print(f"  {e}")
        return 1
    verb = "Would swap" if args.plan else "Swapped"
    print(f"\n{verb} {swapped} slot(s) on {len(channels)} channel(s)" + (f", {skipped} left as they are" if skipped else "")
          + ("." if args.plan else ". Open the copy in Logic before trusting it."))
    return 0


def register(sub) -> None:
    ap = sub.add_parser("swap-plugin", help="every slot holding one plug-in replaced by another, settings and lanes carried (writes a copy)")
    ap.add_argument("project")
    ap.add_argument("--from", required=True, dest="source", metavar="NAME",
                    help="the plug-in to replace: Logic's name, a `Manufacturer/Subtype` code, a native type id or its map's name")
    ap.add_argument("--to", required=True, dest="target", metavar="NAME", help="the library plug-in to put in its place")
    ap.add_argument("--out", help="output directory (a copy)")
    ap.add_argument("--plan", action="store_true", help="say what would change and how each slot's settings would cross; writes nothing")
    ap.add_argument("--channel", action="append", metavar="LABEL", help="only this mixer label (repeatable; default: every channel)")
    ap.add_argument("--stack", action="append", metavar="NAME", help="only this folder stack's members (repeatable)")
    ap.add_argument("--no-translate", action="store_true", dest="no_translate",
                    help="the replacement's own defaults instead of the old settings carried; its lanes drop")
    ap.add_argument("--keep-automation", action="store_true", dest="keep_automation",
                    help="leave each slot's lanes as they are instead of carrying them")
    ap.add_argument("--set", action="append", metavar="NAME=VALUE", help="a value dialled into every replacement (repeatable)")
    ap.add_argument("--library", help="donor library directory (default: the data root's donors/)")
    ap.add_argument("--force", action="store_true", help="write past a version or width refusal")
    ap.set_defaults(func=cmd_swap_plugin)
