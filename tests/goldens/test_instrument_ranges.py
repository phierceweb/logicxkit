"""Each table parameter's `min` and `max` come from the displays Logic showed at its slider's two
ends (read through accessibility with no save): the default sits inside, the ends differ, and
`--set` refuses a number outside them. A slider ending on a word at one end (Mute, off, Linked,
inf) carries the other end alone, and the default sits on its side of it."""

import json
import unittest

from logicxkit.logic.services.mixer.plugin_params import Table, int_word, set_by_name
from logicxkit.utils.data import PACKAGED


class RangesTest(unittest.TestCase):
    def test_every_range_holds_its_default_and_the_counts_are_pinned(self):
        both, one, tables_with = 0, 0, 0
        for f in sorted((PACKAGED / "logic").glob("params-*.json")):
            t = json.loads(f.read_text())
            if any("min" in p and "max" in p for p in t["params"]):
                tables_with += 1
            for p in t["params"]:
                lo, hi = p.get("min"), p.get("max")
                if lo is None and hi is None:
                    continue
                both += lo is not None and hi is not None
                one += (lo is None) != (hi is None)
                with self.subTest(f"{t['name']} {p['name']}"):
                    if lo is not None and hi is not None:
                        self.assertLess(lo, hi)
                    default = p.get("default")
                    if isinstance(default, (int, float)):
                        word = int_word(default) if p.get("kind") == "int" and p.get("offset") is None and abs(default) < 1e-30 else default
                        value = word * p.get("scale", 1.0)
                        if lo is not None:
                            self.assertGreaterEqual(value, lo - 1e-6, (word, lo, hi))
                        if hi is not None:
                            self.assertLessEqual(value, hi + 1e-6, (word, lo, hi))
        self.assertEqual((both, one, tables_with), (1361, 28, 97))     # a fold that drops or adds ranges shows here

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
