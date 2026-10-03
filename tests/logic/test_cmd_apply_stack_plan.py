"""`apply-template --plan` for a template stack the session lacks: the stack op takes the session's
tracks in, so no separate move of them is listed as refused."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import run

FOLDER = "stack-folder-logic"               # Audio 1-3 in folder `Sub 1`
TWO = "tracks-two-audio-logic"              # Audio 1, Audio 2, no stack


@_goldens.needs(FOLDER, TWO)
class StackPlanTest(unittest.TestCase):
    def test_the_stacks_members_are_not_listed_as_refused_moves(self):
        code, text = run("apply-template", _goldens.path(FOLDER), _goldens.path(TWO), "--plan")
        self.assertEqual(code, 0, text)
        self.assertIn("make a stack of 3 track(s)  (1 of them added above)", text)
        self.assertNotIn("does not exist yet", text)
        self.assertIn("2 op(s) to run, 0 refused", text)

    def test_the_run_matches_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run("apply-template", _goldens.path(FOLDER), _goldens.path(TWO), "--out", Path(tmp))
            self.assertEqual(code, 0, text)
            self.assertIn("2 done, 0 refused", text)


if __name__ == "__main__":
    unittest.main()
