"""Which `UCuA` records are plugin slots.

A channel's slot keys run from the slot index base (4, or 2 before Logic 11.2) up to the key
of its `.cst` reference record, which sits at 9, 10, 12 or 13 depending on the session. The
range alone is not enough: every session's Audio 1 also holds a 200-byte 'Audio Recording'
record in it, and aux strips a 68-byte one, both with +6 = 0.
"""

from __future__ import annotations

from .insert import HEADER, SLOT_INDEX_AT, ProjRecord, project_records

_DEFAULT_PROPERTY_KEY = 10


def property_key_base(data: bytes) -> int:
    """The key of the `.cst` reference record — the first key that is a property, not a slot.
    A project whose channels carry no reference (blank-born) still places the two archive
    records every channel carries at that key + 2 and + 3 (the logic README, "The slot key
    range grows"), so their pair says where it would be."""
    records = [r for r in project_records(data) if r.tag == b"UCuA"]
    keys = [r.key for r in records if len(r.raw) - HEADER < 400 and b".cst" in r.raw]
    if keys:
        return min(keys)
    archives = {n: {r.key for r in records if archive_index(r.raw) == n} for n in (1, 2)}
    pairs = [k for k in archives[1] if k + 1 in archives[2]]
    return min(pairs) - 2 if pairs else _DEFAULT_PROPERTY_KEY


def archive_index(raw: bytes) -> int | None:
    """1 or 2 for the two keyed-archive records a channel carries past its reference key."""
    payload = raw[HEADER:]
    if payload[4:6] == b"\x07\x00" and payload[7] == 0 and b"bplist" in payload[:40]:
        return payload[6]
    return None


def is_plugin_slot(record: ProjRecord, base: int, index_base: int) -> bool:
    """In the slot key range AND carrying its slot index at +6 — native and third-party alike."""
    payload = record.raw[HEADER:]
    return (record.tag == b"UCuA" and index_base <= record.key < base
            and len(payload) > SLOT_INDEX_AT and payload[SLOT_INDEX_AT] == record.key - index_base)
