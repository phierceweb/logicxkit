"""A parameter lane carried through the vocabulary: a third-party's 0..1 over its stored range,
the target's index found through its map, the points converted by the same curves."""

import copy
import math
import unittest

from logicxkit.logic.services.regions.automation import Lane, Point
from logicxkit.logic.services.translate.automation_remap import carry_lane, index_of, item_at, to_point, to_vocab
from logicxkit.logic.services.mixer.plugin_params import Table, load_tables, table_for
from logicxkit.logic.services.mixer.slider import point_for
from logicxkit.logic.services.translate.translate import Item, Map, load_maps
from logicxkit.utils.data import PACKAGED

MAPS = load_maps([PACKAGED / "translate"])
PROC, COMP, PROQ = (next(m for m in MAPS if m.plugin == n) for n in ("Pro-C 2", "Compressor", "Pro-Q 4"))
COMP_TABLE = table_for(load_tables(), 154)


class IndexTest(unittest.TestCase):
    def test_a_third_party_index_is_its_parameter_id(self):
        self.assertEqual(item_at(PROC, 1, None)[0], "threshold")
        self.assertEqual(item_at(PROC, 34, None)[0], "mix")
        self.assertIsNone(item_at(PROC, 99, None))
        self.assertEqual(index_of(PROC, "ratio", None), 2)

    def test_a_native_index_is_its_float_index_minus_one(self):
        self.assertEqual(item_at(COMP, 0, COMP_TABLE)[0], "threshold")     # float[1] Threshold
        self.assertEqual(item_at(COMP, 5, COMP_TABLE)[0], "knee")          # float[6] Knee
        self.assertEqual(index_of(COMP, "ratio", COMP_TABLE), 1)
        self.assertIsNone(item_at(COMP, 200, COMP_TABLE))


class ValueTest(unittest.TestCase):
    def test_a_third_party_point_spans_the_stored_range(self):
        thr = PROC.items["threshold"]
        self.assertEqual(to_vocab(PROC, thr, 0.5), -30.0)                   # -60..0 dB
        self.assertEqual(to_point(PROC, thr, -24.0), 0.6)
        ratio = PROC.items["ratio"]
        self.assertAlmostEqual(to_vocab(PROC, ratio, 0.6), 4.0, places=6)   # raw 0..1 on the sampled curve
        self.assertAlmostEqual(to_point(PROC, ratio, 4.0), 0.6, places=6)
        self.assertEqual(to_point(PROC, thr, -90.0), 0.0)                   # clamped

    def test_a_native_without_a_measured_slider_is_refused(self):
        bare = Map("compressor", "Bare", {"threshold": Item("Threshold")}, type=999)
        with self.assertRaises(ValueError):
            to_vocab(bare, bare.items["threshold"], 0.5)

    def test_a_native_point_lands_on_its_slider_units(self):
        raw = {"automation": {"Threshold": {"per": 128, "units": [[0, -50.0], [100, 0.0]]},
                              "Mix": {"per": 200, "units": [[0, 0.0], [200, 100.0]]}}}
        m = Map("compressor", "Synthetic", {"threshold": Item("Threshold"), "mix": Item("Mix"),
                                            "auto_release": Item("Auto Release", switch=True)}, type=999, raw=raw)
        thr = m.items["threshold"]
        self.assertEqual(to_vocab(m, thr, 0.5), -18.0)                      # 64 units of 0.5 dB from -50
        self.assertEqual(to_vocab(m, thr, 62.5 / 128), -19.0)               # floored to 62
        self.assertEqual(to_vocab(m, thr, 1.0), 0.0)                        # clamped at the slider's top
        self.assertAlmostEqual(to_point(m, thr, -18.0), 64.5 / 128)                 # the middle of unit 64
        self.assertAlmostEqual(to_point(m, thr, 0.0), 100.5 / 128)
        self.assertEqual(to_vocab(m, m.items["mix"], 0.5), 50.0)            # 200 per 1.0
        raw["automation"]["Gain"] = {"per": 487, "offset": -2, "units": [[0, -24.0], [240, 0.0], [480, 24.0]]}
        gain = Item("Gain")
        m2 = Map("compressor", "Affine", {"make_up": gain}, type=999, raw=raw)
        self.assertEqual(to_vocab(m2, gain, 0.622407), 6.1)                  # 301 units: 487 x 0.6224 - 2
        self.assertEqual(math.floor(to_point(m2, gain, 6.0) * 487 - 2), 300)
        self.assertEqual((to_vocab(m, m.items["auto_release"], 0.0), to_vocab(m, m.items["auto_release"], 0.1)), (False, True))


