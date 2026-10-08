"""Which object id a new track or stack header takes, as Logic gives it (`stackid-*-logic`, `gone-*-logic`).

A removed object (Convert Folder Stack to Summing Stack, Delete Track) leaves its id behind: the
registry entry with a zero UUID, the index-table entry parked at a low index with its sequence
triple kept, the mixer-order row parked at the head of the flat list. The next object Logic makes
takes the lowest gone id wherever it is parked, re-stamping the entry, moving the table entry and
dropping the parked row; with none gone, the next multiple of four past the highest. A gone id
with no table entry or no parked row is an unmeasured shape and is left alone.
"""

from __future__ import annotations

from ..stream.registry import GNOS_TAG, gone_object_ids
from ..stream.sequence import QESM_KIND_AT, index_table, sequences, table_entry, triple_by_slot
from ..stream.stream import HEADER
from .environment import next_object_id
from .tracklist import flat_run
from .stacks import arrange_run, row_object

FOLDER_COLOUR = 20                  # every folder header Logic 12.4 made in the goldens


def free_object_id(records, objects: dict, track_count: int | None = None) -> tuple[int, bool]:
    """``(id, reused)``: the lowest gone id that keeps a table entry and a parked row, else the
    next past the highest."""
    registry = next((r.raw[HEADER:] for r in records if r.tag == GNOS_TAG), None)
    if registry is None or not objects:
        return next_object_id(records), False
    gone = [g for g in gone_object_ids(registry, min(objects)) if g not in objects]
    if not gone:
        return next_object_id(records), False
    table = records[index_table(records)].raw[HEADER:]
    parked = {row_object(records[i].raw) for i in flat_run(records, arrange_run(records, track_count))}
    lowest = gone[0]
    if table_entry(table, lowest) is not None and lowest in parked:
        return lowest, True
    return next_object_id(records), False


def gone_triple_kind(records, object_id: int) -> int | None:
    """The kind byte (`qeSM +39`: 9 on a track of any kind, 20 on a stack header, 5 on most auxes)
    of a gone object's kept sequence triple, or None without one. No byte of the triple tells an
    audio track from an instrument track (`test_gone_ids.KeptTripleTest`)."""
    table = records[index_table(records)].raw[HEADER:]
    entry = table_entry(table, object_id)
    if entry is None:
        return None
    triple = triple_by_slot(sequences(records), entry[1])
    return None if triple is None else records[triple.start].raw[HEADER + QESM_KIND_AT]
