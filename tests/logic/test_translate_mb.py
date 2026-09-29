"""A multiband compressor's bands across plug-ins: Pro-MB read by its band layout, Multipressor
by its table, the spectrum segmented into the target's bands, and Pro-MB written back."""

import unittest

from logicxkit.logic.services.plugin_params import load_tables, set_by_name, table_for
from logicxkit.logic.services.translate import load_maps, map_for, plan, read_settings
from logicxkit.logic.services.translate_mb import MBand, neutral, segments
from logicxkit.logic.services.translate_write import write_plan
from logicxkit.utils.data import PACKAGED
from test_translate import au_payload, native_payload

MAPS = load_maps([PACKAGED / "translate"])
PROMB, MULTI = (next(m for m in MAPS if m.plugin == n) for n in ("Pro-MB", "Multipressor"))
TABLES = load_tables()


def _r(*values):
    return tuple(round(v, 4) for v in values)


def promb_payload(bands: dict[int, dict], globals_: dict | None = None) -> bytes:
    """A Pro-MB slot payload: 151 pairs, every band unused but the ones given (fields by name)."""
    values = {n * 22: 2.0 for n in range(6)}                    # state: unused
    values.update({133: 1.0, 134: 0.0, 136: 0.0, 141: 1.0})     # mix 100 %, levels 0 dB, lookahead on
    lay = PROMB.raw["bands"]
    for n, fields in bands.items():
        base = (n - 1) * 22
        values[base] = 1.0
        for field, v in fields.items():
            values[base + lay[field]] = v
    values.update(globals_ or {})
    return au_payload(values, count=151, subtype="FPMb")


def multipressor_payload(values: dict) -> bytes:
    payload = native_payload([0.0] * 62, type_id=194)
    defaults = {"Band 1 Monitor": "On", "Band 2 Monitor": "On", "Band 3 Monitor": "On", "Band 4 Monitor": "On",
                "Band 2 Xover Frequency 1/2": 160.0, "Band 3 Xover Frequency 2/3": 1100.0, "Band 4 Xover Frequency 3/4": 7500.0,
                "Band 1 Comp. Ratio": 1.0, "Band 2 Comp. Ratio": 1.0, "Band 3 Comp. Ratio": 1.0, "Band 4 Comp. Ratio": 1.0,
                "Band 1 Exp. Ratio": 1.0, "Band 2 Exp. Ratio": 1.0, "Band 3 Exp. Ratio": 1.0, "Band 4 Exp. Ratio": 1.0}
    return set_by_name(table_for(TABLES, 194), payload, {**defaults, **values})


class ReadProMBTest(unittest.TestCase):
    def test_bands_read_with_their_curves_and_states(self):
        payload = promb_payload({1: {"low": 4.906890869, "high": 6.906890869, "mode": 0, "threshold": 0.7, "range": -6.0,
                                     "ratio": 0.6, "attack": 20.0, "release": 30.0, "knee": 24.0, "lookahead": 1.0, "level": 1.0},
                                 2: {"state": 0.0, "low": 6.906890869, "high": 10.965784285, "mode": 1, "threshold": 0.3,
                                     "range": -10.0, "ratio": 0.4, "attack": 20.0, "release": 20.0, "knee": 24.0, "lookahead": 1.0}},
                                {136: 0.5})
        self.assertIs(map_for(payload, MAPS), PROMB)
        s = read_settings(payload, PROMB)
        self.assertEqual(len(s.bands), 2)
        b1, b2 = s.bands
        self.assertEqual((b1.mode, b1.on, b1.number, b1.time_unit), ("compress", True, 1, "%"))
        self.assertAlmostEqual(b1.low, 30.0, places=3)
        self.assertAlmostEqual(b1.high, 120.0, places=3)
        self.assertEqual(_r(b1.threshold, b1.ratio, b1.range, b1.level), (-18.0, 4.0, -6.0, 1.0))
        self.assertEqual((b2.mode, b2.on, *_r(b2.threshold, b2.ratio)), ("expand", False, -42.0, 2.0))
        self.assertEqual((s.values["mix"], s.values["output_gain"], s.values["lookahead_on"]), (100.0, 18.0, True))
        self.assertEqual(b1.label(), "30 Hz-120 Hz compress -18.0 dB 4.00:1 range -6.0 dB 20/30 % +1.0 dB")


