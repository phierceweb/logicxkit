"""The three output plug-ins' slider grids against Logic. The raw copy, written with no map
loaded, holds its values as written; Logic's re-save of it lays each on the position the map's
snap picks; a lane written by value lands on the unit and value the map predicts; and the
one-row saves moved to sampled positions. Skips without the public corpus."""

import re
import unittest

import _goldens
from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.plugin_names import PLUGIN_NAMES
from logicxkit.logic.services.mixer.plugin_params import decode, load_tables, table_for
from logicxkit.logic.services.mixer.slider import grid_value, is_linear, linear_unit, point_for, slider_curve, snap
from logicxkit.logic.services.mixer.slot_width import plugin_variant
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.translate.translate import load_maps, map_for
from logicxkit.logicx import project_data

OUT_LABEL = "Output 1-2"            # what the file calls the Stereo Out
TABLES = load_tables()
MAPS = load_maps()
ONE_ROW_KEYS = ("master-lpeq-peak3-q-logic", "master-lpeq-peak3-freq-logic", "master-lpeq-peak3-gain-logic",
                "master-adl-gain-logic", "master-adl-out-ceiling-logic", "master-adl-lookahead-logic",
                "master-lim-gain-logic", "master-lim-output-level-logic", "master-lim-release-logic",
                "master-lim-lookahead-logic")
# Where Logic went up and the snap goes down: a row Logic lays either way (Low Shelf Q), or one whose
# display-rounded samples put the slider's midpoint off the map's (Noise Gate Release).
MIDPOINTS_APART = {("Noise Gate", "Release"), ("Linear Phase EQ", "Low Shelf Q-Factor")}


def _slots(key: str) -> dict[str, tuple[bytes, dict[str, float | str]]]:
    """{plug-in name: (slot payload, {table row: value})} of the facts' channel, in slot order."""
    data = project_data(_goldens.path(key))
    channel = _goldens.fact(key, "channel")
    label = OUT_LABEL if channel == "Stereo Out" else channel
    owner = next(o for o, c in channels(data).items() if c.label == label)
    out = {}
    for r in sorted((r for r in project_records(data) if r.tag == b"UCuA" and r.owner == owner), key=lambda r: r.key):
        payload = r.raw[HEADER:]
        if blocks := find_blocks(payload):
            at, type_id, n = blocks[0]
            table = table_for(TABLES, type_id, plugin_variant(payload))
            out[PLUGIN_NAMES[type_id]] = (payload, decode(table, read_block_floats(payload, at, n)))
    return out


def _values(key: str) -> dict[str, dict[str, float | str]]:
    return {plugin: values for plugin, (_payload, values) in _slots(key).items()}


def _number(shown: str) -> float:
    """A Controls display as a number: `+1.5 dB` 1.5, `2.00 kHz` 2000, `52 ms` 52, `1.2 s` 1200."""
    m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(kHz|Hz|dB|ms|s)?", shown.strip().replace("−", "-"))
    if not m:
        raise ValueError(f"unreadable display {shown!r}")
    return float(m.group(1)) * (1000 if m.group(2) in ("kHz", "s") else 1)      # every time row here counts in ms


def _row(m, parameter: str) -> str:
    """The map's row for a fact's parameter name: itself, or the one row that starts with it."""
    rows = list(m.raw["automation"])
    if parameter in rows:
        return parameter
    (found,) = [r for r in rows if r.startswith(parameter)]
    return found


@_goldens.needs("slider-snap-raw")
class RawCopyTest(unittest.TestCase):
    def test_the_raw_copy_holds_every_value_as_written(self):
        values = _values("slider-snap-raw")
        written = _goldens.fact("slider-snap-raw", "written")
        self.assertEqual(list(values), list(written))
        for plugin, rows in written.items():
            for row, value in rows.items():
                with self.subTest(plugin=plugin, row=row):
                    self.assertAlmostEqual(values[plugin][row], value, places=4)


@_goldens.needs(*ONE_ROW_KEYS)
class OneUnitTest(unittest.TestCase):
    """Each one-row save moved a slider one unit: the display before and after are both sampled
    positions of the map's row, and the float the save holds is the one after."""

    def test_before_and_after_are_sampled_positions(self):
        for key in ONE_ROW_KEYS:
            plugin, parameter = _goldens.fact(key, "plugin"), _goldens.fact(key, "parameter")
            payload, values = _slots(key)[plugin]
            m = map_for(payload, MAPS)
            row = _row(m, parameter)
            with self.subTest(key=key, row=row):
                before, after = _number(_goldens.fact(key, "before")), _number(_goldens.fact(key, "after"))
                self.assertEqual(snap(m, row, before), before)
                self.assertEqual(snap(m, row, after), after)
                self.assertAlmostEqual(values[row], after, places=4)
                self.assertAlmostEqual(_goldens.fact(key, "value"), after, places=4)


