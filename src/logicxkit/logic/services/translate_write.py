"""A slot's settings written through its map: one of Logic's own by its parameter table
(`plugin_params.set_by_name`), a third-party into its AU state — FabFilter's id/value pairs
(Pro-C 2, Pro-MB) or binary state (Pro-Q 4) patched in place (`au/services/austate_write`).
sonible's protobuf is read, not written. An EQ takes bands (`translate_eq`)."""

from __future__ import annotations

import math
from dataclasses import replace

from ...au.services.austate_write import patch_ffbs, patch_pairs, replace_data
from ...au.services.embed import find_au_plists
from .plugin_params import load_tables, set_by_name, table_for
from .slot_width import plugin_variant
from .slider import interp, snap
from .translate import VOCABULARY, Item, Map, Plan, _show, clamp, read_settings
from .translate_eq import BRICKWALL, Band, parse_band

_ON = {"on", "true", "yes", "1"}
_OFF = {"off", "false", "no", "0"}


def write_settings(payload: bytes, m: Map, values: dict, tables: dict | None = None) -> tuple[bytes, list[str]]:
    """``values`` by vocabulary name (a switch takes on/off), written through ``m``; the
    notes say what was clamped to the plug-in's range."""
    if m.family == "eq":
        raise ValueError(f"{m.plugin} is an EQ: its settings are bands (`band N=<shape> <frequency> …`)")
    stored, notes = {}, []
    for name, value in values.items():
        item = m.items.get(name)
        if item is None:
            raise ValueError(f"{m.plugin} has no {name!r}; its {m.family} items: {', '.join(m.items)}")
        carried, note = clamp(item, _coerce(item, value, name))
        if note:
            notes.append(f"{name} {value}: {m.plugin}'s {item.param} {note} {carried:g}, set there")
        stored[name] = _rounded(item, item.to_stored(carried)) if m.component is None else item.to_stored(carried)
        if m.component is None and not item.switch:
            stored[name], note = _on_slider(m, item, stored[name])
            notes += [f"{name} {value}: {note}"] if note else []
    if m.component is None:
        by_param = {m.items[n].param: ("On" if v else "Off") if m.items[n].switch else v for n, v in stored.items()}
        return set_by_name(_table(payload, m, tables), payload, by_param), notes
    return write_state(payload, m, {m.items[n].id: v for n, v in stored.items()}), notes


def write_bands(payload: bytes, m: Map, bands: list[Band], master: float | None = None,
                tables: dict | None = None) -> tuple[bytes, list[str]]:
    """An EQ's bands written by number: one of Logic's own into its numbered slots (the others
    kept), a third-party into its band layout, the rest of the layout unused and every band's
    dynamics off — a plan carries a band's static curve only."""
    if m.component is None:
        values = {}
        for band in bands:
            values.update(_slot_values(m, band))
        if master is not None and m.raw.get("master"):
            values[m.raw["master"]] = master
        return set_by_name(_table(payload, m, tables), payload, values), []
    lay = m.raw["bands"]
    by_slot: dict[int, Band] = {}
    for band in bands:
        slot = band.number - 1 if band.number else next(i for i in range(lay["count"]) if i not in by_slot)
        if not 0 <= slot < lay["count"] or slot in by_slot:
            raise ValueError(f"{m.plugin}: band {slot + 1} is taken or past its {lay['count']} bands")
        by_slot[slot] = band
    by_id, notes = {}, []
    for slot in range(lay["count"]):
        if slot in by_slot:
            by_id.update(_band_ids(m, by_slot[slot], slot, notes, static=True))
        else:
            by_id[slot * lay["stride"] + lay["used"]] = 0.0
    if master:
        notes.append(f"master {master:+.1f} dB: no analogue in {m.plugin}")
    return write_state(payload, m, by_id), notes


