"""A track `add-track` bound to a free `Audio` strip is not one Logic counts as used: Logic's next
New Audio Track takes that strip for itself and moves the written track onto the next free one with
no input (`stack-sub-gap-logic-track-after-logic`), and a folder stack over Logic's own track leaves
it as it is (`stack-sub-gap-logic-track-stacked-after-logic`)."""

import unittest

import _goldens

from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.mixer.binding import bound_channels, channels, input_labels
from logicxkit.logicx import project_data

BEFORE, AFTER, STACKED = ("stack-sub-gap-before-logic", "stack-sub-gap-logic-track-after-logic",
                          "stack-sub-gap-logic-track-stacked-after-logic")


def audio4(data: bytes) -> list[tuple]:
    """(object id, channel label, input) of every track named Audio 4, in row order."""
    chans, bound, feeds = channels(data), bound_channels(data), input_labels(data)
    return [(t["object_id"], chans[bound[t["object_id"]]].label, feeds.get(bound[t["object_id"]]))
            for t in read_tracks(data) if t["name"] == "Audio 4"]


@_goldens.needs(BEFORE, AFTER, STACKED)
class StubEvictedTest(unittest.TestCase):
    def test_logics_new_track_takes_the_strip_the_written_track_was_bound_to(self):
        before, after = project_data(_goldens.path(BEFORE)), project_data(_goldens.path(AFTER))
        self.assertEqual(audio4(before), [(108, "Audio 4", "Input 1")])
        self.assertEqual(audio4(after), [(108, "Audio 5", None), (104, "Audio 4", "Input 1-2")])

    def test_a_folder_over_logics_track_leaves_its_channel(self):
        stacked = project_data(_goldens.path(STACKED))
        self.assertEqual(audio4(stacked), [(108, "Audio 5", None), (104, "Audio 4", "Input 1-2")])
        self.assertEqual([(s.name, [m[1] for m in s.members]) for s in read_stacks(stacked)][-1], ("Sub 2", ["Audio 4"]))


if __name__ == "__main__":
    unittest.main()
