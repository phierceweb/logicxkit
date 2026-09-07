"""The sequence triple and index table for a new object, as Logic's own adds write them:
lowest free slot, in slot order, linked by `+234`/`+242`, later entries bumped, nothing else
moved.

The real-file part of tests/logic/test_sequence.py; skips without the owner's files."""

import unittest
import _paths  # noqa: F401
from _records import index_entry, marker, proj, seq_triple, track
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.sequence import (
    free_table_slot,
    index_table,
    sequences,
    table_entries,
)

OBJECTS = [88, 92, 152, 504]                    # indices 2..5, slots 20, 24, 32, 36 (28 is free)
SLOTS = [20, 24, 32, 36]
def session(*, tail: bytes = b"") -> bytes:
    table = b"".join(index_entry(oid, 2 + k, SLOTS[k]) for k, oid in enumerate(OBJECTS)) + tail
    return proj(
        seq_triple(1, big=table),
        track(0, 88), track(1, 92), marker(),
        *(seq_triple(2 + k, slot=SLOTS[k], object_id=oid, index=2 + k) for k, oid in enumerate(OBJECTS)),
        seq_triple(9, slot=1024, size=341))


class FreeSlotAvoidsOccupiedTriplesTest(unittest.TestCase):
    """A slot with no index-table entry can still be held by a triple.

    `free_table_slot` looked only at the table, so on a project carrying an orphan triple it
    handed back a slot already in use and the new object linked to a foreign triple.
    """

    def test_a_slot_held_by_an_orphan_triple_is_not_offered(self):
        data = session()
        records = project_records(data)
        table = records[index_table(records)].raw[HEADER:]
        seqs = sequences(records)
        offered = free_table_slot(table, seqs)
        self.assertNotIn(offered, {t.slot for t in seqs},
                         "handed back a slot a triple already occupies")

    def test_it_still_skips_slots_the_table_uses(self):
        data = session()
        records = project_records(data)
        table = records[index_table(records)].raw[HEADER:]
        seqs = sequences(records)
        used = {slot for _at, _oid, _index, slot in table_entries(table)}
        self.assertNotIn(free_table_slot(table, seqs), used)

    def test_the_real_sessions_never_offer_an_occupied_slot(self):
        root = _paths.RESOURCES
        projects = sorted(p for d in ("legacy", "mixes") for p in (root / d).rglob("*.logicx"))
        if not projects:
            self.skipTest("no sessions under resources/legacy or resources/mixes")
        for project in projects:
            with self.subTest(project.stem):
                raw = sorted(project.glob("Alternatives/*/ProjectData"))[0].read_bytes()
                recs = project_records(raw)
                seqs = sequences(recs)
                offered = free_table_slot(recs[index_table(recs)].raw[HEADER:], seqs)
                self.assertNotIn(offered, {t.slot for t in seqs})


if __name__ == "__main__":
    unittest.main()
