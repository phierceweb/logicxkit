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
        self.assertEqual([stack_parents(out).get(m) for m in members], [stack_parents(self.data).get(m) for m in members])
        self.assertEqual(channel_objects(out)[report["object_id"]].parent, channel_objects(self.data)[members[0]].parent)
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
        from logicxkit.logic.services.arrange.stack_summing import create_summing_stack, own_aux
        headers = {s.object_id for s in read_stacks(self.data, self.count)}
        member = next(r for r in read_tracks(self.data, self.count)
                      if r["depth"] == 1 and r["name"] and r["object_id"] not in headers
                      and (r["label"] or "").startswith("Audio "))
        holder = next(s for s in read_stacks(self.data, self.count) if any(k == member["key"] for k, _n in s.members))
        went = output_labels(self.data).get(member["owner"]) or ""
        # alone on its bus, Logic makes that bus's aux the main track: not measured inside a stack
        alone = went.startswith("Bus ") and own_aux(self.data, went, {member["owner"]}) is not None
        if alone:
            with self.assertRaisesRegex(ValueError, "not measured"):
                create_summing_stack(self.data, name="Nested", members=[member["object_id"]], track_count=self.count)
        for make in (create_stack, create_summing_stack):
            if make is create_summing_stack and alone:
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



FOLDER_PAIRS = (("stack-sub-level-before-logic", "stack-sub-level-after-logic", "Audio 3"),
                ("stack-sub-muted-before-logic", "stack-sub-muted-after-logic", "Audio 3"))


WRITTEN = (("stackid-written-top-mine", "stackid-written-top-resave-logic"),
           ("stackid-written-inner-mine", "stackid-written-inner-resave-logic"))


@_goldens.needs("stackid-c2-logic", *(k for pair in WRITTEN for k in pair))
class WrittenStackResavedTest(unittest.TestCase):
    """Logic 12.4 opened two folder stacks written by this release's rule — the one gone id
    reused, the members' parent taken, colour 20 — one at the top level and one inside a summing
    stack, and re-saved each with every row, stack, strip, parent and table entry as written."""

    def test_the_written_copies_are_reproduced_from_their_source(self):
        from _stackview import obj, view
        from logicxkit.logicx import project_data
        source = project_data(_goldens.path("stackid-c2-logic"))
        for mine, _logic in WRITTEN:
            with self.subTest(mine):
                ours, _report = create_stack(source, name="Sub 1" if "top" in mine else "Inner",
                                             members=[obj(source, n) for n in _goldens.fact(mine, "members")], track_count=7)
                self.assertEqual(view(ours, 8), view(project_data(_goldens.path(mine)), 8))

    def test_logic_resaved_each_as_written(self):
        from _stackview import channel_records, parents, view
        from logicxkit.logicx import project_data
        from logicxkit.logic.services.mixer.binding import channels
        for mine, logic in WRITTEN:
            with self.subTest(logic):
                ours, theirs = project_data(_goldens.path(mine)), project_data(_goldens.path(logic))
                self.assertEqual(view(ours, 8), view(theirs, 8))
                self.assertEqual(parents(ours), parents(theirs))
                header = next(o for o in channel_objects(theirs).values() if o.object_id == _goldens.fact(logic, "header"))
                self.assertEqual((header.parent, header.colour), (_goldens.fact(logic, "parent"), _goldens.fact(logic, "colour")))
                labels = {o: c.label for o, c in channels(ours).items()}
                changed = {labels[o]: [k for k in range(len(a)) if a[k] != b[k]]
                           for o, a in channel_records(ours).items() if (b := channel_records(theirs)[o]) != a}
                self.assertEqual(changed, _goldens.fact(logic, "channel_bytes_changed"))


@_goldens.needs(*(k for pair in FOLDER_PAIRS for k in pair[:2]), "nest-inner-folder-logic", "stack-folder-logic")
class HeaderParentAndColourTest(unittest.TestCase):
    """Logic's Create Track Stack (Folder) gives the new header its members' parent pointer — the
    summing stack they sit in, none inside a plain folder or at the top level — and leaves the
    members' own pointers as they were; every header it made is coloured 20. Three of Logic's
    creates agree (two `stack-sub-*-after`, `nest-inner-folder-logic`)."""

    def test_the_header_takes_the_members_parent_and_the_members_keep_theirs(self):
        from logicxkit.logic.services.project.project import project_metadata
        from logicxkit.logicx import project_data
        for before, after, member in FOLDER_PAIRS:
            with self.subTest(after):
                data, logic = project_data(_goldens.path(before)), project_data(_goldens.path(after))
                count = project_metadata(_goldens.path(before))["tracks"]
                oid = next(r["object_id"] for r in read_tracks(data, count) if r["name"] == member)
                out, report = create_stack(data, name="Sub 1", members=[oid], track_count=count)
                ours, theirs = channel_objects(out), channel_objects(logic)
                header = next(o for o in theirs if o not in channel_objects(data))
                self.assertEqual((ours[report["object_id"]].parent, ours[report["object_id"]].colour),
                                 (theirs[header].parent, theirs[header].colour))
                self.assertEqual(theirs[header].parent, channel_objects(data)[oid].parent)
                self.assertEqual(ours[oid].parent, theirs[oid].parent)
                self.assertEqual(stack_parents(out).get(oid), stack_parents(logic).get(oid))

    def test_inside_a_plain_folder_the_header_has_no_parent(self):
        from logicxkit.logicx import project_data
        logic = project_data(_goldens.path("nest-inner-folder-logic"))
        base = channel_objects(project_data(_goldens.path("stack-folder-logic")))
        header = next(o for o in channel_objects(logic) if o not in base)
        self.assertEqual((channel_objects(logic)[header].parent, channel_objects(logic)[header].colour), (0, 20))


