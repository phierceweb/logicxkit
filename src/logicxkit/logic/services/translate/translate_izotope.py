"""iZotope's Neutron state read through a translation map: its scalar parameters by
``Module/Parameter``, and which of the map's DSP modules is live."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....au.services.embed import find_au_plists
from ....au.services.izotope import dsp_values, parse_izotope

if TYPE_CHECKING:
    from .translate import Map


def izotope_values(payload: bytes, m: Map) -> dict:
    """The iZotope state's scalar parameters, keyed ``Module/Parameter``."""
    data = next((pl.get("data") for _off, pl in find_au_plists(payload) if "manufacturer" in pl), None)
    if not isinstance(data, bytes):
        raise ValueError(f"{m.plugin}: the state holds no iZotope blob")
    return dsp_values(parse_izotope(data))


def izotope_module(m: Map, values: dict) -> tuple[str | None, str | None]:
    """The DSP element the map reads, the first of its ``modules`` that is not bypassed, and a
    note when every one is."""
    modules = m.raw.get("modules") or []
    live = [mod for mod in modules if not values.get(f"{mod}/Bypass", False)]
    if live:
        return live[0], None
    return (modules[0], f"{m.plugin}'s {modules[0]} is bypassed") if modules else (None, None)
