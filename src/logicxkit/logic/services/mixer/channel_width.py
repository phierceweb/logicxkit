"""A channel record's width, and widening whole channels with the slots they carry."""

from __future__ import annotations

import struct

from ..._binary import find_blocks
from .mixer import CHANNEL_FMT_AT, CHANNEL_TAG
from .slot_width import MONO, STEREO, set_slot_format
from ..stream.stream import BODY_START, HEADER, NO_KEY, TOTAL_AT, project_records
from ..stream.validate import require_full_walk, require_valid

# WIDTH, channel side: three bytes move together, not just the count at +123. The same on every
# session on hand, on both class versions, and on a stereo aux Logic itself wrote.
CHANNEL_WIDTH = {78: {MONO: 211, STEREO: 215}, 86: {MONO: 0, STEREO: 1},
                 CHANNEL_FMT_AT: {MONO: MONO, STEREO: STEREO}}


def set_channel_format(raw: bytes, fmt: int) -> bytes:
    """Rewrite a channel record's width. Nothing else in the record moves."""
    payload_len = len(raw) - HEADER
    if payload_len <= CHANNEL_FMT_AT or raw[HEADER + CHANNEL_FMT_AT] == fmt:
        return raw
    buf = bytearray(raw)
    for off, byfmt in CHANNEL_WIDTH.items():
        if off < payload_len:
            buf[HEADER + off] = byfmt[fmt]
    return bytes(buf)


def widen_channels(data: bytes, want: dict[int, int]) -> tuple[bytes, list[int]]:
    """Set the width of whole channels -> ``(project, [owners actually changed])``.

    Plugins already on the channel are re-stamped to match: a slot carries its own width, so a
    channel widened on its own leaves them at the old one and ``validate_project`` refuses the
    result. Running before ``insert_slots`` also hands it the width to give the slots it places.
    """

    require_full_walk(data)
    out, changed = [], []
    for record in project_records(data):
        raw = record.raw
        if record.tag == CHANNEL_TAG and record.key == NO_KEY and record.owner in want:
            new = set_channel_format(raw, want[record.owner])
            if new != raw:
                raw = new
                if record.owner not in changed:
                    changed.append(record.owner)
        elif record.owner in want and find_blocks(raw[HEADER:]):
            try:
                raw = set_slot_format(raw, want[record.owner])
            except ValueError as e:
                raise ValueError(f"channel {record.owner} key {record.key}: cannot follow the "
                                 f"channel to width {want[record.owner]} — {e}") from None
        out.append(raw)
    body = b"".join(out)
    head = bytearray(data[:BODY_START])
    struct.pack_into("<I", head, TOTAL_AT, len(body))
    result = bytes(head) + body
    require_valid(result)
    return result, sorted(changed)
