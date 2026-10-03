"""A stack flattened here, held to Logic's own Flatten Stack on the same project (folder, summing,
and a folder inside a folder): the header's arrange row goes, its members come up a level with
their parents cleared, the header object, its strip and the members' stack indices stay. Skips
without the corpus."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.mixer.binding import channels, output_labels
from logicxkit.logic.services.arrange.environment import PARENT_AT, channel_objects, object_record
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.arrange.stack_moves import flatten_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

FOLDER, FOLDER_FLAT = "stack-folder-logic", "stack-folder-flattened-logic"
SUMMING, SUMMING_FLAT = "stack-summing-logic", "stack-summing-flattened-logic"


def shape(data: bytes) -> dict:
    """What a flatten leaves: the rows, each track's parent and strip, every strip's use."""
    records, chans = project_records(data), channels(data)
    objs, outs = channel_objects(data), output_labels(data)
    return {"rows": [(r["name"], r["label"], r["depth"], r["expanded"]) for r in read_tracks(data)],
            "parents": {o.name: struct.unpack_from("<I", object_record(records, i), HEADER + PARENT_AT)[0]
                        for i, o in objs.items()},
            "strips": {c.label: (c.in_use, c.size, c.stack_index, outs.get(o)) for o, c in chans.items() if c.in_use},
            "selected": sorted(o.name for i, o in objs.items() if object_record(records, i)[HEADER + 80]),
            "stacks": [s.name for s in read_stacks(data)]}


@_goldens.needs(FOLDER, FOLDER_FLAT, SUMMING, SUMMING_FLAT)
class FlattenTest(unittest.TestCase):
    def _flatten(self, key: str) -> tuple[bytes, bytes]:
        base = project_data(_goldens.path(key))
        (stack,) = read_stacks(base)
        return base, flatten_stack(base, stack.object_id)

    def test_a_folder_stack_flattens_as_logics_own(self):
        base, ours = self._flatten(FOLDER)
        self.assertEqual(shape(ours), shape(project_data(_goldens.path(FOLDER_FLAT))))
        self.assertEqual((validate_project(ours), regressions(base, ours)), ([], []))

    def test_a_summing_stack_flattens_as_logics_own(self):
        base, ours = self._flatten(SUMMING)
        self.assertEqual(shape(ours), shape(project_data(_goldens.path(SUMMING_FLAT))))
        self.assertEqual((validate_project(ours), regressions(base, ours)), ([], []))

    def test_a_track_that_is_no_stack_is_refused(self):
        base = project_data(_goldens.path(FOLDER))
        objs = {o.name: i for i, o in channel_objects(base).items()}
        with self.assertRaisesRegex(ValueError, "not a stack"):
            flatten_stack(base, objs["Audio 1"])


NEST, NEST_FLAT = "nest-flatten-before-logic", "nest-flatten-after-logic"


@_goldens.needs(NEST, NEST_FLAT)
class NestedFlattenTest(unittest.TestCase):
    """A folder inside a folder flattened: its member comes up into the outer folder with its parent
    cleared, not set to the outer header, and its channel keeps the inner folder's stack index."""

    def test_an_inner_folder_flattens_as_logics_own(self):
        base = project_data(_goldens.path(NEST))
        inner = next(s for s in read_stacks(base) if s.name == "E")
        ours = flatten_stack(base, inner.object_id)
        logics = project_data(_goldens.path(NEST_FLAT))
        self.assertEqual(shape(ours), shape(logics))
        self.assertEqual(shape(logics)["parents"]["Audio 2"], _goldens.fact(NEST_FLAT, "parents")["Audio 2"])
        self.assertEqual(shape(logics)["strips"]["Audio 2"][2], _goldens.fact(NEST_FLAT, "stack_index")["Audio 2"])
        self.assertEqual((validate_project(ours), regressions(base, ours)), ([], []))


RESAVES = (("stack-folder-flatten-ours", "stack-folder-flatten-resave-logic"),
           ("stack-summing-flatten-ours", "stack-summing-flatten-resave-logic"))


@_goldens.needs(*(k for pair in RESAVES for k in pair))
class LogicResavedFlattenTest(unittest.TestCase):
    def test_logic_kept_every_row_parent_and_strip(self):
        def kept(data):                                   # a re-save re-lays a record's size; its use and routing stay
            s = shape(data)
            return {**s, "strips": {k: (v[0], v[2], v[3]) for k, v in s["strips"].items()}}
        for ours, logics in RESAVES:
            with self.subTest(ours):
                a, b = project_data(_goldens.path(ours)), project_data(_goldens.path(logics))
                self.assertEqual(kept(b), kept(a))
                self.assertEqual([r[0] for r in shape(b)["rows"]], _goldens.fact(logics, "rows"))
                self.assertEqual((validate_project(a), validate_project(b)), ([], []))


if __name__ == "__main__":
    unittest.main()
