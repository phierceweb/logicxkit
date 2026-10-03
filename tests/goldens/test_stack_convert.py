"""A folder stack converted to a summing stack here, held to Logic 12.4's own Track > Convert
Folder Stack to Summing Stack on the same project: the folder's header object replaced by a
summing header on the lowest free `Aux` fed from a free bus, the `Sub` strip left out of use, the
members routed to the bus under the new header with stack index 0. Skips without the public
corpus."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
from logicxkit.logic.services.arrange.environment import PARENT_AT, channel_objects, object_record
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.stream.sequence import index_table, table_entries
from logicxkit.logic.services.arrange.stack_convert import convert_to_summing
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.arrange.tracklist import arrange_run, flat_run, row_object
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

FOLDER, CONVERTED = "stack-folder-logic", "stack-converted-to-summing-logic"
WATCHED = ("Audio 1", "Audio 2", "Audio 3", "Aux 1", "Sub 1", "Bus 1")


def shape(data: bytes) -> dict:
    """What the convert leaves, less what Logic re-lays on save (table indices) and its own
    channel stamp: the rows, the live objects and their parents, the strips' use and routing,
    the flat rows that still name an object, the table's object ids."""
    records, chans, objs = project_records(data), channels(data), channel_objects(data)
    outs, ins = output_labels(data), input_labels(data)
    run = arrange_run(records)
    return {"rows": [(r["name"], r["label"], r["depth"]) for r in read_tracks(data)],
            "objects": sorted(o.name for o in objs.values()),
            "parents": {o.name: struct.unpack_from("<I", object_record(records, i), HEADER + PARENT_AT)[0]
                        for i, o in objs.items() if o.name.startswith(("Audio", "Sum"))},
            "strips": {c.label: (c.in_use, c.stack_index, outs.get(o), ins.get(o), c.words)
                       for o, c in chans.items() if c.label in WATCHED},
            "flat": [objs[row_object(records[i].raw)].name for i in flat_run(records, run) if row_object(records[i].raw) in objs],
            "table": sorted(e[1] for e in table_entries(records[index_table(records)].raw[HEADER:])),
            "stacks": [(s.name, s.kind, s.strip, [n for _k, n in s.members]) for s in read_stacks(data)]}


@_goldens.needs(FOLDER, CONVERTED)
class ConvertTest(unittest.TestCase):
    def setUp(self):
        self.base = project_data(_goldens.path(FOLDER))
        (stack,) = read_stacks(self.base)
        self.ours, self.report = convert_to_summing(self.base, stack.object_id)

    def test_it_reads_as_logics_own_convert_does(self):
        logics = project_data(_goldens.path(CONVERTED))
        self.assertEqual(shape(self.ours), shape(logics))
        name, strip, bus = _goldens.fact(CONVERTED, "header")
        self.assertEqual(shape(logics)["stacks"], [(name, "summing", strip, _goldens.fact(CONVERTED, "members"))])
        self.assertEqual((self.report["bus"], shape(logics)["strips"]["Sub 1"][0]), (bus, _goldens.fact(CONVERTED, "sub_1_in_use")))
        self.assertEqual((validate_project(self.ours), regressions(self.base, self.ours)), ([], []))

    def test_the_report_names_the_new_header(self):
        self.assertEqual((self.report["label"], self.report["bus"], self.report["name"]), ("Aux 1", "Bus 1", "Sum 1"))

    def test_a_summing_stack_or_no_stack_is_refused(self):
        objs = {o.name: i for i, o in channel_objects(self.base).items()}
        with self.assertRaisesRegex(ValueError, "not a stack"):
            convert_to_summing(self.base, objs["Audio 1"])
        (made,) = read_stacks(self.ours)
        with self.assertRaisesRegex(ValueError, "already a summing stack"):
            convert_to_summing(self.ours, made.object_id)


VCA, VCA_CONVERTED = "stack-convert-lane-before-logic", "stack-convert-lane-after-logic"
LEVEL, LEVEL_CONVERTED = "stack-convert-level-before-logic", "stack-convert-level-after-logic"
BAR_ONE, BAR = 38400, 3840                         # ticks at bar 1, and a 4/4 bar


def lanes(data: bytes) -> list:
    return sorted((a.track or "", ln.parameter, tuple((p.tick, p.value) for p in ln.points))
                  for a in read_automation(data) for ln in a.lanes)


