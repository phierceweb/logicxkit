"""A `Sub` strip a convert left out of use with a pan, an insert and a send, reused by Create Track
Stack: Logic keeps the pan and drops the insert and the send (`stack-sub-settings-reused-after-logic`);
`stack-create` on the save before does the same."""

import unittest

import _goldens

from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.levels import read_levels
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.mixer.sends import read_sends
from logicxkit.logicx import project_data

BEFORE, AFTER = "stack-sub-settings-convert-after-logic", "stack-sub-settings-reused-after-logic"


def strip(data: bytes, label: str) -> dict:
    chans = channels(data)
    owner = next(o for o, c in chans.items() if c.label == label)
    return {"in_use": chans[owner].in_use, "pan": read_levels(data)[owner]["pan"],
            "slots": [r.name for r, _p in slot_payloads(data) if r.channel == label],
            "sends": sorted(s.bus for s in read_sends(data).get(owner, []))}


@_goldens.needs(BEFORE, AFTER)
class ReusedSubStripTest(unittest.TestCase):
    def test_logic_kept_the_pan_and_dropped_the_insert_and_the_send(self):
        before, after = project_data(_goldens.path(BEFORE)), project_data(_goldens.path(AFTER))
        self.assertEqual(strip(before, "Sub 1"), {"in_use": False, "pan": 34, "slots": ["Compressor"], "sends": [3]})
        self.assertEqual(strip(after, "Sub 1"), {"in_use": True, "pan": 34, "slots": [], "sends": []})
        self.assertEqual([(s.name, s.kind) for s in read_stacks(after)], [("Sum 2", "summing"), ("Sub 1", "folder")])

    def test_stack_create_reuses_the_strip_the_same_way(self):
        before, after = project_data(_goldens.path(BEFORE)), project_data(_goldens.path(AFTER))
        members = [t["object_id"] for t in read_tracks(before) if t["name"] in ("Audio 1", "Audio 2", "Audio 3")]
        ours, _report = create_stack(before, name="Sub 1", members=members)
        self.assertEqual(strip(ours, "Sub 1"), strip(after, "Sub 1"))
        self.assertEqual([(s.name, s.kind, [m[1] for m in s.members]) for s in read_stacks(ours)],
                         [(s.name, s.kind, [m[1] for m in s.members]) for s in read_stacks(after)])


if __name__ == "__main__":
    unittest.main()
