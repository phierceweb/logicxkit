"""`stacks --convert` on a folder whose main strip is not at Logic's defaults: its Volume lane
moves onto the summing header and its level stays on the `Sub` strip, as Logic's convert left
them; another lane or an insert has no measured fate, so it is refused by name and nothing is
written. A folder inside another folder converts. `stacks --flatten` and `--convert` refuse a
stack with no tracks."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, run, written

from logicxkit.logic.services.regions.automation import read_automation

FOLDER = "stack-folder-logic"               # Audio 1-3 in folder `Sub 1`, its strip at defaults
THREE = "tracks-three-audio-logic"
NESTED = "nest-stack-in-stack-logic"        # folder `Sub 1` (Audio 1, 2) inside folder `Sub 2`


@_goldens.needs(FOLDER)
class ConvertRefusesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def refused(self, bundle: Path, *said: str) -> None:
        code, text = run("stacks", bundle, "--convert", "Sub 1", "--out", self.out / "converted")
        self.assertEqual(code, 1, text)
        for part in said:
            self.assertIn(part, text)
        self.assertFalse((self.out / "converted" / bundle.name).exists(), text)

    def test_a_folder_off_unity_converts_its_level_left_on_the_sub(self):
        from logicxkit.logic.services.mixer.binding import channels
        from logicxkit.logic.services.mixer.levels import read_levels
        level = written(self, "levels", FOLDER, "--fader", "Sub 1=-10", out=self.out / "level")
        code, text = run("stacks", level, "--convert", "Sub 1", "--out", self.out / "converted")
        self.assertEqual(code, 0, text)
        self.assertIn("Sub 1's fader (-10.0 dB) stays on it, as Logic's convert leaves it; Aux 1 is at 0 dB", text)
        dest = data(self.out / "converted" / level.name)
        faders = {c.label: round(read_levels(dest)[o]["fader_db"], 1) for o, c in channels(dest).items()
                  if c.label in ("Sub 1", "Aux 1")}
        self.assertEqual(faders, {"Sub 1": -10.0, "Aux 1": 0.0})

    def test_a_folder_with_a_lane_other_than_volume(self):
        self.refused(written(self, "automation", FOLDER, "--set", "Sub 1:Mute=0@1,127@3", out=self.out / "lane"),
                     "Mute lane")

    def test_a_volume_lane_moves_onto_the_summing_header(self):
        ridden = written(self, "automation", FOLDER, "--set", "Sub 1:Volume=90@1,60@3", out=self.out / "lane")
        dest = written(self, "stacks", ridden, "--convert", "Sub 1", out=self.out / "converted")
        lanes = [(a.track, ln.parameter, [(p.tick, p.value) for p in ln.points])
                 for a in read_automation(data(dest), count(dest)) for ln in a.lanes]
        self.assertEqual(lanes, [("Sum 1", "Volume", [(38400, 90.0), (46080, 60.0)])])

    def test_a_folder_with_an_insert(self):
        self.refused(written(self, "add-plugin", FOLDER, "--plugin", "Compressor", "--channel", "Sub 1",
                             out=self.out / "insert"),
                     "a Compressor insert")

    def test_a_folder_at_its_defaults_converts(self):
        code, text = run("stacks", _goldens.path(FOLDER), "--convert", "Sub 1", "--out", self.out / "converted")
        self.assertEqual(code, 0, text)
        self.assertIn("Sub 1 -> Sum 1 on Aux 1 fed from Bus 1", text)


@_goldens.needs(NESTED)
class NestedConvertTest(unittest.TestCase):
    def test_a_folder_inside_a_folder_converts(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run("stacks", _goldens.path(NESTED), "--convert", "Sub 1", "--out", Path(tmp))
            self.assertEqual(code, 0, text)
            self.assertIn("Sub 1 -> Sum 1 on Aux 1 fed from Bus 1", text)
            self.assertIn("Sub 2: Sum 1, Audio 3", text)


@_goldens.needs(THREE)
class EmptyStackTest(unittest.TestCase):
    def test_flatten_and_convert_refuse_a_stack_with_no_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            made = written(self, "stack-create", THREE, "--name", "D", "--track", "Audio 1", out=out / "made")
            empty = written(self, "stacks", made, "--move-out", "Audio 1", out=out / "empty")
            for flag in ("--flatten", "--convert"):
                with self.subTest(flag):
                    code, text = run("stacks", empty, flag, "D", "--out", out / flag[2:])
                    self.assertEqual(code, 1, text)
                    self.assertIn("D: no track sits in it", text)


if __name__ == "__main__":
    unittest.main()
