"""A write that closes a routing loop says so and names it; the write still lands. A channel's
output on a bus and a send that is not bypassed both carry signal to every aux the bus feeds."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, run, written

from logicxkit.logic.services.mixer.routing_loops import new_loops, routing_loops

TWO_SUMMING = "stack-summing-into-summing-before-logic"     # S on Aux 1 fed Bus 1, T on Aux 2 fed Bus 2
SUMMING = "stack-summing-logic"                             # Sum 1 on Aux 1 fed Bus 1
WARNING = "warning: this leaves a routing loop: "


def said(command: str, bundle, *rest, out: Path) -> tuple[Path, str]:
    code, text = run(command, bundle if isinstance(bundle, Path) else _goldens.path(bundle), *rest, "--out", out)
    assert code == 0, text
    return next(out.glob("*.logicx")), text


@_goldens.needs(TWO_SUMMING, SUMMING)
class RoutingLoopWarningTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def test_two_summing_stacks_moved_into_each_other_are_named_as_a_loop(self):
        inside, text = said("stacks", TWO_SUMMING, "--move", "T:S", out=self.out / "1")
        self.assertNotIn(WARNING, text)
        beside, text = said("stacks", inside, "--move-out", "T", out=self.out / "2")
        self.assertNotIn(WARNING, text)
        looped, text = said("stacks", beside, "--move", "S:T", out=self.out / "3")
        self.assertIn(WARNING + "S (Aux 1) -> Bus 2 -> T (Aux 2) -> Bus 1 -> S (Aux 1)", text)
        self.assertEqual(routing_loops(data(looped)), [("S (Aux 1)", "Bus 2", "T (Aux 2)", "Bus 1", "S (Aux 1)")])

    def test_a_send_back_to_the_bus_that_feeds_the_channel_is_a_loop_unless_bypassed(self):
        looped, text = said("send", SUMMING, "--add", "Aux 1=Bus 1", out=self.out / "1")
        self.assertIn(WARNING + "Sum 1 (Aux 1) -> Bus 1 -> Sum 1 (Aux 1)", text)
        _dest, text = said("send", SUMMING, "--add", "Aux 1=Bus 1", "--bypass", "on", out=self.out / "2")
        self.assertNotIn(WARNING, text)

    def test_a_loop_the_project_already_had_is_not_named_again(self):
        looped = written(self, "send", SUMMING, "--add", "Aux 1=Bus 1", out=self.out / "1")
        _dest, text = said("rename", looped, "--track", "Audio 1=Kick", out=self.out / "2")
        self.assertNotIn(WARNING, text)
        self.assertEqual(new_loops(data(looped), data(looped)), [])

    def test_the_two_bases_carry_none(self):
        for key in (TWO_SUMMING, SUMMING):
            self.assertEqual(routing_loops(data(_goldens.path(key))), [], key)


if __name__ == "__main__":
    unittest.main()
