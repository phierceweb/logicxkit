"""Settings written through a map: a third-party's AU state patched by id in place, one of
Logic's own through its table, bands into Pro-Q 4's layout, and band-label edits."""

import json
import unittest

from logicxkit.au.services.aupreset import parse_au_state
from logicxkit.au.services.embed import find_au_plists
from logicxkit.au.services.ffp import parse_ffp
from logicxkit.logic.services.translate import Settings, load_maps, plan, read_settings
from logicxkit.logic.services.translate_eq import Band, parse_band
from logicxkit.logic.services.translate_write import (
    apply_band_specs,
    split_specs,
    write_bands,
    write_plan,
    write_settings,
)
from logicxkit.utils.data import PACKAGED
from test_translate import au_payload, native_payload
from test_translate_eq import proq_payload

MAPS = load_maps([PACKAGED / "translate"])
PROC, COMP, PROQ, CHEQ, GATE = (next(m for m in MAPS if m.plugin == n)
                                for n in ("Pro-C 2", "Compressor", "Pro-Q 4", "Channel EQ", "smart:gate"))
CHEQ_FLOATS = json.loads((PACKAGED / "logic" / "params-236.json").read_text())["floats"]


def pairs_of(payload: bytes) -> dict[int, float]:
    plist = next(pl for _off, pl in find_au_plists(payload) if "manufacturer" in pl)
    return dict(parse_au_state(plist).param_pairs)


def ffbs_of(payload: bytes) -> tuple[float, ...]:
    plist = next(pl for _off, pl in find_au_plists(payload) if "manufacturer" in pl)
    return parse_ffp(plist["FabFilterPluginState"]).values


class WriteThirdPartyTest(unittest.TestCase):
    def test_values_land_in_the_pairs_by_id(self):
        payload = au_payload({1: -18.0, 2: 0.6, 3: 18.0, 34: 1.0})
        new, notes = write_settings(payload, PROC, {"threshold": -30, "ratio": 4.0, "mix": "80", "auto_release": "on"})
        pairs = pairs_of(new)
        self.assertEqual((pairs[1], pairs[7]), (-30.0, 1.0))
        self.assertAlmostEqual(pairs[2], 0.6, places=6)
        self.assertAlmostEqual(pairs[34], 0.8, places=6)
        self.assertEqual(pairs[3], 18.0)                                   # untouched
        self.assertEqual((len(new), notes), (len(payload), []))

    def test_a_value_past_the_range_is_clamped_with_a_note(self):
        new, notes = write_settings(au_payload({1: -18.0}), PROC, {"threshold": -70})
        self.assertEqual(pairs_of(new)[1], -60.0)
        self.assertEqual(notes, ["threshold -70: Pro-C 2's Threshold starts at -60, set there"])

    def test_unknown_names_and_bad_values_are_refused(self):
        payload = au_payload({1: -18.0})
        for values in ({"knees": 1}, {"threshold": "loud"}, {"auto_gain": "maybe"}):
            with self.subTest(values), self.assertRaises(ValueError):
                write_settings(payload, PROC, values)
        with self.assertRaises(ValueError):
            write_settings(au_payload({1: -18.0}), GATE, {"attack": 10})     # sonible's protobuf is read, not written
        with self.assertRaises(ValueError):
            write_settings(proq_payload({}), PROQ, {"threshold": -10})       # an EQ takes bands


class WriteNativeTest(unittest.TestCase):
    def test_vocabulary_values_land_in_the_block_on_its_grids(self):
        payload = native_payload([0.0] * 52)
        new, notes = write_settings(payload, COMP, {"threshold": -20.3, "ratio": 3.06, "auto_release": "on"})
        s = read_settings(new, COMP)
        self.assertEqual((s.values["threshold"], s.values["auto_release"]), (-20.5, True))
        self.assertAlmostEqual(s.values["ratio"], 3.1, places=5)
        self.assertEqual((len(new), notes), (len(payload), []))


