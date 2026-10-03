"""The `.cst` record container: the record stream of `stream.py` (header layout there), with
no file header and only the channel and child tags.

Child keys observed across the whole library: **0-2 sends**, **4+ plugin slots**, higher keys
per-channel properties. There is no slot-count field, and shipping strips already have sparse
keys (a factory strip carries 0,1,2,4,10,12,13), so slots can be added or dropped freely.

A `.cst` has no file-level length field, so record edits need no size fixups beyond the records
themselves.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from itertools import takewhile

from .stream import HEADER, KEY_OFF, project_records

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
    return [Record(r.tag, r.key, r.raw)
            for r in takewhile(lambda r: r.tag in TAGS, project_records(data, start))]


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