def _slot_values(m: Map, band: Band) -> dict:
    """One of Logic's own EQ slot's table values for ``band`` (its number is the slot's)."""
    slots = [slot for entries in m.raw["slots"].values() for slot in entries]
    if not 1 <= band.number <= len(slots):
        raise ValueError(f"{m.plugin} has no band {band.number}; its slots run 1 to {len(slots)}")
    slot, step = slots[band.number - 1], m.raw.get("steps", {}).get("gain")
    values = {slot["on"]: "On" if band.on else "Off",
              slot["frequency"]: snap(m, slot["frequency"], round(band.frequency, 2)),
              slot["q"]: snap(m, slot["q"], round(band.q, 3))}
    if "gain" in slot:
        gain = band.gain if not step else round(math.floor(band.gain / step + 0.5 + 1e-9) * step, 6)
        values[slot["gain"]] = snap(m, slot["gain"], gain)
    return values


def _band_ids(m: Map, band: Band, slot: int, notes: list[str], *, static: bool) -> dict[int, float]:
    """A third-party layout's ids for ``band`` in ``slot``; ``static`` also turns its dynamics off
    (a new band, or a plan's). A cut with no slope given takes 12 dB/oct, Pro-Q 4's default."""
    lay, shapes, slopes = m.raw["bands"], m.raw["shapes"], m.raw["slopes"]
    if band.shape not in shapes:
        raise ValueError(f"{m.plugin} has no {band.shape.replace('_', ' ')} band")
    slope = 12 if band.slope is None else band.slope
    if slope == BRICKWALL and None in slopes:
        index = slopes.index(None)
    elif slope in slopes:
        index = slopes.index(slope)
    else:
        near = min((s for s in slopes if s is not None), key=lambda s: abs(s - slope))
        notes.append(f"band {slot + 1}: {m.plugin} has no {slope:g} dB/oct slope; {near} dB/oct")
        index = slopes.index(near)
    base = slot * lay["stride"]
    ids = {base + lay["used"]: 1.0, base + lay["enabled"]: 1.0 if band.on else 0.0,
           base + lay["frequency"]: math.log2(band.frequency) if m.raw.get("frequency") == "log2" else band.frequency,
           base + lay["gain"]: band.gain, base + lay["q"]: _q_stored(m, band.q),
           base + lay["shape"]: float(shapes.index(band.shape)), base + lay["slope"]: float(index)}
    if static:
        ids.update({base + lay[f]: 0.0 for f in ("dynamic_range", "dynamics_enabled") if f in lay})
    return ids


def write_plan(payload: bytes, p: Plan, tables: dict | None = None) -> tuple[bytes, list[str]]:
    """The donor payload with the plan written into it; the notes name the target's items the
    plan left as the donor had them."""
    target = p.target
    if target.family == "eq":
        if target.component is None:
            return set_by_name(_table(payload, target, tables), payload, p.values), []
        return write_bands(payload, target, p.bands, None, tables)
    if target.family == "multiband" and target.component:
        from .translate_mb import write_mbands
        out = write_mbands(payload, target, p.bands)
        return write_settings(out, target, p.values, tables) if p.values else (out, [])
    own = read_settings(payload, target, tables)
    named = set(p.values) if target.component else {n for n, i in target.items.items() if i.param in p.values}
    units = VOCABULARY[target.family]
    kept = [f"{n} {_show(v, units[n])}: {target.plugin}'s own, kept" for n, v in own.values.items() if n not in named]
    if target.component is None:
        return set_by_name(_table(payload, target, tables), payload, p.values), kept
    out, notes = write_settings(payload, target, p.values, tables)
    return out, notes + kept


