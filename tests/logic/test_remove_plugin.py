"""`remove_plugin`: one slot out, the rest closed up, the Smart Control mappings kept honest."""

import unittest

from _records import proj
from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.mixer.slots import SLOT_INDEX_AT
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.mixer.remove_plugin import remove_plugin
from logicxkit.logic.services.mixer.slots import archive_index
from logicxkit.logic.services.mixer.smart_controls import mapping_slots
from logicxkit.logic.services.mixer.transplant import channel_slots
from test_add_plugin import _marker
from test_smart_controls import archive
from test_transplant_ids import au, mono_chan, native, ref

OWNER = 3


def _project(mappings: list[int] = ()) -> bytes:
    """Three slots on keys 4..6 and mappings on the slots given by index."""
    return proj(mono_chan(OWNER, "Audio 3"), native(OWNER, 4, 1), au(OWNER, 5, 2), native(OWNER, 6, 3),
                ref(OWNER, 10), archive(list(mappings), key=12, owner=OWNER), archive([], key=13, owner=OWNER, index=2),
                mono_chan(5, "Audio 5"), native(5, 4, 50), ref(5, 10))


def _archive1(data: bytes) -> bytes:
    return next(r.raw for r in project_records(data) if r.owner == OWNER and archive_index(r.raw) == 1)


class RemoveTest(unittest.TestCase):
    def test_the_middle_slot_goes_and_the_last_closes_up(self):
        out, report = remove_plugin(_project(), OWNER, 2)
        got = channel_slots(out, OWNER)
        self.assertEqual([r.key for r in got], [4, 5])
        self.assertEqual([r.raw[HEADER + SLOT_INDEX_AT] for r in got], [0, 1])
        self.assertEqual([_marker(r.raw) for r in got], [_marker(native(OWNER, 4, 1)), _marker(native(OWNER, 6, 3))])
        self.assertEqual((report["key"], report["moved"], report["slots"]), (5, [(6, 5)], 2))

    def test_the_last_slot_moves_nothing(self):
        out, report = remove_plugin(_project(), OWNER, 3)
        self.assertEqual([r.key for r in channel_slots(out, OWNER)], [4, 5])
        self.assertEqual(report["moved"], [])

    def test_a_position_off_the_chain_is_refused(self):
        with self.assertRaises(ValueError):
            remove_plugin(_project(), OWNER, 4)
        with self.assertRaises(ValueError):
            remove_plugin(_project(), OWNER, 0)

    def test_the_other_channel_and_the_rest_survive(self):
        data = _project()
        out, _ = remove_plugin(data, OWNER, 1)
        self.assertEqual([r.key for r in channel_slots(out, 5)], [4])
        self.assertIn(ref(OWNER, 10), out)
        self.assertEqual(len(project_records(out)), len(project_records(data)) - 1)


class MappingTest(unittest.TestCase):
    def test_the_removed_slots_mappings_go_and_later_ones_move_up(self):
        out, _ = remove_plugin(_project([0, 1, 1, 2]), OWNER, 2)
        self.assertEqual(mapping_slots(_archive1(out)), [0, 1])

    def test_removing_the_last_slot_touches_no_mapping_of_the_others(self):
        out, _ = remove_plugin(_project([0, 1]), OWNER, 3)
        self.assertEqual(mapping_slots(_archive1(out)), [0, 1])


class ReplaceTest(unittest.TestCase):
    """Substituting a plug-in is a removal and an insert at the same slot."""

    def test_remove_then_add_at_the_same_slot(self):
        data = _project([0, 1, 2])
        out, _ = remove_plugin(data, OWNER, 2)
        out, report = add_plugin(out, OWNER, native(9, 4, 7), at=2)
        got = channel_slots(out, OWNER)
        self.assertEqual(([r.key for r in got], report["position"]), ([4, 5, 6], 2))
        self.assertEqual(_marker(got[1].raw), _marker(native(OWNER, 5, 7)))
        self.assertEqual(mapping_slots(_archive1(out)), [0, 2])


if __name__ == "__main__":
    unittest.main()