class ReadMultipressorTest(unittest.TestCase):
    def test_four_bands_between_the_crossovers(self):
        payload = multipressor_payload({"Band 1 Comp. Threshold": -18.0, "Band 1 Comp. Ratio": 2.5, "Band 4 Monitor": "Off",
                                        "Band 2 Exp. Threshold": -40.0, "Band 2 Exp. Ratio": 2.0, "Band 2 Reduction": -12.0,
                                        "Lookahead": 2.0, "Auto Gain": "On"})
        self.assertIs(map_for(payload, MAPS), MULTI)
        s = read_settings(payload, MULTI)
        self.assertEqual([(b.low, b.high, b.number) for b in s.bands],
                         [(20.0, 160.0, 1), (160.0, 1100.0, 2), (1100.0, 20000.0, 3)])      # band 4 off: band 3 runs up
        self.assertEqual((s.bands[0].threshold, s.bands[0].ratio, s.bands[0].time_unit), (-18.0, 2.5, "ms"))
        self.assertEqual(s.bands[1].expander, (-40.0, 2.0, -12.0))
        self.assertEqual((s.values["lookahead"], s.values["auto_gain"]), (2.0, True))


    def test_an_off_band_hands_its_range_to_the_live_band_above(self):
        """As Logic's editor draws it: band 3 off, band 4 starts at the 2/3 crossover."""
        s = read_settings(multipressor_payload({"Band 3 Monitor": "Off"}), MULTI)
        self.assertEqual([(b.low, b.high, b.number) for b in s.bands],
                         [(20.0, 160.0, 1), (160.0, 1100.0, 2), (1100.0, 20000.0, 4)])


class SegmentsTest(unittest.TestCase):
    def test_a_gap_is_a_stretch_of_its_own(self):
        bands = [MBand(30, 120, "compress", -20, 3, number=1), MBand(120, 2000, "compress", -20, 3, number=2),
                 MBand(4000, 20000, "compress", -20, 3, number=3)]
        notes = []
        segs = segments(bands, (20, 20000), 4, "Pro-MB", "Multipressor", notes)
        self.assertEqual([(lo, hi, b.number if b else None) for lo, hi, b in segs],
                         [(20, 120, 1), (120, 2000, 2), (2000, 4000, None), (4000, 20000, 3)])   # 20-30 Hz: a sliver
        self.assertEqual(notes, [])

    def test_past_the_count_the_narrowest_gap_then_band_joins_a_neighbour(self):
        bands = [MBand(lo, hi, "compress", -20, 3, number=i + 1)
                 for i, (lo, hi) in enumerate([(20, 100), (100, 400), (400, 1000), (1000, 3000), (3000, 5000), (6000, 20000)])]
        notes = []
        segs = segments(bands, (20, 20000), 4, "Pro-MB", "Multipressor", notes)
        self.assertEqual(len(segs), 4)
        self.assertEqual([(lo, hi, b.number) for lo, hi, b in segs], [(20, 100, 1), (100, 400, 2), (400, 3000, 4), (3000, 20000, 6)])
        self.assertTrue(any(n.startswith("band 5 3.00 kHz-5.00 kHz") and "dropped" in n for n in notes), notes)
        self.assertTrue(any(n.startswith("band 3 400 Hz-1.00 kHz") and "joins the band above" in n for n in notes), notes)


class RangesTest(unittest.TestCase):
    def test_a_value_past_multipressor_range_is_held_with_a_note(self):
        payload = promb_payload({1: {"low": 4.906890869, "high": 14.872674, "mode": 0, "threshold": 0.05, "range": -30.0,
                                     "ratio": 1.0, "level": 25.0}}, {136: 0.9})
        p = plan(read_settings(payload, PROMB), MULTI)
        self.assertEqual((p.values["Band 1 Comp. Threshold"], p.values["Band 1 Comp. Ratio"], p.values["Band 1 Make Up"]),
                         (-60.0, 30.0, 20.0))
        self.assertEqual(p.values["Master Gain"], 20.0)
        self.assertIn("band 1: threshold -81 is past Multipressor's -60..10; set to -60", p.notes)
        self.assertIn("band 1: ratio 100 is past Multipressor's 1..30; set to 30", p.notes)
        self.assertIn("output_gain 32.4 is past Multipressor's -20..20; set to 20", p.notes)


