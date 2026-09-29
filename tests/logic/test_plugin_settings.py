"""`add-plugin --set NAME=VALUE` on one of Logic's own: a mapped parameter goes where its slider
keeps it (held to the measured ends with a note, on the grid, the nearer sampled position); one
no map measures goes as given."""

import unittest

from logicxkit.logic._plugin_settings import gridded
from logicxkit.logic.services.insert import HEADER
from logicxkit.logic.services.plugin_library import find_donor, load_library
from logicxkit.utils.data import PACKAGED


def _payload(name: str) -> bytes:
    return find_donor(load_library([PACKAGED / "donors"]), name, width=None, version=None).raw[HEADER:]


class GriddedTest(unittest.TestCase):
    def test_a_mapped_native_is_held_to_its_slider_and_snapped(self):
        values, notes = gridded(_payload("Compressor"), {"Threshold": "500", "Ratio": "-3", "Attack": "4.05"})
        self.assertEqual(values, {"Threshold": 0.0, "Ratio": 1.0, "Attack": 4.0})
        self.assertEqual(notes, ["Threshold 500: Compressor's slider runs -50..0; set to 0",
                                 "Ratio -3: Compressor's slider runs 1..30; set to 1"])

    def test_a_choice_by_name_and_an_unmapped_plug_in_pass_through(self):
        self.assertEqual(gridded(_payload("Compressor"), {"Auto Release": "On"})[0], {"Auto Release": "On"})

    def test_the_vocabularys_spelling_gets_the_same_grid_and_clamp(self):
        values, notes = gridded(_payload("Compressor"), {"threshold": "999", "attack": "20.5"})
        self.assertEqual(values, {"threshold": 0.0, "attack": 20.0})
        self.assertEqual(len(notes), 1)
        self.assertEqual(gridded(_payload("Gain"), {"Gain": "99"}), ({"Gain": "99"}, []))


if __name__ == "__main__":
    unittest.main()