def apply_band_specs(payload: bytes, m: Map, specs: dict[str, str], tables: dict | None = None) -> tuple[bytes, list[str]]:
    """``band N=<label>`` edits, and nothing else: band N written, every other band as it was.
    One of Logic's own keeps its slot's shape; a third-party takes a new band in an unused slot,
    its dynamics off. A cut named with no slope keeps the band's own."""
    if m.family != "eq":
        raise ValueError(f"{m.plugin} is a {m.family}: band specs edit an EQ's bands (its bands cross with --translate)")
    current = {b.number: b for b in read_settings(payload, m, tables).bands}
    values, by_id, notes = {}, {}, []
    for key, spec in specs.items():
        n = int(key.split()[1])
        band, old = replace(parse_band(spec), number=n), current.get(n)
        if old is None and (m.component is None or n < 1):
            raise ValueError(f"{m.plugin} has no band {n}")
        if old is not None and m.component is None and old.shape != band.shape:
            raise ValueError(f"band {n} of {m.plugin} is its {old.shape.replace('_', ' ')} slot")
        if band.slope is None and old is not None:
            band = replace(band, slope=old.slope)
        if m.component is None:
            values.update(_slot_values(m, band))
        else:
            if not 1 <= n <= m.raw["bands"]["count"]:
                raise ValueError(f"{m.plugin}: band {n} is past its {m.raw['bands']['count']} bands")
            by_id.update(_band_ids(m, band, n - 1, notes, static=old is None))
    if m.component is None:
        return set_by_name(_table(payload, m, tables), payload, values), notes
    return write_state(payload, m, by_id), notes


def split_specs(values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """``--set`` pairs split into band specs (``band N``) and the rest."""
    bands = {k: v for k, v in values.items() if k.lower().startswith("band ") and k.split()[-1].isdigit()}
    return bands, {k: v for k, v in values.items() if k not in bands}


def write_state(payload: bytes, m: Map, by_id: dict[int, float]) -> bytes:
    """Values by AU parameter id into the payload's state, the record's length kept."""
    if m.decoder in ("sonible", "izotope"):
        raise ValueError(f"{m.plugin}: its {m.decoder} state is read, not written")
    plist = next((pl for _off, pl in find_au_plists(payload) if "manufacturer" in pl), None)
    if plist is None:
        raise ValueError(f"{m.plugin}: the slot holds no AU state")
    if m.decoder == "ffbs":
        blob = plist.get("FabFilterPluginState")
        if not isinstance(blob, bytes):
            raise ValueError(f"{m.plugin}: the state holds no FabFilterPluginState")
        return replace_data(payload, "FabFilterPluginState", patch_ffbs(blob, by_id))
    data = plist.get("data")
    if not isinstance(data, bytes):
        raise ValueError(f"{m.plugin}: the state holds no id/value pairs to write")
    return replace_data(payload, "data", patch_pairs(data, by_id))


def _coerce(item: Item, value, name: str) -> float | bool:
    if item.switch:
        if isinstance(value, str):
            if value.lower() in _ON:
                return True
            if value.lower() in _OFF:
                return False
            raise ValueError(f"{name} takes on or off, not {value!r}")
        return bool(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} takes a number, not {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} takes a finite number, not {value!r}")
    return number


def _on_slider(m: Map, item: Item, stored: float) -> tuple[float, str | None]:
    """A native value held to its measured slider's ends and put on the nearer sampled position;
    the note says when it was held, or when it sits between positions the table has not sampled."""
    from .slider import is_linear, slider_curve
    curve = slider_curve(m, item.param)
    if not curve:
        return stored, None
    lo, hi = min(v for _u, v in curve), max(v for _u, v in curve)
    if not lo <= stored <= hi:
        held = min(max(stored, lo), hi)
        return snap(m, item.param, held), f"{m.plugin}'s {item.param} slider runs {lo:g}..{hi:g}; set to {held:g}"
    value = snap(m, item.param, stored)
    if not is_linear(curve) and not any(v == value for _u, v in curve):
        return value, f"between {m.plugin}'s sampled {item.param} positions; Logic lays it on the nearer one"
    return value, None


def _rounded(item: Item, stored: float | bool) -> float | bool:
    if item.switch or not item.step:
        return stored
    return round(math.floor(stored / item.step + 0.5 + 1e-9) * item.step, 6)


def _q_stored(m: Map, q: float) -> float:
    curve = m.raw.get("q_curve")
    return interp(tuple((float(y), float(x)) for x, y in curve), q) if curve else q


def _table(payload: bytes, m: Map, tables: dict | None):
    table = table_for(tables if tables is not None else load_tables(), m.type, plugin_variant(payload))
    if table is None:
        raise ValueError(f"{m.plugin}: no parameter table to write the block by")
    return table
