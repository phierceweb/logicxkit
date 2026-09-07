"""The sequence triple and index table for a new object, as Logic's own adds write them:
lowest free slot, in slot order, linked by `+234`/`+242`, later entries bumped, nothing else
moved."""

import struct
import unittest
import _paths  # noqa: F401
from _records import index_entry, marker, proj, seq_triple, track
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.sequence import (
    QESM_FRESH_AT,
    QESM_INDEX_AT,
    QESM_OBJECT_AT,
    free_table_slot,
    index_table,
    link_errors,
    plan_sequence,
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


def applied(data: bytes, plan) -> bytes:
    records = project_records(data)
    out = []
    for i, r in enumerate(records):
        out.append(plan.rewrite(i, r))
        if i == plan.insert_after:
            out += plan.new
    return data[:24] + b"".join(out)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.data = session()
        self.records = project_records(self.data)
        self.plan = plan_sequence(self.records, like=92, object_id=508)
        self.out = project_records(applied(self.data, self.plan))

    def test_takes_the_lowest_free_slot_and_the_index_after_its_pattern(self):
        self.assertEqual((self.plan.slot, self.plan.index), (28, 4))
        self.assertEqual(free_table_slot(self.records[index_table(self.records)].raw[HEADER:]), 28)

    def test_the_new_triple_links_to_its_entry(self):
        qesm, mk, qsve = self.plan.new
        self.assertEqual(struct.unpack_from("<H", qesm, 10)[0], 28)
        self.assertEqual(struct.unpack_from("<H", qesm, HEADER + QESM_OBJECT_AT)[0], 508)
        self.assertEqual(struct.unpack_from("<h", qesm, HEADER + QESM_INDEX_AT)[0], -4)
        self.assertEqual(struct.unpack_from("<I", qesm, HEADER + QESM_FRESH_AT)[0], 382)
        self.assertEqual(mk[18:22], b"\xff\xff\xff\x7f")            # a real marker, not a row header
        self.assertEqual(struct.unpack_from("<H", mk, 10)[0], 28)
        self.assertEqual((struct.unpack_from("<H", qsve, 10)[0], struct.unpack_from("<H", qsve, 14)[0]),
                         (28, struct.unpack_from("<I", qesm, HEADER + 8)[0]))

    def test_the_seq_id_is_one_nobody_uses(self):
        used = {t.seq_id for t in sequences(self.records)}
        new_id = struct.unpack_from("<I", self.plan.new[0], HEADER + 8)[0]
        self.assertNotIn(new_id, used)

    def test_it_goes_in_slot_order(self):
        slots = [t.slot for t in sequences(self.out) if len(self.out[t.start].raw) - HEADER == 345]
        self.assertEqual(slots, [0, 20, 24, 28, 32, 36])           # the table's own triple leads
        self.assertEqual([t.slot for t in sequences(self.out)][-1], 1024)   # the tail stays last

    def test_later_entries_move_up_and_their_triples_follow(self):
        table = self.out[index_table(self.out)].raw[HEADER:]
        self.assertEqual([(oid, idx, slot) for _a, oid, idx, slot in table_entries(table)],
                         [(88, 2, 20), (92, 3, 24), (152, 5, 32), (504, 6, 36), (508, 4, 28)])
        self.assertEqual(link_errors(self.out), [])

    def test_no_other_triple_moves(self):
        before = {t.slot: (self.records[t.start].raw[:HEADER], self.records[t.start].raw[HEADER:HEADER + QESM_INDEX_AT])
                  for t in sequences(self.records)}
        after = {t.slot: (self.out[t.start].raw[:HEADER], self.out[t.start].raw[HEADER:HEADER + QESM_INDEX_AT])
                 for t in sequences(self.out)}
        for slot, value in before.items():
            self.assertEqual(after[slot], value, slot)

    def test_the_entry_goes_before_the_tail(self):
        data = session(tail=b"\xf1" + bytes(15))
        records = project_records(data)
        plan = plan_sequence(records, like=92, object_id=508)
        self.assertEqual(plan.table[-16:], b"\xf1" + bytes(15))
        self.assertEqual(len(plan.table), 5 * 80 + 16)

    def test_the_table_is_the_one_with_slot_words_not_the_biggest(self):
        zeroed = b"".join(index_entry(0, 0, 0) for _ in range(40)) + bytes(16)
        data = session() + seq_triple(20, slot=0, big=zeroed, size=341)
        data = data[:16] + struct.pack("<I", len(data) - 24) + data[20:]
        records = project_records(data)
        table = records[index_table(records)].raw[HEADER:]
        self.assertEqual(len(table), 4 * 80)
        self.assertEqual(plan_sequence(records, like=92, object_id=508).slot, 28)

    def test_refuses_an_object_without_an_entry(self):
        with self.assertRaises(ValueError):
            plan_sequence(self.records, like=999, object_id=508)


if __name__ == "__main__":
    unittest.main()
