"""Creating a folder stack: the header row, the member rows, the `Sub N` strip, and the
structures a track add also needs. Logic's own Create Track Stack is unsampled; the result
opened in Logic 12.3.1 on 2026-09-02, and the real-file golden holds it to the invariants
every Logic file obeys.

The real-file part of tests/logic/test_stack_create.py; skips without the owner's files."""

import unittest
from collections import Counter
import _goldens
import _paths
from logicxkit.logic.services.mixer.binding import channels, output_labels
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.arrange.stack_create import SUB_NUMBER_AT, create_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks, stack_parents
from logicxkit.logic.services.stream.validate import validate_project

MIX = _paths.staged("Mix")
def names(rows: list[dict]) -> list[str]:
    return [r["name"] for r in rows]


@unittest.skipIf(not MIX.exists(), "the staged Mix template is not present")
class MixTemplateStackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from _invariants import report
        from logicxkit.logic.services.project.project import project_metadata
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

    def test_a_track_inside_a_stack_gets_a_stack_inside_it(self):
        """Both kinds, on the first member of the template's first stack that is a plain track."""
        from _invariants import assert_consistent
        from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
        headers = {s.object_id for s in read_stacks(self.data, self.count)}
        member = next(r for r in read_tracks(self.data, self.count)
                      if r["depth"] == 1 and r["name"] and r["object_id"] not in headers
                      and (r["label"] or "").startswith("Audio "))
        holder = next(s for s in read_stacks(self.data, self.count) if any(k == member["key"] for k, _n in s.members))
        if output_labels(self.data).get(member["owner"]) != "Output 1-2":   # a summing aux's output is measured only there
            with self.assertRaisesRegex(ValueError, "not measured"):
                create_summing_stack(self.data, name="Nested", members=[member["object_id"]], track_count=self.count)
        for make in (create_stack, create_summing_stack):
            if make is create_summing_stack and output_labels(self.data).get(member["owner"]) != "Output 1-2":
                continue
            with self.subTest(make.__name__):
                out, report = make(self.data, name="Nested", members=[member["object_id"]], track_count=self.count)
                assert_consistent(self, out, self.count + 1, selected=report["object_id"],
                                  link_errors_before=self.errors)
                stacks = {s.object_id: s for s in read_stacks(out, self.count + 1)}
                new, outer = stacks[report["object_id"]], stacks[holder.object_id]
                self.assertEqual((new.depth, new.parent, [n for _k, n in new.members]),
                                 (1, holder.object_id, [member["name"]]))
                self.assertEqual([n for _k, n in outer.members],
                                 ["Nested" if n == member["name"] else n for _k, n in holder.members])
                self.assertEqual(len(stacks), len(self.before) + 1)


@_goldens.needs("tracks-three-audio-logic", "stack-folder-logic")
class PublicStacklessTest(unittest.TestCase):
    """Our stack over Logic's three flat tracks against Logic's own Create Track Stack."""

    def test_our_stack_reads_like_logics(self):
        from logicxkit.logic.services.arrange.stack_create import create_stack
        from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
        base = _goldens.path("tracks-three-audio-logic").joinpath("Alternatives/000/ProjectData").read_bytes()
        ids = [r["object_id"] for r in read_tracks(base, 3) if r["name"].startswith("Audio")]
        out, _ = create_stack(base, name="Sub 1", members=ids, track_count=3)
        logic = _goldens.path("stack-folder-logic").joinpath("Alternatives/000/ProjectData").read_bytes()
        (ours,), (logics,) = read_stacks(out, 4), read_stacks(logic, 4)
        self.assertEqual([n for _k, n in ours.members], [n for _k, n in logics.members])
        self.assertEqual((ours.kind, ours.index, ours.owner), (logics.kind, logics.index, logics.owner))


class LogicResavedStacksTest(unittest.TestCase):
    """Our stacks on stack-less sessions, re-saved by Logic: one on three flat tracks, one on a
    project whose flattened stack left a `Sub 1` strip behind."""

    def _check(self, ours_key: str, logic_key: str):
        from logicxkit.logic.services.arrange.stacks import read_stacks
        from logicxkit.logicx import project_data
        ours, logic = (project_data(_goldens.path(k)) for k in (ours_key, logic_key))
        (mine,), (theirs,) = read_stacks(ours, 4), read_stacks(logic, 4)
        self.assertEqual((mine.name, mine.kind, mine.owner, [n for _k, n in mine.members]),
                         (_goldens.fact(ours_key, "name"), _goldens.fact(ours_key, "kind"),
                          _goldens.fact(ours_key, "owner"), _goldens.fact(ours_key, "members")))
        self.assertEqual((mine.name, mine.kind, mine.owner, mine.index, mine.members),
                         (theirs.name, theirs.kind, theirs.owner, theirs.index, theirs.members))

    @_goldens.needs("stack-ours", "stack-resave-logic")
    def test_the_first_stack(self):
        self._check("stack-ours", "stack-resave-logic")

    @_goldens.needs("stack-sub2-ours", "stack-sub2-resave-logic")
    def test_a_stack_after_a_leftover_sub_strip(self):
        self._check("stack-sub2-ours", "stack-sub2-resave-logic")


if __name__ == "__main__":
    unittest.main()
