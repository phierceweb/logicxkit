"""Export a project channel as a `.cst` channel strip setting.

Measured against Logic's own "Save Channel Strip Setting as…" of the same channel
(2026-09-01): the strip is the channel's records copied out verbatim — the `OCuA` channel
record, then every `UCuA` satellite (slots, sends, properties) — followed by a 14-byte `OCuA`
stub with owner 1. Only four header bytes differ: `+8..9` becomes 0x1235 (the strip marker
every library strip carries) and `+112..113` a per-strip value Logic minted. Plugin slots
were byte-identical.
"""

from __future__ import annotations

import struct

from .insert import CHANNEL_TAG, HEADER, NO_KEY, OWNER_OFF, project_records

STRIP_MARKER_AT = 8
STRIP_MARKER = 0x1235
STRIP_ID_AT = 112
# The 14-byte terminator Logic appends, byte for byte (owner 1). Constant across strips.
_STUB = bytes.fromhex("4f43754107000e0000002400000001000000ffffffff0200000002000e00000000000000"
                      "20000000ffff0000000035120000")


def _with_owner(raw: bytes, owner: int) -> bytes:
    buf = bytearray(raw)
    struct.pack_into("<H", buf, OWNER_OFF, owner)
    return bytes(buf)


def export_strip(data: bytes, owner: int, *, strip_id: int | None = None) -> bytes:
    """The channel ``owner`` as `.cst` bytes. ``strip_id`` fills `+112..113`; when omitted
    the project's own value is kept (Logic mints a new one — its rule is not decoded)."""
    channel = None
    satellites = []
    for record in project_records(data):
        if record.owner != owner:
            continue
        if record.tag == CHANNEL_TAG and record.key == NO_KEY:
            payload = len(record.raw) - HEADER
            if payload > 200 and (channel is None or payload > len(channel) - HEADER):
                channel = record.raw
        elif record.tag == b"UCuA":
            satellites.append(record.raw)
    if channel is None:
        raise ValueError(f"no channel record for owner {owner}")
    head = bytearray(_with_owner(channel, 0))
    struct.pack_into("<H", head, HEADER + STRIP_MARKER_AT, STRIP_MARKER)
    if strip_id is not None:
        struct.pack_into("<H", head, HEADER + STRIP_ID_AT, strip_id)
    body = [bytes(head)] + [_with_owner(s, 0) for s in sorted(satellites, key=_key)]
    return b"".join(body) + _STUB


def _key(raw: bytes) -> int:
    return struct.unpack_from("<H", raw, 18)[0]
