"""Each table parameter's `min` and `max` come from the displays Logic showed at its slider's two
ends (read through accessibility with no save): the default sits inside, the ends differ, and
`--set` refuses a number outside them."""

import json
import unittest

from logicxkit.logic.services.mixer.plugin_params import Table, int_word, set_by_name
from logicxkit.utils.data import PACKAGED


class RangesTest(unittest.TestCase):
    def test_every_range_holds_its_default_and_the_count_is_pinned(self):
        ranged, tables_with = 0, 0
        for f in sorted((PACKAGED / "logic").glob("params-*.json")):
            t = json.loads(f.read_text())
            if any("min" in p for p in t["params"]):
                tables_with += 1
            for p in t["params"]:
                if "min" not in p:
                    continue
                ranged += 1
                with self.subTest(f"{t['name']} {p['name']}"):
                    self.assertLess(p["min"], p["max"])
                    default = p.get("default")
                    if isinstance(default, (int, float)):
                        word = int_word(default) if p.get("kind") == "int" and p.get("offset") is None and abs(default) < 1e-30 else default
                        self.assertTrue(p["min"] - 1e-6 <= word * p.get("scale", 1.0) <= p["max"] + 1e-6, (word, p["min"], p["max"]))
        self.assertEqual((ranged, tables_with), (877, 41))          # a fold that drops ranges shows here

    def test_a_number_outside_the_range_is_refused(self):
        from _fixtures import chunk
        table = Table.from_dict({"type": 189, "name": "Test ES1", "floats": 2, "opaque": [0],
                                 "params": [{"index": 1, "name": "Glide", "unit": "ms", "min": 0.0, "max": 5000.0, "default": 0.0}],
                                 "evidence": "synthetic"})
        payload = chunk(189, [0.0, 0.0])
        set_by_name(table, payload, {"Glide": 120})
        with self.assertRaisesRegex(ValueError, "outside 0.0..5000.0 ms"):
            set_by_name(table, payload, {"Glide": 6000})


if __name__ == "__main__":
    unittest.main()
