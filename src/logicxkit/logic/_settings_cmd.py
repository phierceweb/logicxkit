"""`logic settings` — every plug-in slot's settings in its family's vocabulary, read through the
plug-in's map (`services/translate`): what a compressor's threshold, ratio, attack and release
are whichever compressor it is; `--set` writes them into one slot, on a copy."""
from __future__ import annotations

import json
from pathlib import Path

from ._edit import CommandError, edit_copy, first_project_data, owner_by_label
from .services.plugin_params import load_tables
from .services.plugins import slot_payloads
from .services.retrack import find_project
from .services.translate import VOCABULARY, _show, load_maps, map_for, maps_for, read_settings


def cmd_settings(args) -> int:
    maps = load_maps([Path(args.maps)] if args.maps else None)
    tables = load_tables()
    if args.set:
        return _write(args, maps, tables)
    from .services.insert import slot_index_base
    data = first_project_data(find_project(Path(args.project)))
    wanted = {c.strip() for c in args.channel or []}
    base = slot_index_base(data)
    report = []
    for ref, payload in slot_payloads(data):
        if wanted and ref.channel not in wanted:
            continue
        found = maps_for(payload, maps)            # one entry per family the plug-in carries
        for m in found or [None]:
            entry = {"channel": ref.channel, "slot": ref.key - base + 1, "key": ref.key, "name": ref.name,
                     "side_chain": ref.side_chain}
            if m is None:
                entry["settings"] = None
            else:
                s = read_settings(payload, m, tables)
                entry.update({"family": m.family, "plugin": m.plugin, "settings": s.values, "silent": s.silent,
                              "notes": s.notes})
                if s.bands:
                    entry["bands"] = [b.label() for b in s.bands]
                    entry["master"] = s.master
            report.append(entry)
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    for e in report:
        print(_line(e))
    return 0


def _line(e: dict) -> str:
    head = f"  {e['channel']:16s} slot {e['slot']:2d}  {e['name']}"
    if e["settings"] is None:
        return f"{head}: no map for it"
    units = VOCABULARY.get(e["family"], {})                     # an EQ is bands only
    parts = [f"{k} {_show(v, units.get(k, ''))}" for k, v in e["settings"].items()]
    parts += [f"{k} silent" for k in e["silent"]] + list(e.get("notes") or [])
    if e.get("bands") is not None:
        master = f", master {e['master']:+.1f} dB" if e.get("master") is not None else ""
        return f"{head} ({e['family']}): " + "; ".join(e["bands"]) + master + ("; " + ", ".join(parts) if parts else "")
    return f"{head} ({e['family']}): " + ", ".join(parts) + (f"  side chain: {e['side_chain']}" if e["side_chain"] else "")


def _write(args, maps, tables) -> int:
    """``--set NAME=VALUE`` into one slot (`--channel LABEL --at N`) of every alternative, on a
    copy: vocabulary items, or ``band N=<shape> <frequency> …`` for an EQ, through the slot's map."""
    from .services.insert import HEADER, project_records
    from .services.transplant import channel_slots, slot_at, slot_position
    from .services.translate_write import apply_band_specs, split_specs, write_settings
    from .services.validate import require_full_walk, require_valid

    if not args.out or len(args.channel or []) != 1 or args.at is None:
        print("  --set writes a copy: name it with --out, the slot with one --channel and --at")
        return 2
    specs = {}
    for spec in args.set:
        name, sep, value = spec.partition("=")
        if not sep or not name.strip():
            print(f"  --set takes NAME=VALUE, e.g. 'threshold=-18' or 'band 2=bell 250 Hz -4 dB Q 2'; got {spec!r}")
            return 2
        specs[name.strip()] = value.strip()
    label = args.channel[0].strip()
    bands, values = split_specs(specs)

    def step(data, _count, data_file):
        alt = data_file.parent.name
        require_full_walk(data)
        owner = owner_by_label(data, label)
        rec = slot_at(data, owner, args.at)
        if rec is None:
            held = ", ".join(str(slot_position(data, r)) for r in channel_slots(data, owner)) or "none"
            raise CommandError(f"{alt}: {label}: slot {args.at} holds no plug-in (plug-ins in slot(s) {held})")
        payload = rec.raw[HEADER:]
        m = map_for(payload, maps)
        if m is None:
            raise CommandError(f"{alt}: {label} slot {args.at}: no map for the plug-in there")
        try:
            notes = []
            if bands:
                payload, more = apply_band_specs(payload, m, bands, tables)
                notes += more
            if values:
                payload, more = write_settings(payload, m, values, tables)
                notes += more
        except ValueError as e:
            raise CommandError(f"{alt}: {label} slot {args.at}: {e}") from None
        out = [rec.raw[:HEADER] + payload if r.owner == rec.owner and r.key == rec.key and r.raw == rec.raw else r.raw
               for r in project_records(data)]
        result = data[:24] + b"".join(out)
        require_valid(result)
        s = read_settings(payload, m, tables)
        entry = {"channel": label, "slot": args.at, "key": rec.key, "name": m.plugin, "side_chain": None, "family": m.family,
                 "settings": s.values, "silent": s.silent}
        if s.bands:
            entry.update({"bands": [b.label() for b in s.bands], "master": s.master})
        print(f"  {alt}:" + _line(entry))
        for note in notes:
            print(f"      {note}")
        return result

    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print("\nWritten. Open the copy in Logic before trusting it.")
    return 0


def register(sub) -> None:
    ap = sub.add_parser("settings", help="every plug-in slot's settings in its family's vocabulary")
    ap.add_argument("project", help="a .logicx bundle or its folder")
    ap.add_argument("--channel", action="append", metavar="LABEL", help="mixer label (repeatable)")
    ap.add_argument("--maps", help="a directory of translation maps (default: the data root's and the package's)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help="write a vocabulary item, or `band N=<shape> <frequency> …` on an EQ, into one slot "
                         "(repeatable; needs --channel, --at and --out)")
    ap.add_argument("--at", type=int, metavar="N", help="with --set: the mixer slot, from 1, empty slots counted")
    ap.add_argument("--out", help="with --set: output directory (writes a copy)")
    ap.set_defaults(func=cmd_settings)