@_goldens.needs(VCA, VCA_CONVERTED)
class VcaLaneTest(unittest.TestCase):
    """A folder with a Volume lane on its main track: Logic's convert moved the lane onto the new
    header byte for byte and left the folder's automation folder empty."""

    def test_the_lane_moves_as_logic_moved_it(self):
        base = project_data(_goldens.path(VCA))
        (stack,) = read_stacks(base)
        ours, _report = convert_to_summing(base, stack.object_id)
        logics = project_data(_goldens.path(VCA_CONVERTED))
        self.assertEqual((shape(ours), lanes(ours)), (shape(logics), lanes(logics)))
        track, lane, points = _goldens.fact(VCA_CONVERTED, "lane")
        self.assertEqual(lanes(logics), [(track, lane, tuple((BAR_ONE + (b - 1) * BAR, float(v)) for b, v in points))])
        self.assertEqual((validate_project(ours), regressions(base, ours)), ([], []))


@_goldens.needs(LEVEL, LEVEL_CONVERTED)
class LevelLeftTest(unittest.TestCase):
    """A folder at -10 dB: Logic's convert left the level on the `Sub` strip it took out of use
    and put the aux at 0 dB."""

    def test_the_level_stays_on_the_sub_as_logic_left_it(self):
        from logicxkit.logic.services.mixer.levels import read_levels
        base = project_data(_goldens.path(LEVEL))
        (stack,) = read_stacks(base)
        ours, report = convert_to_summing(base, stack.object_id)
        logics = project_data(_goldens.path(LEVEL_CONVERTED))
        self.assertEqual(shape(ours), shape(logics))

        def faders(data):
            return {c.label: round(read_levels(data)[o]["fader_db"], 1) for o, c in channels(data).items()
                    if c.label in _goldens.fact(LEVEL_CONVERTED, "faders")}
        self.assertEqual(faders(ours), faders(logics))
        self.assertEqual(faders(logics), _goldens.fact(LEVEL_CONVERTED, "faders"))
        self.assertEqual(round(report["level_left"], 1), _goldens.fact(LEVEL, "faders")["Sub 1"])
        self.assertEqual((validate_project(ours), regressions(base, ours)), ([], []))


NESTED = {"wrapped": "Sub 1", "inner": "Sub 2"}     # the folder converted inside the other


def every_channel(data: bytes) -> dict:
    outs, ins = output_labels(data), input_labels(data)
    return {(c.owner, c.label): (c.in_use, c.stack_index, outs.get(o), ins.get(o), c.words)
            for o, c in channels(data).items()}


@_goldens.needs(*(f"nest-convert-{tag}-{side}-logic" for tag in NESTED for side in ("before", "after")))
class NestedConvertTest(unittest.TestCase):
    """A folder inside another folder, its strip on the outer number (`wrapped`) or at 0
    (`inner`): Logic's convert put the members and the new aux at stack index 0 and the header
    under the outer folder, and so does ours, channel for channel."""

    def test_each_converts_as_logic_converted_it(self):
        for tag, folder in NESTED.items():
            with self.subTest(tag):
                before, after = f"nest-convert-{tag}-before-logic", f"nest-convert-{tag}-after-logic"
                base, logics = project_data(_goldens.path(before)), project_data(_goldens.path(after))
                stack = next(s for s in read_stacks(base) if s.name == folder)
                ours, report = convert_to_summing(base, stack.object_id)
                self.assertEqual((shape(ours), every_channel(ours)), (shape(logics), every_channel(logics)))
                self.assertEqual(shape(logics)["stacks"], [(n, "summing" if s.startswith("Aux") else "folder", s, m)
                                                           for n, s, m in _goldens.fact(after, "stacks")])
                indices = {c.label: c.stack_index for c in channels(logics).values() if c.in_use}
                self.assertEqual({k: indices[k] for k in _goldens.fact(after, "stack_index")},
                                 _goldens.fact(after, "stack_index"))
                self.assertEqual(report["bus"], _goldens.fact(after, "bus"))
                self.assertEqual((validate_project(ours), regressions(base, ours)), ([], []))


OURS, RESAVE = "stack-convert-ours", "stack-convert-resave-logic"


@_goldens.needs(OURS, RESAVE)
class LogicResavedConvertTest(unittest.TestCase):
    def test_logic_kept_the_summing_stack_as_written(self):
        """Logic re-lays the index table on any save (the folder header's orphan entry gone, the
        Master's added), so that is left out; the rows, objects, routing and strips are held."""
        a, b = project_data(_goldens.path(OURS)), project_data(_goldens.path(RESAVE))
        self.assertEqual({k: v for k, v in shape(b).items() if k != "table"},
                         {k: v for k, v in shape(a).items() if k != "table"})
        self.assertEqual(shape(b)["stacks"], [(n, "summing", s, m) for n, s, _bus, m in _goldens.fact(RESAVE, "stacks")])
        self.assertEqual((validate_project(a), validate_project(b)), ([], []))


if __name__ == "__main__":
    unittest.main()
