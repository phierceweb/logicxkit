"""A Pro-MB dialled to three bands in Logic reads as its window showed; carried into a
Multipressor and back into a Pro-MB, each came back from Logic's re-save as written. Skips
without the public corpus."""

import re
import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.mixer.transplant import slot_at
from logicxkit.logic.services.translate.translate import load_maps, map_for, plan, read_settings
from logicxkit.logic.services.translate.translate_mb import neutral
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


@_goldens.needs("mb-promb")
class DialledProMBTest(unittest.TestCase):
    def test_three_bands_read_as_dialled(self):
        facts, s = _settings("mb-promb")
        self.assertEqual([b.label() for b in s.bands], facts["bands"])
        self.assertEqual((s.values["lookahead_on"], s.values["mix"]), (True, 100.0))
        self.assertAlmostEqual(s.values["output_gain"], 2.0, places=2)


@_goldens.needs("mb-promb", "mb-promb-ours", "mb-promb-resave-logic")
class ProMBIntoMultipressorTest(unittest.TestCase):
    def test_band_3_set_off_hands_its_stretch_to_band_4(self):
        """`mb-promb-ours` sets band 3 (the 2-4 kHz stretch no Pro-MB band covers) Off; Logic's
        editor shows band 4 then starting at 2 kHz, so the stretch is compressed."""
        _f, ours = _settings("mb-promb-ours")
        self.assertEqual([(b.low, b.high, b.number) for b in ours.bands],
                         [(20.0, 120.0, 1), (120.0, 2000.0, 2), (2000.0, 20000.0, 4)])
        self.assertEqual((ours.bands[0].threshold, ours.bands[0].ratio, ours.bands[0].level), (-20.0, 3.0, 1.0))
        self.assertEqual((ours.bands[1].threshold, ours.bands[1].ratio, ours.bands[1].expander), (0.0, 1.0, (-40.0, 2.0, -10.0)))
        self.assertEqual((ours.bands[2].threshold, ours.bands[2].ratio, ours.bands[2].level), (-12.0, 4.0, -1.5))
        self.assertEqual((ours.values["lookahead"], ours.values["output_gain"]), (2.0, 2.0))

    def test_the_plan_passes_the_uncovered_stretch_untouched(self):
        _f, source = _settings("mb-promb")
        p = plan(source, next(m for m in MAPS if m.plugin == "Multipressor"))
        v = p.values
        self.assertEqual((v["Band 3 Monitor"], v["Band 3 Comp. Threshold"], v["Band 3 Comp. Ratio"], v["Band 3 Exp. Ratio"],
                          v["Band 3 Make Up"]), ("On", 0.0, 1.0, 1.0, 0.0))
        self.assertEqual((v["Band 3 Xover Frequency 2/3"], v["Band 4 Xover Frequency 3/4"]), (2000.0, 3900.0))

    def test_logic_showed_and_kept_the_write(self):
        facts, theirs = _settings("mb-promb-resave-logic")
        _f, ours = _settings("mb-promb-ours")
        for i, (a, b) in enumerate(zip(ours.bands, theirs.bands, strict=True)):
            with self.subTest(band=i + 1):
                self.assertEqual(a.on, b.on)
                self.assertAlmostEqual(a.low, b.low, delta=a.low * 0.03)      # 4000 Hz shown as 3900: the knob's grid
                self.assertAlmostEqual(a.high, b.high, delta=a.high * 0.03)
                self.assertAlmostEqual(a.threshold, b.threshold, delta=0.01)
                self.assertAlmostEqual(a.ratio, b.ratio, delta=a.ratio * 0.1)  # 4.0 shown as 3.675, 2.0 as 1.98
                self.assertAlmostEqual(a.level, b.level, delta=0.01)
                if a.expander:
                    self.assertAlmostEqual(a.expander[0], b.expander[0], delta=0.01)
                    self.assertAlmostEqual(a.expander[1], b.expander[1], delta=a.expander[1] * 0.1)
                    self.assertAlmostEqual(a.expander[2], b.expander[2], delta=0.01)
        shown = facts["shown"]
        self.assertEqual((_number(shown["Band 1 Comp. Threshold"]), _number(shown["Band 4 Comp. Threshold"])), (-20.0, -12.0))
        self.assertEqual((shown["Band 3 Monitor"], shown["Band 1 Monitor"]), ("0", "1"))
        self.assertEqual(_number(shown["Band 2 Xover Frequency 1/2"]), 120.0)


