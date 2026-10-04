"""A row that becomes a direct member of a summing stack outputs to the stack's bus; one entering
a folder inside it keeps its output (Logic's own drags, `test_stack_wraps`); a new summing
stack's aux outputs where its members all did, else to Output 1-2 (`test_summing_outputs`).
Skips without the public corpus."""

import unittest

import _goldens

from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.mixer.binding import bound_channels, channels, output_labels
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.mixer.routing import set_output
from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.arrange.stack_moves import move_out_of_stack, move_to_stack
from logicxkit.logic.services.arrange.stacks import read_stacks
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

THREE = "nest-three-audio-logic"


def obj(data: bytes, name: str) -> int:
    return next(i for i, o in channel_objects(data).items() if o.name == name)


def stack(data: bytes, name: str):
    return next(s for s in read_stacks(data) if s.name == name)


def output(data: bytes, name: str) -> str | None:
    return output_labels(data).get(bound_channels(data)[obj(data, name)])


def bus_of(data: bytes, name: str) -> str:
    chans = channels(data)
    feed = chans[stack(data, name).owner].input_uuid
    return next(c.label for c in chans.values() if c.uuid == feed)


@_goldens.needs(THREE)
class EnteringASummingStackTest(unittest.TestCase):
    def setUp(self):
        base = project_data(_goldens.path(THREE))
        self.s, _r = create_summing_stack(base, name="S", members=[obj(base, f"Audio {n}") for n in (1, 2, 3)])

    def test_a_track_added_beside_a_summing_member_outputs_to_the_stack(self):
        for kind in ("audio", "instrument", "aux"):
            with self.subTest(kind):
                out, _r = add_track(self.s, name="Extra", after=obj(self.s, "Audio 2"), kind=kind)
                self.assertEqual(output(out, "Extra"), "Bus 1")
                self.assertEqual(validate_project(out), [])

    def test_a_track_added_at_the_top_level_keeps_the_main_output(self):
        out, _r = add_track(self.s, name="Loose", after=obj(self.s, "S"), member=False)
        self.assertEqual(output(out, "Loose"), "Output 1-2")

    def test_a_summing_stack_inside_a_summing_stack_outputs_where_its_members_did(self):
        out, _r = create_summing_stack(self.s, name="Inner", members=[obj(self.s, "Audio 1"), obj(self.s, "Audio 2")])
        self.assertEqual(output_labels(out)[stack(out, "Inner").owner], bus_of(out, "S"))
        self.assertEqual(output(out, "Audio 1"), bus_of(out, "Inner"))
        self.assertEqual(output(out, "Audio 3"), bus_of(out, "S"))

    def test_one_made_over_members_on_different_outputs_leaves_the_outer_stack(self):
        sent = set_output(self.s, bound_channels(self.s)[obj(self.s, "Audio 1")],
                          next(o for o, c in channels(self.s).items() if c.label == "Bus 9"))
        out, report = create_summing_stack(sent, name="Inner", members=[obj(sent, "Audio 1"), obj(sent, "Audio 2")])
        self.assertEqual(output_labels(out)[stack(out, "Inner").owner], "Output 1-2")
        self.assertEqual(report["left"], {"Audio 1": "Bus 9", "Audio 2": "Bus 1"})

    def test_a_track_moved_into_a_folder_inside_a_summing_stack_keeps_its_output(self):
        inner, _r = create_stack(self.s, name="F", members=[obj(self.s, "Audio 1"), obj(self.s, "Audio 2")])
        out, _r = add_track(inner, name="Loose", after=obj(inner, "S"), member=False)
        out = move_to_stack(out, obj(out, "Loose"), stack(out, "F").object_id)
        self.assertEqual(output(out, "Loose"), "Output 1-2")
        self.assertEqual(validate_project(out), [])

    def test_a_track_added_inside_a_folder_inside_a_summing_stack_keeps_the_main_output(self):
        inner, _r = create_stack(self.s, name="F", members=[obj(self.s, "Audio 1"), obj(self.s, "Audio 2")])
        out, _r = add_track(inner, name="Extra", after=obj(inner, "Audio 1"))
        self.assertEqual(output(out, "Extra"), "Output 1-2")

    def test_a_stack_moved_into_a_folder_inside_a_summing_stack_is_refused_as_a_third_level(self):
        inner, _r = create_stack(self.s, name="F", members=[obj(self.s, "Audio 1")])
        out, _r = add_track(inner, name="Loose", after=obj(inner, "S"), member=False)
        g, _r = create_stack(out, name="G", members=[obj(out, "Loose")])
        with self.assertRaisesRegex(ValueError, "two deep"):
            move_to_stack(g, stack(g, "G").object_id, stack(g, "F").object_id)

    def test_a_track_moving_within_its_summing_stack_keeps_its_output(self):
        sent = set_output(self.s, bound_channels(self.s)[obj(self.s, "Audio 1")],
                          next(o for o, c in channels(self.s).items() if c.label == "Bus 9"))
        inner, _r = create_stack(sent, name="F", members=[obj(sent, "Audio 2")])
        out = move_to_stack(inner, obj(inner, "Audio 1"), stack(inner, "F").object_id)
        self.assertEqual(output(out, "Audio 1"), "Bus 9")

    def test_a_track_moved_out_keeps_the_bus_as_logics_own_drag_did(self):
        out = move_out_of_stack(self.s, obj(self.s, "Audio 1"))
        self.assertEqual(output(out, "Audio 1"), "Bus 1")


@_goldens.needs(THREE)
class MembersSentElsewhereTest(unittest.TestCase):
    def test_the_stack_outputs_to_the_main_output_and_the_report_names_what_was_left(self):
        base = project_data(_goldens.path(THREE))
        bus4 = next(o for o, c in channels(base).items() if c.label == "Bus 4")
        sent = set_output(base, bound_channels(base)[obj(base, "Audio 1")], bus4)
        out, report = create_summing_stack(sent, name="T", members=[obj(sent, "Audio 1"), obj(sent, "Audio 2")])
        self.assertEqual((output_labels(out)[stack(out, "T").owner], report["left"]), ("Output 1-2", {"Audio 1": "Bus 4"}))
        self.assertEqual({output(out, "Audio 1"), output(out, "Audio 2")}, {bus_of(out, "T")})
        out, _r = create_summing_stack(sent, name="T", members=[obj(sent, "Audio 2"), obj(sent, "Audio 3")])
        self.assertEqual(output(out, "Audio 1"), "Bus 4")


if __name__ == "__main__":
    unittest.main()
