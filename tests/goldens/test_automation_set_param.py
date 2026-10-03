"""`automation --set "TRACK:slot N NAME=V@BAR"` on a public project: a Compressor's threshold onto
its slider units, a switch, a Noise Gate's hold, a Pro-C 2's threshold as its AU range's fraction.
Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic._automation_cmd import _apply
from logicxkit.logic._edit import CommandError
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logic.services.song.signature import meter
from logicxkit.logicx import project_data


def _lanes(data: bytes, track: str) -> dict[str, list[tuple[float, float]]]:
    out = {}
    for a in read_automation(data):
        if a.track == track:
            for lane in a.lanes:
                out[lane.parameter] = [(p.tick, round(p.value, 4)) for p in lane.points]
    return out


@_goldens.needs("snap-ours")
class SetParamLaneTest(unittest.TestCase):
    def setUp(self):
        self.data = project_data(_goldens.path("snap-ours"))
        self.bars = meter(self.data)

    def test_a_native_lane_lands_on_slider_units_and_a_third_party_on_its_range(self):
        data, line = _apply(self.data, None, "set", "Audio 2:slot 1 Threshold=-30@1,-24@5,-12@9", self.bars)
        self.assertEqual(line, "Audio 2: slot 1 Compressor Threshold = -30@1,-24@5,-12@9 -> -30 (unit 40), -24 (unit 52), -12 (unit 76)")
        data, _l = _apply(data, None, "set", "Audio 2:slot 1 Auto Release=on@1,off@5", self.bars)
        data, line = _apply(data, None, "set", "Audio 2:slot 3 Threshold=-20@1,-10@5", self.bars)
        self.assertEqual(line, "Audio 2: slot 3 FabF/FC2p Threshold = -20@1,-10@5 -> -20, -10")
        _d, line = _apply(data, None, "set", "Audio 2:slot 1 Threshold=-46.3@1", self.bars)
        self.assertTrue(line.endswith("-> -46.5 (unit 7)"), line)                       # a linear row: exact though unread
        lanes = _lanes(data, "Audio 2")
        self.assertEqual(lanes["insert 1 parameter 0"], [(self.bars.tick(1), round(40.5 / 128, 4)), (self.bars.tick(5), round(52.5 / 128, 4)),
                                                        (self.bars.tick(9), round(76.5 / 128, 4))])
        self.assertEqual(lanes["insert 1 parameter 13"], [(self.bars.tick(1), 1.0), (self.bars.tick(5), 0.0)])
        self.assertEqual(lanes["insert 3 parameter 1"], [(self.bars.tick(1), 0.6667), (self.bars.tick(5), 0.8333)])
        data, line = _apply(data, None, "clear", "Audio 2:slot 3 Threshold", self.bars)
        self.assertNotIn("insert 3 parameter 1", _lanes(data, "Audio 2"))

    def test_what_is_refused(self):
        for spec, why in (("Audio 2:slot 1 Wetness=1@1", "no measured parameter 'Wetness'"),
                          ("Audio 2:slot 1 Threshold=on@1", "not a switch"),
                          ("Audio 2:slot 1 Threshold=-30@1,-12@1", "two points at tick"),
                          ("Audio 2:slot 9 Threshold=1@1", "slot 9 holds no plug-in"),
                          ("Audio 2:slot 3 Threshold=5@1", "outside -60..0"),
                          ("Audio 2:slot 3 Wetness=1@1", "no parameter 'Wetness'"),
                          ("Audio 2:slot 1 Threshold=nan@1", "finite"),
                          ("Audio 2:slot 1 Threshold=inf@1", "finite"),
                          ("Audio 2:slot 3 Threshold=-inf@1", "finite"),
                          ("Audio 2:slot 1 Threshold=-30@inf", "finite"),
                          ("Audio 2:Volume=90@inf", "finite")):
            with self.subTest(spec), self.assertRaises(CommandError) as e:
                _apply(self.data, None, "set", spec, self.bars)
            self.assertIn(why, str(e.exception))

    def test_a_native_value_past_its_slider_is_held_there_with_a_note(self):
        _d, line = _apply(self.data, None, "set", "Audio 2:slot 1 Threshold=999@1,-999@5", self.bars)
        self.assertEqual(line, "Audio 2: slot 1 Compressor Threshold = 999@1,-999@5 -> 0 (unit 100; the slider runs -50..0), "
                               "-50 (unit 0; the slider runs -50..0)")


@_goldens.needs("audio-one-region-logic")
class NamedTrackTest(unittest.TestCase):
    """A track called by its own name, not its channel's label: `Untitled` on Inst 1, whose slot 1
    is its instrument and slot 2 the Compressor put there."""

    def test_a_named_tracks_lane_lands_on_its_channels_insert(self):
        from logicxkit.logic._edit import owner_by_label
        from logicxkit.logic.services.mixer.add_plugin import add_plugin
        from logicxkit.logic.services.mixer.plugin_library import find_donor, load_library
        from logicxkit.logic.services.mixer.transplant import slot_class_version
        from logicxkit.utils.data import PACKAGED
        data = project_data(_goldens.path("audio-one-region-logic"))
        comp = find_donor(load_library([PACKAGED / "donors"]), "Compressor", width=None, version=slot_class_version(data))
        data, _r = add_plugin(data, owner_by_label(data, "Inst 1"), comp.raw, type_id=comp.type_id)
        data, line = _apply(data, None, "set", "Untitled:slot 2 Threshold=-20@1", meter(data))
        self.assertIn("slot 2 Compressor Threshold", line)
        self.assertIn("insert 2 parameter 0", _lanes(data, "Untitled"))


@_goldens.needs("master-track-limiter-logic")
class EmptySlotsCountTest(unittest.TestCase):
    """Audio 1's chain starts at slot 5 (slots 1-4 empty): its Multipressor is slot 6, insert 6."""

    def test_the_lane_carries_the_mixer_slot(self):
        data = project_data(_goldens.path("master-track-limiter-logic"))
        data, line = _apply(data, None, "set", "Audio 1:slot 6 Band 1 Comp. Threshold=-20@1", meter(data))
        self.assertIn("slot 6 Multipressor", line)
        self.assertIn("insert 6 parameter", " ".join(_lanes(data, "Audio 1")))
        with self.assertRaises(CommandError) as e:
            _apply(data, None, "set", "Audio 1:slot 2 Threshold=-20@1", meter(data))
        self.assertIn("slot(s) 5, 6, 7, 8", str(e.exception))


