"""Slot key bases. Projects made before Logic 11.2 number a channel's plugin slots from key
2 and its property records (the 192-byte state, the `.cst` reference, ...) from 10; Logic
12.3.1 numbers slots from 4 and, when it re-saves such a project, moves every key from the
slot base up by 2 (measured on Logic's re-saves of a 2020 project, 2026-09-05: slots 2, 3
-> 4, 5 and the state records 10, 12, 13 -> 12, 14, 15; sends at 0-2 unmoved). `rebase`
applies the same move.

Every channel record also carries the base it was written with, as u16 at +28 — 2 in the
old project, 4 in everything Logic 12 writes or converts. Left at 2 while the keys sit at 4,
Logic drops the plugin at slot 0 on any channel that also carries three sends; set to 4, the
same file keeps them (measured 2026-09-06). `rebase` sets it.
Logic's conversion also turns the u16 at +30 from 5 to 3 and moves property keys by 1 rather
than 2; both layouts load, and neither is touched here.
"""

from __future__ import annotations

import struct

from .channel_alloc import is_mixer_record
from .insert import HEADER, KEY_OFF, project_records, reassemble, slot_index_base
from .keyflags import sync_key_flags
from .sends import is_send
from .transplant import property_key_base
from .validate import require_full_walk, require_valid

MODERN_BASE = 4
SLOT_SHIFT = {2: 2}                  # old slot base -> how far Logic moves slot keys
PROPERTY_SHIFT = {2: 2}              # ... and property keys (the same distance)
CHANNEL_BASE_AT = 28                 # the channel record's own copy of its slot base


def channel_bases(data: bytes) -> dict[int, int]:
    """slot base -> how many channel records carry it at +28."""
    out: dict[int, int] = {}
    for r in project_records(data):
        if is_mixer_record(r):
            base = struct.unpack_from("<H", r.raw, HEADER + CHANNEL_BASE_AT)[0]
            out[base] = out.get(base, 0) + 1
    return out


def needs_rebase(data: bytes) -> bool:
    return slot_index_base(data) in SLOT_SHIFT


def rebase(data: bytes) -> tuple[bytes, dict]:
    """The project with its slot and property keys moved to Logic 12's layout -> ``(project,
    report)``; a project already there comes back unchanged."""
    base = slot_index_base(data)
    if base not in SLOT_SHIFT:
        return data, {"from": base, "to": base, "moved": 0}
    require_full_walk(data)
    prop = property_key_base(data)
    out, moved, marked = [], 0, 0
    for r in project_records(data):
        raw = r.raw
        if r.tag == b"UCuA" and r.key != 0xFFFF and r.key >= base and not is_send(r):
            shift = SLOT_SHIFT[base] if r.key < prop else PROPERTY_SHIFT[base]
            buf = bytearray(raw)
            struct.pack_into("<H", buf, KEY_OFF, r.key + shift)
            raw = bytes(buf)
            moved += 1
        elif is_mixer_record(r) and struct.unpack_from("<H", raw, HEADER + CHANNEL_BASE_AT)[0] == base:
            buf = bytearray(raw)
            struct.pack_into("<H", buf, HEADER + CHANNEL_BASE_AT, MODERN_BASE)
            raw = bytes(buf)
            marked += 1
        out.append(raw)
    result = sync_key_flags(reassemble(data, out))
    require_valid(result)
    if slot_index_base(result) != MODERN_BASE:
        raise ValueError(f"rebase left the slot base at {slot_index_base(result)}")
    return result, {"from": base, "to": MODERN_BASE, "moved": moved, "channels": marked}
