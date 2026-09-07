"""The `karT` track lists — the arrange window's rows, and the flat list in mixer order.

Row payload (58 bytes at Logic 12, 57 at Logic 11):

    +0    u32   flags; bit 0x04000000 hides the row
    +8    u32   object id (`ivnE +16`)
    +14   u8    1 on every row inside a stack, 0 on headers and top-level rows
    +24   16    row UUID
    +40   u8    bit 0x80: a stack header shown expanded; 0x20: selected
    +51   u8    row type: 0x07 audio, 0x85 software instrument

Runs are separated by zero-size `karT` markers. The run holding NumberOfTracks + 1 rows is
the arrange list; the longest other run lists every track in mixer order. A row's header key
is its display position, so every splice ends with a renumber.
"""

from __future__ import annotations

import struct

from .insert import HEADER, ProjRecord
from .recbuild import fresh_uuid, with_key

TRACK_TAG = b"karT"
TRACK_FLAG_AT = 0
TRACK_OBJECT_AT = 8
MEMBER_AT = 14
ROW_UUID_AT = 24
EXPANDED_AT, EXPANDED_BIT = 40, 0x80
SELECTED_AT = 43
ROW_TYPE_AT = 51
ROW_TYPE = {"audio": 0x07, "instrument": 0x85}
HIDDEN_BIT = 0x04000000
OFF_BIT = 0x20000000               # +0: the track's power button off (measured: switching one on
                                  # cleared this bit and nothing else on the track, 2026-09-06)
HIDDEN_FLAG = 0x24000001          # the value most hidden rows carry; the bit is what counts
FLAG_BASE = 0x1
INST_SELECTED_BIT = 0x10000       # +0: set on a selected instrument row only
SELECTED_BIT = 0x20               # +40
SELECTED_MARK = 0x40              # +43
UUID_LEN = 16


def is_marker(record: ProjRecord) -> bool:
    return record.tag == TRACK_TAG and len(record.raw) == HEADER


def track_runs(records: list[ProjRecord]) -> list[list[int]]:
    """Record indices of every `karT` run, split on the zero-size markers."""
    runs, cur = [], []
    for i, r in enumerate(records):
        if r.tag != TRACK_TAG:
            continue
        if is_marker(r):
            if cur:
                runs.append(cur)
                cur = []
        else:
            cur.append(i)
    if cur:
        runs.append(cur)
    return runs


def arrange_run(records: list[ProjRecord], track_count: int | None = None) -> list[int]:
    """The arrange list's record indices: the run nearest ``track_count + 1`` rows; without a
    count, the first run whose objects all sit in a longer run (the mixer-order list holds
    every arranged track and more — 35/35 files agree with the count), else the longest."""
    runs = track_runs(records)
    if not runs:
        raise ValueError("no track list in this project")
    if track_count is not None:
        return min(runs, key=lambda run: abs(len(run) - (track_count + 1)))
    objects = [{row_object(records[i].raw) for i in run} for run in runs]
    for run, objs in zip(runs, objects, strict=True):
        if len(run) > 1 and any(objs < other for other in objects if other is not objs):
            return run
    return max(runs, key=len)


def flat_run(records: list[ProjRecord], arrange: list[int]) -> list[int]:
    """The mixer-order list: the longest run that is not the arrange list."""
    run = max(track_runs(records), key=len)
    if run == arrange:
        raise ValueError("cannot tell the flat list from the arrange list")
    return run


def row_object(raw: bytes) -> int:
    return struct.unpack_from("<I", raw, HEADER + TRACK_OBJECT_AT)[0]


def row_position(records: list[ProjRecord], run: list[int], object_id: int) -> int | None:
    """Position of ``object_id``'s row within ``run``."""
    return next((k for k, i in enumerate(run) if row_object(records[i].raw) == object_id), None)


