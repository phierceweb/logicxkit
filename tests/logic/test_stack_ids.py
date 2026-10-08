"""Which object id a new stack header takes: a gone object's, when its entries sit as Logic's
convert parks them and it is the only one gone, else the next past the highest."""

import struct
import unittest
from _records import (
    chan,
    count_record,
    env_obj,
    gnos,
    index_entry,
    marker,
    proj,
    seq_triple,
    track,
    uuid,
)
from logicxkit.logic.services.arrange.environment import channel_objects, next_object_id
from logicxkit.logic.services.arrange.stack_ids import free_object_id
from logicxkit.logic.services.stream.registry import gone_object_ids
from logicxkit.logic.services.stream.stream import HEADER, project_records

TRACKS = 3
MIXER = [88, 92, 80]                                    # the flat list's bound rows, mixer order


def session(*gone: tuple[int, int], head: int | None = None, no_entry: tuple[int, ...] = ()) -> bytes:
    """Kick In, Snare Up, Master — with ``gone`` as (object id, index-table index) pairs whose
    registry entries carry a zero UUID and no object; with ``head`` set their rows are parked at
    the head of the mixer-order list, as Logic's convert and delete leave them."""
    gone_ids = [g for g, _i in gone]
    table = (b"".join(index_entry(g, i, 100 + 4 * k) for k, (g, i) in enumerate(gone) if g not in no_entry)
             + b"".join(index_entry(oid, 4 + k, 20 + 4 * k) for k, oid in enumerate(MIXER)))
    registry = gnos(*MIXER, *gone_ids)
    for g in gone_ids:
        registry = registry.replace(uuid(g), bytes(16))
    parked = [g for g, _i in gone] if head is not None else []                 # every gone row parked at the head, in order
    flat = parked + [296, 300, 304] + MIXER                                    # the mixer-order list holds more rows
    return proj(
        count_record(6, [2, 0, 0, 1, 0, 0, 0], 6),
        registry,
        env_obj(88, "Kick In"), env_obj(92, "Snare Up"), env_obj(80, "Master", grouping=True),
        chan(0, "Audio 1", uuid=uuid(88)), chan(2, "Audio 3", uuid=uuid(92)),
        chan(382, "Output 1-2", uuid=uuid(80), size=201),
        seq_triple(1, big=table),
        track(0, 88), track(1, 92), track(2, 80, flag=3), marker(),
        *(track(k, oid) for k, oid in enumerate(flat)), marker(),
        *(seq_triple(2 + k, slot=20 + 4 * k, object_id=oid, index=4 + k) for k, oid in enumerate(MIXER)),
        seq_triple(9, slot=100, size=341))


def answer(data: bytes) -> tuple[int, bool]:
    records = project_records(data)
    return free_object_id(records, channel_objects(data), TRACKS)


class GoneIdTest(unittest.TestCase):
    def test_the_fixture_carries_the_gone_ids(self):
        data = session((100, 1), head=100)
        registry = next(r.raw[HEADER:] for r in project_records(data) if r.tag == b"gnoS")
        self.assertEqual(gone_object_ids(registry, min(channel_objects(data))), [100])
        self.assertEqual(gone_object_ids(next(r.raw[HEADER:] for r in project_records(session()) if r.tag == b"gnoS"), 80), [])

    def test_the_one_gone_id_is_taken(self):
        """`stackid-c1-logic` to `-c2`: the entry parked at index 1, its row at the head of the list."""
        self.assertEqual(answer(session((100, 1), head=100)), (100, True))

    def test_none_gone_gives_the_next_past_the_highest(self):
        data = session()
        self.assertEqual(answer(data), (next_object_id(project_records(data)), False))

    def test_a_gone_id_parked_at_another_index_is_taken_too(self):
        """`gone-d4-logic`: Logic's new header took 108 from index 2 over 112 at index 1."""
        self.assertEqual(answer(session((100, 3), head=100)), (100, True))

    def test_the_lowest_of_several_gone_ids_is_taken(self):
        """Three parked (104 at 3, 108 at 2, 112 at 1, rows 112 first): the lowest id, as
        Logic's new track and new header took it (`gone-d3-logic`, `gone-d4-logic`)."""
        self.assertEqual(answer(session((112, 1), (108, 2), (104, 3), head=112)), (104, True))

    def test_a_gone_id_with_no_parked_row_or_no_table_entry_is_not_taken(self):
        data = session((100, 1))                                   # no row parked for it
        self.assertEqual(answer(data), (next_object_id(project_records(data)), False))
        data = session((100, 1), head=100, no_entry=(100,))      # the registry says gone, the table has no entry
        self.assertEqual(answer(data), (next_object_id(project_records(data)), False))

    def test_the_gone_triples_kind_byte_is_read(self):
        """`gone-d3-logic` is the one measured add on a gone id: an audio track on a deleted audio
        track's id, whose kept triple reads 9 at +39; `add_track` reuses on that byte alone."""
        from logicxkit.logic.services.arrange.stack_ids import gone_triple_kind
        from logicxkit.logic.services.stream.stream import reassemble
        data = session((100, 1), head=100)
        records = project_records(data)
        self.assertEqual(gone_triple_kind(records, 100), 0)        # the fixture's triple carries no kind
        self.assertIsNone(gone_triple_kind(project_records(session((100, 1), head=100, no_entry=(100,))), 100))
        out = []
        for r in records:
            raw = bytearray(r.raw)
            if r.tag == b"qeSM" and struct.unpack_from("<I", raw, HEADER + 8)[0] == 9:
                raw[HEADER + 39] = 9
            out.append(bytes(raw))
        self.assertEqual(gone_triple_kind(project_records(reassemble(data, out)), 100), 9)


if __name__ == "__main__":
    unittest.main()
