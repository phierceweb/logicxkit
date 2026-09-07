"""Track stacks and the arrange track list.

`karT` rows (key = display order, +8 = object id, +0 flags, +14 = inside-a-stack), `ivnE`
objects (names), and the `OCuA` channels each row is bound to. A stack is a grouping object
bound to a `Sub N` strip; its members are the rows below it whose +14 byte is set.

The real-file part of tests/logic/test_stacks.py; skips without the owner's files."""

import unittest
import _goldens
from logicxkit.logic.services.stacks import (
    read_stacks,
    read_tracks,
)

GOLDEN_OFF = _goldens.path("power-off")
GOLDEN_ON = _goldens.path("power-on")


TEMPLATE = _goldens.path("tracking-template")


@_goldens.needs("tracking-template")
class GoldenStackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from logicxkit.logic.services.project import project_metadata
        from logicxkit.logicx import project_data
        cls.data = project_data(TEMPLATE)
        cls.count = project_metadata(TEMPLATE)["tracks"]

    def test_exactly_the_sub_bound_stacks(self):
        stacks = read_stacks(self.data, self.count)
        self.assertEqual(sorted(s.index for s in stacks), list(range(1, len(stacks) + 1)))
        self.assertEqual(len(stacks), _goldens.fact("tracking-template", "stacks", 7))

    def test_members_agree_with_the_stack_index_where_it_is_set(self):
        rows = {r["key"]: r for r in read_tracks(self.data, self.count)}
        for s in read_stacks(self.data, self.count):
            for key, name in s.members:
                idx = rows[key]["stack_index"]
                self.assertIn(idx, (0, s.index), f"{name} in {s.name} carries index {idx}")
        top = [r["name"] for r in rows.values() if not r["member"] and not r["grouping"]]
        self.assertIn("Cymbals", top)

    def test_hidden_rows_are_read_by_bit(self):
        hidden = [r["name"] for r in read_tracks(self.data, self.count) if r["hidden"]]
        self.assertGreaterEqual(len(hidden), 4)


@unittest.skipUnless(GOLDEN_OFF and GOLDEN_ON, "the power-button saves are not present")
class GoldenPowerTest(unittest.TestCase):
    def test_switching_a_track_on_flips_the_bit_on_its_row_only(self):
        from logicxkit.logicx import project_data
        from logicxkit.logic.services.project import project_metadata
        from logicxkit.logic.services.stacks import read_tracks
        off, on = project_data(GOLDEN_OFF), project_data(GOLDEN_ON)
        a = {r["name"]: r["on"] for r in read_tracks(off, project_metadata(GOLDEN_OFF)["tracks"])}
        b = {r["name"]: r["on"] for r in read_tracks(on, project_metadata(GOLDEN_ON)["tracks"])}
        self.assertEqual({k for k in a if a[k] != b[k]}, {"Gtr 1 DI"})
        self.assertEqual((a["Gtr 1 DI"], b["Gtr 1 DI"], b["Gtr 2 DI"]), (False, True, False))


if __name__ == "__main__":
    unittest.main()
