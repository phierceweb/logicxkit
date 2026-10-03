"""Output and input routing: the two UUIDs at the tail of a channel record.

The real-file part of tests/logic/test_routing.py; skips without the owner's files."""

import unittest
import _goldens
from logicxkit.logic.services.mixer.binding import output_routing
from logicxkit.logic.services.mixer.routing import set_output



@_goldens.needs("tracking-template")
class GoldenRoutingTest(unittest.TestCase):
    def test_rerouting_a_drum_to_stereo_out_changes_only_that_channel(self):
        from logicxkit.logic.services.stream.recdiff import diff_records
        from logicxkit.logic.services.mixer.transplant import owner_of
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path("tracking-template"))
        kick, so = owner_of(data, "Audio 1"), owner_of(data, "Output 1-2")
        out = set_output(data, kick, so)
        self.assertEqual(output_routing(out)[kick], so)
        d = diff_records(data, out)
        self.assertEqual((d.added, d.removed), ([], []))
        self.assertTrue(all(c.owner == kick for c in d.changed))


@_goldens.needs("route-ours", "route-resave-logic")
class LogicResavedRouteTest(unittest.TestCase):
    def test_logic_kept_the_rerouted_output(self):
        from logicxkit.logic.services.mixer.binding import channels
        from logicxkit.logicx import project_data
        ours, logic = (project_data(_goldens.path(k)) for k in ("route-ours", "route-resave-logic"))
        labels = {o: c.label for o, c in channels(logic).items()}
        want = (_goldens.fact("route-ours", "channel"), _goldens.fact("route-ours", "output"))
        for data in (ours, logic):
            routed = {labels[o]: labels.get(d) for o, d in output_routing(data).items() if o in labels}
            self.assertEqual(routed[want[0]], want[1])
        self.assertEqual({o: d for o, d in output_routing(ours).items() if o in labels},
                         {o: d for o, d in output_routing(logic).items() if o in labels})


if __name__ == "__main__":
    unittest.main()
