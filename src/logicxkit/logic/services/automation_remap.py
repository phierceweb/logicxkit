"""A plug-in parameter lane's points carried from one plug-in to another through the family
vocabulary (`translate`): the lane's parameter index named through the source's map, its 0..1
points read over the parameter's stored range (`raw` in a third-party's map) or, for one of
Logic's own — numbered by its float index minus one — off its measured slider (`slider`),
converted into vocabulary units and written back through the target's map onto the target's
index. A switch is on from half a unit."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .automation import Lane, Point, read_automation
from .automation_write import set_param_lane
from .plugin_params import Table
from .slider import SWITCH_PER, along, interp, point_at, slider_by_name, units_at
from .translate import Item, Map


BAND_FIELDS = {"eq": ("on", "frequency", "gain", "q"), "multiband": ("threshold", "ratio", "level")}
LAYOUT_FIELD = {"eq": {"on": "enabled", "frequency": "frequency", "gain": "gain", "q": "q"},
                "multiband": {"threshold": "threshold", "ratio": "ratio", "level": "level"}}


@dataclass(frozen=True)
class Carried:
    lane: Lane                       # the target's lane
    name: str                        # the vocabulary item
    source_param: str
    target_param: str


def item_at(m: Map, index: int, table: Table | None) -> tuple[str, Item] | None:
    """The vocabulary item a lane's parameter index carries, or None: a third-party's index is
    its AU parameter id; one of Logic's own is its table float index minus one."""
    if m.component:
        return next(((n, i) for n, i in m.items.items() if i.id == index), None)
    if table is None:
        return None
    param = next((p for p in table.params if p.index == index + 1), None)
    if param is None:
        return None
    return next(((n, i) for n, i in m.items.items() if i.param == param.name), None)


def index_of(m: Map, name: str, table: Table | None) -> int | None:
    item = m.items.get(name)
    if item is None:
        return None
    if m.component:
        return item.id
    if table is None:
        return None
    param = next((p for p in table.params if p.name == item.param), None)
    return None if param is None else param.index - 1


def to_vocab(m: Map, item: Item, value: float) -> float | bool:
    """A point's 0..1 as the vocabulary value: a third-party's over its stored range, one of
    Logic's own through its slider (units floored, clamped at the top)."""
    if m.component:
        lo, hi = item_raw(m, item)
        return item.to_vocab(lo + value * (hi - lo))
    if item.switch:
        return value * SWITCH_PER >= 0.5
    per, offset, curve = _slider(m, item)
    return item.to_vocab(interp(curve, units_at(value, per, offset, curve[-1][0])))


def to_point(m: Map, item: Item, value: float | bool) -> float:
    """A vocabulary value as the target's 0..1 point, clamped to its range."""
    if m.component:
        lo, hi = item_raw(m, item)
        stored = item.to_stored(value)
        return min(1.0, max(0.0, (stored - lo) / (hi - lo))) if hi != lo else 0.0
    if item.switch:
        return 1.0 if value else 0.0
    per, offset, curve = _slider(m, item)
    return point_at(interp(tuple((y, x) for x, y in curve), item.to_stored(value)), per, offset)


def item_raw(m: Map, item: Item) -> tuple[float, float]:
    raw = m.raw.get("items", {}).get(_name(m, item), {}).get("raw")
    if not raw:
        raise ValueError(f"{m.plugin} {item.param}: the map has no `raw` range for its automation")
    return float(raw[0]), float(raw[1])


def _slider(m: Map, item: Item) -> tuple[float, float, tuple[tuple[float, float], ...]]:
    """(units per 1.0 of automation, the offset, the slider's (units, value) points)."""
    return slider_by_name(m, item.param)


def _name(m: Map, item: Item) -> str:
    return next(n for n, i in m.items.items() if i is item)


def _slots(m: Map) -> list[dict]:
    slots = m.raw.get("slots", [])
    return [slot for entries in slots.values() for slot in entries] if isinstance(slots, dict) else list(slots)


