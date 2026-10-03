"""`logic automation` end to end on the public corpus: the write flags apply in the order typed,
a write without `--out` is refused, and the listing shows the half-tick border point."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.cli import main
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logicx import project_data


def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main(["logic", *argv])
    return rc, out.getvalue()


@_goldens.needs("automation-volume-three-points-logic")
class AutomationCommandTest(unittest.TestCase):
    def test_clear_then_set_leaves_the_set_lane(self):
        src = str(_goldens.path("automation-volume-three-points-logic"))
        with tempfile.TemporaryDirectory() as tmp:
            rc, text = _run(["automation", src, "--clear", "Audio 2:Volume", "--set", "Audio 2:Volume=100@1", "--out", tmp])
            self.assertEqual(rc, 0, text)
            (written,) = Path(tmp).glob("*.logicx")
            (lane,) = [ln for a in read_automation(project_data(written)) for ln in a.lanes if ln.parameter == "Volume"]
            self.assertEqual([(p.tick, p.value) for p in lane.points], [(38400, 100.0)])
            self.assertLess(text.index("cleared"), text.index("= 100@1"))

    def test_set_then_clear_leaves_nothing(self):
        src = str(_goldens.path("automation-volume-three-points-logic"))
        with tempfile.TemporaryDirectory() as tmp:
            rc, _text = _run(["automation", src, "--set", "Audio 2:Volume=100@1", "--clear", "Audio 2:Volume", "--out", tmp])
            self.assertEqual(rc, 0)
            (written,) = Path(tmp).glob("*.logicx")
            self.assertEqual([ln.parameter for a in read_automation(project_data(written)) for ln in a.lanes if not ln.region], [])

    def test_a_write_without_out_is_refused(self):
        rc, text = _run(["automation", str(_goldens.path("automation-volume-three-points-logic")), "--clear", "Audio 2:Volume"])
        self.assertEqual((rc, "--out is needed" in text), (2, True))

    def test_the_listing_shows_the_half_tick_border_point(self):
        rc, text = _run(["automation", str(_goldens.path("automation-volume-three-points-logic"))])
        self.assertEqual(rc, 0)
        self.assertIn("bar   0.99987", text)


if __name__ == "__main__":
    unittest.main()
