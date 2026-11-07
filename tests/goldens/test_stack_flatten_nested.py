"""Flattening a stack that sits inside another: Logic's own Flatten Stack against `stacks --flatten`
on the save before it, row by row. The freed members take the flattened header's own parent (Sum 2's
header when a summing stack inside Sum 2 is flattened, none under a folder), come up a level, and
every one of them is left selected."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.arrange.environment import PARENT_AT, object_id_of
from logicxkit.logic.services.arrange.stack_moves import flatten_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.arrange.tracklist import EXPANDED_AT, MEMBER_AT, arrange_run, row_object
from logicxkit.logic.services.mixer.binding import output_labels
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

PAIRS = (("nest-flatten-before-logic", "E", "nest-flatten-after-logic"),
         ("stack-out-of-folder-before-logic", "F", "stack-flatten-in-summing-after-logic"),
         ("stack-summing-around-summing-after-logic", "Sum 1", "stack-flatten-inner-summing-after-logic"))


def rows(data: bytes) -> list[tuple]:
    """(name, depth, the row's +40 flags, the object's parent) per arrange row."""
    records = project_records(data)
    parents = {object_id_of(r): struct.unpack_from("<I", r.raw, HEADER + PARENT_AT)[0]
               for r in records if object_id_of(r) is not None and len(r.raw) >= HEADER + PARENT_AT + 4}
    names = {t["object_id"]: t["name"] for t in read_tracks(data)}
    out = []
    for i in arrange_run(records):
        raw = records[i].raw
        oid = row_object(raw)
        out.append((names.get(oid), raw[HEADER + MEMBER_AT], raw[HEADER + EXPANDED_AT], parents.get(oid)))
    return out


def outputs(data: bytes) -> dict[str, str | None]:
    labels = output_labels(data)
    return {t["name"]: labels.get(t["object_id"]) for t in read_tracks(data) if t["name"].startswith(("Audio", "Aux"))}


@_goldens.needs(*[k for pair in PAIRS for k in (pair[0], pair[2])])
class FlattenInsideAStackTest(unittest.TestCase):
    def test_ours_leaves_the_rows_as_logics_flatten_does(self):
        for before_key, header, after_key in PAIRS:
            with self.subTest(after_key):
                before, after = project_data(_goldens.path(before_key)), project_data(_goldens.path(after_key))
                stack = next(s for s in read_stacks(before) if s.name == header)
                ours = flatten_stack(before, stack.object_id)
                self.assertEqual(rows(ours), rows(after))
                self.assertEqual(outputs(ours), outputs(after))


if __name__ == "__main__":
    unittest.main()