class MeasuredCompressorTest(unittest.TestCase):
    """The Compressor's measured tables: 128 units per 1.0, 0.5 dB a unit from -50 dB."""

    def test_threshold_and_mix_follow_their_sliders(self):
        thr = COMP.items["threshold"]
        self.assertEqual(to_vocab(COMP, thr, 0.5), -18.0)
        self.assertEqual(to_vocab(COMP, thr, 62.5 / 128), -19.0)
        self.assertEqual(to_vocab(COMP, thr, 1.0), 0.0)
        self.assertAlmostEqual(to_point(COMP, thr, -30.0), 40.5 / 128)
        self.assertEqual(to_vocab(COMP, COMP.items["mix"], 0.5), 50.0)      # 200 units per 1.0
        self.assertEqual(to_vocab(COMP, COMP.items["auto_release"], 0.1), True)

    def test_a_pro_c_2_threshold_lane_lands_on_the_compressor_grid(self):
        lane = Lane("insert 3 parameter 1", None, 1, (Point(38400, 0.5), Point(42240, 0.8)), False, slot=3)
        notes = []
        got = carry_lane(lane, PROC, COMP, None, COMP_TABLE, notes)
        self.assertEqual((got.param_index, got.slot, got.parameter), (0, 3, "insert 3 parameter 0"))
        self.assertEqual([math.floor(p.value * 128) for p in got.points], [40, 76])       # -30 dB, -12 dB
        self.assertEqual(notes, [])


class PointForTest(unittest.TestCase):
    def test_a_native_value_lands_on_its_slider_unit(self):
        comp = next(m for m in MAPS if m.plugin == "Compressor")
        point, units, landed, sampled = point_for(comp, "Threshold", -24.0)
        self.assertEqual((units, landed, sampled), (52.0, -24.0, True))                  # a linear row: unit 52 is exact though unread
        self.assertAlmostEqual(point, 52.5 / 128, places=9)
        point, units, landed, sampled = point_for(comp, "Attack", 20.5)          # between 20 (unit 40) and 23 (unit 41)
        self.assertEqual((units, landed, sampled), (40.0, 20.0, True))
        self.assertEqual(point_for(comp, "Threshold", -46.3)[1:], (7.0, -46.5, True))    # unit 7 unread, the row linear
        self.assertEqual(point_for(comp, "Auto Release", True)[0], 1.0)
        with self.assertRaises(ValueError):
            point_for(comp, "Not A Row", 1.0)