def band_field_at(m: Map, index: int, table: Table | None) -> tuple[int, str] | None:
    """(band number, field) a lane's parameter index names in a band family's map, or None."""
    if m.component:
        lay = m.raw["bands"]
        n, off = divmod(index, lay["stride"])
        if n >= lay["count"]:
            return None
        raw_field = next((k for k, v in lay.items() if k not in ("count", "stride") and v == off), None)
        field = next((f for f, lf in LAYOUT_FIELD[m.family].items() if lf == raw_field), None)
        return (n + 1, field) if field else None
    if table is None:
        return None
    param = next((p.name for p in table.params if p.index == index + 1), None)
    for number, slot in enumerate(_slots(m), 1):
        for field, name in slot.items():
            if name == param and field in BAND_FIELDS[m.family]:
                return number, field
    return None


def band_index_of(m: Map, placement, field: str, table: Table | None) -> int | None:
    """The parameter index of ``field`` on the target's placement: a slot's field names for one
    of Logic's own, a band number for a third-party's layout."""
    if m.component:
        lay, raw_field = m.raw["bands"], LAYOUT_FIELD[m.family].get(field)
        if raw_field not in lay or not isinstance(placement, int):
            return None
        return (placement - 1) * lay["stride"] + lay[raw_field]
    if not isinstance(placement, dict) or table is None:
        return None
    p = next((p for p in table.params if p.name == placement.get(field)), None)
    return None if p is None else p.index - 1


def _band_raw(m: Map, field: str) -> tuple[float, float]:
    raw = m.raw.get("band_raw", {}).get(LAYOUT_FIELD[m.family][field])
    if not raw:
        raise ValueError(f"{m.plugin}: the map has no `band_raw` range for {field}")
    return float(raw[0]), float(raw[1])


def band_to_vocab(m: Map, field: str, value: float, param: str | None = None) -> float | bool:
    """A point's 0..1 as the field's plain value — Hz, dB, Q, a ratio, on/off."""
    if m.component:
        lo, hi = _band_raw(m, field)
        stored = lo + value * (hi - lo)
        if field == "on":
            return stored >= 0.5
        if field == "frequency" and m.raw.get("frequency") == "log2":
            return 2 ** stored
        if field == "q" and m.raw.get("q_curve"):
            return interp(tuple((float(x), float(y)) for x, y in m.raw["q_curve"]), stored)
        if m.family == "multiband" and field in m.raw.get("curves", {}):
            return interp(tuple((float(x), float(y)) for x, y in m.raw["curves"][field]), stored)
        return stored
    if field == "on":
        return value * SWITCH_PER >= 0.5
    per, offset, curve = slider_by_name(m, param)
    return along(curve, units_at(value, per, offset, curve[-1][0]))


def band_to_point(m: Map, field: str, vocab: float | bool, param: str | None = None) -> float:
    """A field's plain value as the target's 0..1 point, clamped."""
    if m.component:
        lo, hi = _band_raw(m, field)
        if field == "on":
            stored = 1.0 if vocab else 0.0
        elif field == "frequency" and m.raw.get("frequency") == "log2":
            stored = math.log2(float(vocab))
        elif field == "q" and m.raw.get("q_curve"):
            stored = interp(tuple((float(y), float(x)) for x, y in m.raw["q_curve"]), float(vocab))
        elif m.family == "multiband" and field in m.raw.get("curves", {}):
            stored = interp(tuple((float(y), float(x)) for x, y in m.raw["curves"][field]), float(vocab))
        else:
            stored = float(vocab)
        return min(1.0, max(0.0, (stored - lo) / (hi - lo))) if hi != lo else 0.0
    if field == "on":
        return 1.0 if vocab else 0.0
    per, offset, curve = slider_by_name(m, param)
    return point_at(along(curve, float(vocab), inverse=True), per, offset)