class PlanBothWaysTest(unittest.TestCase):
    def test_pro_mb_into_multipressor(self):
        payload = promb_payload({1: {"low": 4.906890869, "high": 6.906890869, "mode": 0, "threshold": 0.7, "range": -6.0,
                                     "ratio": 0.6, "attack": 20.0, "release": 30.0, "knee": 24.0, "lookahead": 1.0, "level": 1.0},
                                 2: {"low": 6.906890869, "high": 10.965784285, "mode": 1, "threshold": 0.3, "range": -10.0,
                                     "ratio": 0.4, "attack": 20.0, "release": 20.0, "knee": 24.0, "lookahead": 1.0}},
                                {136: 0.5})
        p = plan(read_settings(payload, PROMB), MULTI)
        v = p.values
        self.assertEqual((v["Band 1 Monitor"], v["Band 1 Comp. Threshold"], v["Band 1 Comp. Ratio"], v["Band 1 Make Up"]),
                         ("On", -18.0, 3.675, 1.0))                        # the ratio knob's position nearest 4 (Logic did the same)
        self.assertEqual((v["Band 2 Xover Frequency 1/2"], v["Band 3 Xover Frequency 2/3"], v["Band 4 Xover Frequency 3/4"]),
                         (120.0, 2000.0, 20000.0))
        self.assertEqual((v["Band 2 Monitor"], v["Band 2 Comp. Threshold"], v["Band 2 Comp. Ratio"]), ("On", 0.0, 1.0))
        self.assertEqual((v["Band 2 Exp. Threshold"], v["Band 2 Exp. Ratio"], v["Band 2 Reduction"]), (-42.0, 2.0, -10.0))
        self.assertEqual((v["Band 3 Monitor"], v["Band 3 Comp. Threshold"], v["Band 3 Comp. Ratio"], v["Band 3 Exp. Ratio"],
                          v["Band 3 Make Up"], v["Band 4 Monitor"]), ("On", 0.0, 1.0, 1.0, 0.0, "Off"))   # 2-20 kHz untouched
        self.assertEqual((v["Lookahead"], v["Master Gain"]), (1.0, 18.0))
        self.assertIn("band 1 30 Hz-120 Hz compress -18.0 dB 4.00:1 range -6.0 dB 20/30 % +1.0 dB: Pro-MB's range stops "
                      "the gain change at -6.0 dB; Multipressor has no limit", p.notes)
        self.assertIn("attack and release are percentages in Pro-MB; Multipressor keeps its own", p.notes)
        new, notes = write_plan(multipressor_payload({}), p)
        got = read_settings(new, MULTI)
        self.assertEqual((*_r(got.bands[0].threshold, got.bands[0].ratio), _r(*got.bands[1].expander)), (-18.0, 3.675, (-42.0, 2.0, -10.0)))     # the ratio on its knob's position
        self.assertEqual([(b.number, round(b.low), round(b.high)) for b in got.bands], [(1, 20, 120), (2, 120, 2000), (3, 2000, 20000)])
        self.assertTrue(neutral(got.bands[2]))
        self.assertIn("auto_gain off: Multipressor's own, kept", notes)

    def test_multipressor_into_pro_mb(self):
        payload = multipressor_payload({"Band 1 Comp. Threshold": -18.0, "Band 1 Comp. Ratio": 2.5, "Band 1 Make Up": 1.5,
                                        "Band 2 Exp. Threshold": -40.0, "Band 2 Exp. Ratio": 2.0, "Band 2 Reduction": -12.0,
                                        "Band 3 Comp. Threshold": -10.0, "Band 3 Comp. Ratio": 3.0, "Band 3 Exp. Ratio": 1.5,
                                        "Band 4 Monitor": "Off", "Lookahead": 2.0, "Auto Gain": "On", "Master Gain": -1.0})
        p = plan(read_settings(payload, MULTI), PROMB)
        self.assertEqual([(b.low, b.high, b.mode, b.threshold, b.ratio, b.range) for b in p.bands],
                         [(30.0, 160.0, "compress", -18.0, 2.5, -30.0), (160.0, 1100.0, "expand", -40.0, 2.0, -12.0),
                          (1100.0, 20000.0, "compress", -10.0, 3.0, -30.0)])     # Pro-MB starts at 30 Hz; band 4 off
        self.assertIn("band 1: Pro-MB's crossovers run 30 Hz to 30.00 kHz; 20 Hz-160 Hz becomes 30 Hz-160 Hz", p.notes)
        self.assertEqual([b.lookahead for b in p.bands], [2.0, 2.0, 2.0])
        self.assertEqual(p.values, {"output_gain": -1.0, "lookahead_on": True})
        self.assertIn("auto_gain on: no analogue in Pro-MB", p.notes)
        self.assertTrue(any("band 3" in n and "expansion beside compression" in n for n in p.notes), p.notes)
        new, _notes = write_plan(promb_payload({}), p)
        got = read_settings(new, PROMB)
        self.assertEqual(len(got.bands), 3)
        self.assertEqual(_r(got.bands[0].threshold, got.bands[0].ratio, got.bands[0].level, got.bands[0].range), (-18.0, 2.5, 1.5, -30.0))
        self.assertAlmostEqual(got.bands[1].low, 160.0, places=2)
        self.assertEqual((got.bands[1].mode, *_r(got.bands[1].threshold, got.bands[1].range)), ("expand", -40.0, -12.0))
        self.assertEqual((_r(got.values["output_gain"])[0], got.values["lookahead_on"]), (-1.0, True))
        self.assertEqual(len(new), len(promb_payload({})))


if __name__ == "__main__":
    unittest.main()
