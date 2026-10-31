"""`slider.snap` and `grid_value` on the packaged maps: a linear row lands on the unit Logic's
arithmetic gives, sampled or not; a non-finite value is refused before the slider's ends can
swallow it; the one-row Limiter choice row refuses a word that is no choice."""

import math
import unittest

from logicxkit.logic._plugin_settings import gridded
from logicxkit.logic.services.mixer.plugin_library import find_donor, load_library
from logicxkit.logic.services.mixer.chains_channels import on_grid
from logicxkit.logic.services.mixer.plugin_params import _coerce, load_tables, set_by_name, table_of
from logicxkit.logic.services.mixer.slider import grid_value, linear_unit, point_for, slider_curve, snap
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.translate.translate import load_maps
from logicxkit.utils.data import PACKAGED

MAPS = {m.plugin: m for m in load_maps([PACKAGED / "translate"]) if m.type is not None}


def _donor(name: str) -> bytes:
    return find_donor(load_library([PACKAGED / "donors"]), name, width=None, version=None).raw


def _payload(name: str) -> bytes:
    return _donor(name)[HEADER:]


class LinearRowSnapTest(unittest.TestCase):
    def test_a_value_between_samples_lands_on_the_lines_unit_half_up(self):
        """Compressor Threshold is sampled every few units: -46.75 sits at unit 6.5 of its -50..0
        line and goes to unit 7, -46.5, by the half-up single-precision rule; Logic's re-save of these
        very values kept them so (`slider-linear-resave-logic`, `tests/goldens/test_slider_maps.py`)."""
        comp = MAPS["Compressor"]
        self.assertEqual(linear_unit(slider_curve(comp, "Threshold"), -46.75), 7.0)
        self.assertEqual(snap(comp, "Threshold", -46.75), -46.5)
        self.assertEqual(snap(comp, "Threshold", -46.3), -46.5)                       # the nearer unit, unsampled
        self.assertEqual(snap(comp, "Knee", 0.85), 0.9)
        self.assertEqual(snap(MAPS["Noise Gate"], "Lookahead", 2.5), 2.6)
        self.assertEqual(snap(MAPS["Multipressor"], "Master Gain", -19.0), -18.8)     # 0.4 dB per unit: -19.0 is unit 2.5, up to 3

    def test_a_sampled_value_and_the_ends_come_back_as_they_are(self):
        comp = MAPS["Compressor"]
        self.assertEqual(snap(comp, "Threshold", -50.0), -50.0)
        self.assertEqual(snap(comp, "Threshold", 0.0), 0.0)
        self.assertEqual(linear_unit(slider_curve(comp, "Threshold"), -60.0), 0.0)
        self.assertEqual(linear_unit(slider_curve(comp, "Threshold"), 5.0), 100.0)

    def test_a_knob_row_midpoint_still_goes_down(self):
        self.assertEqual(snap(MAPS["Compressor"], "Release", 115.0), 110.0)

    def test_the_linear_arithmetic_sees_the_value_as_given_and_the_knob_gap_the_rounded_one(self):
        comp = MAPS["Compressor"]
        self.assertEqual(snap(comp, "Threshold", -46.75004), -47.0)       # single precision on the raw value: a hair under the midpoint
        self.assertEqual(snap(comp, "Make Up", -8.74996), -9.0)           # a gap: the four-place value, the midpoint, down

    def test_a_plateau_lands_on_its_first_unit_however_it_is_reached(self):
        """Compressor Ratio shows 1.2 on two adjacent units: a hit and a neighbour pick give the same unit."""
        from logicxkit.logic.services.mixer.slider import land
        comp = MAPS["Compressor"]
        curve = slider_curve(comp, "Ratio")
        plateau = [u for u, v in curve if v == 1.2]
        self.assertGreater(len(plateau), 1)
        self.assertEqual(land(curve, "Ratio", 1.2), (plateau[0], 1.2))
        self.assertEqual(land(curve, "Ratio", 1.25), (plateau[0], 1.2))
        self.assertEqual(point_for(comp, "Ratio", 1.25)[1], point_for(comp, "Ratio", 1.2)[1])

    def test_a_one_point_or_constant_curve_is_its_first_point(self):
        from logicxkit.logic.services.mixer.slider import land
        self.assertEqual(land(((3.0, 0.123456),), "x", 7.0), (3.0, 0.1235))
        self.assertEqual(land(((0.0, 0.123456), (4.0, 0.123456)), "x", 0.5), (0.0, 0.1235))

    def test_a_plateau_beside_a_gap_lands_on_its_first_unit_too(self):
        from logicxkit.logic.services.mixer.slider import land
        curve = ((0.0, 1.0), (5.0, 1.2), (6.0, 1.2), (10.0, 2.0))
        self.assertEqual(land(curve, "p", 1.2), (5.0, 1.2))
        self.assertEqual(land(curve, "p", 1.21), (5.0, 1.2))

    def test_a_value_at_or_below_zero_on_a_log_row_is_the_bottom(self):
        """A Q of 0 or -1 is below the slider: its bottom, 0.1 at unit 0, in `snap` and in a lane,
        never a point in the middle through the log domain."""
        lp = MAPS["Linear Phase EQ"]
        for v in (0.0, -1.0, 0.05):
            with self.subTest(v):
                self.assertEqual(snap(lp, "Peak 3 Q-Factor", v), 0.1)
                self.assertEqual(point_for(lp, "Peak 3 Q-Factor", v)[1:3], (0.0, 0.1))
        self.assertEqual(point_for(lp, "Peak 3 Frequency", 1e6)[1:3], (1050.0, 20000.0))


