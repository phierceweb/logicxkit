"""A slider map with no translation family, and a translated value laid on the target's slider grid."""

import unittest

from logic.test_translate import COMP, MAPS, PROC, native_payload

from logicxkit.logic.services.translate.translate import Map, Settings, maps_for, read_settings
from logicxkit.logic.services.translate.translate_plan import plan


class SliderMapTest(unittest.TestCase):
    """A map may carry a slider grid alone: found by type for the grid, no translation map."""
    GRID = {"plugin": "Limiter", "type": 199, "automation": {"Gain": {"per": 128, "units": [[0, -20.0], [1, -19.9]]}}}

    def test_a_map_without_a_family_loads_and_is_found_by_type(self):
        from logicxkit.logic.services.mixer.slider import slider_curve
        m = Map.from_dict(self.GRID)
        self.assertIsNone(m.family)
        self.assertEqual(maps_for(native_payload([0.0] * 13, 199), [m]), [m])
        self.assertEqual(slider_curve(m, "Gain"), ((0.0, -20.0), (1.0, -19.9)))

    def test_a_family_less_map_is_no_translation_map(self):
        m = Map.from_dict(self.GRID)
        with self.assertRaisesRegex(ValueError, "slider grid, not a translation map"):
            plan(Settings(m), m)

    def test_a_family_less_map_reads_and_writes_no_settings(self):
        from logicxkit.logic.services.translate.translate import read_settings
        from logicxkit.logic.services.translate.translate_write import write_settings
        m, payload = Map.from_dict(self.GRID), native_payload([0.0] * 13, 199)
        with self.assertRaisesRegex(ValueError, "no family; it has no settings to read"):
            read_settings(payload, m)
        with self.assertRaisesRegex(ValueError, "no family; it has no settings to write"):
            write_settings(payload, m, {"gain": 0})


class TranslationGridTest(unittest.TestCase):
    def test_a_measured_row_takes_the_sliders_unit_not_the_vocabularys_step(self):
        """swap-plugin and tracking-chains land where `--set` does: Ratio 3.03 on 3.1, not on the
        vocabulary's step, Make Up 10.3 on the curve's 10.5, Threshold -46.75 on the line's -46.5."""
        from logicxkit.logic.services.mixer.slider import grid_value
        values = {"ratio": 3.03, "make_up": 10.3, "threshold": -46.75}
        out = plan(Settings(COMP, values=values), COMP)
        self.assertEqual((out.values["Ratio"], out.values["Make Up"], out.values["Threshold"]), (3.1, 10.5, -46.5))
        for name, v in values.items():
            item = COMP.items[name]
            self.assertEqual(out.values[item.param], grid_value(COMP, item.param, item.to_stored(v))[0])

    def test_a_non_finite_source_value_is_refused_by_name(self):
        with self.assertRaisesRegex(ValueError, "ratio: inf is not a finite number"):
            plan(Settings(COMP, values={"ratio": float("inf")}), COMP)
        with self.assertRaisesRegex(ValueError, "threshold: nan is not a finite number"):   # a third-party target too
            plan(Settings(COMP, values={"threshold": float("nan")}), PROC)

    def test_the_band_planners_take_the_sliders_unit_too(self):
        """An EQ gain 1.55 lands on 1.5 in Channel EQ and Linear Phase EQ (Logic kept Channel EQ's
        1.55 as 1.5, `slider-linear-resave-logic`); a Multipressor threshold lands where `--set` does."""
        from logicxkit.logic.services.mixer.slider import grid_value
        from logicxkit.logic.services.translate.translate_eq import Band, plan_bands
        from logicxkit.logic.services.translate.translate_mb import _gridded
        band = Band("bell", 1000.0, 1.55, 1.0, True, None, False, 1)
        for name in ("Channel EQ", "Linear Phase EQ"):
            target = next(m for m in MAPS if m.plugin == name)
            values, _notes, placed = plan_bands([band], None, target, target)
            with self.subTest(name):
                self.assertEqual(values[placed[1]["gain"]], 1.5)
        q_band = Band("bell", 20.1004, 0.0, 0.1054, True, None, False, 1)   # a hair above two knob midpoints: up, as `--set` goes
        lpeq = next(m for m in MAPS if m.plugin == "Linear Phase EQ")
        values, _notes, placed = plan_bands([q_band], None, lpeq, lpeq)
        self.assertEqual((values[placed[1]["frequency"]], values[placed[1]["q"]]), (20.2, 0.11))
        from logicxkit.logic.services.translate.translate_write import _slot_values
        written = _slot_values(lpeq, Band("bell", 20.1004, 0.0, 0.1054, True, None, False, 3), [])      # `settings --set band 3=…`
        self.assertEqual((written["Peak 1 Frequency"], written["Peak 1 Q-Factor"]), (20.2, 0.11))
        from test_translate_mb import multipressor_payload
        mp = next(m for m in MAPS if m.plugin == "Multipressor")
        source = read_settings(multipressor_payload({"Band 1 Comp. Threshold": -18.0, "Band 1 Comp. Ratio": 1.9551, "Band 1 Attack": 0.2504}), mp)
        out = plan(source, mp)                                               # a hair above two knob midpoints: up, as `--set` goes
        self.assertEqual((out.values["Band 1 Comp. Ratio"], out.values["Band 1 Attack"]), (1.977, 0.5))
        row = mp.raw["slots"][0]["threshold"]
        self.assertEqual(_gridded(mp, row, -59.45, 0.5), grid_value(mp, row, -59.45)[0])
        self.assertNotEqual(_gridded(mp, row, -59.45, 0.5), -60.0)


if __name__ == "__main__":
    unittest.main()
