"""`tracking-chains`: a project's chains made low-latency and native, on a copy — every
third-party slot with a translation map becomes Logic's own of the same family with its
settings carried (one native per live family of a plug-in that carries several), the rest
removed, natives that carry lookahead bypassed; one report line per slot, `--plan` writes
nothing."""

from __future__ import annotations

from pathlib import Path

from ._add_plugin_cmd import _channels, _offsets, _pick
from ._edit import CommandError, edit_copy, owner_by_label
from ._plugin_settings import replace_slot, translation_of

LATENT = {243: "Linear Phase EQ", 194: "Multipressor", 193: "Adaptive Limiter", 199: "Limiter", 157: "Enveloper"}


def bypass_slot(data: bytes, owner: int, at: int) -> bytes:
    from .services.insert import project_records, set_slot_bypass
    from .services.transplant import slot_at
    from .services.validate import require_valid
    record = slot_at(data, owner, at)
    out = [set_slot_bypass(r.raw, True) if r.owner == owner and r.key == record.key else r.raw for r in project_records(data)]
    result = data[:24] + b"".join(out)
    require_valid(result)
    return result


def _made_latent(donor, at: int, args) -> str | None:
    """The line for a native this made that carries lookahead: bypassed like the ones already there."""
    if donor.type_id in LATENT and not args.keep_lookahead:
        return f"slot {at}: {LATENT[donor.type_id]} bypassed: it carries lookahead"
    return None


def live_families(payload: bytes, maps) -> list:
    """The maps of the slot's plug-in whose element is not bypassed (Neutron's gate, off in a
    fresh instance, stays out), in the vocabulary's order: eq, gate, compressor, multiband."""
    from .services.translate import maps_for, read_settings
    order = {"eq": 0, "gate": 1, "compressor": 2, "multiband": 3}
    found = maps_for(payload, maps)
    if len(found) <= 1:
        return found
    live = [m for m in found if not any("bypassed" in note for note in read_settings(payload, m).notes)]
    return sorted(live, key=lambda m: order.get(m.family, 9))


def _slot_lines(data, owner, at, payload, identity, args, donors, libraries, maps, natives, version, width):
    """One slot made native -> (data, lines, kind): kind is swapped / removed / bypassed / kept."""
    from .services.chain_report import native_name
    from .services.insert import HEADER
    from .services.add_plugin import add_plugin
    from .services.remove_plugin import remove_plugin
    from .services.translate_write import write_plan
    if identity and identity[0] == "native":
        name = native_name(identity[1], identity[2] if len(identity) > 2 else None) or f"type {identity[1]}"
        if identity[1] in LATENT and not args.keep_lookahead:
            return (data if args.plan else bypass_slot(data, owner, at)), [f"slot {at}: {name} bypassed: it carries lookahead"], "bypassed"
        return data, [], "kept"
    from .services.transplant import is_instrument_channel
    if at == 1 and is_instrument_channel(data, owner):          # the track's instrument, never an effect
        label = f"{identity[3]}/{identity[2]}" if identity else "an unreadable slot"
        return data, [f"slot 1: {label} kept: the channel's instrument"], "kept"
    families = live_families(payload, maps)
    if not families:
        label = f"{identity[3]}/{identity[2]}" if identity else "an unreadable slot"
        if args.keep_unmapped:
            return data, [f"slot {at}: {label} kept: no native analogue"], "kept"
        if not args.plan:
            data, gone = remove_plugin(data, owner, at)
            return data, [f"slot {at}: {label} removed: no native analogue ({gone['lanes_dropped']} automation point(s) with it)"], "removed"
        return data, [f"slot {at}: {label} removed: no native analogue"], "removed"
    first, extra = families[0], families[1:]
    donor = _pick(donors, natives[first.family], width, version)
    plans = [(fam, _pick(donors, natives[fam.family], width, version)) for fam in extra]
    if args.plan:
        carried = translation_of(payload, donor, first.family)
        lines = [f"slot {at}: {first.plugin} -> {donor.label}"] + [f"    {n} = {v}" for n, v in carried.values.items()]
        lines += [f"    band {b.number}: {b.label()}" for b in carried.bands] + [f"    {n}" for n in carried.notes]
        lines += [f"slot {at + 1 + i}: {first.plugin}'s {fam.family} -> {d.label}, added after it" for i, (fam, d) in enumerate(plans)]
        lines += [n for n in (_made_latent(donor, at, args), *(_made_latent(d, at + 1 + i, args) for i, (_f, d) in enumerate(plans))) if n]
        return data, lines, "swapped"
    data, lines = replace_slot(data, owner, at, donor, id_offsets=_offsets(data, donor, libraries), translate=True)
    lines[0] = f"slot {at}: {first.plugin} -> {lines[0]}"
    if (line := _made_latent(donor, at, args)):
        data = bypass_slot(data, owner, at)
        lines.append(line)
    for i, (fam, d) in enumerate(plans):
        carried = translation_of(payload, d, fam.family)
        body, notes = write_plan(d.raw[HEADER:], carried)
        data, _report = add_plugin(data, owner, d.raw[:HEADER] + body, at=at + 1 + i, id_offsets=_offsets(data, d, libraries),
                                   type_id=d.type_id, side_chain=carried.side_chain)
        lines.append(f"slot {at + 1 + i}: {first.plugin}'s {fam.family} -> {d.label}, added after it")
        lines += [f"    {n} = {v}" for n, v in carried.values.items()] + [f"    band {b.number}: {b.label()}" for b in carried.bands]
        lines += [f"    {n}" for n in carried.notes + notes]
        if (line := _made_latent(d, at + 1 + i, args)):
            data = bypass_slot(data, owner, at + 1 + i)
            lines.append(line)
    return data, lines, "swapped"


