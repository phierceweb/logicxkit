"""Arrange-row moves against Logic's own saves; the real-file part of
tests/logic/test_reorder.py."""

import unittest
import _goldens
from logicxkit.logic.services.reorder import move_track
from logicxkit.logic.services.stacks import read_stacks, read_tracks



@_goldens.needs("tracking-template")
class GoldenMoveTest(unittest.TestCase):
    def test_moving_ride_above_hi_hat_keeps_every_stack(self):
        from logicxkit.logic.services.project import project_metadata
        from logicxkit.logicx import project_data
        template = _goldens.path("tracking-template")
        data = project_data(template)
        count = project_metadata(template)["tracks"]
        by = {r["name"]: r["object_id"] for r in read_tracks(data, count)}
        out = move_track(data, by["Ride"], before=by["Hi Hat"], track_count=count)
        before = [(s.name, len(s.members)) for s in read_stacks(data, count)]
        self.assertEqual([(s.name, len(s.members)) for s in read_stacks(out, count)], before)


if __name__ == "__main__":
    unittest.main()


@_goldens.needs("stack-folder-of-one-logic", "stack-header-reordered-logic")
class StackHeaderMoveTest(unittest.TestCase):
    """Logic's own drag of a stack header two rows down: header and member move as a block."""

    def test_moving_the_header_reproduces_logics_rows(self):
        from logicxkit.logic.services.recdiff import diff_records, load_project_data
        from logicxkit.logic.services.reorder import move_track
        from logicxkit.logic.services.stacks import read_tracks
        a = load_project_data(_goldens.path("stack-folder-of-one-logic"))
        b = load_project_data(_goldens.path("stack-header-reordered-logic"))
        rows = {r["name"]: r for r in read_tracks(a, 5)}
        ours = move_track(a, rows["Sub 2"]["object_id"], after=rows["Audio 2"]["object_id"], track_count=5)
        self.assertEqual([r["name"] for r in read_tracks(ours, 5)], _goldens.fact("stack-header-reordered-logic", "order"))
        d = diff_records(ours, b)
        self.assertFalse(d.added or d.removed)
        self.assertEqual([c.tag for c in d.changed if c.tag not in (b"gnoS", b"qeSM")], [])


@_goldens.needs("stack-summing-logic")
class SummingStackMoveTest(unittest.TestCase):
    def setUp(self):
        from logicxkit.logic.services.recdiff import load_project_data
        self.data = load_project_data(_goldens.path("stack-summing-logic"))
        self.rows = {r["name"]: r["object_id"] for r in read_tracks(self.data, 5)}

    def test_moving_a_member_out_is_refused(self):
        with self.assertRaisesRegex(ValueError, "different parents"):
            move_track(self.data, self.rows["Audio 1"], after=self.rows["Stereo Out"], track_count=5)

    def test_moving_a_top_level_row_in_is_refused(self):
        with self.assertRaisesRegex(ValueError, "different parents"):
            move_track(self.data, self.rows["Stereo Out"], after=self.rows["Audio 1"], track_count=5)
