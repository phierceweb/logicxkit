"""Each table range is reproducible from the corpus: the defaults save's `slider_ends` fact holds
what the Controls view showed with the slider at each end, and the table's `min` and `max` are
those displays' numbers in the parameter's unit."""

import re
import unittest

import _goldens
from logicxkit.logic.services.mixer.plugin_params import load_tables

KEYS = tuple(k for k in sorted(_goldens.manifest()) if k.endswith("-defaults") and _goldens.fact(k, "slider_ends"))


def _number(text: str, unit: str) -> float | None:
    """The display's number in the parameter's unit (s and kHz over ms and Hz words a thousandfold)."""
    m = re.search(r"-?\d+(?:\.\d+)?", (text or "").replace(",", ""))
    if not m:
        return None
    n = float(m.group())
    shown_unit = re.sub(r"[\d.\-+/\s]", "", text or "").lower()
    if shown_unit in ("s", "khz") and unit.lower() in ("ms", "hz"):
        n *= 1000.0
    return n


@_goldens.needs(*KEYS)
class RangeFactsTest(unittest.TestCase):
    def test_every_table_range_is_the_staged_end_displays(self):
        self.assertGreaterEqual(len(KEYS), 38)
        tables = {t.name: t for t in load_tables().values()}
        checked = 0
        for key in KEYS:
            ends = _goldens.fact(key, "slider_ends")
            table = tables.get(_goldens.fact(key, "plugin"))
            if table is None:
                continue
            if table.state != "text":                     # a text state is read, never written: no range to hold
                with self.subTest(f"{table.name} carries ranges"):
                    self.assertTrue(any(p.min is not None for p in table.params))
            for p in table.params:
                if p.min is None or p.name not in ends:
                    continue
                lo, hi = (_number(e, p.unit) for e in ends[p.name])
                with self.subTest(f"{table.name} {p.name}"):
                    self.assertIsNotNone(lo)
                    self.assertIsNotNone(hi)
                    self.assertAlmostEqual(p.min, min(lo, hi), places=3)
                    self.assertAlmostEqual(p.max, max(lo, hi), places=3)
                    checked += 1
        self.assertGreaterEqual(checked, 700)


if __name__ == "__main__":
    unittest.main()
