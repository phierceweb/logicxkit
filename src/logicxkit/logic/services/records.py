"""The `.cst` record container.

A `.cst` is a flat stream of self-describing records:

    +0   4  tag — 'OCuA' (channel/object) or 'UCuA' (child)
    +18  2  key   (uint16) — the child's role within its parent
    +28  4  size  (uint32) — payload length; the next record starts at pos + 36 + size

Child keys observed across the whole library: **0-2 sends**, **4+ plugin slots**, higher keys
per-channel properties. There is no slot-count field, and shipping strips already have sparse
keys (a factory strip carries 0,1,2,4,10,12,13), so slots can be added or dropped freely.

A `.cst` has no file-level length field, so record edits need no size fixups beyond the records
themselves. (`ProjectData` shares the grammar but uses many more tag types and carries a total
at file offset 0x10 == filesize - 24; walking it needs a wider tag set than `TAGS`.)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = 36
KEY_OFF = 18
SIZE_OFF = 28
TAGS = (b"OCuA", b"UCuA")
SEND_KEYS = range(0, 3)
SLOT_KEYS = range(4, 10)


@dataclass(frozen=True)
class Record:
    tag: bytes
    key: int
    raw: bytes  # complete record, header included

    @property
    def payload(self) -> bytes:
        return self.raw[HEADER:]

    def with_key(self, key: int) -> Record:
        buf = bytearray(self.raw)
        struct.pack_into("<H", buf, KEY_OFF, key)
        return Record(self.tag, key, bytes(buf))


def read_records(data: bytes, start: int = 0) -> list[Record]:
    """Walk the record stream, stopping at the first non-record byte."""
    out, pos = [], start
    while pos + HEADER <= len(data):
        tag = data[pos:pos + 4]
        if tag not in TAGS:
            break
        size = struct.unpack_from("<I", data, pos + SIZE_OFF)[0]
        end = pos + HEADER + size
        if end > len(data):
            break
        key = struct.unpack_from("<H", data, pos + KEY_OFF)[0]
        out.append(Record(tag, key, data[pos:end]))
        pos = end
    return out


def write_records(records: list[Record]) -> bytes:
    return b"".join(r.raw for r in records)


def plugin_slots(data: bytes) -> list[Record]:
    return [r for r in read_records(data) if r.tag == b"UCuA" and r.key in SLOT_KEYS]


def _assert_not_a_reference(records: list[Record]) -> None:
    """Guard the schema-version assumption behind SLOT_KEYS.

    A channel's `.cst` reference lives in a small record whose key varies with the Logic build
    that wrote the file. No known build puts one inside SLOT_KEYS; if one did, dropping it
    would erase the strip's identity — so fail loudly rather than silently.
    """
    for r in records:
        if b".cst" in r.payload and len(r.payload) < 400:
            raise ValueError(
                f"record key {r.key} is inside the slot range but looks like a .cst reference "
                "— slot-key numbering differs in this file; refusing to edit it blindly")


def replace_slots(data: bytes, slots: list[bytes]) -> bytes:
    """Swap the plugin-slot records for ``slots`` (raw records), renumbered from 4.

    Everything else — the channel header, sends, and property records — is kept verbatim,
    so the strip's routing survives intact.
    """
    new = [Record(r.tag, r.key, r.raw) for s in slots for r in read_records(s)]
    kept = read_records(data)
    _assert_not_a_reference([r for r in kept if r.tag == b"UCuA" and r.key in SLOT_KEYS])
    out, inserted = [], False
    for record in kept:
        if record.tag == b"UCuA" and record.key in SLOT_KEYS:
            if not inserted:
                out += [r.with_key(SLOT_KEYS.start + i) for i, r in enumerate(new)]
                inserted = True
            continue
        out.append(record)
    if not inserted:  # target had no slots — insert after the sends
        at = max((i for i, r in enumerate(out)
                  if r.tag == b"UCuA" and r.key in SEND_KEYS), default=0) + 1
        out[at:at] = [r.with_key(SLOT_KEYS.start + i) for i, r in enumerate(new)]
    return write_records(out)
