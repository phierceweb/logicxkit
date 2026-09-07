"""Output and input routing: the two UUIDs at the tail of a channel record.

The real-file part of tests/logic/test_routing.py; skips without the owner's files."""

import unittest
import _goldens
from logicxkit.logic.services.binding import output_routing
from logicxkit.logic.services.routing import set_output



@_goldens.needs("tracking-template")
class GoldenRoutingTest(unittest.TestCase):
    def test_rerouting_a_drum_to_stereo_out_changes_only_that_channel(self):
        from logicxkit.logic.services.recdiff import diff_records
        from logicxkit.logic.services.transplant import owner_of
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path("tracking-template"))
        kick, so = owner_of(data, "Audio 1"), owner_of(data, "Output 1-2")
        out = set_output(data, kick, so)
        self.assertEqual(output_routing(out)[kick], so)
        d = diff_records(data, out)
        self.assertEqual((d.added, d.removed), ([], []))
        self.assertTrue(all(c.owner == kick for c in d.changed))


if __name__ == "__main__":
    unittest.main()