@_goldens.needs("mb-promb", "mb-neutral-mine", "mb-neutral-logic")
class NeutralBandTest(unittest.TestCase):
    """The uncovered stretch as a band that passes it untouched; Logic's editor drew four live
    bands, band 3 at 0 dB and 1:1 both ways (the facts), and the re-save reads the same."""

    def test_the_copy_holds_the_plan_and_logic_kept_it(self):
        _f, source = _settings("mb-promb")
        target = next(m for m in MAPS if m.plugin == "Multipressor")
        _f, ours = _settings("mb-neutral-mine")
        _f, theirs = _settings("mb-neutral-logic")
        self.assertEqual([b.number for b in ours.bands], [1, 2, 3, 4])
        self.assertEqual(round(ours.bands[2].low), 2000)
        self.assertTrue(neutral(ours.bands[2]))
        p = plan(source, target)
        self.assertEqual((ours.bands[2].threshold, ours.bands[2].ratio), (p.values["Band 3 Comp. Threshold"], p.values["Band 3 Comp. Ratio"]))
        for a, b in zip(ours.bands, theirs.bands, strict=True):
            with self.subTest(band=a.number):
                self.assertEqual((a.number, round(a.low), round(a.high)), (b.number, round(b.low), round(b.high)))
                self.assertAlmostEqual(a.threshold, b.threshold, delta=0.01)
        self.assertEqual(_goldens.fact("mb-neutral-logic", "editor")["bands"], [1, 2, 3, 4])


@_goldens.needs("mb-multi2promb", "mb-multi2promb-resave-logic")
class MultipressorIntoProMBTest(unittest.TestCase):
    def test_the_bands_came_back_and_logic_showed_them(self):
        _f, ours = _settings("mb-multi2promb")
        facts, theirs = _settings("mb-multi2promb-resave-logic")
        self.assertEqual([(b.mode, b.on) for b in ours.bands], [("compress", True), ("expand", True), ("compress", True)])
        self.assertEqual([round(b.low) for b in ours.bands], [30, 120, 3900])       # Logic's crossover grid, from the re-save
        self.assertEqual((ours.bands[0].range, ours.bands[1].range, ours.bands[2].range), (-30.0, -10.0, -30.0))
        for i, (a, b) in enumerate(zip(ours.bands, theirs.bands, strict=True)):
            with self.subTest(band=i + 1):
                self.assertEqual((a.mode, a.on), (b.mode, b.on))
                self.assertAlmostEqual(a.low, b.low, delta=a.low * 0.001)
                self.assertAlmostEqual(a.high, b.high, delta=a.high * 0.001)
                self.assertAlmostEqual(a.threshold, b.threshold, delta=0.05)
                self.assertAlmostEqual(a.ratio, b.ratio, delta=0.05)
                self.assertEqual((a.range, a.level), (b.range, b.level))
        for number, want in facts["shown"].items():
            if not number.isdigit():
                continue
            band = theirs.bands[int(number) - 1]
            with self.subTest(number):
                self.assertEqual((band.on, band.mode), (want["state"] == "Enabled", {"Compression": "compress", "Expansion": "expand"}[want["mode"]]))
                self.assertAlmostEqual(band.low, _number(want["low"]), delta=_number(want["low"]) * 0.001)
                self.assertAlmostEqual(band.threshold, _number(want["threshold"]), delta=0.05)
                self.assertAlmostEqual(band.ratio, _number(want["ratio"]), delta=0.05)
                self.assertAlmostEqual(band.range, _number(want["range"]), delta=0.05)
        self.assertEqual(theirs.values["mix"], 100.0)
        self.assertAlmostEqual(theirs.values["output_gain"], 2.0, places=2)


if __name__ == "__main__":
    unittest.main()
