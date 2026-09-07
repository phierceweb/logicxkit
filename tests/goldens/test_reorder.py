"""Arrange-row moves. A real drag (Ride above Hi Hat, 2026-09-01) renumbered two keys and
touched nothing else, so a same-parent move is a splice plus renumber.

The real-file part of tests/logic/test_reorder.py; skips without the owner's files."""

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
