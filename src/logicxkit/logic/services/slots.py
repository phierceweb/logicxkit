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
    """The key of the `.cst` reference record — the first key that is a property, not a slot."""
    keys = [r.key for r in project_records(data)
            if r.tag == b"UCuA" and len(r.raw) - HEADER < 400 and b".cst" in r.raw]
    return min(keys) if keys else _DEFAULT_PROPERTY_KEY


def is_plugin_slot(record: ProjRecord, base: int, index_base: int) -> bool:
    """In the slot key range AND carrying its slot index at +6 — native and third-party alike."""
    payload = record.raw[HEADER:]
    return (record.tag == b"UCuA" and index_base <= record.key < base
            and len(payload) > SLOT_INDEX_AT and payload[SLOT_INDEX_AT] == record.key - index_base)
