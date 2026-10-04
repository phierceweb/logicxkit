"""A row dragged out of an inner stack to a direct place in a summing stack takes that stack's
bus, out of a folder and out of a summing stack alike; a folder flattened inside a summing stack
leaves its tracks' outputs alone; and two summing stacks dragged into each other are left
feeding each other, in Logic 12.4's own save as in a written one. Logic re-saved a written
move-out of each kind as written. Skips without the public corpus."""

import unittest

import _goldens
from _stackview import channel_records, load, obj, parents, placed, view

from logicxkit.logic.services.arrange.stack_moves import flatten_stack, move_out_of_stack, move_to_stack
from logicxkit.logic.services.arrange.stacks import read_stacks
from logicxkit.logic.services.mixer.binding import channels, output_labels
from logicxkit.logic.services.mixer.routing_loops import routing_loops
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.stream.validate import validate_project

IN_FOLDER = "stack-out-of-folder-before-logic"       # summing S { folder F { Audio 1, Audio 3, Audio 2 } }, Audio 3 on Output 1-2
NESTED = "stack-loop-before-logic"                   # summing S { Audio 1, summing T { Audio 3 }, Audio 2 }, T's aux on Bus 1
# (Logic's save before, the track dragged out, Logic's save after, the bus it took)
LEAVES = ((IN_FOLDER, "Audio 3", "stack-out-of-folder-after-logic", "Bus 1"),
          (NESTED, "Audio 3", "stack-out-of-inner-summing-after-logic", "Bus 1"))
WRITTEN = ("stack-out-of-folder", "stack-out-of-inner-summing")
LOOP = ("S (Aux 1)", "Bus 2", "T (Aux 2)", "Bus 1", "S (Aux 1)")


def output_of(data: bytes, label: str) -> str | None:
    return next(output_labels(data).get(o) for o, c in channels(data).items() if c.label == label)


@_goldens.needs(IN_FOLDER, NESTED, "stack-flatten-in-summing-after-logic", "stack-loop-out-logic",
                "stack-loop-after-logic", *(after for _b, _t, after, _bus in LEAVES))
class LeavingAnInnerStackTest(unittest.TestCase):
    def held(self, before: bytes, out: bytes, count: int, logic_key: str):
        logic, logic_count = load(logic_key)
        self.assertEqual(placed(out, count), placed(logic, logic_count))
        self.assertEqual(channel_records(out, like=logic), channel_records(logic))
        self.assertEqual((validate_project(out), regressions(before, out)), ([], []))

    def test_a_row_that_lands_a_direct_member_of_a_summing_stack_takes_its_bus(self):
        for before, track, after, bus in LEAVES:
            with self.subTest(after):
                data, count = load(before)
                out = move_out_of_stack(data, obj(data, track), track_count=count)
                self.assertNotEqual(output_of(data, track), bus)
                self.assertEqual(output_of(out, track), bus)
                self.held(data, out, count, after)

    def test_a_folder_flattened_inside_a_summing_stack_leaves_the_outputs_alone(self):
        data, count = load(IN_FOLDER)
        logic, logic_count = load("stack-flatten-in-summing-after-logic")
        folder = next(s for s in read_stacks(data, count) if s.name == "F")
        out = flatten_stack(data, folder.object_id, track_count=count)
        self.assertEqual(output_of(out, "Audio 3"), "Output 1-2")
        self.assertEqual((view(out, count - 1), parents(out)), (view(logic, logic_count), parents(logic)))
        self.assertEqual(channel_records(out, like=logic), channel_records(logic))

    def test_two_summing_stacks_moved_into_each_other_loop_as_logics_drags_left_them(self):
        data, count = load(NESTED)
        beside = move_out_of_stack(data, obj(data, "T"), track_count=count)
        self.assertEqual(output_of(beside, "Aux 2"), "Bus 1")           # out at the top level, still on S's bus
        self.held(data, beside, count, "stack-loop-out-logic")
        looped = move_to_stack(beside, obj(beside, "S"), obj(beside, "T"), track_count=count)
        self.held(beside, looped, count, "stack-loop-after-logic")
        self.assertEqual((routing_loops(data), routing_loops(beside)), ([], []))
        self.assertEqual((routing_loops(looped), routing_loops(load("stack-loop-after-logic")[0])), ([LOOP], [LOOP]))


@_goldens.needs(*(f"{stem}-{side}" for stem in WRITTEN for side in ("ours", "resave-logic")))
class LogicKeptTheWrittenMovesTest(unittest.TestCase):
    def test_each_copy_came_back_as_written(self):
        for stem in WRITTEN:
            with self.subTest(stem):
                ours, count = load(f"{stem}-ours")
                logic, logic_count = load(f"{stem}-resave-logic")
                self.assertEqual((view(ours, count), parents(ours)), (view(logic, logic_count), parents(logic)))
                self.assertEqual(channel_records(ours), channel_records(logic))
                self.assertEqual(validate_project(logic), [])


if __name__ == "__main__":
    unittest.main()
