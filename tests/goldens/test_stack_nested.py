"""A stack made from tracks that already sit inside a folder stack, held to Logic's own Create
Track Stack over two of a folder's three members, of each kind. Skips without the public corpus."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
from logicxkit.logic.services.arrange.environment import PARENT_AT, channel_objects, object_record
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

BASE, FOLDER, SUMMING, TWO = "stack-folder-logic", "nest-inner-folder-logic", "nest-inner-summing-logic", "nest-stack-in-stack-logic"


def rows(data: bytes) -> list[list]:
    """[name, strip class, depth, the strip's stack index] per arrange row."""
    chans = channels(data)
    return [[r["name"], r["label"].split()[0], r["depth"], chans[r["owner"]].stack_index] for r in read_tracks(data)]


def parents(data: bytes) -> dict[str, str | None]:
    records, names = project_records(data), {i: o.name for i, o in channel_objects(data).items()}
    return {r["name"]: names.get(struct.unpack_from("<I", object_record(records, r["object_id"]), HEADER + PARENT_AT)[0])
            for r in read_tracks(data)}


def members(data: bytes, *names: str) -> list[int]:
    objs = {o.name: i for i, o in channel_objects(data).items()}
    return [objs[n] for n in names]


@_goldens.needs(BASE, FOLDER, SUMMING, TWO)
class InnerStackTest(unittest.TestCase):
    def setUp(self):
        self.base = project_data(_goldens.path(BASE))

    def test_a_folder_inside_a_folder_reads_as_logics_own(self):
        logics = project_data(_goldens.path(FOLDER))
        ours, report = create_stack(self.base, name="Sub 2", members=members(self.base, "Audio 2", "Audio 3"))
        self.assertEqual(rows(ours), rows(logics))
        self.assertEqual(rows(logics), [[n, lab.split()[0], d, i] for n, lab, d, i in _goldens.fact(FOLDER, "rows")])
        self.assertEqual(parents(ours)["Sub 2"], None)
        self.assertEqual([(s.name, s.depth, [n for _k, n in s.members]) for s in read_stacks(ours)],
                         [("Sub 1", 0, ["Audio 1", "Sub 2"]), ("Sub 2", 1, ["Audio 2", "Audio 3"])])
        self.assertEqual((validate_project(ours), regressions(self.base, ours)), ([], []))

    def test_a_summing_stack_inside_a_folder_reads_as_logics_own(self):
        logics = project_data(_goldens.path(SUMMING))
        ours, report = create_summing_stack(self.base, name="Sum 1", members=members(self.base, "Audio 2", "Audio 3"))
        self.assertEqual(rows(ours), rows(logics))
        self.assertEqual(rows(logics), [[n, lab.split()[0], d, i] for n, lab, d, i in _goldens.fact(SUMMING, "rows")])
        self.assertEqual(parents(ours), parents(logics))
        self.assertEqual(parents(ours), {"Sub 1": None, "Audio 1": None, "Sum 1": "Sub 1", "Audio 2": "Sum 1",
                                         "Audio 3": "Sum 1", "Stereo Out": None})
        for data in (ours, logics):
            outs, ins = output_labels(data), input_labels(data)
            by_name = {r["name"]: r["owner"] for r in read_tracks(data)}
            self.assertEqual((ins[by_name["Sum 1"]], outs[by_name["Audio 2"]], outs[by_name["Audio 3"]], outs[by_name["Audio 1"]]),
                             ("Bus 1", "Bus 1", "Bus 1", "Output 1-2"))
        self.assertEqual((validate_project(ours), regressions(self.base, ours)), ([], []))

    def test_a_new_sub_strip_carries_the_projects_words(self):
        from logicxkit.logic.services.mixer.channel_alloc import PROJECT_WORDS, project_words
        data = project_data(_goldens.path("markers-edits-resave-logic"))      # +42 is 3 there, 0 on the packaged strip
        out, report = create_stack(data, name="Band", members=members(data, "Audio 1", "Audio 2"))
        strip = max((r.raw for r in project_records(out) if r.tag == b"OCuA" and r.owner == report["owner"]), key=len)
        self.assertEqual({at: struct.unpack_from("<H", strip, HEADER + at)[0] for at in PROJECT_WORDS}, project_words(data))

    def test_members_of_two_stacks_or_two_depths_and_a_header_are_refused(self):
        two = project_data(_goldens.path(TWO))                    # Sub 2 { Sub 1 { Audio 1, Audio 2 }, Audio 3 }
        for names in (("Audio 1", "Audio 3"), ("Sub 1",), ("Sub 1", "Audio 3")):
            for make in (create_stack, create_summing_stack):
                with self.subTest(names, make=make.__name__), self.assertRaisesRegex(ValueError, "one stack|header"):
                    make(two, name="X", members=members(two, *names))


OURS, RESAVE, SOURCE = "nest-inner-stub-ours", "nest-inner-stub-resave-logic", "markers-edits-resave-logic"


def whole(data: bytes) -> dict:
    """Every row, every in-use channel's routing and every stack: what a re-save has to keep."""
    chans, outs, ins = channels(data), output_labels(data), input_labels(data)
    return {"rows": [(r["name"], r["label"], r["owner"], r["depth"]) for r in read_tracks(data)],
            "routes": {c.label: (outs.get(o), ins.get(o), c.stack_index) for o, c in chans.items() if c.in_use},
            "stacks": [[s.name, s.kind, s.strip, [n for _k, n in s.members]] for s in read_stacks(data)]}


@_goldens.needs(OURS, RESAVE, SOURCE)
class LogicResavedNestedTest(unittest.TestCase):
    def setUp(self):
        self.ours, self.logics = (project_data(_goldens.path(k)) for k in (OURS, RESAVE))

    def test_logic_kept_every_row_route_and_stack(self):
        self.assertEqual(whole(self.logics), whole(self.ours))
        self.assertEqual(whole(self.logics)["stacks"], _goldens.fact(RESAVE, "stacks"))
        self.assertEqual((validate_project(self.ours), validate_project(self.logics)), ([], []))

    def test_the_writers_make_the_channel_records_logic_saved(self):
        """The same steps on the source make every in-use strip as Logic's re-save holds it."""
        data = project_data(_goldens.path(SOURCE))
        for name, summing, names in _goldens.fact(OURS, "steps"):
            make = create_summing_stack if summing else create_stack
            data, _report = make(data, name=name, members=members(data, *names))
        self.assertEqual(whole(data), whole(self.logics))

        def strips(d):                                    # each in-use strip less the UUIDs at its end
            return {c.label: max((r.raw for r in project_records(d) if r.tag == b"OCuA" and r.owner == o
                                  and r.key == 0xFFFF), key=len)[HEADER:-48]
                    for o, c in channels(d).items() if c.in_use}
        self.assertEqual(strips(data), strips(self.logics))


if __name__ == "__main__":
    unittest.main()