def new_row(template: bytes, *, object_id: int, member: int, row_type: int | None = None,
            expanded: bool | None = None) -> bytes:
    """An arrange row for a new object in the shape of ``template``: base flags, no group
    word, fresh UUID, unselected. ``member`` is the +14 byte of the row it will sit under;
    a top-level row is written expanded, as Logic writes fresh ones; ``row_type`` stays the
    template's when not given."""
    row = bytearray(template)
    struct.pack_into("<I", row, HEADER + TRACK_FLAG_AT, FLAG_BASE)
    struct.pack_into("<I", row, HEADER + 4, 0)
    struct.pack_into("<I", row, HEADER + TRACK_OBJECT_AT, object_id)
    row[HEADER + MEMBER_AT] = member
    row[HEADER + ROW_UUID_AT:HEADER + ROW_UUID_AT + UUID_LEN] = fresh_uuid()
    if expanded is None:
        expanded = not member
    row[HEADER + EXPANDED_AT] = EXPANDED_BIT if expanded else 0
    row[HEADER + SELECTED_AT] = 0
    if row_type is not None:
        row[HEADER + ROW_TYPE_AT] = row_type
    return bytes(row)


def with_member(raw: bytes, member: int) -> bytes:
    """The +14 byte; a row moved inside a stack also loses the expanded bit, which no
    member row carries."""
    row = bytearray(raw)
    row[HEADER + MEMBER_AT] = member
    if member:
        row[HEADER + EXPANDED_AT] &= ~EXPANDED_BIT & 0xFF
    return bytes(row)


def with_power(raw: bytes, on: bool) -> bytes:
    """The track on or off: `OFF_BIT` in the flags at +0."""
    row = bytearray(raw)
    flag = struct.unpack_from("<I", row, HEADER + TRACK_FLAG_AT)[0]
    flag = flag & ~OFF_BIT if on else flag | OFF_BIT
    struct.pack_into("<I", row, HEADER + TRACK_FLAG_AT, flag)
    return bytes(row)


def with_hidden(raw: bytes, hidden: bool) -> bytes:
    """The hidden bit at +0 — the one field every hidden row shares (values seen:
    0x24000001, 0x241c0001, 0x24080001, 0x4000001)."""
    row = bytearray(raw)
    flag = struct.unpack_from("<I", row, HEADER + TRACK_FLAG_AT)[0]
    flag = flag | HIDDEN_BIT if hidden else flag & ~HIDDEN_BIT
    struct.pack_into("<I", row, HEADER + TRACK_FLAG_AT, flag)
    return bytes(row)


def select_rows(rows: list[bytes], object_id: int) -> list[bytes]:
    """``rows`` with ``object_id``'s row selected and every other one deselected."""
    out = []
    for raw in rows:
        row = bytearray(raw)
        selected = row_object(raw) == object_id
        flag = struct.unpack_from("<I", row, HEADER + TRACK_FLAG_AT)[0] & ~INST_SELECTED_BIT
        if selected and row[HEADER + ROW_TYPE_AT] == ROW_TYPE["instrument"]:
            flag |= INST_SELECTED_BIT
        struct.pack_into("<I", row, HEADER + TRACK_FLAG_AT, flag)
        if selected:
            row[HEADER + EXPANDED_AT] |= SELECTED_BIT
        else:
            row[HEADER + EXPANDED_AT] &= ~SELECTED_BIT & 0xFF
        row[HEADER + SELECTED_AT] = SELECTED_MARK if selected else 0
        out.append(bytes(row))
    return out


def clone_flat_row(template: bytes, object_id: int) -> bytes:
    """A mixer-order row for ``object_id``, everything else as ``template``."""
    row = bytearray(template)
    struct.pack_into("<I", row, HEADER + TRACK_OBJECT_AT, object_id)
    row[HEADER + ROW_UUID_AT:HEADER + ROW_UUID_AT + UUID_LEN] = fresh_uuid()
    return bytes(row)


def renumbered(records: list[ProjRecord]) -> list[bytes]:
    """Every record's bytes, with the keys of each multi-row track list renumbered 0..n."""
    key_of: dict[int, int] = {}
    for run in track_runs(records):
        if len(run) > 1:
            key_of.update({i: k for k, i in enumerate(run)})
    return [with_key(r.raw, key_of[i]) if i in key_of else r.raw for i, r in enumerate(records)]
