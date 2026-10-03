"""A plug-in parameter lane written into a Logic-made automation folder and read back, the
folder's other lanes kept. Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logic.services.regions.automation_write import set_param_lane
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logicx import project_data


@_goldens.needs("automation-plugin-point-logic")
class ParamLaneTest(unittest.TestCase):
    def test_a_lane_is_written_beside_the_others_and_replaced_by_index(self):
        data = project_data(_goldens.path("automation-plugin-point-logic"))
        obj = next(r["object_id"] for r in read_tracks(data, None) if r["name"] == "Audio 2")
        before = {lane.parameter: len(lane.points) for a in read_automation(data) if a.track == "Audio 2" for lane in a.lanes if not a.lanes[0].region}
        out = set_param_lane(data, obj, 3, [(38400, 0.25), (42240, 0.75)])
        out = set_param_lane(out, obj, 26, [(38400, 0.5)])                  # Logic's own High Shelf Gain lane, replaced
        lanes = {lane.parameter: lane for a in read_automation(out) if a.track == "Audio 2" for lane in a.lanes if not lane.region}
        self.assertEqual([(p.tick, p.value) for p in lanes["insert 1 parameter 3"].points], [(38400, 0.25), (42240, 0.75)])
        self.assertEqual([(p.tick, p.value) for p in lanes["insert 1 parameter 26"].points], [(38400, 0.5)])
        self.assertEqual(len(lanes["Volume"].points), before["Volume"])


@_goldens.needs("translate-proc")
class CarrySlotTest(unittest.TestCase):
    def test_lanes_of_a_slot_are_carried_and_the_rest_left(self):
        from logicxkit.logic.services.translate.automation_remap import carry_slot, slot_lanes
        from logicxkit.logic.services.translate.translate import load_maps
        from logicxkit.utils.data import PACKAGED
        proc = next(m for m in load_maps([PACKAGED / "translate"]) if m.plugin == "Pro-C 2")
        data = project_data(_goldens.path("translate-proc"))
        obj = next(r["object_id"] for r in read_tracks(data, None) if r["name"] == "Audio 2")
        data = set_param_lane(data, obj, 1, [(38400, 0.5), (42240, 0.75)], slot=3)      # Pro-C 2 threshold
        data = set_param_lane(data, obj, 99, [(38400, 0.5)], slot=3)                    # nothing the map names
        data = set_param_lane(data, obj, 0, [(38400, 0.25)], slot=1)                    # the Compressor's, left alone
        out, notes = carry_slot(data, obj, 3, proc, proc, None, None)
        lanes = {lane.param_index: lane for lane in slot_lanes(out, obj, 3)}
        self.assertEqual(sorted(lanes), [1])
        self.assertEqual([(p.tick, p.value) for p in lanes[1].points], [(38400, 0.5), (42240, 0.75)])
        self.assertEqual([lane.param_index for lane in slot_lanes(out, obj, 1)], [0])
        self.assertEqual(notes, ["lane insert 3 parameter 99: Pro-C 2 has no vocabulary item there; dropped",
                                 "lane insert 3 parameter 1 -> insert 3 parameter 1: 2 point(s) carried"])


if __name__ == "__main__":
    unittest.main()