@_goldens.needs("stackid-s1-logic", "stackid-s2-logic", "stackid-c2-logic", "stackid-s3-logic")
class HeaderObjectIdTest(unittest.TestCase):
    """Which object id Logic gives a new stack header (one session, 2026-10-06): the lowest id
    whose object is gone — a converted folder's, its registry entry left with a zero UUID and
    its mixer-order row parked at the head of the list — re-stamping that entry and dropping
    the parked row; with none gone, the next multiple of four past the highest, with a new
    entry. Ours must write the same."""

    @staticmethod
    def _registry(data: bytes) -> dict[int, bytes]:
        from logicxkit.logic.services.stream.registry import GNOS_TAG, OBJECT_TYPE, UUID_STRIDE, run_entries
        g = next(r.raw[HEADER:] for r in project_records(data) if r.tag == GNOS_TAG)
        return {eid: g[at + 8: at + 24] for at, eid in run_entries(g, OBJECT_TYPE, UUID_STRIDE)}

    def _create(self, before: str, member: str):
        from logicxkit.logic.services.arrange.environment import channel_objects
        from logicxkit.logic.services.arrange.stacks import arrange_run, row_object
        from logicxkit.logic.services.arrange.tracklist import flat_run
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path(before))
        count = _goldens.fact(before, "tracks")
        oid = next(r["object_id"] for r in read_tracks(data, count) if r["name"] == member)
        out, report = create_stack(data, name="Sub 1", members=[oid], track_count=count)
        records = project_records(out)
        run = arrange_run(records, count + 1)
        from logicxkit.logic.services.stream.sequence import index_table, table_entries
        table = records[index_table(records)].raw[HEADER:]
        return out, report, {"arrange": [row_object(records[i].raw) for i in run],
                             "flat": [row_object(records[i].raw) for i in flat_run(records, run)],
                             "objects": sorted(channel_objects(out)), "registry": self._registry(out),
                             "table": [(oid, idx, slot) for _at, oid, idx, slot in table_entries(table)],
                             "triples": sum(1 for r in records if r.tag == b"qeSM")}

    @staticmethod
    def _logic_table(key: str):
        from logicxkit.logic.services.stream.sequence import index_table, table_entries
        from logicxkit.logicx import project_data
        records = project_records(project_data(_goldens.path(key)))
        table = records[index_table(records)].raw[HEADER:]
        return [(oid, idx, slot) for _at, oid, idx, slot in table_entries(table)], sum(1 for r in records if r.tag == b"qeSM")

    def test_with_a_gone_id_the_header_reuses_it_as_logic_did(self):
        out, report, ours = self._create("stackid-c2-logic", "Audio 5")
        logic = _goldens.fact("stackid-s3-logic", "new")
        self.assertEqual([report["object_id"]], logic)
        self.assertEqual(ours["objects"], _goldens.fact("stackid-s3-logic", "objects"))
        self.assertEqual(ours["arrange"], _goldens.fact("stackid-s3-logic", "arrange"))
        self.assertEqual(ours["flat"], _goldens.fact("stackid-s3-logic", "flat"))
        self.assertEqual(sorted(ours["registry"]), _goldens.fact("stackid-s3-logic", "registry_objects"))
        self.assertNotEqual(ours["registry"][report["object_id"]], bytes(16))
        self.assertEqual([e for e, u in ours["registry"].items() if u == bytes(16)], _goldens.fact("stackid-s3-logic", "zero_uuid_entries"))
        self.assertEqual((ours["table"], ours["triples"]), self._logic_table("stackid-s3-logic"))

    def test_with_no_gone_id_the_header_takes_the_next_past_the_highest(self):
        out, report, ours = self._create("stackid-s1-logic", "Audio 4")
        self.assertEqual([report["object_id"]], _goldens.fact("stackid-s2-logic", "new"))
        self.assertEqual(ours["objects"], _goldens.fact("stackid-s2-logic", "objects"))
        self.assertEqual(ours["arrange"], _goldens.fact("stackid-s2-logic", "arrange"))
        self.assertEqual(ours["flat"], _goldens.fact("stackid-s2-logic", "flat"))
        self.assertEqual(sorted(ours["registry"]), _goldens.fact("stackid-s2-logic", "registry_objects"))
        self.assertEqual((ours["table"], ours["triples"]), self._logic_table("stackid-s2-logic"))


if __name__ == "__main__":
    unittest.main()
