"""The exact float each knob-row position stores: a value a tenth of a step inside a sampled
position comes back from Logic's re-save as that position's float, and that float is the display
value to display precision. Skips without the public corpus."""

import struct
import unittest

import _goldens
from goldens.test_slider_maps import MAPS, _slots, _values

from logicxkit.logic.services.mixer.slider import slider_curve
from logicxkit.logic.services.translate.translate import map_for

SETS = ("midpoints", "ties1", "ties2", "ties3", "siblings")
KEYS = [k for name in SETS for side in ("lo", "hi")
        for k in (f"slider-nbr-{side}-{name}-raw", f"slider-nbr-{side}-{name}-resave-logic")]
MIDPOINT_KEYS = [k for name in SETS for k in (f"slider-{name}-raw", f"slider-{name}-resave-logic")]


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _neighbours(curve, value: float):
    """((unit, sample) under ``value``, (unit, sample) over it), a display plateau's highest unit under."""
    below = max((p for p in curve if p[1] < value), key=lambda p: (p[1], p[0]))
    above = min((p for p in curve if p[1] > value), key=lambda p: (p[1], p[0]))
    return below, above


@_goldens.needs(*KEYS, *MIDPOINT_KEYS)
class StoredFloatsTest(unittest.TestCase):
    def test_each_copy_lands_on_the_position_it_sits_inside(self):
        for name in SETS:
            for side in ("lo", "hi"):
                raw_key, resave_key = f"slider-nbr-{side}-{name}-raw", f"slider-nbr-{side}-{name}-resave-logic"
                written, kept = _goldens.fact(raw_key, "written"), _goldens.fact(resave_key, "kept")
                raw, resaved = _slots(raw_key), _slots(resave_key)
                for plugin, rows in written.items():
                    m = map_for(raw[plugin][0], MAPS)
                    for row, v in rows.items():
                        with self.subTest(key=raw_key, plugin=plugin, row=row):
                            self.assertAlmostEqual(raw[plugin][1][row], v, delta=abs(v) * 1e-6 + 1e-4)   # float32 in the file
                            self.assertAlmostEqual(resaved[plugin][1][row], kept[plugin][row], delta=abs(v) * 1e-6 + 1e-4)
                            below, above = _neighbours(slider_curve(m, row), v)
                            near, far = (below, above) if side == "lo" else (above, below)
                            self.assertLess(abs(kept[plugin][row] - near[1]), abs(kept[plugin][row] - far[1]))

    def test_the_maps_samples_are_the_stored_floats_and_the_midpoints_are_exact_ties(self):
        """A position's float is its Controls display to display precision (7150 stores 7150.0005; the
        Noise Gate's release and the Multipressor's ratios store what the display rounds), so a value
        midway between two displays is an exact tie in single precision on most rows, and the side
        Logic takes there is the row's own (`TiesTest`), not the floats'."""
        ties = total = 0
        for name in SETS:
            written = _goldens.fact(f"slider-{name}-raw", "written")
            lo, hi = _values(f"slider-nbr-lo-{name}-resave-logic"), _values(f"slider-nbr-hi-{name}-resave-logic")
            raw = _slots(f"slider-{name}-raw")
            for plugin, rows in written.items():
                m = map_for(raw[plugin][0], MAPS)
                for row, v in rows.items():
                    with self.subTest(set=name, plugin=plugin, row=row):
                        below, above = _neighbours(slider_curve(m, row), v)
                        f_lo, f_hi = lo[plugin][row], hi[plugin][row]
                        self.assertLessEqual(abs(f_lo - below[1]), 1e-3 * abs(below[1]))
                        self.assertLessEqual(abs(f_hi - above[1]), 1e-3 * abs(above[1]))
                        total += 1
                        ties += _f32(v) - f_lo == f_hi - _f32(v)
        self.assertEqual((ties, total), (67, 95))


if __name__ == "__main__":
    unittest.main()
