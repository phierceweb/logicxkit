"""`--set` and `--translate` for `add-plugin` and `replace-plugin`: the values dialled into a
donor on the way in, the old slot's settings carried through the family vocabulary, and the
slot's automation lanes carried after them."""

from __future__ import annotations


def set_specs(specs: list[str] | None) -> dict[str, str]:
    """``NAME=VALUE`` pairs from ``--set``."""
    out = {}
    for spec in specs or []:
        name, sep, value = spec.partition("=")
        if not sep or not name.strip():
            raise SystemExit(f"  --set takes NAME=VALUE, e.g. 'Threshold=-18'; got {spec!r}")
        out[name.strip()] = value.strip()
    return out


def dialled(donor, settings: dict[str, str], raw: bytes | None = None):
    """``--set`` applied: band specs (``band N=…``) and a third-party's items through its map into
    the donor's payload; one of Logic's own keeps its table names for `add_plugin` to dial ->
    ``(raw, values for the table, notes)``."""
    from .services.insert import HEADER
    from .services.translate import load_maps, map_for
    from .services.translate_write import apply_band_specs, split_specs, write_settings
    raw = donor.raw if raw is None else raw
    if not settings:
        return raw, None, []
    bands, values = split_specs(settings)
    if donor.type_id is not None and not bands:
        values, notes = gridded(raw[HEADER:], values)
        return raw, values, notes
    m = map_for(raw[HEADER:], load_maps())
    if m is None:
        raise LookupError(f"{donor.label} has no translation map; `--set` on a third-party (and `band N=` on any "
                          "EQ) needs one (data/translate)")
    payload, notes = raw[HEADER:], []
    if bands:
        payload, more = apply_band_specs(payload, m, bands)
        notes += more
    if values and donor.type_id is None:
        payload, more = write_settings(payload, m, values)
        notes += more
        values = None
    return raw[:HEADER] + payload, values or None, notes


def gridded(payload: bytes, values: dict[str, str]) -> tuple[dict, list[str]]:
    """Table-name values for one of Logic's own as its sliders keep them: held to a measured
    slider's ends with a note, on the item's grid and the nearer sampled position — what
    `settings --set` writes. A parameter no map measures goes as given."""
    from .services.slider import slider_curve, snap
    from .services.translate import load_maps, map_for
    m = map_for(payload, load_maps())
    if m is None:
        return values, []
    out, notes = {}, []
    for name, raw in values.items():
        param = next((k for k in m.raw.get("automation", {}) if k.lower() == name.lower()), name)   # the table's spelling
        curve = slider_curve(m, param)
        item = next((i for i in m.items.values() if i.param.lower() == name.lower()), None)
        try:
            value = float(raw)
        except ValueError:
            out[name] = raw                                       # a choice by name
            continue
        if curve:
            lo, hi = min(v for _u, v in curve), max(v for _u, v in curve)
            if not lo <= value <= hi:
                notes.append(f"{name} {value:g}: {m.plugin}'s slider runs {lo:g}..{hi:g}; set to {min(max(value, lo), hi):g}")
                value = min(max(value, lo), hi)
        if item is not None and item.step and not item.switch:
            value = round(round(value / item.step) * item.step, 6)
        out[name] = snap(m, param, value) if curve else value
    return out, notes


def translation(data, owner: int, at: int, donor):
    """The old slot's settings carried into ``donor`` through the family vocabulary, with the
    old slot's side chain riding along; refused when either plug-in has no map."""
    from .services.insert import HEADER
    from .services.transplant import slot_at
    record = slot_at(data, owner, at)
    if record is None:
        raise ValueError(f"slot {at} holds no plug-in")
    try:
        return translation_of(record.raw[HEADER:], donor)
    except LookupError:
        raise ValueError(f"no translation map for the plug-in in slot {at}") from None


def translation_of(old: bytes, donor, family: str | None = None):
    """The plan carrying ``old``'s settings into ``donor`` — through the map of ``family`` when
    the old plug-in has several — with its side chain; LookupError when the old plug-in has no
    map, ValueError when the donor has none or the families differ."""
    from .services.insert import HEADER
    from .services.plugin_params import load_tables
    from .services.sidechain import side_chain
    from .services.translate import load_maps, map_for, maps_for, plan, read_settings
    maps = load_maps()
    src_maps, dst_map = maps_for(old, maps), map_for(donor.raw[HEADER:], maps)
    if not src_maps:
        raise LookupError("no translation map")
    if dst_map is None:
        raise ValueError(f"no translation map for {donor.label}")
    wanted = family or dst_map.family
    src_map = next((m for m in src_maps if m.family == wanted), src_maps[0])   # a plug-in of several families
    out = plan(read_settings(old, src_map, load_tables()), dst_map)
    out.side_chain = side_chain(old)
    return out


