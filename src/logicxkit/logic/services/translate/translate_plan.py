"""A translation's plan: the target's parameters set from the source's vocabulary values
(`translate.read_settings`), clamped to the target's range and laid on its slider, with the report
of what could not be carried."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

from ..mixer.slider import slider_curve, snap
from .translate import VOCABULARY, Map, Settings, _show, clamp


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
    bypass: bool = False                             # the target goes in bypassed, as the source's element was
    modes: dict = field(default_factory=dict)        # a multiband: source band number -> the side it crossed as, compress or expand


def plan(settings: Settings, target: Map) -> Plan:
    """The target's parameters set to the source's vocabulary values, with the report."""
    bare = next((m for m in (settings.map, target) if m.family is None), None)
    if bare is not None:
        raise ValueError(f"{bare.plugin}'s map is a slider grid, not a translation map")
    if settings.map.family != target.family:
        raise ValueError(f"{settings.map.plugin} is a {settings.map.family}, {target.plugin} a {target.family}")
    _refuse_non_finite(settings)
    out = Plan(target, source=settings.map)
    if target.family == "eq":
        from .translate_eq import plan_bands, plan_bands_into
        if target.component:
            out.bands, out.notes, out.assignment = plan_bands_into(settings.bands, settings.master, settings.map, target)
        else:
            out.values, out.notes, out.assignment = plan_bands(settings.bands, settings.master, settings.map, target)
        out.notes.extend(_bypass_notes(out, settings, target))
        return out
    if target.family == "multiband":
        from .translate_mb import plan_mbands
        out.values, out.bands, out.notes, out.assignment, out.modes = plan_mbands(settings, target)
        out.notes.extend(_bypass_notes(out, settings, target))
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
        if item.step and not item.switch and slider_curve(target, item.param) is None:   # an unmeasured row: the vocabulary's step
            stored = round(math.floor(stored / item.step + 0.5 + 1e-9) * item.step, 6)
        if not item.switch:
            stored = snap(target, item.param, stored)                                  # a measured row: the slider's own unit
        out.values[item.param] = "On" if item.switch and stored else "Off" if item.switch else round(stored, 4)
        if item.approx:
            out.notes.append(f"{name} {_show(value, units[name])} -> {item.param} {out.values[item.param]}: approximate ({item.approx})")
    for name in settings.silent:
        out.notes.append(f"{name}: silent (-inf) in {settings.map.plugin}; {target.plugin} keeps its own")
    out.notes.extend(_bypass_notes(out, settings, target))
    for what, why in settings.map.not_carried.items():
        out.notes.append(f"{settings.map.plugin} {what}: {why}")
    return out


def _bypass_notes(out: Plan, settings: Settings, target: Map) -> list[str]:
    """The reader's notes; a bypassed source element has the target go in bypassed too."""
    if not settings.bypassed:
        return list(settings.notes)
    out.bypass = True
    return [f"{n}; {target.plugin} goes in bypassed" if n.endswith(" is bypassed") else n for n in settings.notes]


def _refuse_non_finite(settings: Settings) -> None:
    """A source value, band field or master gain that is not a finite number, refused before any
    path clamps it to a slider's end."""
    numbers = list(settings.values.items())
    for i, band in enumerate(settings.bands, 1):
        label = f"band {getattr(band, 'number', 0) or i}"
        for f in fields(band):
            value = getattr(band, f.name)
            if f.name == "slope" and value == math.inf:                             # a brickwall cut's slope
                continue
            if isinstance(value, tuple):
                numbers += [(f"{label} {f.name}[{k}]", x) for k, x in enumerate(value)]
            else:
                numbers.append((f"{label} {f.name}", value))
    if settings.master is not None:
        numbers.append(("master", settings.master))
    for name, value in numbers:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{name}: {value} is not a finite number")
