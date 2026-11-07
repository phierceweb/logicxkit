"""A plug-in parameter lane's points carried from one plug-in to another through the family
vocabulary (`translate`): the lane's parameter index named through the source's map, its 0..1
points read over the parameter's stored range (`raw` in a third-party's map) or, for one of
Logic's own — numbered by its float index minus one — off its measured slider (`slider`),
converted into vocabulary units and written back through the target's map onto the target's
index. A switch is on from half a unit."""

from __future__ import annotations

from dataclasses import dataclass

from ..regions.automation import Lane, Point, read_automation
from ..regions.automation_write import set_param_lane
from ..mixer.plugin_params import Table
from ..mixer.slider import SWITCH_PER, interp, point_at, slider_by_name, units_at
from .automation_remap_bands import BAND_FIELDS, carry_band_lane
from .translate import Item, Map


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


def carry_lane(lane: Lane, src: Map, dst: Map, src_table: Table | None, dst_table: Table | None,
               notes: list[str], assignment: dict | None = None, modes: dict | None = None) -> Lane | None:
    """The lane on the target's parameter with its points converted, or None with a note."""
    if src.family in BAND_FIELDS:
        return carry_band_lane(lane, src, dst, src_table, dst_table, assignment or {}, notes, modes)
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
               lanes: list[Lane] | None = None, modes: dict | None = None) -> tuple[bytes, list[str]]:
    """Every parameter lane of the track object's insert ``slot`` — or ``lanes``, taken before the
    slot was emptied — carried from ``src`` to ``dst``: the old lanes cleared, the carried ones
    written on the target's indices; the notes say what was carried and what was dropped."""
    notes: list[str] = []
    lanes = slot_lanes(data, track_object, slot) if lanes is None else lanes
    if not lanes:
        return data, notes
    carried = []
    for lane in lanes:
        new = carry_lane(lane, src, dst, src_table, dst_table, notes, assignment, modes)
        if new is not None:
            carried.append((lane, new))
    for lane in lanes:
        data = set_param_lane(data, track_object, lane.param_index, [], slot=slot)
    for lane, new in carried:
        data = set_param_lane(data, track_object, new.param_index, [(p.tick, p.value, p.fraction) for p in new.points], slot=slot)
        notes.append(f"lane {lane.parameter} -> {new.parameter}: {len(new.points)} point(s) carried")
    return data, notes
