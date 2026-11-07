"""apply-template meets stacks of one name and a return it cannot place: a template stack means
the session stack its header pairs with, and a bus nothing in the session would hear gets an aux
before a track is sent to it. Skips without the public corpus."""

import unittest

import _goldens

from logicxkit.logic.orchestrators.apply_template import apply_template
from logicxkit.logic.services.mixer.binding import bound_channels, channels, input_labels, output_labels
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.arrange.stacks import read_stacks
from logicxkit.logic.services.stream.validate import validate_project
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
        self.assertIn("move from D (Aux 1) to D (Sub 1)", [op.detail for op in ops])     # the summing header on the lowest free stub
        self.assertEqual(members(out)["Sub 1"], ["Audio 1", "Audio 2", "Audio 3"])
        self.assertEqual([output(out, f"Audio {n}") for n in (1, 2, 3)], ["Output 1-2"] * 3)


@_goldens.needs(THREE, SUMMING)
class BusBroughtUpTest(unittest.TestCase):
    def test_a_bus_nothing_would_hear_gets_an_aux_before_the_outputs_go_to_it(self):
        """Logic's summing stack as the template, its aux the first row, so it cannot be placed:
        the bus comes into use as Logic's own output change leaves one, then the outputs go to it."""
        template, session = (project_data(_goldens.path(k)) for k in (SUMMING, THREE))
        out, ops, _n = apply_template(template, session, template_count=None, session_count=None)
        self.assertEqual([(op.target, op.detail, op.status) for op in ops if op.kind == "return"],
                         [("Bus 1", "put in use: Aux 1 fed from it, output Output 1-2, as Logic's own does", "done")])
        self.assertEqual({(op.detail, op.status) for op in ops if op.kind == "output"}, {("-> Bus 1", "done")})
        self.assertEqual([output(out, f"Audio {n}") for n in (1, 2, 3)], ["Bus 1"] * 3)
        aux = next(o for o, c in channels(out).items() if c.label == "Aux 1")
        self.assertEqual((channels(out)[aux].in_use, input_labels(out)[aux], output_labels(out)[aux]),
                         (True, "Bus 1", "Output 1-2"))
        self.assertEqual(validate_project(out), [])

if __name__ == "__main__":
    unittest.main()
