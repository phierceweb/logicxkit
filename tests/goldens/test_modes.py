"""Transport modes and the count-in against Logic's own saves, one press each."""

import unittest

import _goldens
from logicxkit.logic.services.modes import MODES, copy_modes, read_modes, set_modes
from logicxkit.logic.services.recdiff import diff_records, load_project_data

KEYS = ["modes-base-logic", "modes-cycle-logic", "modes-count-in-logic", "modes-replace-logic", "modes-solo-logic",
        "modes-base-b-logic", "modes-autopunch-logic", "modes-metronome-logic", "modes-count-in-2-bars-logic",
        "modes-count-in-3-beats-logic", "modes-count-in-1-bar-logic"]
PATHS = {k: _goldens.path(k) for k in KEYS}


def _data(key):
    return load_project_data(PATHS[key])


@unittest.skipUnless(all(PATHS.values()), "no mode saves")
class GoldenModesTest(unittest.TestCase):
    def test_each_save_reads_as_the_press_it_recorded(self):
        for key in KEYS:
            facts = _goldens.entry(key).get("facts", {})
            state = read_modes(_data(key))
            lit = {name for name, on in state.items() if on is True}
            with self.subTest(key=key):
                if "on" in facts:
                    self.assertEqual(lit, set(facts["on"]))
                if "count_in" in facts:
                    self.assertEqual(state["Count-in"], facts["count_in"])
                if not facts:
                    self.assertEqual(lit, set())
                    self.assertEqual(state["Count-in"], "Off")

    def test_our_write_matches_logics_save_but_for_noise(self):
        """Base B with Autopunch and Metronome Click set by us against Logic's save of the same
        two presses: the song record differs only at three bytes Logic churns on any press."""
        ours = set_modes(_data("modes-base-b-logic"), {"Autopunch": True, "Metronome Click": True})
        d = diff_records(ours, _data("modes-metronome-logic"))
        song = [c for c in d.changed if c.tag == b"gnoS"]
        self.assertEqual(len(song), 1)
        self.assertTrue(set(song[0].offsets) <= {173, 258, 2504}, song[0].offsets)
        self.assertFalse(d.added or d.removed)

    def test_copy_carries_every_mode_and_the_count_in(self):
        out, want = copy_modes(_data("modes-solo-logic"), _data("modes-base-b-logic"))
        self.assertEqual({k: v for k, v in read_modes(out).items() if k != "Solo"}, want)
        self.assertEqual({n for n, on in want.items() if on is True}, {"Cycle", "Replace"})
        self.assertEqual(want["Count-in"], "1 Bar")
        self.assertEqual((set(MODES) | {"Count-in"}) - {"Solo"}, set(want))


if __name__ == "__main__":
    unittest.main()
