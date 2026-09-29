"""Settings across plug-ins of one family, through a vocabulary. A map per plug-in
(`translate/<Manu>_<Sub>.json` for a third-party, `translate/logic-<type>.json` for one of
Logic's own) says which of its parameters carries each vocabulary item and how: as stored
(the same unit), `scale` (vocabulary = stored x scale; `floor` is the stored value meaning
silent), `curve` (sampled stored-to-vocabulary points, interpolated both ways), `switch`
(nonzero is on), `min`/`max` (the target's range, clamped to with a note), `step` (the grid
the plug-in keeps its value on — Logic rounds a written value to it on load, so the plan
rounds first) and, for one of Logic's own, the slider's measured positions (`automation` in the
map — a write lands on the nearest one, the value Logic keeps). Translating A to B reads A's
map backwards into the vocabulary and B's forwards; an item without a home in B is reported,
never guessed, and an `approx` item says so in the report. A plan for one of Logic's own names
its table parameters with stored values; one for a third-party names the vocabulary items its
map writes (`translate_write`).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ...au.services.aupreset import parse_au_state
from ...au.services.embed import find_au_plists
from ...au.services.ffp import parse_ffp
from ...au.services.sonible import decode_sonible
from ...utils.data import MissingData, data_dirs
from .._binary import find_blocks, read_block_floats
from .plugin_params import decode, load_tables, table_for
from .slider import interp, snap
from .slot_width import plugin_variant
from .translate_izotope import izotope_module, izotope_values

VOCABULARY: dict[str, dict[str, str]] = {                  # family -> item -> unit
    "compressor": {"threshold": "dB", "ratio": ":1", "attack": "ms", "release": "ms", "knee": "dB",
                   "make_up": "dB", "mix": "%", "auto_release": "", "auto_gain": "", "lookahead": "ms",
                   "input_gain": "dB", "output_gain": "dB"},
    "gate": {"threshold": "dB", "hysteresis": "dB", "range": "dB", "attack": "ms", "hold": "ms", "release": "ms",
             "lookahead": "ms", "low_cut": "Hz", "high_cut": "Hz", "filter_on": ""},
    "multiband": {"mix": "%", "input_gain": "dB", "output_gain": "dB", "lookahead": "ms", "lookahead_on": "",
                  "auto_gain": ""},                       # the globals; the bands carry the rest (`translate_mb`)
}


@dataclass(frozen=True)
class Item:
    param: str
    id: int | None = None                # an AU parameter id
    field: str | None = None             # a field of a vendor blob the map's decoder reads (`3.36`)
    scale: float | None = None
    floor: float | None = None
    curve: tuple[tuple[float, float], ...] = ()
    switch: bool = False
    max: float | None = None
    step: float | None = None
    approx: str | None = None
    min: float | None = None

    def to_vocab(self, stored: float) -> float | bool | None:
        """The vocabulary value of a stored one; None when the stored value means silent."""
        if self.switch:
            return stored != 0
        if self.floor is not None and stored <= self.floor:
            return None
        if self.curve:
            return interp(self.curve, stored)
        return stored * self.scale if self.scale is not None else stored

    def to_stored(self, value: float | bool) -> float:
        if self.switch:
            return 1.0 if value else 0.0
        if self.curve:
            return interp(tuple((y, x) for x, y in self.curve), float(value))
        return float(value) / self.scale if self.scale is not None else float(value)


@dataclass(frozen=True)
class Map:
    family: str
    plugin: str
    items: dict[str, Item]
    component: tuple[str, str, str] | None = None     # (type, subtype, manufacturer) of a third-party
    type: int | None = None                            # one of Logic's own: block type and variant base
    variant: int | None = None
    evidence: str = ""
    decoder: str | None = None                         # "sonible" (protobuf), "ffbs" (FabFilter), "izotope" (zlib JSON)
    not_carried: dict[str, str] = field(default_factory=dict)   # what this plug-in has that the vocabulary does not, and why

    raw: dict = field(default_factory=dict, compare=False, repr=False)   # the whole map, for a structured family (eq)

    @classmethod
    def from_dict(cls, d: dict) -> Map:
        items = {name: Item(i["param"], i.get("id"), i.get("field"), i.get("scale"), i.get("floor"),
                            tuple((float(x), float(y)) for x, y in i.get("curve", ())), bool(i.get("switch")),
                            i.get("max"), i.get("step"), i.get("approx"), min=i.get("min"))
                 for name, i in d.get("items", {}).items()}
        comp = tuple(d["component"]) if d.get("component") else None
        return cls(d["family"], d["plugin"], items, comp, d.get("type"), d.get("variant"), d.get("evidence", ""),
                   d.get("decoder"), dict(d.get("not_carried", {})), d)


@dataclass
class Settings:
    """A slot's settings in vocabulary terms; ``silent`` names items stored as off/-inf; an
    EQ's come as ``bands`` and a ``master`` gain instead."""
    map: Map
    values: dict[str, float | bool] = field(default_factory=dict)
    silent: list[str] = field(default_factory=list)
    bands: list = field(default_factory=list)
    master: float | None = None
    notes: list[str] = field(default_factory=list)      # what the reader saw that the plan should repeat


