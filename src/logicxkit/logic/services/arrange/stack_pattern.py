"""Logic's own first stack of a kind on a blank project, packaged: what a session with no stack
patterns a new one on (`stack-folder-12.3.1.json`, `stack-summing-12.3.1.json`)."""

from __future__ import annotations

import json
import struct

from ....utils.data import data_file
from ..mixer.mixer import CHANNEL_BASE_AT
from ..mixer.slots import slot_index_base
from ..stream.sequence import index_table, table_entries
from ..stream.stream import HEADER
from .environment import ENV_TAG, STAMP_AT, name_end, object_id_of, object_stamp

_DATA, _SUMMING_DATA = "stack-folder-12.3.1.json", "stack-summing-12.3.1.json"
_AFTER_NAME_AT = (10, 12)           # 2 and 250 on the packaged header; Logic saved a written one with 0


def packaged_pattern(name: str = _DATA) -> dict[str, bytes]:
    """Logic's own first stack of a kind on a blank project: the strip, the header object, its
    arrange row and its flat row (roles `strip`, `object`, `row`, `flat_row`)."""
    t = json.loads(data_file("logic", name).read_text())
    return {role: bytes.fromhex(r["header"]) + bytes.fromhex(r["payload"]) for role, r in t["records"].items()}


def stamped_last(obj: bytes, records) -> bytes:
    """``obj`` stamped past every existing object."""
    out = bytearray(obj)
    top = max(object_stamp(r.raw) for r in records if r.tag == ENV_TAG and object_id_of(r) is not None)
    struct.pack_into("<I", out, HEADER + STAMP_AT, top)
    return bytes(out)


def packaged_aux(records) -> dict[str, bytes]:
    """The pattern for a session with no aux track: the header object, arrange row and flat row
    of Logic's own summing stack on a blank project, with the two bytes it carries past the name
    cleared: Logic cleared them when it saved a header written with them."""
    packaged = packaged_pattern(_SUMMING_DATA)
    obj = bytearray(stamped_last(packaged["object"], records))
    end = HEADER + name_end(obj[HEADER:])
    for at in _AFTER_NAME_AT:
        obj[end + at] = 0
    return {**packaged, "object": bytes(obj)}


def first_stack(data: bytes, records) -> tuple[int, bytes, bytes, bytes]:
    """What a session with no folder stack patterns one on -> ``(like, object, strip, row)``:
    Logic's own packaged pieces, the strip with the session's slot base, the object stamped past
    every existing one, the sequence shaped like the highest-indexed object's."""
    packaged = packaged_pattern()
    strip = bytearray(packaged["strip"])
    strip[HEADER + CHANNEL_BASE_AT] = slot_index_base(data)
    table = records[index_table(records)].raw[HEADER:]
    like = max(table_entries(table), key=lambda e: e[2])[1]
    return like, stamped_last(packaged["object"], records), bytes(strip), packaged["row"]
