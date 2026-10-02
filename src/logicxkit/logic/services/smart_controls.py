"""The channel's Smart Control mappings, the first of the two keyed-archive records past its
reference key: an `NSMutableDictionary` of knob number -> `NSMutableArray` of
`MAPlugInParameterMapping`, each naming the plug-in it reads by **slot index** (`slot`) and
parameter (`parameterIndex_1`). Moving a plug-in to another slot without moving its mappings
made Logic reset the channel on load (2026-09-21), so a slot move carries them along.

Record layout: payload `+16` u32 the bplist's size, the bplist from `+20`, a 16-byte tail.
"""

from __future__ import annotations

import plistlib
import struct

from .stream import HEADER

SIZE_AT, PLIST_AT = 16, 20
MAPPING = "MAPlugInParameterMapping"


def mapping_slots(raw: bytes) -> list[int]:
    """Every mapping's slot index, in archive order."""
    plist = _plist(raw)
    objects = plist["$objects"]
    return [_value(objects, m["slot"]) for m in _mappings(objects)]


def shift_mapping_slots(raw: bytes, *, from_index: int, by: int) -> bytes:
    """The archive record with every mapping at a slot index >= ``from_index`` moved ``by``.
    Ints are shared objects in a keyed archive, so a moved mapping gets an int of its own."""
    plist = _plist(raw)
    objects = plist["$objects"]
    changed = False
    for mapping in _mappings(objects):
        slot = _value(objects, mapping["slot"])
        if slot is not None and slot >= from_index:
            objects.append(slot + by)
            mapping["slot"] = plistlib.UID(len(objects) - 1)
            changed = True
    return _rewrite(raw, plist) if changed else raw


def drop_mapping_slot(raw: bytes, index: int) -> bytes:
    """The archive record without the mappings of slot ``index`` (their plug-in is gone);
    a knob left with no mapping keeps an empty array, as Logic writes one."""
    plist = _plist(raw)
    objects = plist["$objects"]
    doomed = {i for i, o in enumerate(objects)
              if isinstance(o, dict) and o in _mappings(objects) and _value(objects, o["slot"]) == index}
    if not doomed:
        return raw
    for o in objects:
        if isinstance(o, dict) and "NS.objects" in o:
            o["NS.objects"] = [u for u in o["NS.objects"] if not (isinstance(u, plistlib.UID) and u.data in doomed)]
    for i in doomed:                       # keep every other UID where it is
        objects[i] = "$null"
    return _rewrite(raw, plist)


def _rewrite(raw: bytes, plist: dict) -> bytes:
    body = plistlib.dumps(plist, fmt=plistlib.FMT_BINARY)
    payload = bytearray(raw[HEADER:])
    old = struct.unpack_from("<I", payload, SIZE_AT)[0]
    payload[PLIST_AT:PLIST_AT + old] = body
    struct.pack_into("<I", payload, SIZE_AT, len(body))
    out = bytearray(raw[:HEADER]) + payload
    struct.pack_into("<I", out, 28, len(payload))
    return bytes(out)


def _plist(raw: bytes) -> dict:
    payload = raw[HEADER:]
    size = struct.unpack_from("<I", payload, SIZE_AT)[0]
    return plistlib.loads(payload[PLIST_AT:PLIST_AT + size])


def _mappings(objects: list) -> list[dict]:
    out = []
    for o in objects:
        if isinstance(o, dict) and "$class" in o:
            cls = objects[o["$class"].data]
            if isinstance(cls, dict) and cls.get("$classname") == MAPPING and "slot" in o:
                out.append(o)
    return out


def _value(objects: list, v):
    v = objects[v.data] if isinstance(v, plistlib.UID) else v
    return v if isinstance(v, int) and not isinstance(v, bool) else None