def carry_lanes(data, owner: int, at: int, carried, raw: bytes, old_raw: bytes, lanes) -> tuple[bytes, list[str]]:
    """``lanes``, the old slot's automation taken before it was emptied, carried through the
    plan's maps onto insert ``at`` (`automation_remap`)."""
    from .services.automation_remap import carry_slot
    from .services.insert import HEADER
    from .services.insert_lanes import channel_object
    from .services.plugin_params import load_tables, table_for
    from .services.slot_width import plugin_variant
    obj = channel_object(data, owner)
    if obj is None:
        return data, ["automation: the channel is bound to no track; nothing to carry"]
    tables = load_tables()
    src, dst = carried.source, carried.target
    src_table = table_for(tables, src.type, plugin_variant(old_raw[HEADER:])) if src.type is not None else None
    dst_table = table_for(tables, dst.type, plugin_variant(raw[HEADER:])) if dst.type is not None else None
    return carry_slot(data, obj, at, src, dst, src_table, dst_table, carried.assignment, lanes=lanes)


def restore_lanes(data, owner: int, at: int, lanes) -> bytes:
    """``lanes`` written back onto insert ``at`` as they were (`--keep-automation`)."""
    from .services.automation_write import set_param_lane
    from .services.insert_lanes import channel_object
    obj = channel_object(data, owner)
    for lane in lanes:
        data = set_param_lane(data, obj, lane.param_index, [(p.tick, p.value, p.fraction) for p in lane.points], slot=at)
    return data


def donor_table(donor):
    from .services.insert import HEADER, plugin_variant
    from .services.plugin_params import load_tables, table_for
    table = (table_for(load_tables(), donor.type_id, plugin_variant(donor.raw[HEADER:]))
             if donor.type_id is not None else None)
    if table is None:
        raise LookupError(f"{donor.label} has no parameter table; `--set` needs one measured "
                          "(the logic README, 'Parameter tables from the Controls view')")
    return table


def replace_slot(data, owner: int, at: int, donor, *, id_offsets, settings: dict[str, str] | None = None,
                 translate: bool = False, keep_automation: bool = False, bypass: bool = False,
                 side_chain: str | None = None, force: bool = False) -> tuple[bytes, list[str]]:
    """Mixer slot ``at`` of channel ``owner`` replaced by ``donor`` — the old slot's settings
    carried when ``translate``, its lanes carried after them (or kept as they were, or dropped
    with a note), ``--set`` values dialled in — one gate. Returns the data and the report lines."""
    from .services.add_plugin import add_plugin
    from .services.insert import HEADER
    from .services.insert_lanes import insert_lanes
    from .services.remove_plugin import remove_plugin
    from .services.sidechain import resolve, side_chain as side_chain_of, source_name
    from .services.transplant import slot_at
    from .services.translate_write import write_plan
    old = slot_at(data, owner, at)
    old_key = side_chain_of(old.raw[HEADER:]) if old is not None else None
    dropped = source_name(data, old_key) if old_key and not side_chain and not translate else None
    lanes = insert_lanes(data, owner, at)
    carried = translation(data, owner, at, donor) if translate else None
    raw, kept = donor.raw, []
    if carried:
        payload, kept = write_plan(raw[HEADER:], carried)
        raw = raw[:HEADER] + payload
    raw, by_table, notes = dialled(donor, settings or {}, raw)
    notes = kept + notes
    data, gone = remove_plugin(data, owner, at)
    data, report = add_plugin(data, owner, raw, at=at, id_offsets=id_offsets, type_id=donor.type_id, bypass=bypass,
                              force=force, settings=by_table, table=donor_table(donor) if by_table else None,
                              side_chain=resolve(data, side_chain) if side_chain else (carried.side_chain if carried else None))
    if lanes and keep_automation:
        data = restore_lanes(data, owner, at, lanes)
        notes.append(f"automation: {len(lanes)} lane(s) kept on slot {at} as they were")
    elif lanes and carried:
        data, more = carry_lanes(data, owner, at, carried, raw, old.raw, lanes)
        notes += more
    elif lanes:
        notes.append(f"automation: {len(lanes)} lane(s) of the old plug-in dropped "
                     f"({gone['lanes_dropped']} point(s)); --translate carries them, --keep-automation keeps them")
    if dropped:
        notes.append(f"side chain {dropped} dropped with the old plug-in; --translate carries it")
    keyed = f"  side chain {side_chain or 'carried'} ({report['side_chain']})" if report["side_chain"] else ""
    lines = [f"slot {at}: {donor.label} in, key {gone['key']} out{keyed}"]
    if carried:
        lines += [f"    {name} = {value}" for name, value in carried.values.items()]
        lines += [f"    band {band.number}: {band.label()}" for band in carried.bands]
        lines += [f"    {note}" for note in carried.notes]
    lines += [f"    {note}" for note in notes]
    return data, lines
