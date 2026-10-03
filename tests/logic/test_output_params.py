"""The output plug-ins' parameter tables: measured indices only, bounds held."""

import unittest

from logicxkit.logic.services.mixer.output_params import (
    ADAPTIVE_LIMITER,
    FLOATS,
    LIMITER,
    LINEAR_PHASE_EQ,
    MULTIPRESSOR,
    PARAMS,
    lpeq_index,
    read_params,
    set_params,
)


class TableTest(unittest.TestCase):
    def test_the_measured_indices(self):
        self.assertEqual((lpeq_index("low_cut", "enable"), lpeq_index("peak3", "freq"),
                          lpeq_index("peak3", "gain"), lpeq_index("peak3", "q")), (1, 18, 19, 20))
        self.assertEqual(PARAMS[MULTIPRESSOR]["band1_threshold"], 41)
        self.assertEqual(PARAMS[ADAPTIVE_LIMITER]["remove_dc"], 6)
        self.assertEqual(PARAMS[LIMITER]["output_level"], 5)

    def test_every_index_is_inside_its_block(self):
        for type_id, table in PARAMS.items():
            self.assertTrue(all(0 <= i < FLOATS[type_id] for i in table.values()), type_id)
            self.assertEqual(len(set(table.values())), len(table), f"{type_id}: two names share an index")

    def test_an_unknown_band_or_field_is_refused(self):
        with self.assertRaises(ValueError):
            lpeq_index("peak5", "gain")
        with self.assertRaises(ValueError):
            lpeq_index("peak1", "slope")

    def test_a_cut_band_has_a_slope_where_a_peak_has_a_gain(self):
        self.assertEqual((lpeq_index("low_cut", "slope"), lpeq_index("high_cut", "slope")), (3, 31))
        self.assertEqual((PARAMS[LINEAR_PHASE_EQ]["low_cut_slope"], PARAMS[LINEAR_PHASE_EQ]["high_cut_slope"]), (3, 31))
        for name in ("low_cut_gain", "high_cut_gain"):
            self.assertNotIn(name, PARAMS[LINEAR_PHASE_EQ])
        with self.assertRaises(ValueError):
            lpeq_index("low_cut", "gain")


class SetAndReadTest(unittest.TestCase):
    def test_set_writes_only_the_named_indices(self):
        floats = [0.0] * FLOATS[LIMITER]
        out = set_params(LIMITER, floats, {"gain": 0.1, "release": 260})
        self.assertEqual((out[1], out[4]), (0.1, 260.0))
        self.assertEqual([v for i, v in enumerate(out) if i not in (1, 4)], [0.0] * (FLOATS[LIMITER] - 2))
        self.assertEqual(floats, [0.0] * FLOATS[LIMITER])

    def test_read_names_every_measured_float(self):
        floats = list(range(FLOATS[ADAPTIVE_LIMITER]))
        self.assertEqual(read_params(ADAPTIVE_LIMITER, floats), {"gain": 2, "out_ceiling": 3, "lookahead": 5, "remove_dc": 6})

    def test_refusals(self):
        with self.assertRaises(ValueError):
            set_params(LIMITER, [0.0] * 12, {"gain": 1})
        with self.assertRaises(ValueError):
            set_params(LIMITER, [0.0] * FLOATS[LIMITER], {"ceiling": 1})
        with self.assertRaises(ValueError):
            set_params(999, [], {})
        self.assertIn("low_cut_enable", PARAMS[LINEAR_PHASE_EQ])


if __name__ == "__main__":
    unittest.main()
