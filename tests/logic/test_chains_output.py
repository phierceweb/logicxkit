"""`logic chains` on a channel named rather than referenced: the Stereo Out's mastering chain."""

import unittest

from _fixtures import chunk
from logicxkit.logic import chain_plan
from logicxkit.logic.services.mixer.binding import LABEL_AT
from logicxkit.logic.services.mixer.output_params import PARAMS
from logicxkit.logic.services.mixer.slots import slot_index_base
from test_chains import proj, rec

OUT = 269


def channel(owner: int, label: str) -> bytes:
    payload = bytearray(b"C" * 225)
    payload[LABEL_AT:LABEL_AT + 32] = (" " + label).encode().ljust(32, b"\x00")
    return rec(b"OCuA", owner, 0xFFFF, bytes(payload))


def donor(owner: int, type_id: int, n: int) -> bytes:
    return rec(b"UCuA", owner, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(type_id, [0.5] * n))


class OutputChainTest(unittest.TestCase):
    def setUp(self):
        self.data = proj(channel(0, "Audio 1"), channel(OUT, "Output 1-2"))
        self.extra = {"lpeq": (donor(90, 243, 52), 243), "mp": (donor(91, 194, 62), 194),
                      "adl": (donor(92, 193, 10), 193), "lim": (donor(93, 199, 13), 199)}
        self.cfg = {"chains": {"Stereo Out": {"label": "Master", "plugins": [
            {"donor": "lpeq", "params": {"peak3_gain": 1.5}}, {"donor": "mp"},
            {"donor": "adl", "params": {"out_ceiling": -0.3, "3": -0.3}}, {"donor": "lim", "params": {"5": -0.1}}]}}}

    def test_the_stereo_out_gets_the_plugins_in_order_with_named_parameters(self):
        plan, report = chain_plan(self.data, self.cfg, None, None, extra=self.extra)
        self.assertEqual(list(plan), [OUT])
        self.assertEqual([s[6] for s in plan[OUT]], [243, 194, 193, 199])
        base = slot_index_base(self.data)
        self.assertEqual([s[1] for s in plan[OUT]], [base, base + 1, base + 2, base + 3])
        self.assertEqual(plan[OUT][0][8], {PARAMS[243]["peak3_gain"]: 1.5})
        self.assertEqual(plan[OUT][2][8], {PARAMS[193]["out_ceiling"]: -0.3})
        self.assertEqual(plan[OUT][3][8], {5: -0.1})
        self.assertEqual((report["matched"], report["missing_from_project"]), (["Stereo Out"], []))
        self.assertTrue(all(s[4] == "Trk - Master" for s in plan[OUT]))

    def test_a_channel_the_project_lacks_is_reported_not_planned(self):
        plan, report = chain_plan(proj(channel(0, "Audio 1")), self.cfg, None, None, extra=self.extra)
        self.assertEqual((plan, report["missing_from_project"]), ({}, ["Stereo Out"]))

    def test_an_unknown_parameter_or_donor_is_refused_by_name(self):
        cfg = {"chains": {"Stereo Out": {"plugins": [{"donor": "lim", "params": {"ceiling": -1}}]}}}
        with self.assertRaises(ValueError) as e:
            chain_plan(self.data, cfg, None, None, extra=self.extra)
        self.assertIn("no parameter 'ceiling'", str(e.exception))
        with self.assertRaises(ValueError):
            chain_plan(self.data, {"chains": {"Stereo Out": {"plugins": [{"donor": "nope"}]}}}, None, None, extra=self.extra)

    def test_a_plain_channel_name_matches_its_own_label(self):
        cfg = {"chains": {"Audio 1": {"plugins": [{"donor": "lim"}]}}}
        plan, _ = chain_plan(self.data, cfg, None, None, extra=self.extra)
        self.assertEqual(list(plan), [0])


