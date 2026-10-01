"""Track automation as Logic's own point creates wrote it (2026-09-16): a volume
point at the region border, two more, a plug-in parameter point, the lane converted to region
automation. Skips without the public corpus."""

import unittest
import _goldens
from logicxkit.logic.services.automation import read_automation
from logicxkit.logic.services.events import BAR_ONE
from logicxkit.logicx import project_data

KEYS = ("automation-volume-point-logic", "automation-volume-three-points-logic", "automation-eq-inserted-logic",
        "automation-region-converted-logic", "automation-pan-point-logic", "automation-plugin-point-logic")


def _lanes(key: str) -> list[dict]:
    folders = [a for a in read_automation(project_data(_goldens.path(key))) if a.lanes]
    return [{"track": a.track, "parameter": ln.parameter, "region": ln.region,
             "ticks": [p.tick for p in ln.points], "values": [round(p.value, 4) for p in ln.points]}
            for a in folders for ln in a.lanes]


@_goldens.needs(*KEYS)
class AutomationGoldensTest(unittest.TestCase):
    def test_each_save_reads_the_lanes_its_manifest_records(self):
        for key in KEYS:
            with self.subTest(key):
                self.assertEqual(_lanes(key), _goldens.fact(key, "lanes"))

    def test_the_first_point_sits_at_bar_one_at_unity(self):
        (lane,) = _lanes("automation-volume-point-logic")
        self.assertEqual((lane["track"], lane["parameter"], lane["ticks"], lane["values"]), ("Audio 2", "Volume", [BAR_ONE], [90.0]))

    def test_create_two_adds_the_border_pair(self):
        (lane,) = [ln for ln in _lanes("automation-volume-three-points-logic") if ln["parameter"] == "Volume"]
        self.assertEqual(len(lane["ticks"]), 3)

    def test_the_border_points_sit_half_a_tick_either_side_of_the_region(self):
        """Create 2 puts one point half a tick before the region start and one half a tick after."""
        folders = read_automation(project_data(_goldens.path("automation-volume-three-points-logic")))
        (lane,) = [ln for a in folders for ln in a.lanes if ln.parameter == "Volume"]
        self.assertEqual([p.position for p in lane.points], [BAR_ONE - 0.5, BAR_ONE, BAR_ONE + 0.5])
        self.assertEqual([p.fraction for p in lane.points], [0x8000, 0, 0x8000])

    def test_a_plugin_parameter_point_carries_its_index_and_a_unit_float(self):
        lanes = _lanes("automation-plugin-point-logic")
        (param,) = [ln for ln in lanes if ln["parameter"].startswith("insert ")]
        self.assertEqual((param["parameter"], param["ticks"], param["values"]), ("insert 1 parameter 26", [BAR_ONE], [0.4961]))    # u32 3f7fff50 over 2^31: 0 dB of ±30

    def test_conversion_gives_the_region_its_own_lane(self):
        lanes = _lanes("automation-region-converted-logic")
        self.assertTrue(any(ln["region"] for ln in lanes), lanes)
        self.assertTrue(all(ln["track"] == "Audio 2" for ln in lanes), lanes)


@_goldens.needs("meter-baseline-logic")
class FlaggedParameterPointTest(unittest.TestCase):
    """A real song's parameter lane holds points whose type word carries bit 14; they read as
    flagged rather than vanishing from the count."""

    def test_every_parameter_point_is_read(self):
        key = "meter-baseline-logic"
        folders = read_automation(project_data(_goldens.path(key)))
        obj = _goldens.fact(key, "param_track_object")
        (lane,) = [ln for a in folders if a.track_object == obj for ln in a.lanes if ln.param_index is not None]
        self.assertEqual(len(lane.points), _goldens.fact(key, "param_points"))
        self.assertEqual(sum(p.flagged for p in lane.points), _goldens.fact(key, "flagged_points"))
        self.assertGreater(_goldens.fact(key, "flagged_points"), 0)


if __name__ == "__main__":
    unittest.main()