class BandLanesTest(unittest.TestCase):
    """A band family's lanes cross by the plan's placement: a Pro-Q 4 band's gain onto the Channel
    EQ slot it landed in, converted by that slot's measured slider."""

    def _cheq(self):
        raw = {"slots": {"bell": [{"on": "Peak 1 On/Off", "frequency": "Peak 1 Frequency", "gain": "Peak 1 Gain", "q": "Peak 1 Q-Factor"}]},
               "automation": {"Peak 1 Gain": {"per": 480, "units": [[0, -30.0], [240, 0.0], [480, 30.0]]},
                              "Peak 1 Frequency": {"per": 1200, "units": [[0, 20.0], [600, 1000.0], [1200, 20000.0]]},
                              "Peak 1 Q-Factor": {"per": 128, "units": [[0, 0.1], [43, 1.0], [100, 100.0]]}}}
        m = Map("eq", "Synthetic EQ", {}, type=999, raw=raw)
        table = Table.from_dict({"type": 999, "name": "Synthetic EQ", "floats": 8, "params": [
            {"index": 3, "name": "Peak 1 On/Off", "choices": ["Off", "On"]}, {"index": 4, "name": "Peak 1 Frequency", "unit": "Hz"},
            {"index": 5, "name": "Peak 1 Gain", "unit": "dB"}, {"index": 6, "name": "Peak 1 Q-Factor"}]})
        return m, table

    def test_a_pro_q_4_gain_lane_lands_on_the_placed_slot(self):
        cheq, table = self._cheq()
        lane = Lane("insert 1 parameter 26", None, 26, (Point(38400, 26 / 60), Point(42240, 0.5)), False, slot=1)   # band 2 gain: -4 dB, 0 dB
        notes = []
        got = carry_lane(lane, PROQ, cheq, None, table, notes, assignment={2: cheq.raw["slots"]["bell"][0]})
        self.assertEqual((got.param_index, [math.floor(p.value * 480) for p in got.points], notes), (4, [208, 240], []))   # 8 units a dB

    def test_frequency_crosses_in_the_log_domain_and_on_off_as_a_switch(self):
        cheq, table = self._cheq()
        placement = {1: cheq.raw["slots"]["bell"][0]}
        freq = Lane("insert 1 parameter 2", None, 2, (Point(38400, (math.log2(1000) - 3.321928) / (14.872675 - 3.321928)),), False, slot=1)
        got = carry_lane(freq, PROQ, cheq, None, table, [], assignment=placement)
        self.assertEqual((got.param_index, math.floor(got.points[0].value * 1200)), (3, 600))
        on = Lane("insert 1 parameter 1", None, 1, (Point(38400, 0.0), Point(42240, 1.0)), False, slot=1)   # enabled
        got = carry_lane(on, PROQ, cheq, None, table, [], assignment=placement)
        self.assertEqual((got.param_index, [p.value for p in got.points]), (2, [0.0, 1.0]))

    def test_an_unplaced_band_and_an_odd_field_are_dropped_with_notes(self):
        cheq, table = self._cheq()
        notes = []
        self.assertIsNone(carry_lane(Lane("insert 1 parameter 26", None, 26, (), False, slot=1), PROQ, cheq, None, table, notes, assignment={}))
        self.assertIsNone(carry_lane(Lane("insert 1 parameter 5", None, 5, (), False, slot=1), PROQ, cheq, None, table, notes, assignment={1: {}}))   # band 1 shape
        self.assertEqual(notes, ["lane insert 1 parameter 26 (band 2 gain): band 2 has no place in Synthetic EQ; dropped",
                                 "lane insert 1 parameter 5: not a band's frequency, gain, Q or on/off in Pro-Q 4; dropped"])

    def test_a_channel_eq_lane_crosses_back_into_pro_q_4(self):
        cheq, table = self._cheq()
        lane = Lane("insert 1 parameter 4", None, 4, (Point(38400, 200 / 480),), False, slot=1)              # Peak 1 Gain -5 dB
        got = carry_lane(lane, cheq, PROQ, table, None, [], assignment={1: 3})                            # onto Pro-Q 4 band 3
        self.assertEqual(got.param_index, 2 * 23 + 3)
        self.assertAlmostEqual(got.points[0].value, 25 / 60, places=6)

    def test_a_pro_mb_threshold_lane_lands_on_the_multipressor_slot(self):
        promb = next(m for m in MAPS if m.plugin == "Pro-MB")
        raw = {"slots": [{"on": "Band 1 Monitor", "threshold": "Band 1 Comp. Threshold", "ratio": "Band 1 Comp. Ratio", "level": "Band 1 Make Up"}],
               "automation": {"Band 1 Comp. Threshold": {"per": 128, "units": [[0, -60.0], [60, -20.0], [160, 10.0]]}}}
        multi = Map("multiband", "Synthetic MB", {}, type=998, raw=raw)
        table = Table.from_dict({"type": 998, "name": "Synthetic MB", "floats": 10, "params": [
            {"index": 9, "name": "Band 1 Comp. Threshold", "unit": "dB"}]})
        lane = Lane("insert 1 parameter 6", None, 6, (Point(38400, 0.7),), False, slot=1)                 # band 1 threshold: -18 dB
        notes = []
        got = carry_lane(lane, promb, multi, None, table, notes, assignment={1: raw["slots"][0]})
        self.assertEqual((got.param_index, math.floor(got.points[0].value * 128), notes), (8, 66, []))   # -18 dB between the table's points


