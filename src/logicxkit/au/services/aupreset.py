"""AU ClassInfo dicts (.aupreset files and .cst/.logicx-embedded plists) -> typed state.

Two state shapes appear in the wild:

- the AU-standard ``data`` key — 12B header (8 reserved bytes + u32 BE pair
  count) + (u32 BE param id, f32 BE value) pairs. Classic FabFilter plugins
  (Pro-C 2, Pro-MB) store their whole state here; param ids match .ffp
  positions.
- vendor blob keys (``FabFilterPluginState``, ``jucePluginState``,
  ``Waves_XPst``, ``Line6PresetData``, …) — kept raw for the specialist
  decoders or the AU host.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from logicxkit.au.services.embed import fourcc

_IDENTITY_KEYS = ("type", "subtype", "manufacturer", "version", "name", "data")


@dataclass(frozen=True)
class AuState:
    type: str
    subtype: str
    manufacturer: str
    name: str | None
    param_pairs: list[tuple[int, float]] | None
    blobs: dict[str, bytes]


def _parse_pairs(blob: bytes) -> list[tuple[int, float]] | None:
    if len(blob) < 12:
        return None
    count = struct.unpack_from(">I", blob, 8)[0]
    if len(blob) != 12 + 8 * count:
        return None
    return [struct.unpack_from(">If", blob, 12 + 8 * i) for i in range(count)]


def parse_au_state(plist: dict) -> AuState:
    data = plist.get("data")
    name = plist.get("name")
    return AuState(
        type=fourcc(plist.get("type", 0)),
        subtype=fourcc(plist.get("subtype", 0)),
        manufacturer=fourcc(plist.get("manufacturer", 0)),
        name=name if isinstance(name, str) else None,
        param_pairs=_parse_pairs(data) if isinstance(data, bytes) else None,
        blobs={k: v for k, v in plist.items()
               if isinstance(v, bytes) and k not in _IDENTITY_KEYS},
    )
