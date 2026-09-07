"""The real rig baseline: the documented scene must pass the checked-in expected-config
cleanly. x32scene's own golden runs against an anonymized scene, not this one.
"""

import json
import os
import unittest

import _paths

try:                                    # the opt-in `rig` extra (bin/run setup rig)
    from x32scene.model import Scene
    from x32scene.services.preflight import preflight
except ImportError as e:
    raise unittest.SkipTest(f"x32scene is not installed: {e} — run bin/run setup") from e

REAL_SCENE = str(_paths.SCENE)
RIG_PREFLIGHT = str(_paths.RIG_CONFIG / "x32" / "preflight.json")


@unittest.skipIf(not os.path.exists(REAL_SCENE) or not os.path.exists(RIG_PREFLIGHT),
                 "the rig scene or its preflight config is not present")
class GoldenPreflightTest(unittest.TestCase):
    def test_documented_scene_passes_checked_in_config(self):
        with open(RIG_PREFLIGHT, encoding="utf-8") as fh:
            expected = json.load(fh)
        self.assertEqual(preflight(Scene.load(REAL_SCENE), expected), [])


if __name__ == "__main__":
    unittest.main()
