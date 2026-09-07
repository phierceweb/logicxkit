"""Creating a folder stack: the header row, the member rows, the `Sub N` strip, and the
structures a track add also needs. Logic's own Create Track Stack is unsampled; the result
opened in Logic 12.3.1 on 2026-09-02, and the real-file golden holds it to the invariants
every Logic file obeys.

The real-file part of tests/logic/test_stack_create.py; skips without the owner's files."""

import unittest
from collections import Counter
import _paths
from logicxkit.logic.services.binding import channels
from logicxkit.logic.services.environment import channel_objects
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.stack_create import SUB_NUMBER_AT, create_stack
from logicxkit.logic.services.stacks import read_stacks, read_tracks, stack_parents
from logicxkit.logic.services.validate import validate_project

MIX = _paths.staged("Mix")
def names(rows: list[dict]) -> list[str]:
    return [r["name"] for r in rows]


@unittest.skipIf(not MIX.exists(), "the staged Mix template is not present")
class MixTemplateStackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from _invariants import report
        from logicxkit.logic.services.project import project_metadata
        from logicxkit.logicx import project_data
        cls.data = project_data(MIX)
        cls.count = project_metadata(MIX)["tracks"]
        rows = read_tracks(cls.data, cls.count)
        names = Counter(r["name"] for r in rows)
        cls.top = [r for r in rows if not r["member"] and not r["grouping"] and names[r["name"]] == 1]
        cls.before = cls.shape(read_stacks(cls.data, cls.count))
        cls.errors = report(cls.data, cls.count)["link_errors"]

    @staticmethod
    def shape(stacks) -> list[tuple]:
        return [(s.name, s.index, s.owner, [n for _k, n in s.members]) for s in stacks]

    def test_two_top_level_tracks_become_a_stack(self):
        from _invariants import assert_consistent
        members = [r["object_id"] for r in self.top[-2:]]
        out, report = create_stack(self.data, name="Nested Stack", members=members[::-1],
                                   track_count=self.count)
        assert_consistent(self, out, self.count + 1, selected=report["object_id"],
                          link_errors_before=self.errors)
        stacks = read_stacks(out, self.count + 1)
        new = next(s for s in stacks if s.name == "Nested Stack")
        highest = max(s.index for s in read_stacks(self.data, self.count))
        self.assertEqual(([n for _k, n in new.members], new.index, report["members"]),
                         ([r["name"] for r in self.top[-2:]], highest + 1, members))
        self.assertEqual(report["label"], f"Sub {highest + 1}")
        self.assertEqual([s for s in self.shape(stacks) if s[0] != "Nested Stack"],
                         [(n, i, o + (1 if o >= report["owner"] else 0), m) for n, i, o, m in self.before])
        rows = read_tracks(out, self.count + 1)
        self.assertEqual([r["key"] for r in rows], list(range(self.count + 2)))
        self.assertEqual(stack_parents(out)[members[0]], report["object_id"])
        for m in members:
            self.assertEqual(channels(out)[next(r["owner"] for r in rows if r["object_id"] == m)].stack_index,
                             highest + 1)
        strip = next(r.raw[HEADER:] for r in project_records(out)
                     if r.tag == b"OCuA" and r.owner == report["owner"])
        self.assertEqual(strip[SUB_NUMBER_AT], highest + 1)
        self.assertEqual(strip[-48:-32], channel_objects(out)[report["object_id"]].uuid)

    def test_a_second_stack_takes_the_next_sub(self):
        first, r1 = create_stack(self.data, name="Nested Stack", members=[self.top[-1]["object_id"]],
                                 track_count=self.count)
        out, r2 = create_stack(first, name="Second", members=[self.top[-2]["object_id"]],
                               track_count=self.count + 1)
        self.assertEqual((r2["owner"], r2["object_id"]), (r1["owner"] + 1, r1["object_id"] + 4))
        self.assertEqual(validate_project(out), [])
        self.assertEqual(sorted(s.index for s in read_stacks(out, self.count + 2))[-2:],
                         [int(r1["label"][4:]), int(r2["label"][4:])])

    def test_refuses_a_track_inside_a_stack(self):
        member = next(r for r in read_tracks(self.data, self.count) if r["member"] and r["name"])
        with self.assertRaises(ValueError):
            create_stack(self.data, name="Nested", members=[member["object_id"]], track_count=self.count)


if __name__ == "__main__":
    unittest.main()
