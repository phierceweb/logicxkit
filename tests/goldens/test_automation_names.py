"""A parameter lane's plug-in, name and values held to what Logic showed: the Automation Event
List's name for each index, and the Controls view's value at each point's bar. Skips without the
public corpus."""

import re
import unittest

import _goldens
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logic.services.regions.automation_names import lane_target
from logicxkit.logic.services.mixer.binding import bound_channels
from logicxkit.logic.services.song.events import BAR_ONE, PPQ
from logicxkit.logicx import project_data

RESAVES = ("auto-lanes-resave-logic", "auto-eqlanes-resave-logic", "auto-mblanes-resave-logic")


def number(text: str) -> float:
    return float(re.match(r"[+-]?\d+(\.\d+)?", text).group())


def targets(key: str) -> dict[int, tuple]:
    """parameter index -> (target, points) for the lanes on the golden's channel and slot."""
    path = _goldens.path(key)
    data = project_data(path)
    out = {}
    for a in read_automation(data):
        owner = bound_channels(data).get(a.track_object)
        for ln in a.lanes:
            if ln.slot == _goldens.fact(key, "slot") and owner is not None:
                out[ln.param_index] = (lane_target(data, owner, ln.slot, ln.param_index), ln.points)
    return out


@unittest.skipUnless(all(_goldens.path(k) for k in (*RESAVES, "auto-lanes")), "public corpus not present")
class NamedByLogicTest(unittest.TestCase):
    def test_each_index_takes_the_name_the_event_list_gave_it(self):
        for key in RESAVES:
            with self.subTest(key):
                read = targets(key)
                listed = {r["num"]: r["name"] for r in _goldens.fact(key, "event_list")}
                self.assertEqual({i: t.name for i, (t, _p) in read.items()}, listed)
                self.assertEqual({t.plugin for t, _p in read.values()}, {_goldens.fact(key, "plugin")})

    def test_each_point_reads_as_the_value_the_controls_view_showed_at_its_bar(self):
        for key in RESAVES:
            shown = _goldens.fact(key, "shown")
            for target, points in targets(key).values():
                for p in points:
                    bar = str((p.tick - BAR_ONE) // (4 * PPQ) + 1)
                    with self.subTest(key, name=target.name, bar=bar):
                        want, got = number(shown[bar][target.name]), target.value(p.value)
                        self.assertAlmostEqual(float(got), want, delta=0.05 if want < 100 else 0.5)

    def test_a_third_partys_lanes_are_named_by_its_au_table_or_its_map(self):
        """The AU table's spelling where the data root holds one, else the map's vocabulary."""
        read = targets("auto-lanes")
        self.assertEqual({i: t.name.lower() for i, (t, _p) in read.items()},
                         {1: "threshold", 2: "ratio", 5: "attack", 8: "lookahead"})
        self.assertEqual({t.plugin for t, _p in read.values()}, {"Pro-C 2"})
        threshold, points = read[1]
        self.assertEqual([round(threshold.value(p.value), 2) for p in points], [-30.0, -24.0, -12.0])

    def test_an_insert_holding_no_plug_in_names_nothing(self):
        data = project_data(_goldens.path("auto-lanes"))
        owner = bound_channels(data)[next(a.track_object for a in read_automation(data) if a.lanes)]
        self.assertIsNone(lane_target(data, owner, 9, 1))
        unnamed = lane_target(data, owner, 3, 9999)
        self.assertEqual((unnamed.plugin, unnamed.name, unnamed.value(0.5)), ("Pro-C 2", None, None))


if __name__ == "__main__":
    unittest.main()
