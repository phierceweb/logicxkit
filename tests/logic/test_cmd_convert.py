"""`stacks --convert` on a folder whose main strip is not at Logic's defaults: its Volume, Mute
and Solo lanes move onto the summing header and its level stays on the `Sub` strip, as Logic's
convert left them; another lane or an insert has no measured fate, so it is refused by name and
nothing is written. A folder inside another folder converts. Members on different outputs convert as
Logic's own does and the output names what they left; members that are all their bus has take
that bus's own aux as the main track. `stacks --flatten` and `--convert` refuse a stack with no
tracks."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, run, written

from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.regions.automation import read_automation

FOLDER = "stack-folder-logic"               # Audio 1-3 in folder `Sub 1`, its strip at defaults
THREE = "tracks-three-audio-logic"
NESTED = "nest-stack-in-stack-logic"        # folder `Sub 1` (Audio 1, 2) inside folder `Sub 2`
DIFFER = "stack-convert-differ-before-logic"    # folder `Sub 1`: Audio 1 and 2 on Bus 1, Audio 3 on Output 1-2
ALL_OF_A_BUS = "stack-convert-reuse-before-logic"   # folder `Sub 1`: all three on Bus 1, which only they feed
ON_A_BUS = "route-out-bus-second-logic"         # no stack: Audio 1 and 2 on Bus 1, Audio 3 on Output 1-2
AUX_A_TRACK = "stack-convert-reuse-track-before-logic"  # as ALL_OF_A_BUS, with Aux 1 a track below the folder


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

    def test_a_folder_with_a_lane_logics_convert_is_not_measured_on(self):
        self.refused(written(self, "automation", FOLDER, "--set", "Sub 1:Pan=40@1,90@3", out=self.out / "lane"),
                     "Pan lane")

    def test_a_mute_lane_moves_onto_the_summing_header(self):
        ridden = written(self, "automation", FOLDER, "--set", "Sub 1:Mute=0@1,127@3", out=self.out / "lane")
        dest = written(self, "stacks", ridden, "--convert", "Sub 1", out=self.out / "converted")
        lanes = [(a.track, ln.parameter, [(p.tick, p.value) for p in ln.points])
                 for a in read_automation(data(dest), count(dest)) for ln in a.lanes]
        self.assertEqual(lanes, [("Sum 1", "Mute", [(38400, 0.0), (46080, 127.0)])])

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


@_goldens.needs(DIFFER, ALL_OF_A_BUS, ON_A_BUS, AUX_A_TRACK)
class MembersOnABusTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def test_members_on_different_outputs_convert_and_the_output_names_what_they_left(self):
        code, text = run("stacks", _goldens.path(DIFFER), "--convert", "Sub 1", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("Sub 1 -> Sum 2 on Aux 2 fed from Bus 2, output Output 1-2; Sub 1 out of use", text)
        self.assertIn("their own outputs are replaced, as by Logic's own stack: Audio 1 (was Bus 1), Audio 2 (was Bus 1)", text)

    def test_stack_create_says_the_same(self):
        code, text = run("stack-create", _goldens.path(ON_A_BUS), "--name", "S", "--summing", "--track", "Audio 1",
                         "--track", "Audio 2", "--track", "Audio 3", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("fed from Bus 2, output Output 1-2", text)
        self.assertIn("Audio 1 (was Bus 1), Audio 2 (was Bus 1)", text)

    def test_members_that_are_all_their_bus_has_take_its_aux_as_the_main_track(self):
        dest = written(self, "stacks", ALL_OF_A_BUS, "--convert", "Sub 1", out=self.out / "convert")
        self.assertEqual((count(dest), [(s.name, s.kind, s.strip) for s in read_stacks(data(dest), count(dest))]),
                         (4, [("Aux 1", "summing", "Aux 1")]))
        code, text = run("stack-create", _goldens.path(ON_A_BUS), "--name", "S", "--summing", "--track", "Audio 1",
                         "--track", "Audio 2", "--out", self.out / "create")
        self.assertEqual(code, 0, text)
        self.assertIn("'Aux 1': Aux 1 (owner 8), fed from Bus 1, output Output 1-2", text)
        self.assertIn("Bus 1's own Aux 1 is the main track, as Logic makes it: no new aux, no output changed, "
                      "the track's name kept; --name 'S' is not applied", text)
        self.assertIn("NumberOfTracks -> 4", text)

    def test_a_folder_off_unity_leaves_its_level_on_the_sub_and_the_aux_keeps_its_own(self):
        level = written(self, "levels", ALL_OF_A_BUS, "--fader", "Sub 1=-10", "--fader", "Aux 1=-3", out=self.out / "level")
        code, text = run("stacks", level, "--convert", "Sub 1", "--out", self.out / "converted")
        self.assertEqual(code, 0, text)
        self.assertIn("Sub 1's fader (-10.0 dB) stays on it, as Logic's convert leaves it; Aux 1 keeps its own level", text)

    def test_the_track_count_drops_when_the_aux_was_a_track_already(self):
        dest = written(self, "stacks", AUX_A_TRACK, "--convert", "Sub 1", out=self.out)
        self.assertEqual((count(AUX_A_TRACK), count(dest)), (5, 4))
        self.assertEqual([r["name"] for r in read_tracks(data(dest), 4)][:4], ["Aux 1", "Audio 1", "Audio 2", "Audio 3"])


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