@_goldens.needs("autoset-ours", "autoset-resave-logic")
class LogicShowedTest(unittest.TestCase):
    def test_the_event_list_named_every_lane_on_the_written_units(self):
        facts = _goldens.entry("autoset-resave-logic")["facts"]
        rows = {(r["bar"], r["ch"], r["num"]): (r["name"], r["val"]) for r in facts["shown"]}
        self.assertEqual(rows[(1, 2, 0)], ("Threshold", 40))                 # insert 1's Compressor: ch 2 = slot 1
        self.assertEqual([rows[(b, 2, 0)][1] for b in (1, 5, 9)], [40, 52, 76])
        self.assertEqual([rows[(b, 2, 13)] for b in (1, 5)], [("Auto Release", 127), ("Auto Release", 0)])
        self.assertEqual([rows[(b, 3, 4)] for b in (1, 5)], [("Hold", 25), ("Hold", 20)])
        self.assertEqual([rows[(b, 4, 1)] for b in (1, 5)], [("Threshold", 85), ("Threshold", 106)])   # 0.6667 and 0.8333 of 128
        ours = _lanes(project_data(_goldens.path("autoset-ours")), "Audio 2")
        theirs = _lanes(project_data(_goldens.path("autoset-resave-logic")), "Audio 2")
        self.assertEqual(ours, theirs)                                        # Logic kept the points as written


@_goldens.needs("autoset-mb-ours", "autoset-mb-resave-logic")
class MultipressorRowsTest(unittest.TestCase):
    """The rows the Controls view lists without a band name, on their measured sliders."""

    def test_the_written_units_are_what_logic_showed(self):
        from logicxkit.logic.services.mixer.slider import units_at
        from logicxkit.logic.services.translate.translate import load_maps
        from logicxkit.utils.data import PACKAGED
        mb = next(m for m in load_maps([PACKAGED / "translate"]) if m.plugin == "Multipressor")
        ours = _lanes(project_data(_goldens.path("autoset-mb-ours")), "Audio 3")
        shown = _goldens.entry("autoset-mb-resave-logic")["facts"]["shown"]
        bars = meter(project_data(_goldens.path("autoset-mb-ours")))
        for name, index in (("Band 1 Exp. Threshold", 38), ("Band 1 Reduction", 37), ("Band 1 Response", 36)):
            table = mb.raw["automation"][name]
            points = dict(ours[f"insert 1 parameter {index}"])
            for bar, (_display, units) in shown[name].items():
                with self.subTest(name=name, bar=bar):
                    value = points.get(bars.tick(float(bar)), points[bars.tick(1.0)])          # a lane holds its last point
                    self.assertEqual(units_at(value, table["per"], 0.0, table["units"][-1][0]), units)
        self.assertEqual(ours, _lanes(project_data(_goldens.path("autoset-mb-resave-logic")), "Audio 3"))


if __name__ == "__main__":
    unittest.main()
