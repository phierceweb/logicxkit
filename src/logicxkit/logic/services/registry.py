"""The `gnoS` registry — one record listing every object the project holds.

Runs of fixed-stride entries, each ``<u32 type><u32 id>`` followed by 16 bytes (a UUID) or
8 bytes (the UUID's v1 time fields, used as a modification stamp):

    type 0x14   keyed by object id — a new object gets one entry in each run, right after
                the highest object id's
    type 0x17   keyed by index-table slot word, one entry per multiple of 4 from 0 up to
                the highest slot in use — the pair for the new track's slot is filled in,
                or appended (with every skipped slot word) when the runs end below it;
                the ids 4 and 8 (the arrange and flat lists) are re-stamped on every add

A row whose triple's slot has no entry is dropped when Logic loads the project (measured
2026-09-04: 46 added rows, the ones past the runs' last slot gone on Logic's re-save, which
extended both runs to the highest slot). Three fields near the top hold what Logic leaves
selected (`selection.py`). Measured on Logic's adds (02 -> 03, 08 -> 09) at byte offsets that
match ours exactly.
"""

from __future__ import annotations

import struct

from .insert import HEADER, project_records
from .recbuild import fresh_uuid, time_fields

GNOS_TAG = b"gnoS"
OBJECT_TYPE = 0x14
SLOT_TYPE = 0x17
GROUP_TYPE = 0x11
LIST_IDS = (4, 8)
_RUN_TYPES = (0x14, 0x16, 0x17)
UUID_STRIDE, TIME_STRIDE = 24, 16
SELECTED_OBJECT_AT = 94
SELECTED_TRACK_AT, SELECTED_TRACK2_AT = 210, 214


_MAX_ID = 4096


def _is_entry(payload: bytes, at: int, kind: int) -> bool:
    return (0 <= at and at + 8 <= len(payload) and struct.unpack_from("<I", payload, at)[0] == kind
            and struct.unpack_from("<I", payload, at + 4)[0] < _MAX_ID)


def _run(payload: bytes, kind: int, stride: int) -> list[int]:
    """Offsets of the entries in the ``stride``-byte run of ``kind``: the longest chain of
    entries exactly ``stride`` apart, two or more — every real registry holds one such chain
    per kind and stride, and a stray word inside a UUID makes at most a short one."""
    best, s = [], 0
    while s + stride <= len(payload):
        if _is_entry(payload, s, kind) and not _is_entry(payload, s - stride, kind):
            chain = [s]
            while _is_entry(payload, chain[-1] + stride, kind):
                chain.append(chain[-1] + stride)
            if len(chain) >= 2:
                if len(chain) > len(best):
                    best = chain
                s = chain[-1] + stride
                continue
        s += 4
    return best


def run_entries(payload: bytes, kind: int, stride: int) -> list[tuple[int, int]]:
    """``(offset, id)`` of every entry in the ``stride``-byte run of ``kind``."""
    return [(at, struct.unpack_from("<I", payload, at + 4)[0]) for at in _run(payload, kind, stride)]


def entry_at(payload: bytes, kind: int, entry_id: int, stride: int) -> int | None:
    """Offset of the ``<kind><entry_id>`` entry in the ``stride``-byte run, if present. With
    no run of that stride at all (a fixture of one entry), any lone ``<kind><entry_id>``
    word pair serves."""
    for at, i in run_entries(payload, kind, stride):
        if i == entry_id:
            return at
    if _run(payload, kind, stride):
        return None
    s = 0
    while s + 8 <= len(payload):
        if struct.unpack_from("<II", payload, s) == (kind, entry_id):
            return s
        s += 4
    return None


def gnos_insert(payload: bytes, entry: bytes, *, stride: int, top: int) -> bytes:
    """Insert ``entry`` right after the object entry of ``top`` (the highest id)."""
    at = entry_at(payload, OBJECT_TYPE, top, stride)
    if at is None:
        raise ValueError(f"gnoS: no {stride}-byte registry entry for object {top}")
    at += stride
    return payload[:at] + entry + payload[at:]


def _stamp(payload: bytearray, kind: int, entry_id: int, value: bytes, stride: int) -> None:
    at = entry_at(payload, kind, entry_id, stride)
    if at is not None:
        payload[at + 8:at + 8 + len(value)] = value


def _slot_value(slot: int, slot_uuid: bytes, stride: int) -> bytes:
    return struct.pack("<II", SLOT_TYPE, slot) + (slot_uuid if stride == UUID_STRIDE else time_fields(slot_uuid))