class TieTest(unittest.TestCase):
    def test_a_midpoint_goes_down_unless_the_row_ties_up(self):
        from logicxkit.logic.services.mixer.slider import is_linear, land, ties_up
        curve = ((0.0, 1.0), (1.0, 2.0), (2.0, 5.0))
        self.assertEqual((land(curve, "x", 3.5), land(curve, "x", 3.5, up=True)), ((1.0, 2.0), (2.0, 5.0)))
        comp = MAPS["Compressor"]
        for param, up in (("Attack", True), next((p, False) for p in comp.raw["automation"]
                                                 if comp.raw["automation"][p].get("tie") is None and not is_linear(slider_curve(comp, p)))):
            with self.subTest(param=param):
                self.assertEqual(ties_up(comp, param), up)
                curve = slider_curve(comp, param)
                (_u0, lo), (_u1, hi) = next((a, b) for a, b in zip(curve, curve[1:], strict=False)
                                            if b[0] - a[0] == 1 and b[1] > a[1] and round((a[1] + b[1]) / 2, 4) == (a[1] + b[1]) / 2)
                mid, want = (lo + hi) / 2, hi if up else lo
                self.assertEqual(snap(comp, param, mid), want)
                self.assertEqual(grid_value(comp, param, mid)[0], want)
                self.assertEqual(point_for(comp, param, mid)[2], want)


class FallingCurveTest(unittest.TestCase):
    def test_a_curve_whose_values_fall_is_refused_and_every_shipped_one_rises(self):
        from logicxkit.logic.services.mixer.slider import land
        with self.assertRaisesRegex(ValueError, "x: its sampled values fall"):
            land(((0.0, 10.0), (1.0, 5.0), (2.0, 0.0)), "x", 7.5)
        for m in MAPS.values():
            for param in m.raw.get("automation", {}):
                curve = slider_curve(m, param)
                if curve:
                    land(curve, param, curve[0][1])


class NonFiniteTest(unittest.TestCase):
    def test_grid_value_and_gridded_refuse_nan_and_inf(self):
        lim = MAPS["Limiter"]
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(bad):
                with self.assertRaisesRegex(ValueError, "not a finite number"):
                    grid_value(lim, "Gain", bad)
        with self.assertRaisesRegex(ValueError, "Gain: nan is not a finite number"):
            gridded(_payload("Limiter"), {"Gain": "nan"})
        self.assertEqual(gridded(_payload("Limiter"), {"Gain": "99"}), ({"Gain": 20.0}, ["Gain 99: Limiter's slider runs -20..20; set to 20"]))


class ChoiceWordTest(unittest.TestCase):
    def test_a_number_on_a_choices_row_must_be_one_of_its_words(self):
        payload = _payload("Limiter")
        table = table_of(load_tables(), payload)
        set_by_name(table, payload, {"Limiter Mode": "0"})
        set_by_name(table, payload, {"Limiter Mode": "Legacy"})
        for bad in ("7", "2", "0.5", "-1", "1e-7"):
            with self.subTest(bad):
                with self.assertRaisesRegex(ValueError, "Limiter Mode: .* is not one of Legacy, Precision"):
                    set_by_name(table, payload, {"Limiter Mode": bad})
        with self.assertRaisesRegex(ValueError, "True is not a value here; give a number or one of its words"):
            _coerce(table, next(p for p in table.params if p.name == "Limiter Mode"), True)
        with self.assertRaisesRegex(ValueError, "Gain: True is not a value here; give a number$"):
            _coerce(table, next(p for p in table.params if p.name == "Gain"), True)


