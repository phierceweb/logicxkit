"""The regions command's edits run in-process on a public corpus bundle, and the copy read back."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import run, written

BASE = "regions-a00-base-logic"          # region 1 is MIDI; 2, 3 and 4 are audio


@_goldens.needs(BASE)
class RegionsCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_fades_gain_and_transpose_on_an_audio_region(self):
        dest = written(self, "regions", BASE, "--fade-in", "2=500", "--fade-out", "2=500:50:x", "--gain", "2=3",
                       "--transpose", "2=2", out=self.out)
        code, text = run("regions", dest)
        self.assertEqual(code, 0, text)
        line = next(ln for ln in text.splitlines() if ln.strip().startswith("2 "))
        self.assertIn("fade", line)

    def test_a_fade_on_a_midi_region_is_refused(self):
        code, text = run("regions", _goldens.path(BASE), "--fade-in", "1=500", "--out", self.out / "no")
        self.assertEqual(code, 1, text)
        self.assertIn("MIDI", text)

    def test_a_malformed_fade_is_refused(self):
        code, text = run("regions", _goldens.path(BASE), "--fade-out", "2=500:50:bogus", "--out", self.out / "no")
        self.assertEqual(code, 1, text)
        self.assertIn("fade-out", text)


if __name__ == "__main__":
    unittest.main()
