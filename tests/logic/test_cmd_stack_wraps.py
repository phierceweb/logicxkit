"""`stack-create` around a stack and `stacks --move` of a stack into a summing stack, as Logic's
own Create Track Stack and drags left them, a third level refused; `levels` naming a muted and a
soloed channel; `stacks --convert` saying where a muted folder's mute went, and refusing a Mute
lane where no save shows its fate and a folder that holds a stack."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, run, wrapped, written

from logicxkit.logic.services.arrange.stacks import read_stacks
from logicxkit.logic.services.mixer.binding import channels, output_labels

FOLDER = "stack-folder-logic"                           # folder `Sub 1`: Audio 1-3
SUMMING = "stack-summing-logic"                         # summing `Sum 1` on Aux 1: Audio 1-3 on Bus 1
TWO_SUMMING = "stack-summing-into-summing-before-logic"     # S (Audio 1, 2) and T (Audio 3), both summing
MUTED = "stack-folder-muted-logic"
SOLOED = "solo-audio-2-logic"
ALL_OF_A_BUS = "stack-convert-reuse-before-logic"       # folder `Sub 1`: all three on Bus 1, which only they feed
NESTED = "stack-folder-around-summing-after-logic"      # Sub 2 { Sum 1 { Audio 1-3 } }
HOLDING = "stack-convert-holding-folder-before-logic"   # Sub 2 { Sub 1 { Audio 1, Audio 2 }, Audio 3 }
SUB_FREE = "stack-sub-after-convert-before-logic"       # folder on Sub 1, Sub 2 out of use, Audio 3 at the top level
IN_FOLDER = "stack-out-of-folder-before-logic"          # S { F { Audio 1, Audio 3, Audio 2 } }, Audio 3 on Output 1-2


def stacks(bundle: Path) -> dict[str, tuple]:
    return {s.name: (s.kind, s.depth, [n for _k, n in s.members]) for s in read_stacks(data(bundle), count(bundle))}


def outputs(bundle: Path) -> dict[str, str | None]:
    found, outs = data(bundle), output_labels(data(bundle))
    return {c.label: outs.get(o) for o, c in channels(found).items() if c.in_use}


@_goldens.needs(FOLDER, SUMMING, TWO_SUMMING, MUTED, SOLOED, ALL_OF_A_BUS, NESTED, HOLDING, SUB_FREE, IN_FOLDER)
class StackWrapCommandsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def test_a_summing_stack_around_a_folder_routes_the_folders_tracks(self):
        dest = written(self, "stack-create", FOLDER, "--name", "Outer", "--summing", "--track", "Sub 1", out=self.out)
        self.assertEqual(stacks(dest), {"Outer": ("summing", 0, ["Sub 1"]),
                                        "Sub 1": ("folder", 1, ["Audio 1", "Audio 2", "Audio 3"])})
        self.assertEqual({outputs(dest)[f"Audio {n}"] for n in (1, 2, 3)}, {"Bus 1"})
        self.assertEqual(count(dest), count(FOLDER) + 1)

    def test_a_folder_around_a_summing_stack_changes_no_routing(self):
        dest = written(self, "stack-create", SUMMING, "--name", "Outer", "--track", "Sum 1", out=self.out)
        self.assertEqual(stacks(dest), {"Outer": ("folder", 0, ["Sum 1"]),
                                        "Sum 1": ("summing", 1, ["Audio 1", "Audio 2", "Audio 3"])})
        self.assertEqual(outputs(dest)["Aux 1"], "Output 1-2")

    def test_a_summing_stack_around_a_summing_stack_sends_the_inner_aux_to_the_new_bus(self):
        dest = written(self, "stack-create", SUMMING, "--name", "Outer", "--summing", "--track", "Sum 1", out=self.out)
        self.assertEqual(stacks(dest)["Outer"], ("summing", 0, ["Sum 1"]))
        self.assertEqual((outputs(dest)["Aux 1"], outputs(dest)["Aux 2"], outputs(dest)["Audio 1"]),
                         ("Bus 2", "Output 1-2", "Bus 1"))

    def test_a_summing_stack_around_a_folder_on_a_bus_says_what_its_tracks_left(self):
        code, text = run("stack-create", _goldens.path(ALL_OF_A_BUS), "--name", "Outer", "--summing", "--track", "Sub 1",
                         "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("fed from Bus 2, output Output 1-2", text)
        self.assertIn("their own outputs are replaced, as by Logic's own stack: Audio 1 (was Bus 1)", text)
        self.assertNotIn("is the main track", text)

    def test_a_new_folder_takes_a_sub_strip_that_is_out_of_use(self):
        code, text = run("stack-create", _goldens.path(SUB_FREE), "--name", "New", "--track", "Audio 3", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("'New': Sub 2 (owner", text)
        dest = self.out / _goldens.path(SUB_FREE).name
        self.assertEqual(stacks(dest)["New"], ("folder", 0, ["Audio 3"]))

    def test_a_third_level_of_stack_is_refused(self):
        code, text = wrapped("stack-create", _goldens.path(NESTED), "--name", "Third", "--track", "Sum 1", "--out", self.out)
        self.assertEqual(code, 1, text)
        self.assertIn("Logic nests stacks two deep", text)
        self.assertFalse(any(self.out.iterdir()), text)

    def test_a_folder_that_holds_a_stack_is_not_converted(self):
        code, text = run("stacks", _goldens.path(HOLDING), "--convert", "Sub 2", "--out", self.out)
        self.assertEqual(code, 1, text)
        self.assertIn("it holds the stack 'Sub 1'", text)

    def test_a_summing_stack_moved_into_another_outputs_to_its_bus(self):
        dest = written(self, "stacks", TWO_SUMMING, "--move", "T:S", out=self.out)
        self.assertEqual(stacks(dest)["S"], ("summing", 0, ["Audio 1", "Audio 2", "T"]))
        self.assertEqual((outputs(dest)["Aux 2"], outputs(dest)["Audio 3"]), ("Bus 1", "Bus 2"))

    def test_levels_names_the_muted_and_the_soloed_channel(self):
        code, text = run("levels", _goldens.path(SOLOED))
        self.assertEqual(code, 0, text)
        rows = {int(ln.split()[0]): ln for ln in text.splitlines()[1:] if ln.split()}
        self.assertTrue(rows[0].endswith("muted") and rows[1].endswith("soloed"), text)
        self.assertNotIn("muted", rows.get(2, ""))

    def test_a_muted_folder_converts_and_the_output_says_where_the_mute_went(self):
        code, text = run("stacks", _goldens.path(MUTED), "--convert", "Sub 1", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("Sub 1's mute stays on it, as Logic's convert leaves it; Aux 1 is not muted", text)

    def test_a_mute_lane_on_a_folder_whose_bus_aux_becomes_the_main_track_is_refused(self):
        ridden = written(self, "automation", ALL_OF_A_BUS, "--set", "Sub 1:Mute=0@1,127@3", out=self.out / "lane")
        code, text = run("stacks", ridden, "--convert", "Sub 1", "--out", self.out / "converted")
        self.assertEqual(code, 1, text)
        self.assertIn("the folder carries a Mute lane", text)
        self.assertFalse((self.out / "converted" / ridden.name).exists(), text)

    def test_a_folder_made_after_a_muted_convert_takes_the_sub_the_convert_left(self):
        converted = written(self, "stacks", MUTED, "--convert", "Sub 1", out=self.out / "converted")
        code, text = run("stack-create", converted, "--name", "Inner", "--track", "Audio 3", "--out", self.out / "folder")
        self.assertEqual(code, 0, text)
        self.assertIn("'Inner': Sub 1", text)
        folder = self.out / "folder" / converted.name
        self.assertEqual(stacks(folder)["Inner"], ("folder", 1, ["Audio 3"]))
        code, text = run("levels", folder)
        self.assertNotIn("muted", text)

    def test_a_track_moved_out_of_a_folder_to_a_direct_place_in_a_summing_stack_takes_its_bus(self):
        self.assertEqual(outputs(_goldens.path(IN_FOLDER))["Audio 3"], "Output 1-2")
        dest = written(self, "stacks", IN_FOLDER, "--move-out", "Audio 3", out=self.out)
        self.assertEqual((stacks(dest)["S"][2], outputs(dest)["Audio 3"]), (["F", "Audio 3"], "Bus 1"))


if __name__ == "__main__":
    unittest.main()