@dataclass
class Plan:
    """What a target gets: its parameter names with values (a third-party EQ's as ``bands``),
    and what could not be carried."""
    target: Map
    values: dict[str, float | str | bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    bands: list = field(default_factory=list)
    source: Map | None = None
    assignment: dict = field(default_factory=dict)   # a band family: source band number -> the target's slot or band number


def load_maps(dirs: list[Path] | None = None) -> list[Map]:
    if dirs is None and not (dirs := data_dirs("translate")):
        raise MissingData("translate/: no translation maps in the data root or the package — "
                          "a broken install, not a plug-in without a map")
    out: dict[str, Map] = {}
    for d in dirs:
        for path in sorted(Path(d).glob("*.json")):
            out.setdefault(path.stem, Map.from_dict(json.loads(path.read_text())))
    return list(out.values())


def maps_for(payload: bytes, maps: list[Map]) -> list[Map]:
    """Every map of the plug-in a slot payload holds — by block type and variant, or AU
    component — one per family it carries (Neutron 5 has a compressor, a gate and an EQ)."""
    blocks = find_blocks(payload)
    if blocks:
        type_id, variant = blocks[0][1], plugin_variant(payload)
        return [m for m in maps if m.type == type_id and (m.variant is None or variant is None or m.variant == variant)]
    for _off, plist in find_au_plists(payload):
        if "manufacturer" in plist:
            st = parse_au_state(plist)
            comp = (st.type, st.subtype, st.manufacturer)
            return [m for m in maps if m.component == comp]
    return []


def map_for(payload: bytes, maps: list[Map]) -> Map | None:
    """The first map of the plug-in a slot payload holds (`maps_for` for all of them)."""
    found = maps_for(payload, maps)
    return found[0] if found else None


def read_settings(payload: bytes, m: Map, tables: dict | None = None) -> Settings:
    """A slot's settings through its map: a third-party's from the AU state's id/value pairs,
    one of Logic's own from its float block by its parameter table."""
    out = Settings(m)
    if m.family == "eq":
        from .translate_eq import read_bands
        out.bands, out.master = read_bands(payload, m, tables if tables is not None else load_tables())
        if m.decoder == "izotope":
            _module, note = izotope_module(m, izotope_values(payload, m))
            out.notes += [note] if note else []
        return out
    if m.family == "multiband":
        from .translate_mb import read_mbands
        out.bands = read_mbands(payload, m, tables if tables is not None else load_tables())
    if m.component:
        state = next((parse_au_state(plist) for _off, plist in find_au_plists(payload) if "manufacturer" in plist), None)
        if state is None:
            raise ValueError(f"{m.plugin}: the slot holds no AU state")
        if m.decoder == "sonible":
            blob = state.blobs.get("jucePluginState")
            block = ((decode_sonible(blob) if blob else None) or {}).get("fields", {}).get("3", {})
            values = {f"3.{k}": v for k, v in block.items() if isinstance(v, (int, float))}
            stored = {name: values.get(item.field) for name, item in m.items.items()}
        elif m.decoder == "izotope":                   # zlib over typed JSON: real units by module and name
            values = izotope_values(payload, m)
            module, note = izotope_module(m, values)
            if note:
                out.notes.append(note)
            stored = {name: values.get(f"{module}/{item.field}") for name, item in m.items.items()}
        elif m.decoder == "ffbs":                      # FabFilter's binary state: the .ffp layout, values by id
            blob = state.blobs.get("FabFilterPluginState")
            if not blob:
                raise ValueError(f"{m.plugin}: the state holds no FabFilterPluginState")
            values = parse_ffp(blob).values
            stored = {name: (values[item.id] if item.id is not None and item.id < len(values) else None)
                      for name, item in m.items.items()}
        else:
            pairs = dict(state.param_pairs or [])
            if not pairs:
                raise ValueError(f"{m.plugin}: the state holds no id/value pairs to read")
            stored = {name: pairs.get(item.id) for name, item in m.items.items()}
    else:
        blocks = find_blocks(payload)
        table = table_for(tables if tables is not None else load_tables(), m.type, plugin_variant(payload))
        if not blocks or table is None:
            raise ValueError(f"{m.plugin}: no parameter table to read the block by")
        idx, _t, n = blocks[0]
        decoded = decode(table, read_block_floats(payload, idx, n))
        stored = {name: _number(decoded.get(item.param)) for name, item in m.items.items()}
    for name, item in m.items.items():
        if stored.get(name) is None:
            continue
        value = item.to_vocab(stored[name])
        if value is None:
            out.silent.append(name)
        else:
            out.values[name] = value
    return out


def _number(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, str):
        return {"off": 0.0, "on": 1.0}.get(v.lower())
    return float(v)


def plan(settings: Settings, target: Map) -> Plan:
    """The target's parameters set to the source's vocabulary values, with the report."""
    if settings.map.family != target.family:
        raise ValueError(f"{settings.map.plugin} is a {settings.map.family}, {target.plugin} a {target.family}")
    out = Plan(target, source=settings.map)
    if target.family == "eq":
        from .translate_eq import plan_bands, plan_bands_into
        if target.component:
            out.bands, out.notes, out.assignment = plan_bands_into(settings.bands, settings.master, settings.map, target)
        else:
            out.values, out.notes, out.assignment = plan_bands(settings.bands, settings.master, settings.map, target)
        return out
    if target.family == "multiband":
        from .translate_mb import plan_mbands
        out.values, out.bands, out.notes, out.assignment = plan_mbands(settings, target)
        return out
    units = VOCABULARY[target.family]
    for name, value in settings.values.items():
        item = target.items.get(name)
        if item is None:
            out.notes.append(f"{name} {_show(value, units[name])}: no analogue in {target.plugin}")
            continue
        carried, note = clamp(item, value)
        if note:
            out.notes.append(f"{name} {_show(value, units[name])}: {target.plugin}'s {item.param} {note} "
                             f"{_show(carried, units[name])}, set there")
        if target.component:                       # a third-party: the vocabulary value, its map writes it
            out.values[name] = carried if item.switch else round(float(carried), 4)
            if item.approx:
                out.notes.append(f"{name} {_show(value, units[name])} -> {item.param}: approximate ({item.approx})")
            continue
        stored = item.to_stored(carried)
        if item.step and not item.switch:
            stored = round(math.floor(stored / item.step + 0.5 + 1e-9) * item.step, 6)   # half up, float32 noise aside
        if not item.switch:
            stored = snap(target, item.param, stored)
        out.values[item.param] = "On" if item.switch and stored else "Off" if item.switch else round(stored, 4)
        if item.approx:
            out.notes.append(f"{name} {_show(value, units[name])} -> {item.param} {out.values[item.param]}: approximate ({item.approx})")
    for name in settings.silent:
        out.notes.append(f"{name}: silent (-inf) in {settings.map.plugin}; {target.plugin} keeps its own")
    out.notes.extend(settings.notes)
    for what, why in settings.map.not_carried.items():
        out.notes.append(f"{settings.map.plugin} {what}: {why}")
    return out


def clamp(item: Item, value) -> tuple[float | bool, str | None]:
    """``value`` within the item's range, and how it moved ("stops at" / "starts at") if it did."""
    if item.switch:
        return value, None
    if item.max is not None and float(value) > item.max:
        return item.max, "stops at"
    if item.min is not None and float(value) < item.min:
        return item.min, "starts at"
    return value, None


def _show(value, unit: str) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    text = f"{value:.4g}"
    if "e" in text:                                # four figures written out: 20000, not 2e+04
        text = format(Decimal(text), "f")
    return f"{text}{unit}" if unit in (":1", "%") else f"{text} {unit}".rstrip()
