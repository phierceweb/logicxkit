"""A Pro-C 2's automation lanes carried into a Compressor by `replace-plugin --translate`, and
Logic showing the carried points on the Compressor's own grid. Skips without the public corpus."""

import math
import re
import unittest

import _goldens
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logicx import project_data


def _number(text: str) -> float:
    return float(re.match(r"[-+]?\d+(?:\.\d+)?", text).group())


def _lanes(key: str, slot: int) -> dict[int, list[tuple[int, float]]]:
    data = project_data(_goldens.path(key))
    track = _goldens.entry(key)["facts"]["channel"]
    return {lane.param_index: [(p.tick, p.value) for p in lane.points]
            for a in read_automation(data) if a.track == track for lane in a.lanes if lane.slot == slot}


@_goldens.needs("auto-lanes", "auto-lanes-ours")
class CarriedLanesTest(unittest.TestCase):
    def test_the_lanes_land_on_the_compressor_indices_in_slider_units(self):
        facts = _goldens.entry("auto-lanes-ours")["facts"]
        got = _lanes("auto-lanes-ours", facts["slot"])
        self.assertEqual(sorted(got), sorted(int(k) for k in facts["lanes"]))
        for index, points in facts["lanes"].items():
            with self.subTest(index):
                self.assertEqual([(t, math.floor(v * facts["units_per"] + 1e-9)) for t, v in got[int(index)]],
                                 [(t, u) for t, u in points])                # Logic floors the units
        source = _lanes("auto-lanes", 3)
        self.assertEqual(sorted(source), [1, 2, 5, 8])                       # the lookahead lane (8) had no home


@_goldens.needs("auto-lanes-ours", "auto-lanes-resave-logic")
class LogicShowedTheCarriedPointsTest(unittest.TestCase):
    def test_logic_kept_the_lanes_and_showed_the_values(self):
        ours = _lanes("auto-lanes-ours", 3)
        theirs = _lanes("auto-lanes-resave-logic", 3)
        self.assertEqual(sorted(theirs), sorted(ours))
        for index in ours:
            with self.subTest(index):
                self.assertEqual([t for t, _v in theirs[index]], [t for t, _v in ours[index]])
                for (_t, a), (_t2, b) in zip(ours[index], theirs[index], strict=True):
                    self.assertAlmostEqual(a, b, places=6)
        shown = _goldens.entry("auto-lanes-resave-logic")["facts"]["shown"]
        expect = {"1": {"Threshold": -30.0, "Ratio": 3.9, "Attack": 10.5}, "2": {"Threshold": -24.0, "Attack": 16.0},
                  "3": {"Threshold": -12.0, "Ratio": 2.7}}                     # the Pro-C 2 lanes on the Compressor's grid; 10.5 ms is the static attack before its point
        for bar, rows in expect.items():
            for param, want in rows.items():
                with self.subTest(f"bar {bar} {param}"):
                    got = float(re.match(r"[-+]?\d+(?:\.\d+)?", shown[bar][param]).group())
                    self.assertAlmostEqual(got, want, delta=0.06)


def _band_round(self, key_ours: str, key_theirs: str, slot: int):
    """A band family's carried lanes: the copy's points floor to the facts' units under each
    lane's rate and Logic kept them; each caller checks what the Controls view showed per bar."""
    facts = _goldens.entry(key_ours)["facts"]
    ours = _lanes(key_ours, slot)
    self.assertEqual(sorted(ours), sorted(int(k) for k in facts["lanes"]))
    for index, points in facts["lanes"].items():
        per = facts["units_per"][index]
        with self.subTest(index):
            got = [(t, math.floor(v * per + 1e-9)) for t, v in ours[int(index)]] if per != 1 else [(t, round(v)) for t, v in ours[int(index)]]
            self.assertEqual(got, [(t, u) for t, u in points])
    theirs = _lanes(key_theirs, slot)
    self.assertEqual(sorted(theirs), sorted(ours))
    for index in ours:
        with self.subTest(f"kept {index}"):
            self.assertEqual([(t, round(v, 6)) for t, v in theirs[index]], [(t, round(v, 6)) for t, v in ours[index]])