class WriteBandsTest(unittest.TestCase):
    def test_bands_fill_the_layout_and_clear_the_rest(self):
        payload = proq_payload({1: {"shape": 0, "frequency": 100.0}, 2: {"shape": 0, "frequency": 200.0},
                                3: {"shape": 0, "frequency": 300.0}})
        bands = [Band("low_cut", 80.0, 0.0, 1.0, True, 24.0), Band("bell", 250.0, -4.0, 2.4, False)]
        new, notes = write_bands(payload, PROQ, bands, master=1.5)
        v = ffbs_of(new)
        self.assertEqual((v[0], v[1], v[5], v[6]), (1.0, 1.0, 2.0, 4.0))          # used, enabled, low cut, 24 dB/oct
        self.assertEqual((v[23], v[24], v[26], v[28]), (1.0, 0.0, -4.0, 0.0))     # band 2 bypassed, bell
        self.assertEqual(v[29], 2.0)                                              # a bell keeps the 12 dB/oct default
        self.assertEqual(v[46], 0.0)                                              # band 3 unused
        self.assertEqual(len(new), len(payload))
        got = read_settings(new, PROQ).bands
        self.assertEqual([b.label() for b in got][:1], ["low cut 80 Hz Q 1.00 24 dB/oct"])
        self.assertAlmostEqual(got[1].q, 2.4, delta=0.02)
        self.assertEqual(notes, ["master +1.5 dB: no analogue in Pro-Q 4"])

    def test_numbered_bands_keep_their_positions(self):
        bands = [Band("bell", 100.0, 1.0, 1.0, True, number=1), Band("bell", 300.0, 3.0, 1.0, True, number=3)]
        v = ffbs_of(write_bands(proq_payload({}), PROQ, bands)[0])
        self.assertEqual((v[0], v[23], v[46]), (1.0, 0.0, 1.0))
        with self.assertRaises(ValueError):
            write_bands(proq_payload({}), PROQ, [Band("bell", 1.0, 0.0, 1.0, True, number=25)])


class PlanIntoThirdPartyTest(unittest.TestCase):
    def test_channel_eq_bands_cross_into_pro_q_4(self):
        s = Settings(CHEQ, bands=[Band("low_cut", 80.0, 0.0, 1.0, True, None, number=1),
                                  Band("low_shelf", 80.0, 0.0, 1.1, False, None, number=2),
                                  Band("bell", 250.0, -4.0, 2.5, True, None, number=3)], master=0.0)
        p = plan(s, PROQ)
        self.assertEqual([b.label() for b in p.bands], ["low cut 80 Hz Q 1.00 12 dB/oct", "bell 250 Hz -4.0 dB Q 2.50"])
        self.assertIn("band 1 low cut 80 Hz Q 1.00: Channel EQ carries no slope for it; Pro-Q 4 gets 12 dB/oct", p.notes)
        new, _notes = write_plan(proq_payload({}), p)
        v = ffbs_of(new)
        self.assertEqual((v[0], v[5], v[6], v[23], v[26]), (1.0, 2.0, 2.0, 1.0, -4.0))

    def test_a_compressor_crosses_into_pro_c_2(self):
        s = Settings(COMP, values={"threshold": -30.0, "ratio": 3.1, "attack": 10.5, "make_up": 3.0, "mix": 80.0,
                                   "auto_release": False, "knee": 0.1})
        p = plan(s, PROC)
        self.assertEqual(p.values["threshold"], -30.0)
        self.assertEqual((p.values["ratio"], p.values["auto_release"]), (3.1, False))
        new, notes = write_plan(au_payload({1: -18.0, 2: 0.6, 5: 0.1, 10: 0.0, 34: 1.0}), p)
        pairs = pairs_of(new)
        self.assertEqual(pairs[1], -30.0)
        self.assertAlmostEqual(pairs[2], PROC.items["ratio"].to_stored(3.1), places=6)
        self.assertAlmostEqual(pairs[10], 3.0 / 36, places=6)
        self.assertEqual(notes, ["release 10 ms: Pro-C 2's own, kept", "auto_gain off: Pro-C 2's own, kept",
                                 "lookahead 0 ms: Pro-C 2's own, kept", "input_gain 0 dB: Pro-C 2's own, kept",
                                 "output_gain 0 dB: Pro-C 2's own, kept"])


class DialledDonorTest(unittest.TestCase):
    """`--set` on a third-party donor goes through its map; band specs through any EQ's."""

    def test_a_third_party_donor_is_dialled_through_its_map(self):
        from types import SimpleNamespace

        from logicxkit.logic._plugin_settings import dialled
        from logicxkit.logic.services.insert import HEADER
        donor = SimpleNamespace(label="Pro-C 2", type_id=None, raw=bytes(HEADER) + au_payload({1: -18.0, 2: 0.6}))
        raw, by_table, notes = dialled(donor, {"threshold": "-24", "ratio": "6"})
        self.assertEqual((by_table, notes, len(raw)), (None, [], len(donor.raw)))
        self.assertEqual(pairs_of(raw[HEADER:])[1], -24.0)
        self.assertEqual(dialled(donor, {}), (donor.raw, None, []))
        with self.assertRaises(ValueError):
            dialled(donor, {"Threshold": "-24"})                        # the vocabulary's name, not the table's

    def test_a_native_donor_keeps_its_table_names_but_takes_band_specs(self):
        from types import SimpleNamespace

        from logicxkit.logic._plugin_settings import dialled
        from logicxkit.logic.services.insert import HEADER
        comp = SimpleNamespace(label="Compressor", type_id=154, raw=bytes(HEADER) + native_payload([0.0] * 52))
        self.assertEqual(dialled(comp, {"Threshold": "-24"}), (comp.raw, {"Threshold": -24.0}, []))   # held and snapped
        eq = SimpleNamespace(label="Channel EQ", type_id=236, raw=bytes(HEADER) + native_payload([0.0] * CHEQ_FLOATS, 236))
        raw, by_table, _notes = dialled(eq, {"band 3": "bell 500 Hz +2 dB Q 1", "Master  Gain": "1.5"})
        self.assertEqual(by_table, {"Master  Gain": "1.5"})
        self.assertEqual(read_settings(raw[HEADER:], CHEQ).bands[2].label(), "bell 500 Hz +2.0 dB Q 1.00")