class ExpanderLanesTest(unittest.TestCase):
    """A Multipressor band crosses into a Pro-MB band as one side, its compressor or its
    expander; the plan says which, and that side's lanes carry while the other's drop."""

    def _multi(self):
        raw = {"slots": [{"on": "Band 1 Monitor", "threshold": "Band 1 Comp. Threshold", "ratio": "Band 1 Comp. Ratio",
                          "level": "Band 1 Make Up", "exp_threshold": "Band 1 Exp. Threshold",
                          "exp_ratio": "Band 1 Exp. Ratio", "reduction": "Band 1 Reduction"}],
               "automation": {"Band 1 Comp. Threshold": {"per": 128, "units": [[0, -60.0], [60, -20.0], [160, 10.0]]},
                              "Band 1 Exp. Threshold": {"per": 128, "units": [[0, -60.0], [60, -20.0], [160, 10.0]]},
                              "Band 1 Exp. Ratio": {"per": 128, "units": [[0, 1.0], [128, 4.0]]},
                              "Band 1 Reduction": {"per": 128, "units": [[0, -30.0], [128, 0.0]]}}}
        multi = Map("multiband", "Synthetic MB", {}, type=998, raw=raw)
        table = Table.from_dict({"type": 998, "name": "Synthetic MB", "floats": 10, "params": [
            {"index": 9, "name": "Band 1 Comp. Threshold", "unit": "dB"}, {"index": 7, "name": "Band 1 Exp. Threshold", "unit": "dB"},
            {"index": 8, "name": "Band 1 Exp. Ratio"}, {"index": 6, "name": "Band 1 Reduction", "unit": "dB"}]})
        return multi, table

    def test_the_expanders_lanes_land_on_a_pro_mb_band_set_to_expand(self):
        promb = next(m for m in MAPS if m.plugin == "Pro-MB")
        multi, table = self._multi()
        notes = []
        exp = Lane("insert 1 parameter 6", None, 6, (Point(38400, 60 / 128),), False, slot=1)       # Exp. Threshold -20 dB
        got = carry_lane(exp, multi, promb, table, None, notes, assignment={1: 1}, modes={1: "expand"})
        self.assertEqual(got.param_index, 6)                                                           # band 1 threshold
        red = Lane("insert 1 parameter 5", None, 5, (Point(38400, 0.5),), False, slot=1)             # Reduction -15 dB
        got = carry_lane(red, multi, promb, table, None, notes, assignment={1: 1}, modes={1: "expand"})
        self.assertEqual((got.param_index, got.points[0].value), (7, 0.25))                           # range -30..30
        self.assertEqual(notes, [])

    def test_the_other_sides_lanes_drop_saying_which_side_crossed(self):
        promb = next(m for m in MAPS if m.plugin == "Pro-MB")
        multi, table = self._multi()
        notes = []
        comp = Lane("insert 1 parameter 8", None, 8, (Point(38400, 0.5),), False, slot=1)            # Comp. Threshold
        self.assertIsNone(carry_lane(comp, multi, promb, table, None, notes, assignment={1: 1}, modes={1: "expand"}))
        exp = Lane("insert 1 parameter 6", None, 6, (Point(38400, 0.5),), False, slot=1)             # Exp. Threshold
        self.assertIsNone(carry_lane(exp, multi, promb, table, None, notes, assignment={1: 1}, modes={1: "compress"}))
        self.assertEqual(notes, ["lane insert 1 parameter 8 (band 1 threshold): band 1 crossed as its expander; "
                                 "the compressor's threshold has no place in Pro-MB; dropped",
                                 "lane insert 1 parameter 6 (band 1 exp_threshold): band 1 crossed as its compressor; "
                                 "the expander's exp_threshold has no place in Pro-MB; dropped"])


class CarryTest(unittest.TestCase):
    def test_a_lane_crosses_between_third_parties_of_one_map(self):
        lane = Lane("insert 1 parameter 1", None, 1, (Point(38400, 0.5), Point(42240, 0.75)), False)
        notes = []
        got = carry_lane(lane, PROC, PROC, None, None, notes)
        self.assertEqual((got.param_index, [(p.tick, p.value) for p in got.points], notes),
                         (1, [(38400, 0.5), (42240, 0.75)], []))

    def test_a_knee_lane_carries_with_a_note_on_its_short_slider(self):
        lane = Lane("insert 1 parameter 3", None, 3, (Point(38400, 0.25), Point(42240, 1.0)), False)   # Pro-C 2 knee 6 / 24 dB
        notes = []
        got = carry_lane(lane, PROC, COMP, None, COMP_TABLE, notes)
        self.assertEqual(got.param_index, 5)
        self.assertEqual(notes, ["lane insert 1 parameter 3 (knee): Compressor's Knee slider spans units 0..10 of 128 per 1.0, "
                                 "so a point above 0.08 sits at its top: nearly a switch"])
        notes = []
        carry_lane(Lane("insert 1 parameter 1", None, 1, (Point(38400, 0.5),), False), PROC, COMP, None, COMP_TABLE, notes)
        self.assertEqual(notes, [])                                             # the threshold slider is long

    def test_a_lane_without_a_home_is_dropped_with_a_note(self):
        lane = Lane("insert 1 parameter 8", None, 8, (Point(38400, 0.5),), False)   # Pro-C 2 lookahead
        notes = []
        self.assertIsNone(carry_lane(lane, PROC, COMP, None, COMP_TABLE, notes))
        self.assertEqual(notes, ["lane insert 1 parameter 8 (lookahead): no analogue in Compressor; dropped"])
        notes = []
        self.assertIsNone(carry_lane(Lane("insert 1 parameter 99", None, 99, (), False), PROC, COMP, None, COMP_TABLE, notes))
        self.assertIn("has no vocabulary item there", notes[0])

    def test_a_native_target_without_a_measured_slider_drops_the_lane_with_the_reason(self):
        lane = Lane("insert 1 parameter 8", None, 8, (Point(38400, 0.5),), False)          # Pro-C 2 lookahead -> Noise Gate's
        raw = copy.deepcopy(next(m for m in MAPS if m.plugin == "Noise Gate").raw)
        del raw["automation"]["Lookahead"]                                                # a slider nobody sampled
        notes = []
        self.assertIsNone(carry_lane(lane, PROC, Map.from_dict(raw), None, table_for(load_tables(), 179), notes))
        self.assertIn("slider is not measured", notes[0])


if __name__ == "__main__":
    unittest.main()
