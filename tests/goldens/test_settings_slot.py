"""`logic settings` numbers slots as the mixer does: the Pro-Q 4 in `translate-proq` sits in slot 4
behind three empty ones, so the listing says slot 4 and `--set --at 4` writes it."""

import contextlib
import io
import tempfile
import unittest

import _goldens
from logicxkit.cli import main

KEY = "translate-proq"


def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main(["logic", *argv])
    return rc, out.getvalue()


@_goldens.needs(KEY)
class MixerSlotTest(unittest.TestCase):
    def test_the_listing_names_the_mixer_slot(self):
        rc, text = _run(["settings", str(_goldens.path(KEY)), "--channel", "Audio 2"])
        self.assertEqual(rc, 0, text)
        self.assertIn(f"Audio 2          slot  {_goldens.fact(KEY, 'slot')}  ", text)

    def test_set_writes_the_slot_it_names_and_refuses_an_empty_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, text = _run(["settings", str(_goldens.path(KEY)), "--channel", "Audio 2", "--at", "1",
                             "--set", "band 3=bell 1000 Hz +2 dB Q 1", "--out", tmp])
            self.assertEqual(rc, 1)
            self.assertIn("slot 1 holds no plug-in (plug-ins in slot(s) 4)", text)
        with tempfile.TemporaryDirectory() as tmp:
            rc, text = _run(["settings", str(_goldens.path(KEY)), "--channel", "Audio 2", "--at", "4",
                             "--set", "band 3=bell 1000 Hz +2 dB Q 1", "--out", tmp])
            self.assertEqual(rc, 0, text)
            self.assertIn("bell 250 Hz -4.0 dB Q 2.43; bell 1.00 kHz +2.0 dB Q 1.00; high shelf", text)


@_goldens.needs("slider-midpoints-resave-logic")
class SliderOnlyMapTest(unittest.TestCase):
    def test_set_on_a_plug_in_with_sliders_but_no_vocabulary_names_the_other_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, text = _run(["settings", str(_goldens.path("slider-midpoints-resave-logic")), "--channel", "Output 1-2",
                             "--at", "5", "--set", "gain=1", "--out", tmp])
        self.assertEqual(rc, 1)
        self.assertIn("slot 5: Limiter has no settings vocabulary; use add-plugin/replace-plugin --set or automation --set", text)

    def test_the_listing_says_the_same(self):
        rc, text = _run(["settings", str(_goldens.path("slider-midpoints-resave-logic")), "--channel", "Output 1-2"])
        self.assertEqual(rc, 0, text)
        self.assertIn("slot  5  Limiter: no settings vocabulary; use add-plugin/replace-plugin --set or automation --set", text)


if __name__ == "__main__":
    unittest.main()
