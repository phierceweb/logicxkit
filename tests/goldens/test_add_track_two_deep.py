"""Track > New Audio Track with a track selected two levels down (inside a folder that sits in a
summing stack): Logic puts the new track at the top level, right after the outer stack, in no
stack and on Output 1-2; `add-track` after that track does the same."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.arrange.environment import PARENT_AT, object_id_of
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.arrange.tracklist import MEMBER_AT, arrange_run, row_object
from logicxkit.logic.services.mixer.binding import channels, output_routing
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

BEFORE, AFTER = "stack-summing-around-folder-after-logic", "stack-newtrack-in-folder-in-summing-after-logic"


def rows(data: bytes) -> list[tuple]:
    records = project_records(data)
    parents = {object_id_of(r): struct.unpack_from("<I", r.raw, HEADER + PARENT_AT)[0]
               for r in records if object_id_of(r) is not None and len(r.raw) >= HEADER + PARENT_AT + 4}
    names = {t["object_id"]: t["name"] for t in read_tracks(data)}
    return [(names.get(row_object(records[i].raw)), records[i].raw[HEADER + MEMBER_AT], parents.get(row_object(records[i].raw)))
            for i in arrange_run(records)]


def outputs(data: bytes) -> dict[str, str | None]:
    chans, route = channels(data), output_routing(data)
    return {c.label: (chans[route[o]].label if route.get(o) in chans else None)
            for o, c in chans.items() if c.in_use and c.label.startswith(("Audio", "Aux"))}


@_goldens.needs(BEFORE, AFTER)
class NewTrackTwoDeepTest(unittest.TestCase):
    def test_logics_new_track_sits_at_the_top_level_after_the_outer_stack(self):
        after = project_data(_goldens.path(AFTER))
        self.assertEqual(rows(after), [("Sum 1", 0, 0), ("Sub 1", 1, 104), ("Audio 1", 2, 104), ("Audio 2", 2, 104),
                                       ("Audio 3", 2, 104), ("Audio 4", 0, 0), ("Stereo Out", 0, 0)])
        self.assertEqual([(s.name, [m[1] for m in s.members]) for s in read_stacks(after)],
                         [("Sum 1", ["Sub 1"]), ("Sub 1", ["Audio 1", "Audio 2", "Audio 3"])])
        self.assertEqual(outputs(after)["Audio 4"], "Output 1-2")

    def test_add_track_after_a_track_two_deep_does_the_same(self):
        before = project_data(_goldens.path(BEFORE))
        selected = next(t["object_id"] for t in read_tracks(before) if t["name"] == "Audio 2")
        ours, _report = add_track(before, name="Audio 4", after=selected)
        after = project_data(_goldens.path(AFTER))
        self.assertEqual(rows(ours), rows(after))
        self.assertEqual(outputs(ours), outputs(after))


if __name__ == "__main__":
    unittest.main()
