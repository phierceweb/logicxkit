"""The automation reader held to what Logic's own Automation Event List displayed for each golden
(read off the screen, 2026-09-17): every fader point's tick and value. The list shows positions to
the tick, so the half-tick point reads as the display tick before it; the fraction is the reader's
alone. Skips without the public corpus."""

import unittest
import _goldens
from logicxkit.logic.services.regions.automation import FADER_NAMES, read_automation
from logicxkit.logic.services.song.events import BAR_ONE, PPQ
from logicxkit.logicx import project_data

DIVISION = PPQ // 4                      # the list's division is a sixteenth at 4/4; its tick is a file tick


def shown_tick(pos: list[int]) -> int:
    """`bar beat division tick` as the list shows it (4/4, ticks 1-based) -> the file tick."""
    bar, beat, div, tick = pos
    return BAR_ONE + ((bar - 1) * 4 + (beat - 1)) * PPQ + (div - 1) * DIVISION + (tick - 1)


class ShownPositionTest(unittest.TestCase):
    def test_the_lists_positions_read_as_ticks(self):
        self.assertEqual(shown_tick([1, 1, 1, 1]), BAR_ONE)
        self.assertEqual(shown_tick([0, 4, 4, 240]), BAR_ONE - 1)
        self.assertEqual(shown_tick([1, 3, 1, 1]), BAR_ONE + 2 * PPQ)
        self.assertEqual(shown_tick([2, 1, 1, 1]), BAR_ONE + 4 * PPQ)


class ShownTest(unittest.TestCase):
    """Every public automation golden whose facts carry what the list showed."""

    def _keys(self):
        return [k for k, e in _goldens.manifest().items()
                if k.startswith("automation-") and isinstance(e, dict)
                and isinstance(e.get("facts", {}).get("shown"), dict) and _goldens.path(k)]

    def test_every_fader_point_shown_is_read_at_its_tick_and_value(self):
        keys = self._keys()
        self.assertTrue(keys, "no golden carries a `shown` fact")
        for key in keys:
            with self.subTest(key):
                shown = _goldens.fact(key, "shown")
                folders = [a for a in read_automation(project_data(_goldens.path(key))) if a.track == shown["track"]]
                read = sorted((p.tick, ln.fader, int(p.value), ln.relative)
                              for a in folders for ln in a.lanes if ln.fader is not None and not ln.region for p in ln.points)
                listed = sorted((shown_tick(r["pos"]), r["num"], r["val"], r["name"].startswith("±") or "Relative" in r["name"])
                                for r in shown["rows"] if r["status"] == "Fader" and r["num"] in FADER_NAMES)
                self.assertEqual([(t, f, v) for t, f, v, _r in read], [(t, f, v) for t, f, v, _r in listed])

    def test_the_half_tick_point_shows_as_the_tick_before_the_region(self):
        shown = _goldens.fact("automation-volume-three-points-logic", "shown")
        self.assertIn([0, 4, 4, 240], [r["pos"] for r in shown["rows"]])
        self.assertEqual([r["pos"] for r in shown["rows"]].count([1, 1, 1, 1]), 2)


if __name__ == "__main__":
    unittest.main()