def cmd_tracking_chains(args) -> int:
    from ..utils.data import data_dirs
    from .services.insert import HEADER, channel_formats, slot_index_base
    from .services.plugin_library import load_library
    from .services.plugins import plugin_identity, slot_payloads
    from .services.retrack import find_project
    from .services.translate import load_maps
    from .services.transplant import channel_slots, slot_class_version

    if not args.plan and not args.out:
        print("  name the copy's directory with --out, or ask for --plan")
        return 2
    libraries = [Path(args.library)] if args.library else data_dirs("donors")
    donors = load_library(libraries)
    if not donors:
        print("  no donors in the library; `logic donors PROJECT` harvests them")
        return 1
    maps = load_maps()
    natives = {m.family: m.plugin for m in maps if m.type is not None}
    counts: dict[str, int] = {}

    def step(data, count, data_file):
        alt = data_file.parent.name
        version, formats = slot_class_version(data), channel_formats(data)
        labels = _channels(args, data, count) if args.channel or args.stack else list(dict.fromkeys(r.channel for r, _p in slot_payloads(data)))
        for label in labels:
            owner = owner_by_label(data, label)
            base = slot_index_base(data)
            slots = [(r.key - base + 1, r.raw[HEADER:]) for r in channel_slots(data, owner)]
            for at, payload in sorted(slots, reverse=True):          # from the last slot up, so positions stay put
                try:
                    data, lines, kind = _slot_lines(data, owner, at, payload, plugin_identity(payload), args, donors, libraries,
                                                    maps, natives, version, formats.get(owner))
                except (LookupError, ValueError) as e:
                    raise CommandError(f"{alt}: {label} slot {at}: {e}") from None
                counts[kind] = counts.get(kind, 0) + 1
                for i, line in enumerate(lines):
                    print(f"  {alt}: {label:11s} {line}" if i == 0 else f"  {line}")
        return data

    project = find_project(Path(args.project))
    try:
        if args.plan:
            first = sorted(project.glob("Alternatives/*/ProjectData"))[0]
            step(first.read_bytes(), None, first)
        else:
            edit_copy(project, Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    said = ", ".join(f"{n} {k}" for k, n in counts.items() if k != "kept")
    print(f"\n{'Would make' if args.plan else 'Made'} native: {said or 'nothing to change'}" + ("." if args.plan else ". Open the copy in Logic before trusting it."))
    return 0


def register(sub) -> None:
    ap = sub.add_parser("tracking-chains", help="every third-party plug-in made its native counterpart with its settings, the rest removed, "
                                                "lookahead bypassed — a low-latency copy for tracking")
    ap.add_argument("project")
    ap.add_argument("--out", help="output directory (a copy)")
    ap.add_argument("--plan", action="store_true", help="say what each slot would become; writes nothing")
    ap.add_argument("--channel", action="append", metavar="LABEL", help="only this mixer label (repeatable; default: every channel)")
    ap.add_argument("--stack", action="append", metavar="NAME", help="only this folder stack's members (repeatable)")
    ap.add_argument("--keep-unmapped", action="store_true", dest="keep_unmapped", help="leave a third-party plug-in without a native analogue in place")
    ap.add_argument("--keep-lookahead", action="store_true", dest="keep_lookahead", help="leave the natives that carry lookahead enabled")
    ap.add_argument("--library", help="donor library directory (default: the data root's donors/)")
    ap.set_defaults(func=cmd_tracking_chains)