@_goldens.needs("slider-snap-raw", "slider-snap-raw-resave-logic")
class SnapResaveTest(unittest.TestCase):
    """Logic's re-save of the raw copy lays every value on the position the snap picks, and the
    Controls view showed that position before the save."""

    def test_logic_keeps_what_the_snap_picks(self):
        written = _goldens.fact("slider-snap-raw", "written")
        kept, shown = _goldens.fact("slider-snap-raw-resave-logic", "kept"), _goldens.fact("slider-snap-raw-resave-logic", "shown")
        slots = _slots("slider-snap-raw-resave-logic")
        self.assertEqual(list(slots), list(written))
        for plugin, rows in written.items():
            payload, values = slots[plugin]
            m = map_for(payload, MAPS)
            for row, raw in rows.items():
                with self.subTest(plugin=plugin, row=row):
                    self.assertAlmostEqual(values[row], kept[plugin][row], places=4)
                    self.assertAlmostEqual(kept[plugin][row], snap(m, row, raw), places=3)
                    self.assertAlmostEqual(_number(shown[plugin][row]), kept[plugin][row], places=2)
                    self.assertNotAlmostEqual(kept[plugin][row], raw, places=3)


@_goldens.needs("slider-lanes-ours")
class LanesTest(unittest.TestCase):
    """A lane written by value lands on the unit and value `point_for` predicts, and Logic's
    Controls view at that bar shows the landed value."""

    def test_each_lane_lands_where_the_map_predicts(self):
        """The unit and value `point_for` predicts for the value written, and Logic's display of the
        stored point at that bar: the display is the measurement, the unit the pin."""
        slots = _slots("slider-lanes-ours")
        for lane in _goldens.fact("slider-lanes-ours", "lanes"):
            m = map_for(slots[lane["plugin"]][0], MAPS)
            with self.subTest(plugin=lane["plugin"], row=lane["row"], bar=lane["bar"]):
                _point, unit, landed, _sampled = point_for(m, lane["row"], lane["value"])
                self.assertEqual((unit, landed), (lane["unit"], lane["landed"]))
                self.assertAlmostEqual(_number(lane["shown"]), landed, places=2)


@_goldens.needs("slider-midpoints-raw", "slider-midpoints-resave-logic")
class MidpointsTest(unittest.TestCase):
    """Values written exactly midway between two positions of knob-shaped rows: Logic lays each on
    one of the two, the side set by the row's taper."""

    def test_each_midpoint_lands_on_a_neighbour_and_the_facts_are_the_files(self):
        written = _goldens.fact("slider-midpoints-raw", "written")
        kept = _goldens.fact("slider-midpoints-resave-logic", "kept")
        raw, resaved = _slots("slider-midpoints-raw"), _slots("slider-midpoints-resave-logic")
        self.assertEqual(list(raw), list(written))
        up = down = 0
        apart = set()
        for plugin, rows in written.items():
            m = map_for(raw[plugin][0], MAPS)
            for row, v in rows.items():
                with self.subTest(plugin=plugin, row=row):
                    curve = slider_curve(m, row)
                    below, above = max(p for p in curve if p[1] < v), min(p for p in curve if p[1] > v)
                    self.assertEqual(above[0] - below[0], 1)
                    self.assertAlmostEqual(v - below[1], above[1] - v, places=4)
                    self.assertAlmostEqual(raw[plugin][1][row], v, places=4)
                    self.assertAlmostEqual(resaved[plugin][1][row], kept[plugin][row], places=4)
                    gap_down, gap_up = abs(kept[plugin][row] - below[1]), abs(above[1] - kept[plugin][row])
                    self.assertLess(min(gap_down, gap_up), 0.01)        # the Noise Gate's release positions are not round numbers
                    self.assertFalse(is_linear(curve))
                    up += gap_up < gap_down
                    down += gap_down < gap_up
                    landed = grid_value(m, row, v)[0]
                    self.assertIn(landed, (below[1], above[1]))
                    if abs(landed - kept[plugin][row]) > 0.01:
                        apart.add((plugin, row))
        self.assertEqual((up, down), (8, 10))
        self.assertEqual(apart, MIDPOINTS_APART)


