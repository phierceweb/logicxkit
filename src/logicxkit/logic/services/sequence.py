"""Sequence triples and the index table — what ties a track to its automation lanes.

Every track object owns a triple in the record stream: a `qeSM` (345 bytes here, 309 in
older saves), a zero-size `karT` marker and a 16-byte `qSvE`. The three share a header slot
(+10). The index table — the largest `qSvE`: 80-byte entries, then a 16-byte tail — links an
object to its triple through that slot:

    entry +16   object id             qeSM +234   u16 object id
    entry +20   17 + mixer rank       qeSM +242   i16, -(entry +20)
    entry +32   slot word             qeSM +300   u32, 382 on a track Logic just made
                                      qeSM +39    9 on a track, 20 on a stack (Sub 5: 9)

Measured on Logic's own adds (02 -> 03 audio, 08 -> 09 instrument): the new entry goes in
before the tail with the lowest free slot word (multiples of 4 from 20); every entry at or
past the new index moves up one, and the triple it links to has +242 decremented; the new
triple goes into the stream in slot order; no other triple moves. `qeSM +8`, repeated as the
`qSvE` owner, is a per-triple id Logic renumbers freely — any unused value will do.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .insert import HEADER, ProjRecord
from .recbuild import rec, slot_of, with_owner, with_slot
from .tracklist import is_marker

SEQ_TAG, SEQ_END_TAG = b"qeSM", b"qSvE"
QESM_ID_AT = 8
QESM_OBJECT_AT = 234
QESM_INDEX_AT = 242
QESM_FRESH_AT, QESM_FRESH = 300, 382
TABLE_ENTRY = 80
TABLE_ID_AT, TABLE_INDEX_AT, TABLE_SLOT_AT = 16, 20, 32
TABLE_FIRST_SLOT = 20
SLOT_STEP = 4
_MAX_ID = 512
KIND_AT = 6                    # header: 0x11 on a group's triple (`groups.py`)
GROUP_KIND = 0x11


def is_group(raw: bytes) -> bool:
    return raw[KIND_AT] == GROUP_KIND


@dataclass(frozen=True)
class Triple:
    start: int             # record index of the qeSM
    marker: int | None     # the zero-size karT between them, when present
    end: int               # record index of the qSvE
    slot: int              # header +10, shared by all three
    seq_id: int            # qeSM +8


def sequences(records: list[ProjRecord]) -> list[Triple]:
    out, start = [], None
    for i, r in enumerate(records):
        if r.tag == SEQ_TAG:
            start = i
        elif r.tag == SEQ_END_TAG and start is not None:
            marker = start + 1 if start + 1 < i and is_marker(records[start + 1]) else None
            seq_id = struct.unpack_from("<I", records[start].raw, HEADER + QESM_ID_AT)[0]
            out.append(Triple(start, marker, i, slot_of(records[start].raw), seq_id))
            start = None
    return out


def _table_score(payload: bytes, object_ids: set[int]) -> int:
    """How many distinct channel objects the entries name with a real slot word, less any
    repeated ids — the index table has one entry per track. Templates and mixes hold larger
    qSvEs (490 to 21,000 entries: zeroed, or regions repeating a track's id), so size alone
    misleads."""
    if len(payload) % TABLE_ENTRY not in (0, 16):
        return -1
    entries = table_entries(payload)
    named = {oid for _at, oid, _index, slot in entries
             if oid in object_ids and 0 < slot < 0x8000 and slot % SLOT_STEP == 0}
    duplicates = len(entries) - len({oid for _at, oid, _i, _s in entries})
    return len(named) - duplicates         # one entry per track; a region table repeats ids


def index_table(records: list[ProjRecord]) -> int:
    """Record index of the index table."""
    from .environment import object_id_of
    object_ids = {oid for oid in (object_id_of(r) for r in records) if oid is not None}
    candidates = [i for i, r in enumerate(records) if r.tag == SEQ_END_TAG
                  and len(r.raw) - HEADER >= TABLE_ENTRY + 16]
    if not candidates:
        raise ValueError("no index table in this project")
    return max(candidates, key=lambda i: (_table_score(records[i].raw[HEADER:], object_ids),
                                          -len(records[i].raw)))


def table_entries(table: bytes) -> list[tuple[int, int, int, int]]:
    """``(offset, object id, index, slot)`` per 80-byte entry, the tail excluded."""
    out = []
    for k in range(len(table) // TABLE_ENTRY):
        at = TABLE_ENTRY * k
        out.append((at, struct.unpack_from("<I", table, at + TABLE_ID_AT)[0],
                    table[at + TABLE_INDEX_AT], struct.unpack_from("<H", table, at + TABLE_SLOT_AT)[0]))
    return out


def table_entry(table: bytes, object_id: int) -> tuple[int, int, bytes] | None:
    """``(index, slot, entry bytes)`` of ``object_id``'s entry."""
    for at, oid, index, slot in table_entries(table):
        if oid == object_id:
            return index, slot, bytes(table[at:at + TABLE_ENTRY])
    return None


def free_table_slot(table: bytes, seqs: list[Triple] | None = None) -> int:
    """The lowest slot word neither an index-table entry nor an existing triple uses.

    The table is not the whole picture: every session on hand carries triples holding slots no
    entry names, so a table-only answer collides with one of them and the new object links to a
    foreign triple.
    """
    used = {slot for _at, _oid, _index, slot in table_entries(table)}
    used |= {t.slot for t in seqs or ()}
    slot = TABLE_FIRST_SLOT
    while slot in used:
        slot += SLOT_STEP
    return slot


def triple_by_slot(seqs: list[Triple], slot: int) -> Triple | None:
    return next((t for t in seqs if t.slot == slot), None)


def free_seq_id(seqs: list[Triple]) -> int:
    return min(set(range(1, _MAX_ID)) - {t.seq_id for t in seqs})


@dataclass
class SequencePlan:
    """A new object's triple and table entry, and the +242 decrements they cause."""
    index: int
    slot: int
    insert_after: int             # record index the new triple follows
    new: list[bytes]              # qeSM, marker, qSvE
    table_at: int
    table: bytes
    decremented: dict[int, int] = field(default_factory=dict)   # qeSM record index -> new +242

    def rewrite(self, i: int, record: ProjRecord) -> bytes:
        raw = record.raw
        if i in self.decremented:
            buf = bytearray(raw)
            struct.pack_into("<h", buf, HEADER + QESM_INDEX_AT, self.decremented[i])
            raw = bytes(buf)
        if i == self.table_at:
            raw = rec(SEQ_END_TAG, raw, self.table)
        return raw


QESM_KIND_AT = 39


def plan_sequence(records: list[ProjRecord], *, like: int, object_id: int,
                  fresh_word: int = QESM_FRESH, kind_byte: int | None = None) -> SequencePlan:
    """The triple and table entry for ``object_id``, in the shape of object ``like``'s,
    indexed right after it. ``fresh_word`` is what Logic puts at `+300` (382 on a track,
    360 on an aux); ``kind_byte`` overrides `+39` (5 on a fresh aux, 9 on a track)."""
    seqs = sequences(records)
    table_at = index_table(records)
    table = bytearray(records[table_at].raw[HEADER:])
    found = table_entry(table, like)
    if found is None:
        raise ValueError(f"object {like} has no index-table entry")
    ref_index, ref_slot, ref_entry = found
    ref = triple_by_slot(seqs, ref_slot)
    if ref is None:
        raise ValueError(f"object {like}'s sequence triple (slot {ref_slot}) is missing")
    index = ref_index + 1
    slot = free_table_slot(table, seqs)
    seq_id = free_seq_id(seqs)

    qesm = bytearray(with_slot(records[ref.start].raw, slot))
    struct.pack_into("<I", qesm, HEADER + QESM_ID_AT, seq_id)
    if len(qesm) >= HEADER + QESM_INDEX_AT + 2:
        struct.pack_into("<H", qesm, HEADER + QESM_OBJECT_AT, object_id)
        struct.pack_into("<h", qesm, HEADER + QESM_INDEX_AT, -index)
    if len(qesm) >= HEADER + QESM_FRESH_AT + 4:
        struct.pack_into("<I", qesm, HEADER + QESM_FRESH_AT, fresh_word)
    if kind_byte is not None and len(qesm) > HEADER + QESM_KIND_AT:
        qesm[HEADER + QESM_KIND_AT] = kind_byte
    marker_src = ref.marker if ref.marker is not None else next(
        (t.marker for t in seqs if t.marker is not None), None)
    if marker_src is None:
        raise ValueError("no sequence marker to clone")
    marker = with_slot(records[marker_src].raw, slot)
    qsve = with_slot(with_owner(records[ref.end].raw, seq_id), slot)

    bumped_slots = []
    for at, _oid, entry_index, entry_slot in table_entries(table):
        if index <= entry_index < 255:
            table[at + TABLE_INDEX_AT] += 1
            bumped_slots.append(entry_slot)
    entry = bytearray(ref_entry)
    struct.pack_into("<I", entry, TABLE_ID_AT, object_id)
    entry[TABLE_INDEX_AT] = index
    struct.pack_into("<H", entry, TABLE_SLOT_AT, slot)
    end = (len(table) // TABLE_ENTRY) * TABLE_ENTRY
    table[end:end] = bytes(entry)

    decremented = {}
    for s in bumped_slots:
        t = triple_by_slot(seqs, s)
        if t is not None and len(records[t.start].raw) >= HEADER + QESM_INDEX_AT + 2:
            v = struct.unpack_from("<h", records[t.start].raw, HEADER + QESM_INDEX_AT)[0]
            decremented[t.start] = v - 1

    size = len(records[ref.start].raw)
    peers = [t for t in seqs if len(records[t.start].raw) == size and not is_group(records[t.start].raw)]
    after = next((t for t in peers if t.slot > slot), None)
    if after is not None:
        insert_after = after.start - 1
    else:
        insert_after = peers[-1].end if peers else ref.end   # a stack's shape has no peers
    return SequencePlan(index=index, slot=slot, insert_after=insert_after,
                        new=[bytes(qesm), marker, qsve], table_at=table_at,
                        table=bytes(table), decremented=decremented)


def link_errors(records: list[ProjRecord]) -> list[str]:
    """Index-table entries whose triple is missing or disagrees with them (`+234`, `+242`).

    Logic's own files are not spotless — a few entries per session point at triples that
    carry another value — so callers compare before and after rather than demanding zero.
    """
    seqs = sequences(records)
    table = records[index_table(records)].raw[HEADER:]
    out = []
    for _at, oid, index, slot in table_entries(table):
        t = triple_by_slot(seqs, slot)
        if t is None:
            out.append(f"object {oid}: no triple at slot {slot}")
            continue
        q = records[t.start].raw
        if len(q) < HEADER + QESM_INDEX_AT + 2:
            continue
        got_oid = struct.unpack_from("<H", q, HEADER + QESM_OBJECT_AT)[0]
        got_index = -struct.unpack_from("<h", q, HEADER + QESM_INDEX_AT)[0]
        if got_oid != oid or got_index != index:
            out.append(f"object {oid}: slot {slot} triple carries object {got_oid}, index {got_index} (entry {index})")
    return out
