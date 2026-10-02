"""The song container — the sequence triple that holds the arrange rows — and what in it
must follow the rows: the row count and the region placements.

**Row count.** The container's `qeSM` carries the number of arrange rows times 60 as a u32
269 bytes before its end (the name before it is variable-length, so the field is addressed
from the end); every Logic file on hand agrees. Logic reads that many rows and drops the rest
on its next save (measured 2026-09-04: after rows were added, only the first 11 were kept).

**Region placement.** The container's `qSvE` is an event list of 80-byte entries and a
16-byte tail. An entry that places a region carries the track's object id at `+16`, the
track's **1-based arrange row** at `+20` (the object's first row, when a channel has two)
and the region's own sequence slot at `+32`. Logic rewrites `+20` whenever a row moves
(measured on its own add, `37 -> 38`); every entry on hand agrees.

Every writer that adds or moves a row ends by syncing both.
"""

from __future__ import annotations

import struct

from .stream import HEADER, ProjRecord, project_records, reassemble
from .sequence import Triple, sequences
from .tracklist import arrange_run, row_object

ENTRY, TAIL = 80, 16
TRACK_OBJECT_AT, TRACK_ROW_AT = 16, 20
ROW_COUNT_FROM_END, ROW_UNIT = 269, 60


def song_container(records: list[ProjRecord], run: list[int]) -> Triple | None:
    return next((t for t in sequences(records) if t.start < run[0] < t.end), None)


MARKER_KIND_AT, MARKER_KIND = 7, 0xAA        # a flex marker block after a flexed entry
MARKER_BYTES_AT, MARKER_BYTE = (23, 39, 55, 71), 0x88   # on every block Logic writes, on no entry


def song_events(records: list[ProjRecord], track_count: int | None = None) -> bytes | None:
    """The song container's `qSvE` payload, or None without an arrange list or container."""
    try:
        run = arrange_run(records, track_count)
    except ValueError:
        return None
    song = song_container(records, run)
    return None if song is None else records[song.end].raw[HEADER:]


def entry_blocks(events: bytes) -> list[tuple[int, int]]:
    """``(offset, marker blocks after it)`` for every entry `entry_offsets` finds."""
    out, off, end = [], 0, len(events) - TAIL
    while off + ENTRY <= end:
        start, off = off, off + ENTRY
        while off + ENTRY <= end and events[off + MARKER_KIND_AT] == MARKER_KIND:
            off += ENTRY
        out.append((start, (off - start) // ENTRY - 1))
    return out


def entry_offsets(events: bytes) -> list[int]:
    """Offsets of the 80-byte region entries in a song container's events: a flexed entry is
    followed by 80-byte flex marker blocks (byte 7 = 0xAA), which are not entries."""
    return [off for off, _blocks in entry_blocks(events)]


def _rows(records: list[ProjRecord], run: list[int]) -> dict[int, int]:
    """Object id -> 1-based position of its first arrange row."""
    out: dict[int, int] = {}
    for k, i in enumerate(run):
        out.setdefault(row_object(records[i].raw), k + 1)
    return out


def placements(records: list[ProjRecord], track_count: int | None = None) -> list[tuple[int, int, int]]:
    """``(entry offset, object id, row number)`` for every entry placing a region on a track."""
    run = arrange_run(records, track_count)
    song = song_container(records, run)
    if song is None:
        return []
    rows = _rows(records, run)
    events = records[song.end].raw[HEADER:]
    out = []
    for off in entry_offsets(events):
        oid = struct.unpack_from("<H", events, off + TRACK_OBJECT_AT)[0]
        if oid in rows:
            out.append((off, oid, struct.unpack_from("<H", events, off + TRACK_ROW_AT)[0]))
    return out


def sync_region_tracks(data: bytes, track_count: int | None = None) -> bytes:
    """Every region placement renumbered to the row its track sits on now."""
    records = project_records(data)
    run = arrange_run(records, track_count)
    song = song_container(records, run)
    if song is None:
        return data
    rows = _rows(records, run)
    raw = bytearray(records[song.end].raw)
    for off, oid, _row in placements(records, track_count):
        struct.pack_into("<H", raw, HEADER + off + TRACK_ROW_AT, rows[oid])
    if bytes(raw) == records[song.end].raw:
        return data
    out = [r.raw for r in records]
    out[song.end] = bytes(raw)
    return reassemble(data, out)


def row_count(records: list[ProjRecord], song: Triple) -> int:
    q = records[song.start].raw[HEADER:]
    return struct.unpack_from("<I", q, len(q) - ROW_COUNT_FROM_END)[0] // ROW_UNIT


def sync_row_count(data: bytes, track_count: int | None = None) -> bytes:
    """The song container's row count set to the rows it holds."""
    records = project_records(data)
    run = arrange_run(records, track_count)
    song = song_container(records, run)
    if song is None or row_count(records, song) == len(run):
        return data
    raw = bytearray(records[song.start].raw)
    struct.pack_into("<I", raw, len(raw) - ROW_COUNT_FROM_END, ROW_UNIT * len(run))
    out = [r.raw for r in records]
    out[song.start] = bytes(raw)
    return reassemble(data, out)


def row_count_errors(data: bytes, track_count: int | None = None) -> list[str]:
    records = project_records(data)
    try:
        run = arrange_run(records, track_count)
    except ValueError:
        return []
    song = song_container(records, run)
    if song is None or row_count(records, song) == len(run):
        return []
    return [f"song container says {row_count(records, song)} rows, the list holds {len(run)}"]


def region_errors(data: bytes, track_count: int | None = None) -> list[str]:
    """Placements whose row number is not the row their track sits on."""
    records = project_records(data)
    try:
        run = arrange_run(records, track_count)
    except ValueError:
        return []
    rows = _rows(records, run)
    return [f"object {oid}: placed on row {row}, sits on row {rows[oid]}"
            for _off, oid, row in placements(records, track_count) if row != rows[oid]]
