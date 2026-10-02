"""apply-template meets stacks of one name and a return it cannot place: a template stack means
the session stack its header pairs with, and a track is not sent to a bus nothing in the session
will take. Skips without the public corpus."""

import unittest

import _goldens

from logicxkit.logic.orchestrators.apply_template import apply_template
from logicxkit.logic.services.binding import bound_channels, output_labels
from logicxkit.logic.services.environment import channel_objects
from logicxkit.logic.services.stack_create import create_stack
from logicxkit.logic.services.stack_summing import create_summing_stack
from logicxkit.logic.services.stacks import read_stacks
from logicxkit.logic.services.validate import validate_project
from logicxkit.logicx import project_data

THREE, SUMMING = "nest-three-audio-logic", "stack-summing-logic"


def obj(data: bytes, name: str) -> int:
    return next(i for i, o in channel_objects(data).items() if o.name == name)


def members(data: bytes) -> dict[str, list[str]]:
    return {s.strip: [n for _k, n in s.members] for s in read_stacks(data)}


def output(data: bytes, name: str) -> str | None:
    return output_labels(data).get(bound_channels(data)[obj(data, name)])


@_goldens.needs(THREE)
class TwoStacksOfOneNameTest(unittest.TestCase):
    """The session has a folder D (Sub 1: Audio 1) and a summing D (Aux 3: Audio 3)."""

    def setUp(self):
        self.base = project_data(_goldens.path(THREE))
        folder, _r = create_stack(self.base, name="D", members=[obj(self.base, "Audio 1")])
        self.session, _r = create_summing_stack(folder, name="D", members=[obj(folder, "Audio 3")])

    def _apply(self, *tracks: str) -> tuple[bytes, list]:
        template, _r = create_stack(self.base, name="D", members=[obj(self.base, t) for t in tracks])
        out, ops, _n = apply_template(template, self.session, template_count=None, session_count=None)
        self.assertEqual([op.line() for op in ops if op.status == "failed"], [])
        self.assertEqual(validate_project(out), [])
        return out, ops

    def test_a_track_goes_to_the_stack_the_template_header_pairs_with(self):
        out, _ops = self._apply("Audio 1", "Audio 2")
        self.assertEqual(members(out)["Sub 1"], ["Audio 1", "Audio 2"])
        self.assertEqual(output(out, "Audio 2"), "Output 1-2")

    def test_a_track_in_the_other_stack_of_the_name_is_moved(self):
        out, ops = self._apply("Audio 1", "Audio 2", "Audio 3")
        self.assertIn("move from D (Aux 3) to D (Sub 1)", [op.detail for op in ops])
        self.assertEqual(members(out)["Sub 1"], ["Audio 1", "Audio 2", "Audio 3"])
        self.assertEqual([output(out, f"Audio {n}") for n in (1, 2, 3)], ["Output 1-2"] * 3)


@_goldens.needs(THREE, SUMMING)
class RefusedReturnTest(unittest.TestCase):
    def test_a_track_is_not_sent_to_a_bus_nothing_will_take(self):
        """Logic's summing stack as the template, its aux the first row, so it cannot be placed."""
        template, session = (project_data(_goldens.path(k)) for k in (SUMMING, THREE))
        out, ops, _n = apply_template(template, session, template_count=None, session_count=None)
        outputs = [op for op in ops if op.kind == "output"]
        self.assertEqual({(op.status, op.note) for op in outputs},
                         {("refused", "nothing in the session takes Bus 1 as input")})
        self.assertEqual([output(out, f"Audio {n}") for n in (1, 2, 3)], ["Output 1-2"] * 3)


if __name__ == "__main__":
    unittest.main()
