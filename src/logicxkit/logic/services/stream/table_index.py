"""The index table's indices: an entry's `+20` is its object's 1-based place in the mixer-order
track list, and its triple's `qeSM +242` the negative of it.

So on every Logic save on hand — the public corpus and the owner's sessions, 2026-10-03. Logic
re-lays an entry that is off its place when it loads the project, and gives the sequence of an
object with no arrange row to whichever object holds that place. A writer that adds a channel
or a row ends with `sync_indices`; `integrity.regressions` counts what is off.
"""

from __future__ import annotations

import struct

from ..arrange.tracklist import arrange_run, flat_run, row_object
from .sequence import (
    QESM_INDEX_AT, QESM_OBJECT_AT, TABLE_INDEX_AT, Triple, index_table, sequences, table_entries, triple_by_slot,
)
from .stream import HEADER, ProjRecord


def _places(records: list[ProjRecord], track_count: int | None) -> dict[int, int]:
    """object id -> its 1-based place in the mixer-order track list; empty when the project has
    no such list that can be told from the arrange list (it holds every arranged track and more)."""
    try:
        run = arrange_run(records, track_count)
        flat = flat_run(records, run)
    except ValueError:
        return {}
    if len(flat) <= len(run):
        return {}
    out: dict[int, int] = {}
    for k, i in enumerate(flat):
        out.setdefault(row_object(records[i].raw), k + 1)
    return out


def _linked(records: list[ProjRecord], seqs: list[Triple], oid: int, slot: int) -> Triple | None:
    """The triple an entry leads to when it carries the entry's object — what makes it an
    index-table entry; other 80-byte tables (a song container's regions) lead nowhere."""
    t = triple_by_slot(seqs, slot)
    if t is None or len(records[t.start].raw) < HEADER + QESM_INDEX_AT + 2:
        return None
    return t if struct.unpack_from("<H", records[t.start].raw, HEADER + QESM_OBJECT_AT)[0] == oid else None


def _off_place(records: list[ProjRecord], track_count: int | None):
    """``(table index, entry offset, object, index, place, triple)`` for every entry off its
    object's place in the mixer-order list; the triple is None when the entry's slot leads to
    one that carries another object, as a few entries of Logic's own do."""
    places = _places(records, track_count)
    if not places:
        return
    try:
        table_at = index_table(records)
    except ValueError:
        return
    seqs = sequences(records)
    for at, oid, index, slot in table_entries(records[table_at].raw[HEADER:]):
        place = places.get(oid)
        if place is not None and place != index and place <= 255:
            yield table_at, at, oid, index, place, _linked(records, seqs, oid, slot)


def index_errors(records: list[ProjRecord], track_count: int | None = None) -> list[str]:
    """Index-table entries, each leading to its own object's triple, whose index is not that
    object's place in the mixer-order list."""
    return [f"object {oid}: index {index}, place {place}"
            for _table, _at, oid, index, place, t in _off_place(records, track_count) if t is not None]


def sync_indices(records: list[ProjRecord], track_count: int | None = None) -> list[bytes]:
    """Every record's bytes, each index-table entry's index set to its object's place in the
    mixer-order list, and its own triple's `+242` with it; Logic's convert moved the entries
    whose triple carries another object too (`tracking-convert-after-logic`). An entry whose
    object has no row there is left."""
    out = [r.raw for r in records]
    for table_at, at, _oid, _index, place, t in _off_place(records, track_count):
        table = bytearray(out[table_at])
        table[HEADER + at + TABLE_INDEX_AT] = place
        out[table_at] = bytes(table)
        if t is not None:
            q = bytearray(out[t.start])
            struct.pack_into("<h", q, HEADER + QESM_INDEX_AT, -place)
            out[t.start] = bytes(q)
    return out
