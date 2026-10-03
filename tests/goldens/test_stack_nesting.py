"""A stack inside a stack, as Logic's own creates and drags wrote it (2026-09-16), and
our moves held against those drags: membership, depth and stack index per row — not row order,
which a drag chooses and a write appends."""

import unittest
import _goldens
from logicxkit.logic.services.arrange.stack_moves import move_out_of_stack, move_to_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks, stack_parents
from logicxkit.logicx import project_data

KEYS = ("nest-folder-logic", "nest-stack-in-stack-logic", "nest-member-into-inner-logic",
        "nest-member-up-to-outer-logic", "nest-inner-stack-out-logic")
RESAVE = "nest-ours-resave-logic"


def _load(key):
    return project_data(_goldens.path(key))


def _object(data, name):
    return next(r["object_id"] for r in read_tracks(data) if r["name"] == name)


def _shape(data):
    """{row name: (depth, stack index)} plus each stack's members, what a move must reproduce. The
    expanded bit is left out: Logic's drag expands the stacks it drops into, a view choice."""
    rows = {r["name"]: (r["depth"], r["stack_index"]) for r in read_tracks(data)}
    return rows, {s.name: sorted(n for _k, n in s.members) for s in read_stacks(data)}


def _expanded(data):
    return {r["name"]: r["expanded"] for r in read_tracks(data) if r["grouping"]}


@_goldens.needs(*KEYS)
class NestingReadTest(unittest.TestCase):
    def test_each_save_reads_the_stacks_its_manifest_records(self):
        for key in KEYS:
            with self.subTest(key):
                stacks = read_stacks(_load(key))
                self.assertEqual({s.name: [n for _k, n in s.members] for s in stacks}, _goldens.fact(key, "stacks"))

    def test_a_nested_header_knows_its_parent_and_depth(self):
        stacks = {s.name: s for s in read_stacks(_load("nest-stack-in-stack-logic"))}
        self.assertEqual((stacks["Sub 1"].depth, stacks["Sub 1"].parent), (1, stacks["Sub 2"].object_id))
        self.assertEqual((stacks["Sub 2"].depth, stacks["Sub 2"].parent), (0, None))

    def test_the_member_byte_is_the_depth(self):
        rows = {r["name"]: r["depth"] for r in read_tracks(_load("nest-stack-in-stack-logic"))}
        self.assertEqual((rows["Sub 2"], rows["Sub 1"], rows["Audio 1"], rows["Audio 3"]), (0, 1, 2, 1))


@_goldens.needs(*KEYS)
class NestingWriteTest(unittest.TestCase):
    def test_a_track_moved_into_the_inner_stack_matches_logics_drag(self):
        base, logic = _load("nest-stack-in-stack-logic"), _load("nest-member-into-inner-logic")
        ours = move_to_stack(base, _object(base, "Audio 3"), _object(base, "Sub 1"))
        self.assertEqual(_shape(ours), _shape(logic))

    def test_a_member_moved_out_to_the_outer_stack_matches_logics_drag(self):
        base, logic = _load("nest-member-into-inner-logic"), _load("nest-member-up-to-outer-logic")
        ours = move_out_of_stack(base, _object(base, "Audio 2"))
        self.assertEqual(_shape(ours), _shape(logic))
        self.assertEqual(stack_parents(ours).get(_object(base, "Audio 2")), _object(base, "Sub 2"))

    def test_the_inner_stack_moved_out_matches_logics_drag(self):
        base, logic = _load("nest-member-up-to-outer-logic"), _load("nest-inner-stack-out-logic")
        ours = move_out_of_stack(base, _object(base, "Sub 1"))
        self.assertEqual(_shape(ours), _shape(logic))

    def test_a_moved_header_keeps_its_expanded_bit(self):
        """Logic's own save of the nested header inside a stack has it expanded; a move must not
        collapse it (only a plain row loses the bit)."""
        base = _load("nest-member-up-to-outer-logic")
        self.assertTrue(_expanded(base)["Sub 1"])
        out = move_out_of_stack(base, _object(base, "Sub 1"))
        self.assertEqual(_expanded(out), _expanded(base))
        back = move_to_stack(out, _object(out, "Sub 1"), _object(out, "Sub 2"))
        self.assertEqual(_expanded(back), _expanded(base))

    def test_a_stack_moved_into_a_stack_reads_back_nested(self):
        base = _load("nest-folder-logic")
        ours = move_to_stack(base, _object(base, "Audio 3"), _object(base, "Sub 1"))
        self.assertEqual(_shape(ours)[1], {"Sub 1": ["Audio 1", "Audio 2", "Audio 3"]})
        with self.assertRaises(ValueError):
            move_to_stack(_load("nest-stack-in-stack-logic"), _object(base, "Sub 1") if False else _object(_load("nest-stack-in-stack-logic"), "Sub 2"), _object(_load("nest-stack-in-stack-logic"), "Sub 1"))


@_goldens.needs("nest-stack-in-stack-logic", RESAVE)
class ResaveTest(unittest.TestCase):
    def test_logic_resaves_our_nested_move_as_written(self):
        """The copy `stacks --move` wrote was opened and re-saved by Logic; the re-save reads the
        same nesting as our write, and as the manifest records."""
        base = _load("nest-stack-in-stack-logic")
        ours = move_to_stack(base, _object(base, "Audio 3"), _object(base, "Sub 1"))
        logic = _load(RESAVE)
        self.assertEqual(_shape(ours), _shape(logic))
        self.assertEqual({s.name: [n for _k, n in s.members] for s in read_stacks(logic)}, _goldens.fact(RESAVE, "stacks"))


@_goldens.needs("nest-stack-in-stack-logic")
class AddTrackInNestedStackTest(unittest.TestCase):
    """A track added inside a nested stack takes the depth of its place: beside a member, under a
    header, or beside a nested header at the outer level."""

    def _added(self, after, member):
        from logicxkit.logic.services.arrange.addtrack import add_track
        base = _load("nest-stack-in-stack-logic")
        out, _report = add_track(base, name="New", after=_object(base, after), member=member)
        rows = {r["name"]: (r["depth"], r["stack_index"]) for r in read_tracks(out)}
        return rows, {s.name: [n for _k, n in s.members] for s in read_stacks(out)}

    def test_beside_a_member_of_the_inner_stack(self):
        rows, stacks = self._added("Audio 1", True)
        self.assertEqual(rows["New"], rows["Audio 1"])
        self.assertEqual(stacks, {"Sub 2": ["Sub 1", "Audio 3"], "Sub 1": ["Audio 1", "New", "Audio 2"]})

    def test_under_the_inner_header(self):
        rows, stacks = self._added("Sub 1", True)
        self.assertEqual(rows["New"], rows["Audio 1"])
        self.assertEqual(stacks["Sub 1"], ["New", "Audio 1", "Audio 2"])

    def test_beside_the_inner_header_at_the_outer_level(self):
        rows, stacks = self._added("Sub 1", None)
        self.assertEqual(rows["New"], rows["Audio 3"])
        self.assertEqual(stacks, {"Sub 2": ["Sub 1", "New", "Audio 3"], "Sub 1": ["Audio 1", "Audio 2"]})


if __name__ == "__main__":
    unittest.main()