def _insert_slot(payload: bytearray, slot: int, slot_uuid: bytes, stride: int) -> None:
    """Give the run an entry for ``slot``: past its last entry, every skipped multiple of 4
    is appended too, the way Logic extends the runs; inside it, the one entry goes in at
    its sorted place."""
    run = run_entries(payload, SLOT_TYPE, stride)
    if not run:
        raise ValueError("gnoS: no slot-entry run to extend")
    last_at, last = run[-1]
    if slot > last:
        new = b"".join(_slot_value(s, slot_uuid if s == slot else fresh_uuid(), stride)
                       for s in range(last + 4, slot + 1, 4))
        at = last_at + stride
    else:
        new = _slot_value(slot, slot_uuid, stride)
        at = next(a for a, s in run if s > slot)
    payload[at:at] = new


def group_entries(payload: bytes, stride: int) -> list[tuple[int, int]]:
    """``(offset, slot)`` of the group entries: the block directly before the object run."""
    run = run_entries(payload, OBJECT_TYPE, stride)
    if not run:
        return []
    at = run[0][0]
    while _is_entry(payload, at - stride, GROUP_TYPE):
        at -= stride
    return [(o, struct.unpack_from("<I", payload, o + 4)[0]) for o in range(at, run[0][0], stride)]


def register_group(payload: bytes, *, slot: int, uuid: bytes) -> bytes:
    """The pair for a group's ``slot``, in slot order among the group entries (a filled one
    is re-stamped)."""
    g = payload
    for stride in (UUID_STRIDE, TIME_STRIDE):
        run = run_entries(g, OBJECT_TYPE, stride)
        if not run:
            raise ValueError(f"gnoS: no {stride}-byte object run to put the group entry before")
        value = struct.pack("<II", GROUP_TYPE, slot) + (uuid if stride == UUID_STRIDE else time_fields(uuid))
        have = group_entries(g, stride)
        at = next((o for o, s in have if s == slot), None)
        if at is not None:
            g = g[:at] + value + g[at + stride:]
            continue
        at = next((o for o, s in have if s > slot), run[0][0])
        g = g[:at] + value + g[at:]
    return g


def register_object(payload: bytes, *, object_id: int, top: int, uuid: bytes,
                    slot: int | None = None) -> bytes:
    """Both object entries for a new object, the pair for its index-table ``slot`` (filled
    in, or appended when the runs end below it), and the list stamps."""
    head = struct.pack("<II", OBJECT_TYPE, object_id)
    g = gnos_insert(payload, head + uuid, stride=UUID_STRIDE, top=top)
    g = bytearray(gnos_insert(g, head + time_fields(uuid), stride=TIME_STRIDE, top=top))
    if slot is not None:
        slot_uuid = fresh_uuid()
        for stride in (UUID_STRIDE, TIME_STRIDE):
            if any(s == slot for _at, s in run_entries(g, SLOT_TYPE, stride)):
                _stamp(g, SLOT_TYPE, slot, _slot_value(slot, slot_uuid, stride)[8:], stride)
            else:
                _insert_slot(g, slot, slot_uuid, stride)
    return bytes(touch_lists(g))


def slot_errors(data: bytes) -> list[str]:
    """Track triples whose slot has no entry in one of the registry's slot runs."""
    from .sequence import QESM_OBJECT_AT, is_group, sequences
    records = project_records(data)
    g = next((r.raw[HEADER:] for r in records if r.tag == GNOS_TAG), None)
    if g is None:
        return []
    have = [{slot for _at, slot in run_entries(g, SLOT_TYPE, stride)} for stride in (UUID_STRIDE, TIME_STRIDE)]
    out = []
    for t in sequences(records):
        if is_group(records[t.start].raw):
            continue
        oid = struct.unpack_from("<H", records[t.start].raw, HEADER + QESM_OBJECT_AT)[0]
        if oid and any(t.slot not in run for run in have):
            out.append(f"object {oid}: slot {t.slot} has no registry entry")
    return out


def touch_lists(payload: bytes) -> bytes:
    """Re-stamp the arrange and flat lists, as Logic does when a row is added or moved."""
    g = bytearray(payload)
    for list_id in LIST_IDS:
        _stamp(g, SLOT_TYPE, list_id, time_fields(fresh_uuid()), TIME_STRIDE)
    return bytes(g)


def set_selection(payload: bytes, *, object_id: int, track_number: int) -> bytes:
    """The selected object and its 1-based row number."""
    if len(payload) < SELECTED_TRACK2_AT + 4:
        return payload
    g = bytearray(payload)
    struct.pack_into("<I", g, SELECTED_OBJECT_AT, object_id)
    struct.pack_into("<H", g, SELECTED_TRACK_AT, track_number)
    struct.pack_into("<I", g, SELECTED_TRACK2_AT, track_number)
    return bytes(g)
