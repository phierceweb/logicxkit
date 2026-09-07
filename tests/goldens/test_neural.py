"""Neural DSP plugin-state decode: AU plist discovery, NDSP filtering, and
file-level reading. The JUCE container formats themselves are covered in
tests/au/test_juce.py.

Golden tests run against the real strips and templates and auto-skip when absent.

The real-file part of tests/logic/test_neural.py; skips without the owner's files."""

import os
import unittest
import _paths
from logicxkit.logic import read_neural

GUITAR_DIR = str(_paths.STRIP_ROOT / "Track" / _paths.STRIP_LIB)
SLO_CST = os.path.join(GUITAR_DIR, "Guitar", "Guitar SLO.cst")
OLD_SOLDANO_CST = os.path.join(GUITAR_DIR, "Drums", "Guitar 1.cst")
MIX_TEMPLATE = str(_paths.project("Mix"))


@unittest.skipIf(not os.path.exists(SLO_CST), "real Guitar SLO.cst not present")
class GoldenSloTest(unittest.TestCase):
    def test_slo_strip_decodes_known_knobs(self):
        states = read_neural(SLO_CST)
        self.assertEqual(len(states), 1)
        s = states[0]
        self.assertEqual(s["format"], "xml")
        self.assertEqual(s["meta"]["pluginVersion"], "1.0.0")
        self.assertEqual(s["sections"]["amp"]["ampBass"], 0.71)
        self.assertIs(s["sections"]["drive1"]["drive1Active"], True)
        self.assertIs(s["sections"]["soldanoEQ"]["soldanoEQActive"], True)


@unittest.skipIf(not os.path.exists(OLD_SOLDANO_CST), "real Guitar 1.cst not present")
class GoldenOldSoldanoTest(unittest.TestCase):
    def test_v1_soldano_value_tree_decodes(self):
        states = read_neural(OLD_SOLDANO_CST)
        self.assertEqual(len(states), 1)
        s = states[0]
        self.assertEqual(s["format"], "tree")
        self.assertEqual(s["meta"]["plugin_name"], "Soldano SLO-100")
        self.assertEqual(s["meta"]["presetNameProp"], "Default")
        self.assertAlmostEqual(s["sections"]["params"]["ampBass"], 0.71, places=5)


@unittest.skipIf(not os.path.isdir(MIX_TEMPLATE), "Mix template not present")
class GoldenMixTemplateTest(unittest.TestCase):
    def test_template_neural_states_attributed_to_channels(self):
        states = read_neural(MIX_TEMPLATE)
        self.assertGreaterEqual(len(states), 2)
        for s in states:
            self.assertTrue(s["sections"])
        attributed = [s for s in states if s.get("channel")]
        self.assertGreaterEqual(len(attributed), 2)


if __name__ == "__main__":
    unittest.main()
