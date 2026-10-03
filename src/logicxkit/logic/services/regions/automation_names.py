"""What a plug-in parameter lane addresses: the plug-in in its insert, the parameter's name and a
point's 0..1 in the parameter's own unit — `automation --set TRACK:slot N NAME` read back.

One of Logic's own is named by its parameter table (lane index = float index - 1) and valued
through its measured slider; a third-party by its AU table (lane index = parameter id) over the
table's range, else by its translation map's vocabulary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from logicxkit.au.services.tables import load_table

from ..translate.automation_remap import item_raw
from ..mixer.plugin_names import plugin_name
from ..mixer.plugin_params import load_tables, table_for
from ..mixer.plugins import plugin_identity
from ..mixer.slider import SWITCH_PER, along, slider_by_name, units_at
from ..mixer.slot_width import plugin_variant
from ..stream.stream import HEADER
from ..translate.translate import load_maps, map_for
from ..mixer.transplant import slot_at

Value = float | bool | None


@dataclass(frozen=True)
class LaneTarget:
    plugin: str
    name: str | None                                  # None: no table or map names the index
    unit: str = ""
    _value: Callable[[float], Value] | None = None

    def value(self, point: float) -> Value:
        """The point in the parameter's own unit; None where its scale is not measured."""
        return None if self._value is None else self._value(point)


def _native(payload: bytes, identity: tuple, index: int, tables, maps) -> LaneTarget:
    table = table_for(tables, identity[1], plugin_variant(payload))
    plugin = table.name if table else plugin_name(payload) or f"type {identity[1]}"
    param = next((p for p in (table.params if table else ()) if p.index == index + 1), None)
    if param is None:
        return LaneTarget(plugin, None)
    m = map_for(payload, maps)
    if tuple(param.choices) == ("Off", "On") or (m and any(i.switch and i.param == param.name for i in m.items.values())):
        return LaneTarget(plugin, param.name, "", lambda point: point * SWITCH_PER >= 0.5)
    try:
        per, offset, curve = slider_by_name(m, param.name) if m else (None, None, None)
    except ValueError:
        curve = None
    if not curve:
        return LaneTarget(plugin, param.name, param.unit)
    return LaneTarget(plugin, param.name, param.unit,
                      lambda point: round(along(curve, units_at(point, per, offset, curve[-1][0])), 4))


def _third_party(payload: bytes, identity: tuple, index: int, maps) -> LaneTarget:
    _type, subtype, manu = identity[1:]
    table = load_table(manu, subtype) or {}
    plugin = plugin_name(payload) or str(table.get("component", "")).rpartition(": ")[2] or f"{manu}/{subtype}"
    entry = next((e for e in table.get("params", []) if e.get("id") == index), None)
    if entry is not None:
        lo, hi = float(entry.get("min", 0)), float(entry.get("max", 1))
        unit = "" if entry.get("unit") in (None, "generic", "indexed") else str(entry["unit"])
        return LaneTarget(plugin, str(entry["name"]), unit, lambda point: round(lo + point * (hi - lo), 4))
    m = map_for(payload, maps)
    found = next(((n, i) for n, i in (m.items.items() if m else ()) if i.id == index), None)
    if found is None:
        return LaneTarget(plugin, None)
    name, item = found
    try:
        lo, hi = item_raw(m, item)
    except ValueError:
        return LaneTarget(plugin, name)
    return LaneTarget(plugin, name, "", lambda point: item.to_vocab(lo + point * (hi - lo)))


def lane_target(data: bytes, owner: int, slot: int, index: int, *, tables=None, maps=None) -> LaneTarget | None:
    """What parameter ``index`` of insert ``slot`` (the mixer's, from 1) on channel ``owner``
    is; None when that insert holds no plug-in this can identify."""
    record = slot_at(data, owner, slot)
    identity = plugin_identity(record.raw[HEADER:]) if record is not None else None
    if identity is None:
        return None
    payload = record.raw[HEADER:]
    maps = load_maps() if maps is None else maps
    if identity[0] == "native":
        return _native(payload, identity, index, load_tables() if tables is None else tables, maps)
    return _third_party(payload, identity, index, maps)