class RefusalsTest(unittest.TestCase):
    """What a channel-keyed chain refuses before anything is written."""

    def setUp(self):
        self.extra = {"lim": (donor(93, 199, 13), 199), "short": (donor(94, 199, 12), 199)}

    def test_a_label_two_channels_carry_is_refused(self):
        data = proj(channel(0, "Audio 1"), channel(1, "Audio 1"))
        with self.assertRaises(ValueError) as e:
            chain_plan(data, {"chains": {"Audio 1": {"plugins": [{"donor": "lim"}]}}}, None, None, extra=self.extra)
        self.assertIn("2 channels carry that label", str(e.exception))

    def test_an_index_outside_the_donors_block_is_refused(self):
        data = proj(channel(0, "Audio 1"))
        for index in ("13", "999", "-1"):
            with self.subTest(index), self.assertRaises(ValueError) as e:
                chain_plan(data, {"chains": {"Audio 1": {"plugins": [{"donor": "lim", "params": {index: 1.0}}]}}}, None, None, extra=self.extra)
            self.assertIn("outside the Limiter block of 13", str(e.exception))

    def test_a_named_parameter_needs_the_donors_full_block(self):
        data = proj(channel(0, "Audio 1"))
        with self.assertRaises(ValueError) as e:
            chain_plan(data, {"chains": {"Audio 1": {"plugins": [{"donor": "short", "params": {"gain": 1}}]}}}, None, None, extra=self.extra)
        self.assertIn("12 floats", str(e.exception))

    def test_a_channel_keyed_by_reference_and_by_name_is_refused(self):
        ref = rec(b"UCuA", 0, 10, b"\x00" * 16 + b"Kick In.cst".ljust(64, b"\x00"))
        data = proj(channel(0, "Audio 1"), ref)
        cfg = {"chains": {"Kick In.cst": {"pre": ["lim"]}, "Audio 1": {"plugins": [{"donor": "lim"}]}}}
        with self.assertRaises(ValueError) as e:
            chain_plan(data, cfg, None, None, extra=self.extra)
        self.assertIn("keyed twice", str(e.exception))
        self.assertIn("Kick In.cst / Audio 1", str(e.exception))

    def test_a_pre_or_post_parameter_goes_by_name_or_index(self):
        ref = rec(b"UCuA", 0, 10, b"\x00" * 16 + b"Kick In.cst".ljust(64, b"\x00"))
        data = proj(channel(0, "Audio 1"), ref)
        cfg = {"chains": {"Kick In.cst": {"pre": ["lim"], "params": {"lim": {"output_level": -0.1, "2": 5}}}}}
        plan, _report = chain_plan(data, cfg, None, None, extra=self.extra)
        self.assertEqual(plan[0][0][8], {5: -0.1, 2: 5.0})
        with self.assertRaises(ValueError) as e:
            chain_plan(data, {"chains": {"Kick In.cst": {"pre": ["lim"], "params": {"lim": {"ceiling": -1}}}}}, None, None, extra=self.extra)
        self.assertIn("no parameter 'ceiling'", str(e.exception))


class ReportAndWidthTest(unittest.TestCase):
    def test_the_plan_names_the_channel_not_its_owner_number(self):
        from logicxkit.logic.services.mixer.chain_report import chain_changes
        data = proj(channel(0, "Audio 1"), channel(OUT, "Output 1-2"))
        extra = {"lim": (donor(93, 199, 13), 199)}
        plan, _ = chain_plan(data, {"chains": {"Stereo Out": {"plugins": [{"donor": "lim"}]}}}, None, None, extra=extra)
        self.assertEqual([c.ref for c in chain_changes(data, plan)], ["Stereo Out"])

    def test_stereo_on_a_channel_keyed_chain_widens_it(self):
        from logicxkit.logic.services.mixer.chains import width_plan
        from logicxkit.logic.services.mixer.slot_width import STEREO
        data = proj(channel(0, "Audio 1"), channel(OUT, "Output 1-2"))
        self.assertEqual(width_plan(data, {"chains": {"Stereo Out": {"stereo": True, "plugins": []}}}), {OUT: STEREO})


class StampOrderTest(unittest.TestCase):
    def test_a_dialled_value_wins_over_the_strips_float(self):
        from logicxkit.logic._binary import find_blocks, read_block_floats
        from logicxkit.logic.services.mixer.insert import _stamp
        from logicxkit.logic.services.stream.stream import HEADER
        raw = _stamp(donor(93, 199, 13), 0, 4, [0.0] * 13, 13, "seed", overrides={3: -0.3})
        idx, _tid, n = find_blocks(raw[HEADER:])[0]
        self.assertAlmostEqual(read_block_floats(raw[HEADER:], idx, n)[3], -0.3, places=5)
        with self.assertRaises(ValueError):
            _stamp(donor(93, 199, 13), 0, 4, None, 0, "seed", overrides={13: 1.0})