TIE_KEYS = [(f"slider-ties{k}-raw", f"slider-ties{k}-resave-logic") for k in (1, 2, 3)] + [("slider-siblings-raw", "slider-siblings-resave-logic")]
# Where Logic went up and the snap goes down: rows Logic lays either way, and the Multipressor's band 1
# ratio, whose one true midpoint here Logic laid up (its samples are display-rounded).
TIES_APART = {("Compressor", "Ratio", 1.45), ("Linear Phase EQ", "Low Cut Q-Factor", 0.305),
              ("Linear Phase EQ", "Peak 3 Q-Factor", 0.305), ("Linear Phase EQ", "Low Shelf Q-Factor", 0.435),
              ("Multipressor", "Band 1 Comp. Ratio", 21.5625)}


@_goldens.needs(*[k for pair in TIE_KEYS for k in pair])
class TiesTest(unittest.TestCase):
    """Three more midpoints on each row `MidpointsTest` measured, and one on every row sharing a tied
    row's curve: the snap lands each on the side Logic laid it, the row's `tie` deciding, but on the
    rows Logic lays either way and where the map's samples are display-rounded."""

    def test_the_snap_takes_logics_side_but_on_the_mixed_rows(self):
        apart = set()
        for raw_key, resave_key in TIE_KEYS:
            written, kept = _goldens.fact(raw_key, "written"), _goldens.fact(resave_key, "kept")
            raw, resaved = _slots(raw_key), _slots(resave_key)
            for plugin, rows in written.items():
                m = map_for(raw[plugin][0], MAPS)
                for row, v in rows.items():
                    with self.subTest(key=raw_key, plugin=plugin, row=row):
                        self.assertAlmostEqual(raw[plugin][1][row], v, places=4)
                        self.assertAlmostEqual(resaved[plugin][1][row], kept[plugin][row], places=4)
                        curve = slider_curve(m, row)
                        below, above = max(p for p in curve if p[1] < v), min(p for p in curve if p[1] > v)
                        self.assertAlmostEqual(v - below[1], above[1] - v, places=4)
                        landed, logics = grid_value(m, row, v)[0], kept[plugin][row]
                        self.assertIn(landed, (below[1], above[1]))
                        if (abs(landed - above[1]) < abs(landed - below[1])) != (abs(logics - above[1]) < abs(logics - below[1])):
                            apart.add((plugin, row, v))
        self.assertEqual(apart, TIES_APART)


@_goldens.needs("slider-linear-raw", "slider-linear-resave-logic")
class LinearUnitsTest(unittest.TestCase):
    """Values written between the samples of linear rows (dB and ms rows sampled every few units),
    some at midpoints of unsampled units, one on an unsampled unit: Logic lays each on the unit
    `linear_unit` gives, so the snap predicts the kept value on every mapped row."""

    def test_logic_keeps_the_units_the_snap_predicts(self):
        written = _goldens.fact("slider-linear-raw", "written")
        kept = _goldens.fact("slider-linear-resave-logic", "kept")
        raw, resaved = _slots("slider-linear-raw"), _slots("slider-linear-resave-logic")
        self.assertEqual(list(raw), list(written))
        predicted = 0
        for plugin, rows in written.items():
            m = map_for(raw[plugin][0], MAPS)
            for row, v in rows.items():
                with self.subTest(plugin=plugin, row=row):
                    self.assertAlmostEqual(raw[plugin][1][row], v, places=4)
                    self.assertAlmostEqual(resaved[plugin][1][row], kept[plugin][row], places=4)
                    curve = slider_curve(m, row)
                    if curve is None:                                 # Channel EQ's Master Gain: unmapped, Logic lays it alone
                        continue
                    self.assertTrue(is_linear(curve))
                    self.assertFalse(any(u == linear_unit(curve, v) for u, _value in curve), "the unit was sampled: not this test's case")
                    self.assertAlmostEqual(kept[plugin][row], snap(m, row, v), places=3)   # on a unit: 50.5 stays, 0.85 goes to 0.9
                    self.assertAlmostEqual(kept[plugin][row], grid_value(m, row, v)[0], places=3)   # the `--set` and chains path
                    predicted += 1
        self.assertGreaterEqual(predicted, 8)


if __name__ == "__main__":
    unittest.main()
