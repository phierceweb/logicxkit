"""FabFilter states written by logicxkit and re-saved by Logic: an in-place `settings --set` on a
Pro-C 2, a Compressor carried into a Pro-C 2, a Channel EQ carried into a Pro-Q 4 — each read
back in Logic's Controls view as written. Skips without the public corpus."""

import re
import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.mixer.transplant import channel_slots, slot_at
from logicxkit.logic.services.translate.translate import load_maps, map_for, read_settings
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

MAPS = load_maps([PACKAGED / "translate"])


def _settings(key: str):
    data = project_data(_goldens.path(key))
    facts = _goldens.entry(key)["facts"]
    payload = slot_at(data, owner_by_label(data, facts["channel"]), facts["slot"]).raw[HEADER:]
    return facts, read_settings(payload, map_for(payload, MAPS))


def _number(text: str) -> float:
    return float(re.match(r"[-+]?\d+(?:\.\d+)?", text).group())


@_goldens.needs("translate-proc", "write-proc", "write-proc-resave-logic")
class InPlaceWriteTest(unittest.TestCase):
    def test_three_items_changed_and_the_rest_stayed(self):
        _f, source = _settings("translate-proc")
        _f, ours = _settings("write-proc")
        self.assertEqual((ours.values["threshold"], ours.values["auto_gain"]), (-24.0, False))
        self.assertAlmostEqual(ours.values["ratio"], 6.0, places=5)
        for name, value in source.values.items():
            if name not in ("threshold", "ratio", "auto_gain"):
                with self.subTest(name):
                    self.assertEqual(ours.values[name], value)

    def test_logic_showed_and_kept_the_write(self):
        facts, theirs = _settings("write-proc-resave-logic")
        _f, ours = _settings("write-proc")
        for name, value in ours.values.items():
            with self.subTest(name):
                self.assertAlmostEqual(theirs.values[name], value, delta=0.01) if not isinstance(value, bool) \
                    else self.assertEqual(theirs.values[name], value)
        shown = facts["shown"]
        self.assertEqual((_number(shown["Threshold"]), _number(shown["Ratio"]), shown["Auto Gain"]), (-24.0, 6.0, "Off"))


@_goldens.needs("write-comp2proc", "write-comp2proc-resave-logic", "translate-ours-resave-logic")
class CompressorIntoProC2Test(unittest.TestCase):
    def test_the_compressor_values_landed_in_pro_c_2(self):
        _f, ours = _settings("write-comp2proc")
        for name, want in {"threshold": -30.0, "ratio": 3.1, "attack": 10.5, "release": 110.0, "make_up": 3.0,
                           "mix": 80.0, "knee": 7.2}.items():
            with self.subTest(name):
                self.assertAlmostEqual(ours.values[name], want, delta=0.01)
        self.assertEqual((ours.values["auto_release"], ours.values["auto_gain"]), (False, True))    # carried; the donor's own

    def test_logic_showed_the_write_between_the_curves_samples(self):
        facts, theirs = _settings("write-comp2proc-resave-logic")
        _f, ours = _settings("write-comp2proc")
        for name, value in ours.values.items():
            with self.subTest(name):
                self.assertAlmostEqual(theirs.values[name], value, delta=0.01) if not isinstance(value, bool) \
                    else self.assertEqual(theirs.values[name], value)
        shown = facts["shown"]
        self.assertEqual((_number(shown["Threshold"]), _number(shown["Ratio"]), _number(shown["Knee"])), (-30.0, 3.1, 7.2))
        self.assertAlmostEqual(_number(shown["Attack"]), 10.5, delta=0.05)          # 10.49 ms: the curve's samples
        self.assertAlmostEqual(_number(shown["Release"]), 110.0, delta=0.5)         # 109.8 ms


@_goldens.needs("write-eq2proq", "write-eq2proq-resave-logic")
class ChannelEQIntoProQ4Test(unittest.TestCase):
    def test_seven_bands_landed_and_logic_showed_them(self):
        _f, ours = _settings("write-eq2proq")
        facts, theirs = _settings("write-eq2proq-resave-logic")
        self.assertEqual([b.label() for b in ours.bands], [
            "low cut 80 Hz Q 1.00 12 dB/oct", "bell 250 Hz -4.0 dB Q 2.50", "bell 500 Hz +1.0 dB Q 1.00",
            "bell 1.00 kHz +3.0 dB Q 1.00", "bell 2.00 kHz -1.0 dB Q 1.00", "high shelf 8.00 kHz -2.0 dB Q 1.00",
            "high cut 16.00 kHz Q 1.00 12 dB/oct"])
        self.assertEqual(len(theirs.bands), 7)
        for number, want in facts["shown"].items():
            band = theirs.bands[int(number) - 1]
            with self.subTest(number):
                self.assertEqual(band.shape, ours.bands[int(number) - 1].shape)      # the Shape popup reads blank
                if band.shape in ("low_cut", "high_cut"):
                    self.assertEqual(band.slope, _number(want["slope"]))
                freq = _number(want["frequency"])
                self.assertAlmostEqual(band.frequency, freq, delta=freq * 0.001)
                self.assertAlmostEqual(band.gain, _number(want["gain"]), delta=0.01)
                self.assertAlmostEqual(band.q, _number(want["q"]), delta=0.02)


@_goldens.needs("translate-proq")
class OneBandEditTest(unittest.TestCase):
    """`band N=` writes band N and nothing else: a brickwall cut and a dynamic band elsewhere in
    the Logic-dialled Pro-Q 4 come through an edit of band 2 unchanged."""

    def test_the_other_bands_keep_their_brickwall_and_their_dynamics(self):
        from logicxkit.logic.services.translate.translate_eq import BRICKWALL, parse_band, read_bands
        from logicxkit.logic.services.translate.translate_write import apply_band_specs, write_state
        data = project_data(_goldens.path("translate-proq"))
        payload = channel_slots(data, owner_by_label(data, "Audio 2"))[0].raw[HEADER:]
        m = map_for(payload, MAPS)
        lay = m.raw["bands"]
        payload = write_state(payload, m, {lay["slope"]: 10.0, 5 * lay["stride"] + lay["dynamic_range"]: 6.0,
                                           5 * lay["stride"] + lay["dynamics_enabled"]: 1.0})
        before, _ = read_bands(payload, m, {})
        self.assertEqual((before[0].slope, before[5].dynamic), (BRICKWALL, True))
        self.assertIn("brickwall", before[0].label())
        after, _master = read_bands(apply_band_specs(payload, m, {"band 2": "bell 300 Hz -4 dB Q 2.4"})[0], m, {})
        self.assertEqual([b for b in after if b.number != 2], [b for b in before if b.number != 2])
        self.assertEqual(next(b for b in after if b.number == 2).label(), "bell 300 Hz -4.0 dB Q 2.40")
        self.assertEqual(parse_band("low cut 80 Hz brickwall").slope, BRICKWALL)


if __name__ == "__main__":
    unittest.main()
