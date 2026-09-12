"""`levels --to` against Logic's own re-save of its output: the copied fader survives."""

import unittest

import _goldens
from logicxkit.logic.services.levels import read_levels
from logicxkit.logicx import project_data


@_goldens.needs("levels-ours", "levels-resave-logic")
class LogicResavedLevelsTest(unittest.TestCase):
    def test_logic_kept_the_copied_fader_and_every_other(self):
        ours = read_levels(project_data(_goldens.path("levels-ours")))
        logic = read_levels(project_data(_goldens.path("levels-resave-logic")))
        owner = _goldens.fact("levels-ours", "click_owner")
        self.assertEqual(ours[owner]["fader"], _goldens.fact("levels-ours", "fader"))
        self.assertEqual({o: (v["fader"], v["pan"]) for o, v in ours.items()},
                         {o: (v["fader"], v["pan"]) for o, v in logic.items()})


if __name__ == "__main__":
    unittest.main()