class GridTest(unittest.TestCase):
    """A measured value goes where `--set` puts it: Multipressor's ratio slider holds 2.466 and 2.511
    around 2.5, its threshold -20 exactly; one outside the slider is refused."""

    def setUp(self):
        self.data = proj(channel(0, "Audio 1"), channel(OUT, "Output 1-2"))
        self.extra = {"mp": (donor(91, 194, 62), 194), "lpeq": (donor(90, 243, 52), 243)}

    def _plan(self, params):
        cfg = {"chains": {"Stereo Out": {"plugins": [{"donor": "mp", "params": params}]}}}
        return chain_plan(self.data, cfg, None, None, extra=self.extra)[0][OUT][0][8]

    def test_a_measured_parameter_lands_on_the_nearer_sampled_position(self):
        self.assertEqual(self._plan({"band1_ratio": 2.5, "band1_threshold": -20}),
                         {PARAMS[194]["band1_ratio"]: 2.511, PARAMS[194]["band1_threshold"]: -20.0})

    def test_a_value_outside_the_slider_is_refused(self):
        with self.assertRaises(ValueError) as e:
            self._plan({"band1_ratio": 99})
        self.assertIn("Band 1 Comp. Ratio 99 is outside Multipressor's", str(e.exception))

    def test_a_plug_in_with_no_map_takes_the_value_as_given(self):
        cfg = {"chains": {"Stereo Out": {"plugins": [{"donor": "lpeq", "params": {"peak3_q": 0.8}}]}}}
        self.assertEqual(chain_plan(self.data, cfg, None, None, extra=self.extra)[0][OUT][0][8], {PARAMS[243]["peak3_q"]: 0.8})

    def test_a_value_outside_the_tables_range_is_refused_with_or_without_a_map(self):
        """The Limiter has a table (Gain -20..20 dB) and no map; `--set` refuses the same value."""
        extra = {"lim": (donor(93, 199, 13), 199)}
        ok = {"chains": {"Stereo Out": {"plugins": [{"donor": "lim", "params": {"gain": 0, "output_level": -0.1}}]}}}
        self.assertEqual(chain_plan(self.data, ok, None, None, extra=extra)[0][OUT][0][8], {PARAMS[199]["gain"]: 0.0, PARAMS[199]["output_level"]: -0.1})
        with self.assertRaises(ValueError) as e:
            chain_plan(self.data, {"chains": {"Stereo Out": {"plugins": [{"donor": "lim", "params": {"gain": 99}}]}}}, None, None, extra=extra)
        self.assertIn("Gain 99 is outside Limiter's measured -20..20 dB", str(e.exception))
        at_end = {"chains": {"Stereo Out": {"plugins": [{"donor": "lim", "params": {"5": -10}}]}}}      # by index, at the range's end
        self.assertEqual(chain_plan(self.data, at_end, None, None, extra=extra)[0][OUT][0][8], {5: -10.0})
        with self.assertRaisesRegex(ValueError, "Output Level -10.5 is outside Limiter's measured -10..1 dB"):
            chain_plan(self.data, {"chains": {"Stereo Out": {"plugins": [{"donor": "lim", "params": {"5": -10.5}}]}}}, None, None, extra=extra)

    def test_a_curve_rows_word_is_held_to_its_curves_ends(self):
        """Vintage Graphic EQ's bands read through a curve; the chain writes the word, so the word's ends hold it."""
        extra = {"vgeq": (donor(95, 285, 17), 285)}
        plan, _ = chain_plan(self.data, {"chains": {"Stereo Out": {"plugins": [{"donor": "vgeq", "params": {"2": 6.5}}]}}}, None, None, extra=extra)
        self.assertEqual(plan[OUT][0][8], {2: 6.5})
        with self.assertRaisesRegex(ValueError, "8.0K 99 is outside Vintage Graphic EQ's measured -12..12"):
            chain_plan(self.data, {"chains": {"Stereo Out": {"plugins": [{"donor": "vgeq", "params": {"2": 99}}]}}}, None, None, extra=extra)

    def test_a_scaled_rows_word_is_checked_and_gridded_as_shown(self):
        """A range and a slider are what Logic shows. No shipped effect row is scaled, so the
        Compressor's Threshold is given a scale of 0.01: word -4970 shows -49.7, the slider keeps
        -49.5, and the word written is -4950; word -6000 shows -60, outside -50..0."""
        import dataclasses
        from unittest import mock
        from logicxkit.logic.services.mixer.plugin_params import load_tables
        real = load_tables()[154]
        scaled = dataclasses.replace(real, params=tuple(dataclasses.replace(p, scale=0.01) if p.name == "Threshold" else p
                                                        for p in real.params))
        extra = {"comp": (donor(96, 154, 31), 154)}

        def plan(word):
            cfg = {"chains": {"Stereo Out": {"plugins": [{"donor": "comp", "params": {"1": word}}]}}}
            return chain_plan(self.data, cfg, None, None, extra=extra)[0][OUT][0][8]
        with mock.patch("logicxkit.logic.services.mixer.chains_channels.load_tables", return_value={154: scaled}):
            self.assertAlmostEqual(plan(-4970)[1], -4950.0, places=6)
            with self.assertRaisesRegex(ValueError, "Threshold -60 is outside Compressor's measured -50..0 dB"):
                plan(-6000)


if __name__ == "__main__":
    unittest.main()