@_goldens.needs("auto-eqlanes", "auto-eqlanes-ours", "auto-eqlanes-resave-logic")
class ChannelEQLanesTest(unittest.TestCase):
    def test_pro_q_4_band_lanes_reached_the_placed_slots(self):
        _band_round(self, "auto-eqlanes-ours", "auto-eqlanes-resave-logic", 1)
        shown = _goldens.entry("auto-eqlanes-resave-logic")["facts"]["shown"]
        self.assertEqual([shown[b]["Low Cut On/Off"] for b in ("1", "2", "3")], ["1", "0", "1"])
        self.assertEqual([_number(shown[b]["Peak 1 Gain"]) for b in ("1", "2", "3")], [-4.0, 0.0, 6.0])
        self.assertEqual([_number(shown[b]["Peak 3 Frequency"]) for b in ("1", "3")], [1000.0, 2000.0])


@_goldens.needs("auto-mblanes", "auto-mblanes-ours", "auto-mblanes-resave-logic")
class MultipressorLanesTest(unittest.TestCase):
    def test_pro_mb_band_lanes_reached_the_placed_slots(self):
        _band_round(self, "auto-mblanes-ours", "auto-mblanes-resave-logic", 1)
        shown = _goldens.entry("auto-mblanes-resave-logic")["facts"]["shown"]
        self.assertEqual([_number(shown[b]["Band 1 Comp. Threshold"]) for b in ("1", "2", "3")], [-20.0, -12.0, -30.0])
        self.assertAlmostEqual(_number(shown["1"]["Band 4 Comp. Ratio"]), 4.0, delta=0.35)    # 3.675: the ratio knob's grid at unit 46
        self.assertAlmostEqual(_number(shown["3"]["Band 4 Comp. Ratio"]), 2.0, delta=0.15)


@_goldens.needs("mb-expander-lanes", "mb-expander-lanes-ours", "mb-expander-lanes-resave-logic")
class ExpanderLanesTest(unittest.TestCase):
    def test_a_multipressor_expanders_lanes_reached_the_pro_mb_band_and_logic_named_them(self):
        """Exp. Threshold and Reduction (parameters 27, 26) onto the band's threshold and range
        (28, 29), the threshold on Pro-MB's own curve; Logic kept the points and its Event List
        named them."""
        source, ours, theirs = (_lanes(k, 1) for k in ("mb-expander-lanes", "mb-expander-lanes-ours",
                                                       "mb-expander-lanes-resave-logic"))
        self.assertEqual((sorted(source), sorted(ours)), ([26, 27], [28, 29]))
        self.assertEqual([[t for t, _v in ours[to]] for to in (28, 29)], [[t for t, _v in source[was]] for was in (27, 26)])
        self.assertEqual([round(v, 4) for _t, v in ours[28]], [0.3333, 0.5, 0.1917])       # -40, -30, -50 dB
        self.assertEqual([round(v, 4) for _t, v in ours[29]], [0.3, 0.4])                  # -12, -6 dB
        self.assertEqual(theirs, ours)
        facts = _goldens.entry("mb-expander-lanes-resave-logic")["facts"]
        self.assertEqual({(e["num"], e["name"]) for e in facts["event_list"]}, {(28, "Band 2 Threshold"), (29, "Band 2 Range")})
        self.assertEqual(sorted(e["val"] for e in facts["event_list"]),
                         sorted(round(v * 127) for points in ours.values() for _t, v in points))
        self.assertEqual((facts["shown"]["Band 2 Dynamics Mode"], _number(facts["shown"]["Band 2 Threshold"])), ("Expansion", -40.0))


if __name__ == "__main__":
    unittest.main()