class BandSpecTest(unittest.TestCase):
    def test_labels_parse_both_ways(self):
        self.assertEqual(parse_band("bell 250 Hz -4 dB Q 2.4"), Band("bell", 250.0, -4.0, 2.4, True, None))
        self.assertEqual(parse_band("low cut 80 Hz 24 dB/oct"), Band("low_cut", 80.0, 0.0, 1.0, True, 24.0))
        self.assertEqual(parse_band("high shelf 8.00 kHz -2.0 dB Q 1.10 (off)"), Band("high_shelf", 8000.0, -2.0, 1.1, False, None))
        for band in (Band("bell", 1000.0, 3.0, 1.0, True), Band("notch", 60.0, 0.0, 1.0, True), Band("high_cut", 16000.0, 0.0, 1.0, True, 24.0)):
            self.assertEqual(parse_band(band.label()), band)

    def test_bad_specs_are_refused(self):
        for spec in ("250 Hz", "bell -4 dB", "bell 250"):
            with self.subTest(spec), self.assertRaises(ValueError):
                parse_band(spec)

    def test_band_edits_on_pro_q_4(self):
        payload = proq_payload({1: {"shape": 2, "frequency": 80.0, "slope": 4}, 2: {"shape": 0, "frequency": 1000.0, "gain": 3.0}})
        new, _notes = apply_band_specs(payload, PROQ, {"band 2": "bell 1 kHz +6 dB Q 2", "band 3": "notch 60 Hz"})
        got = read_settings(new, PROQ).bands
        self.assertEqual([got[0].label(), got[2].label()], ["low cut 80 Hz Q 1.00 24 dB/oct", "notch 60 Hz Q 1.00"])
        self.assertEqual((got[1].shape, got[1].gain, got[1].number), ("bell", 6.0, 2))
        self.assertAlmostEqual(got[1].frequency, 1000.0, places=2)
        self.assertAlmostEqual(got[1].q, 2.0, delta=0.02)
        with self.assertRaises(ValueError):
            apply_band_specs(payload, PROQ, {"band 0": "bell 1 kHz"})

    def test_band_edits_on_channel_eq_keep_the_slot_shape(self):
        payload = native_payload([0.0] * CHEQ_FLOATS, type_id=236)
        new, _notes = apply_band_specs(payload, CHEQ, {"band 3": "bell 500 Hz +2 dB Q 1"})
        self.assertEqual(read_settings(new, CHEQ).bands[2].label(), "bell 500 Hz +2.0 dB Q 1.00")
        for specs in ({"band 3": "notch 500 Hz"}, {"band 9": "bell 500 Hz"}):
            with self.subTest(specs), self.assertRaises(ValueError):
                apply_band_specs(payload, CHEQ, specs)

    def test_specs_split_into_bands_and_values(self):
        self.assertEqual(split_specs({"band 1": "x", "threshold": "-20", "Band 12": "y"}),
                         ({"band 1": "x", "Band 12": "y"}, {"threshold": "-20"}))


class SliderEndsTest(unittest.TestCase):
    def test_a_native_is_held_to_its_slider_and_told_when_between_samples(self):
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
        from test_translate import native_payload
        from logicxkit.logic.services.translate import load_maps, map_for, read_settings
        from logicxkit.utils.data import PACKAGED
        payload = native_payload([0.0] * 29)
        m = map_for(payload, load_maps([PACKAGED / "translate"]))
        out, notes = write_settings(payload, m, {"threshold": "999"})
        self.assertEqual(read_settings(out, m).values["threshold"], 0.0)
        self.assertEqual(notes, ["threshold 999: Compressor's Threshold slider runs -50..0; set to 0"])
        out, notes = write_settings(payload, m, {"threshold": "-46.5"})
        self.assertEqual((read_settings(out, m).values["threshold"], notes), (-46.5, []))   # a linear row: exact though unread
        for bad in ("inf", "-inf", "nan"):
            with self.subTest(bad), self.assertRaises(ValueError):
                write_settings(payload, m, {"threshold": bad})


if __name__ == "__main__":
    unittest.main()