def carry_band_lane(lane: Lane, src: Map, dst: Map, src_table: Table | None, dst_table: Table | None,
                    assignment: dict, notes: list[str]) -> Lane | None:
    """A band family's lane: the source band's field onto the target band the plan placed it in."""
    at = band_field_at(src, lane.param_index, src_table)
    if at is None:
        fields = ("frequency, gain, Q or on/off" if src.family == "eq"
                  else "threshold, ratio or level (an expander's rows have no analogue in a one-mode band)")
        notes.append(f"lane {lane.parameter}: not a band's {fields} in {src.plugin}; dropped")
        return None
    number, field = at
    placement = assignment.get(number)
    if placement is None:
        notes.append(f"lane {lane.parameter} (band {number} {field}): band {number} has no place in {dst.plugin}; dropped")
        return None
    index = band_index_of(dst, placement, field, dst_table)
    if index is None:
        notes.append(f"lane {lane.parameter} (band {number} {field}): no analogue in {dst.plugin}; dropped")
        return None
    src_param = None if src.component else _slots(src)[number - 1].get(field)
    dst_param = None if dst.component else placement.get(field)
    try:
        points = tuple(Point(p.tick, band_to_point(dst, field, band_to_vocab(src, field, p.value, src_param), dst_param), p.fraction)
                       for p in lane.points)
    except ValueError as e:
        notes.append(f"lane {lane.parameter} (band {number} {field}): {e}; dropped")
        return None
    label = f"insert {lane.slot or 1} parameter {index}"
    return Lane(label, None, index, points, lane.region, slot=lane.slot)


def carry_lane(lane: Lane, src: Map, dst: Map, src_table: Table | None, dst_table: Table | None,
               notes: list[str], assignment: dict | None = None) -> Lane | None:
    """The lane on the target's parameter with its points converted, or None with a note."""
    if src.family in BAND_FIELDS:
        return carry_band_lane(lane, src, dst, src_table, dst_table, assignment or {}, notes)
    found = item_at(src, lane.param_index, src_table)
    if found is None:
        notes.append(f"lane {lane.parameter}: {src.plugin} has no vocabulary item there; dropped")
        return None
    name, item = found
    index = index_of(dst, name, dst_table)
    if index is None:
        notes.append(f"lane {lane.parameter} ({name}): no analogue in {dst.plugin}; dropped")
        return None
    target = dst.items[name]
    try:
        points = tuple(Point(p.tick, to_point(dst, target, to_vocab(src, item, p.value)), p.fraction) for p in lane.points)
    except ValueError as e:
        notes.append(f"lane {lane.parameter} ({name}): {e}; dropped")
        return None
    label = f"insert {lane.slot or 1} parameter {index}"
    if (short := _short_slider(dst, target)) is not None:
        notes.append(f"lane {lane.parameter} ({name}): {dst.plugin}'s {target.param} slider spans units 0..{short[0]:g} of "
                     f"{short[1]:g} per 1.0, so a point above {short[0] / short[1]:.2f} sits at its top: nearly a switch")
    return Lane(label, None, index, points, lane.region, slot=lane.slot)


def _short_slider(m: Map, item: Item) -> tuple[float, float] | None:
    """(top, per) of one of Logic's own sliders whose automation reaches past it by four times or
    more — the Compressor's Knee stops at unit 10 of 128 — else None."""
    if m.component or item.switch:
        return None
    try:
        per, _offset, curve = _slider(m, item)
    except ValueError:
        return None
    return (curve[-1][0], per) if curve[-1][0] * 4 <= per else None


def slot_lanes(data: bytes, track_object: int, slot: int) -> list[Lane]:
    """The track object's parameter lanes on insert ``slot`` (its own, not a region's)."""
    return [lane for a in read_automation(data) if a.track_object == track_object
            for lane in a.lanes if lane.slot == slot and not lane.region]


def carry_slot(data: bytes, track_object: int, slot: int, src: Map, dst: Map,
               src_table: Table | None, dst_table: Table | None, assignment: dict | None = None,
               lanes: list[Lane] | None = None) -> tuple[bytes, list[str]]:
    """Every parameter lane of the track object's insert ``slot`` — or ``lanes``, taken before the
    slot was emptied — carried from ``src`` to ``dst``: the old lanes cleared, the carried ones
    written on the target's indices; the notes say what was carried and what was dropped."""
    notes: list[str] = []
    lanes = slot_lanes(data, track_object, slot) if lanes is None else lanes
    if not lanes:
        return data, notes
    carried = []
    for lane in lanes:
        new = carry_lane(lane, src, dst, src_table, dst_table, notes, assignment)
        if new is not None:
            carried.append((lane, new))
    for lane in lanes:
        data = set_param_lane(data, track_object, lane.param_index, [], slot=slot)
    for lane, new in carried:
        data = set_param_lane(data, track_object, new.param_index, [(p.tick, p.value, p.fraction) for p in new.points], slot=slot)
        notes.append(f"lane {lane.parameter} -> {new.parameter}: {len(new.points)} point(s) carried")
    return data, notes
