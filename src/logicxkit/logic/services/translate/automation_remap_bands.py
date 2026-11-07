"""A band family's lanes carried across plug-ins (`automation_remap`): an EQ's or a multiband's
lane names a band and a field, carried onto the band the plan assigned it."""

from __future__ import annotations

import math

from ..regions.automation import Lane, Point
from ..mixer.plugin_params import Table
from ..mixer.slider import SWITCH_PER, along, interp, point_at, slider_by_name, units_at
from .translate import Map


BAND_FIELDS = {"eq": ("on", "frequency", "gain", "q"),
               "multiband": ("threshold", "ratio", "range", "level", "exp_threshold", "exp_ratio", "reduction")}
LAYOUT_FIELD = {"eq": {"on": "enabled", "frequency": "frequency", "gain": "gain", "q": "q"},
                "multiband": {"threshold": "threshold", "ratio": "ratio", "range": "range", "level": "level"}}
# A Multipressor band has a compressor and an expander side by side; a one-mode band (Pro-MB's)
# is one or the other, so a band crosses as one side and that side's rows are the band's.
EXPANDER_AS = {"exp_threshold": "threshold", "exp_ratio": "ratio", "reduction": "range"}
COMPRESSOR_SIDE = set(EXPANDER_AS.values())


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


def _side_field(field: str, side: str | None, placement, dst: Map) -> tuple[str | None, str | None]:
    """The target field a multiband lane lands on, given the side the plan crossed the band as:
    ``(field, the side whose rows stay behind)``. An expander's rows land on an expand band's
    one-mode fields; the other side's rows stay with the source."""
    expander = field in EXPANDER_AS
    if side == "expand":
        if field in COMPRESSOR_SIDE and not (isinstance(placement, dict) and "exp_threshold" in placement):
            return None, "compressor"
        if expander:
            return EXPANDER_AS[field], None
        if field in COMPRESSOR_SIDE and isinstance(placement, dict):      # a one-mode source into both sides
            return next(k for k, v in EXPANDER_AS.items() if v == field), None
        return field, None
    if expander:
        return (field, None) if isinstance(placement, dict) and field in placement else (None, "expander")
    return field, None


def carry_band_lane(lane: Lane, src: Map, dst: Map, src_table: Table | None, dst_table: Table | None,
                    assignment: dict, notes: list[str], modes: dict | None = None) -> Lane | None:
    """A band family's lane: the source band's field onto the target band the plan placed it in,
    as the side ``modes`` says the band crossed (a multiband's compress or expand)."""
    at = band_field_at(src, lane.param_index, src_table)
    if at is None:
        fields = "frequency, gain, Q or on/off" if src.family == "eq" else "threshold, ratio, range or level"
        notes.append(f"lane {lane.parameter}: not a band's {fields} in {src.plugin}; dropped")
        return None
    number, field = at
    placement = assignment.get(number)
    if placement is None:
        notes.append(f"lane {lane.parameter} (band {number} {field}): band {number} has no place in {dst.plugin}; dropped")
        return None
    target_field, stays = (field, None) if src.family == "eq" else _side_field(field, (modes or {}).get(number), placement, dst)
    if target_field is None:
        crossed = "expander" if stays == "compressor" else "compressor"
        notes.append(f"lane {lane.parameter} (band {number} {field}): band {number} crossed as its {crossed}; "
                     f"the {stays}'s {field} has no place in {dst.plugin}; dropped")
        return None
    index = band_index_of(dst, placement, target_field, dst_table)
    if index is None:
        notes.append(f"lane {lane.parameter} (band {number} {field}): no analogue in {dst.plugin}; dropped")
        return None
    src_param = None if src.component else _slots(src)[number - 1].get(field)
    dst_param = None if dst.component else placement.get(target_field)
    try:
        points = tuple(Point(p.tick, band_to_point(dst, target_field, band_to_vocab(src, field, p.value, src_param), dst_param), p.fraction)
                       for p in lane.points)
    except ValueError as e:
        notes.append(f"lane {lane.parameter} (band {number} {field}): {e}; dropped")
        return None
    label = f"insert {lane.slot or 1} parameter {index}"
    return Lane(label, None, index, points, lane.region, slot=lane.slot)
