"""Which `UCuA` records are plugin slots.

A channel's slot keys run from the slot index base (4, or 2 before Logic 11.2) up to the key
of its `.cst` reference record, which sits at 9, 10, 12 or 13 depending on the session. The
range alone is not enough: every session's Audio 1 also holds a 200-byte 'Audio Recording'
record in it, and aux strips a 68-byte one, both with +6 = 0.
"""

from __future__ import annotations

import struct

from ..._binary import find_blocks
from .mixer import CHANNEL_BASE_AT, CHANNEL_TAG
from ..stream.stream import HEADER, ProjRecord, project_records


# BYPASS — payload +112: 0 = active, 1 = bypassed. Confirmed in Logic: a build written with 1 on
# nine Enveloper slots opened with them bypassed, and after they were enabled by hand the flag read
# 0 on exactly those channels while untouched ones still read 1.
SLOT_BYPASS_AT = 112

# Slot INDEX within the channel, written by Logic as key - 3 and unique per channel. A clone
# inherits the donor's, so without rewriting it two slots claim the same index and Logic renders
# only one of them.
SLOT_INDEX_AT = 6

SLOT_INDEX_BASE_DEFAULT = 4   # Logic 11.2 / 12; older builds start their slot keys at 3

_PLUGIN_MARKS = (b"GAMETSPP", b"<plist")      # native chunks and XML AU states; the binary-plist
                                              # property records (the strip reference) are not slots


def slot_index_base(data: bytes) -> int:
    """The key that slot index 0 corresponds to: 2 with up to one send in the project, 3 with
    two, 4 with three (Logic moves it with the sends, 2026-09-12). Every channel record
    carries it at +28; when they all agree that is the answer, else the project's own plugin
    slots (native chunks and AU states alike) vote."""
    words = {struct.unpack_from("<H", r.raw, HEADER + CHANNEL_BASE_AT)[0]
             for r in project_records(data) if r.tag == CHANNEL_TAG and len(r.raw) - HEADER > CHANNEL_BASE_AT + 2}
    if len(words) == 1 and next(iter(words)) in (2, 3, 4):
        return words.pop()
    votes: dict[int, int] = {}
    for record in project_records(data):
        if record.tag != b"UCuA" or not any(m in record.raw for m in _PLUGIN_MARKS):
            continue
        payload = record.raw[HEADER:]
        if len(payload) > SLOT_INDEX_AT and (find_blocks(payload) or b"GAMETSPP" not in payload):
            base = record.key - payload[SLOT_INDEX_AT]
            votes[base] = votes.get(base, 0) + 1
    return max(votes, key=votes.get) if votes else SLOT_INDEX_BASE_DEFAULT


def slot_bypassed(raw: bytes) -> bool:
    payload = raw[HEADER:]
    return len(payload) > SLOT_BYPASS_AT and payload[SLOT_BYPASS_AT] == 1


def set_slot_bypass(raw: bytes, bypassed: bool) -> bytes:
    buf = bytearray(raw)
    at = HEADER + SLOT_BYPASS_AT
    if at < len(buf):
        buf[at] = 1 if bypassed else 0
    return bytes(buf)

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