class SetPathTest(unittest.TestCase):
    """`grid_value`, the `--set` and chains path, lands where `snap` does, the vocabulary item's step
    aside on a measured row (Logic kept a knee 0.85 as 0.9, a threshold -46.75 as -46.5,
    `slider-linear-resave-logic`)."""

    def test_set_lands_on_the_sliders_unit_not_the_vocabularys_step(self):
        comp = MAPS["Compressor"]
        self.assertEqual(gridded(_payload("Compressor"), {"Knee": "0.85", "Threshold": "-46.75"})[0], {"Knee": 0.9, "Threshold": -46.5})
        self.assertEqual(grid_value(comp, "Ratio", 3.03), (3.1, None))                  # the slider's unit, not the vocabulary's step
        self.assertEqual(grid_value(comp, "Knee", 0.65), (0.6, None))                   # single precision, not the step's 0.7
        self.assertEqual(grid_value(comp, "Threshold", -60.0), (-50.0, (-50.0, 0.0)))   # held, with the ends to note

    def test_a_knob_rows_gap_lands_on_the_curves_unit(self):
        """Make Up is sampled at 20 of its 111 units: a value in a gap goes to the curve's value at the
        nearest unit along the samples, whatever the vocabulary's 0.5 step says."""
        comp = MAPS["Compressor"]
        for v, kept in ((10.3, 10.5), (2.34, 2.5), (-5.6, -5.5), (46.1, 46.0)):
            with self.subTest(v):
                self.assertEqual(grid_value(comp, "Make Up", v)[0], kept)
        self.assertEqual(snap(comp, "Make Up", -8.75), -9.0)       # a gap's own midpoint: down, the choice (unmeasured on gap rows)

    def test_settings_by_vocabulary_name_land_where_set_does(self):
        from logicxkit.logic.services.mixer.plugin_params import decode
        from logicxkit.logic.services.translate.translate_write import write_settings
        payload = _payload("Compressor")
        out, _notes = write_settings(payload, MAPS["Compressor"], {"ratio": "3.03", "make_up": "10.3"})
        table = table_of(load_tables(), out)
        from logicxkit.logic._binary import find_blocks, read_block_floats
        at, _t, n = find_blocks(out)[0]
        values = decode(table, read_block_floats(out, at, n))
        self.assertAlmostEqual(values["Ratio"], 3.1, places=4)
        self.assertAlmostEqual(values["Make Up"], 10.5, places=4)


class ScaledChoiceTest(unittest.TestCase):
    def test_a_number_on_a_scaled_choices_row_is_the_choices_index(self):
        """Chorus D-Mode stores its choice at scale 0.01: \"1\" (On) is word 100, as every number in
        `_coerce` is the shown value; 100 is no choice."""
        payload = _payload("Chorus")
        table = table_of(load_tables(), payload)
        dmode = next(p for p in table.params if p.name == "D-Mode")
        self.assertEqual((dmode.scale, dmode.choices), (0.01, ("Off", "On")))
        self.assertEqual(_coerce(table, dmode, "1"), 100.0)
        self.assertEqual(_coerce(table, dmode, "On"), 100.0)
        with self.assertRaisesRegex(ValueError, "D-Mode: '100' is not one of Off, On"):
            _coerce(table, dmode, "100")
        self.assertEqual(on_grid({dmode.index: 100.0}, _donor("Chorus"), "x")[dmode.index], 100.0)   # chains gives the word
        with self.assertRaisesRegex(ValueError, r"D-Mode: word 50.0 is not one of Off \(0\), On \(100\)"):
            on_grid({dmode.index: 50.0}, _donor("Chorus"), "x")

    def test_chains_by_index_refuses_a_non_choice_and_a_non_finite_value(self):
        lim = _donor("Limiter")
        self.assertEqual(on_grid({8: 1.0000004}, lim, "x"), {8: 1.0})
        for bad in ({8: 0.5}, {7: 0.5}):
            with self.subTest(bad):
                with self.assertRaisesRegex(ValueError, "is not one of"):
                    on_grid(bad, lim, "x")
        for bad in ({0: math.nan}, {8: math.inf}):
            with self.subTest(bad):
                with self.assertRaisesRegex(ValueError, "not a finite number"):
                    on_grid(bad, lim, "x")
        with self.assertRaisesRegex(ValueError, "not a finite number"):          # a donor no table names
            on_grid({0: math.nan}, _donor("Correlation Meter"), "x")
        with self.assertRaisesRegex(ValueError, "a choice is a word, not True"):
            on_grid({8: True}, lim, "x")


class PastTheEndsTest(unittest.TestCase):
    def test_every_report_of_a_held_value_sees_float_noise_at_an_end_as_the_end(self):
        from logicxkit.logic.services.mixer.slider import past_ends
        from logicxkit.logic.services.translate.translate_eq import held
        from logicxkit.logic.services.translate.translate_write import _on_slider
        comp = MAPS["Compressor"]
        item = next(i for i in comp.items.values() if i.param == "Threshold")
        curve = slider_curve(comp, "Threshold")
        for value, past in ((-50.000000001, False), (-49.99999, False), (-50.001, True)):
            with self.subTest(value=value):
                self.assertEqual(past_ends(curve, value) is not None, past)
                self.assertEqual(grid_value(comp, "Threshold", value)[1] is not None, past)
                self.assertEqual(held(comp, "Threshold", value, "b") is not None, past)
                self.assertEqual(_on_slider(comp, item, value)[1] is not None and "slider runs" in _on_slider(comp, item, value)[1], past)


if __name__ == "__main__":
    unittest.main()
