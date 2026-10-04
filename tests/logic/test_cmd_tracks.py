"""The track commands run in-process on a public corpus bundle, and the bundle they write read
back: reorder, colour, rename, hide, add-track, stack-create."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, run, wrapped, written

from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks

THREE = "tracks-three-audio-logic"          # Audio 1, Audio 2, Audio 3, then the Stereo Out row
# the track named Audio 1 plays through the strip Audio 3, the strips Audio 1 and Audio 2 are free,
# and the tracks FX 01-03 have no channel
FIRST_STRIP_FREE = ("addtrack-order-logic", "addtrack-order-logic-12-4")


def rows(bundle) -> list[dict]:
    return read_tracks(data(bundle), count(bundle))


def names(bundle) -> list[str]:
    return [r["name"] for r in rows(bundle)]


def row(bundle, name: str) -> dict:
    return next(r for r in rows(bundle) if r["name"] == name)


@_goldens.needs(*FIRST_STRIP_FREE)
class FirstStripFreeTest(unittest.TestCase):
    def test_add_track_binds_the_first_audio_strip_when_it_is_the_free_one(self):
        for key in FIRST_STRIP_FREE:
            with self.subTest(key), tempfile.TemporaryDirectory() as tmp:
                dest = written(self, "add-track", key, "--name", "Room", "--after", "Audio 1", out=Path(tmp))
                self.assertEqual(names(dest)[:2], ["Audio 1", "Room"])
                self.assertEqual(row(dest, "Room")["label"], "Audio 1")

    def test_a_summing_stack_over_a_track_with_no_channel_is_refused_by_the_tracks_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = wrapped("stack-create", _goldens.path(FIRST_STRIP_FREE[0]), "--out", tmp, "--summing",
                                 "--name", "S", "--track", "Audio 1", "--track", "FX 01")
            self.assertEqual(code, 1, text)
            self.assertIn("'FX 01': a track with no channel", text)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            folder = written(self, "stack-create", FIRST_STRIP_FREE[0], "--name", "F", "--track", "Audio 1",
                             "--track", "FX 01", out=Path(tmp))
            self.assertEqual(names(folder)[:3], ["F", "Audio 1", "FX 01"])


@_goldens.needs(THREE)
class TrackCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_rename(self):
        dest = written(self, "rename", THREE, "--track", "Audio 2=Snare", out=self.out)
        self.assertEqual(names(dest), ["Audio 1", "Snare", "Audio 3", "Stereo Out"])

    def test_rename_to_a_name_outside_ascii(self):
        dest = written(self, "rename", THREE, "--track", "Audio 2=Gitarre \u00fc", out=self.out)
        self.assertEqual(names(dest), ["Audio 1", "Gitarre \u00fc", "Audio 3", "Stereo Out"])

    def test_a_track_added_under_such_a_name_is_found_by_it(self):
        guitar = "\U0001F3B8 Lead"
        added = written(self, "add-track", THREE, "--name", guitar, "--after", "Audio 3",
                        out=self.out / "added")
        self.assertIn(guitar, names(added))
        after = written(self, "add-track", added, "--name", "Keys", "--after", guitar,
                        "--instrument", out=self.out / "after")
        self.assertEqual(names(after).index("Keys"), names(after).index(guitar) + 1)

    def test_stack_create_summing_routes_the_members_through_a_free_bus(self):
        from logicxkit.logic.services.mixer.binding import input_labels, output_labels
        dest = written(self, "stack-create", THREE, "--name", "Guitars", "--summing", "--track", "Audio 1",
                       "--track", "Audio 3", out=self.out)
        (stack,) = read_stacks(data(dest), count(dest))
        self.assertEqual((stack.kind, stack.strip, [n for _k, n in stack.members]),
                         ("summing", "Aux 1", ["Audio 1", "Audio 3"]))
        self.assertEqual(names(dest), ["Guitars", "Audio 1", "Audio 3", "Audio 2", "Stereo Out"])
        outs, ins = output_labels(data(dest)), input_labels(data(dest))
        rows = {r["name"]: r["owner"] for r in read_tracks(data(dest), count(dest))}
        self.assertEqual((ins[rows["Guitars"]], outs[rows["Guitars"]]), ("Bus 1", "Output 1-2"))
        self.assertEqual([outs[rows[n]] for n in ("Audio 1", "Audio 3", "Audio 2")], ["Bus 1", "Bus 1", "Output 1-2"])
        code, text = run("stacks", dest)
        self.assertIn("Guitars  [summing]  Aux 1", text)
        moved = written(self, "stacks", dest, "--move", "Audio 2:Guitars", out=self.out / "moved")
        (stack,) = read_stacks(data(moved), count(moved))
        self.assertEqual([n for _k, n in stack.members], ["Audio 1", "Audio 3", "Audio 2"])
        self.assertEqual(output_labels(data(moved))[rows["Audio 2"]], "Bus 1")

    def test_stacks_move_out_takes_a_member_one_level_out_as_logics_drag_did(self):
        from logicxkit.logic.services.mixer.binding import channels, output_labels
        key = "stack-folder-dragged-out-logic"
        dest = written(self, "stacks", "stack-folder-logic", "--move-out", "Audio 3", out=self.out)
        for bundle in (dest, _goldens.path(key)):
            row = next(r for r in read_tracks(data(bundle), count(bundle)) if r["name"] == "Audio 3")
            (stack,) = read_stacks(data(bundle), count(bundle))
            self.assertEqual((row["depth"], channels(data(bundle))[row["owner"]].stack_index,
                              output_labels(data(bundle))[row["owner"]], [n for _k, n in stack.members]),
                             tuple(_goldens.fact(key, k) for k in ("depth", "stack_index", "output", "members")))
        self.assertEqual(names(dest), ["Sub 1", "Audio 1", "Audio 2", "Audio 3", "Stereo Out"])   # ours lands after the stack
        code, text = run("stacks", _goldens.path("stack-folder-logic"), "--move-out", "Audio 3")
        self.assertEqual(code, 2, text)

    def test_flatten_takes_a_stack_apart_as_logic_does(self):
        for key, name, flat in (("stack-folder-logic", "Sub 1", "stack-folder-flattened-logic"),
                                ("stack-summing-logic", "Sum 1", "stack-summing-flattened-logic")):
            with self.subTest(key):
                dest = written(self, "stacks", key, "--flatten", name, out=self.out / key)
                self.assertEqual((read_stacks(data(dest), count(dest)), count(dest)), ([], count(_goldens.path(flat))))
                self.assertEqual(names(dest), ["Audio 1", "Audio 2", "Audio 3", "Stereo Out"])
        code, text = run("stacks", _goldens.path("stack-folder-logic"), "--flatten", "Sub 1")
        self.assertEqual(code, 2, text)
        code, text = run("stacks", _goldens.path("stack-folder-logic"), "--flatten", "Audio 1", "--out", self.out / "no")
        self.assertEqual(code, 1, text)
        self.assertIn("no stack named 'Audio 1'", text)

    def test_convert_makes_a_folder_stack_a_summing_one_as_logic_does(self):
        from logicxkit.logic.services.mixer.binding import input_labels, output_labels
        dest = written(self, "stacks", "stack-folder-logic", "--convert", "Sub 1", out=self.out)
        (stack,) = read_stacks(data(dest), count(dest))
        self.assertEqual((stack.name, stack.kind, stack.strip, [n for _k, n in stack.members]),
                         ("Sum 1", "summing", "Aux 1", ["Audio 1", "Audio 2", "Audio 3"]))
        self.assertEqual(count(dest), count(_goldens.path("stack-converted-to-summing-logic")))
        outs, ins = output_labels(data(dest)), input_labels(data(dest))
        self.assertEqual((ins[stack.owner], [outs[r["owner"]] for r in rows(dest) if r["name"].startswith("Audio")]),
                         ("Bus 1", ["Bus 1"] * 3))
        code, text = run("stacks", dest, "--convert", "Sum 1", "--out", self.out / "again")
        self.assertEqual(code, 1, text)
        self.assertIn("already a summing stack", text)

    def test_a_track_leaving_a_summing_stack_keeps_its_bus(self):
        from logicxkit.logic.services.mixer.binding import output_labels
        dest = written(self, "stacks", "stack-summing-dragged-in-logic", "--move-out", "Audio 3", out=self.out)
        row = next(r for r in read_tracks(data(dest), count(dest)) if r["name"] == "Audio 3")
        self.assertEqual((row["depth"], output_labels(data(dest))[row["owner"]]), (0, "Bus 1"))
        (stack,) = read_stacks(data(dest), count(dest))
        self.assertEqual([n for _k, n in stack.members], ["Audio 1", "Audio 2"])

    def test_a_stack_is_found_by_a_decomposed_name(self):
        made = written(self, "stack-create", THREE, "--name", "Bl\u00e4ser", "--track", "Audio 1",
                       out=self.out / "made")
        moved = written(self, "stacks", made, "--move", "Audio 3:Bla\u0308ser",
                        out=self.out / "moved")
        (stack,) = read_stacks(data(moved), count(moved))
        self.assertEqual([name for _key, name in stack.members], ["Audio 1", "Audio 3"])
        dest = written(self, "add-plugin", made, "--plugin", "Channel EQ", "--stack",
                       "Bla\u0308ser", out=self.out / "eq")
        self.assertTrue((dest / "Alternatives").is_dir())

    def test_a_stack_named_outside_ascii(self):
        dest = written(self, "stack-create", THREE, "--name", "Bl\u00e4ser", "--track", "Audio 1",
                       "--track", "Audio 2", out=self.out)
        self.assertEqual([s.name for s in read_stacks(data(dest), count(dest))], ["Bl\u00e4ser"])

    def test_colour(self):
        dest = written(self, "colour", THREE, "--track", "Audio 1=5", out=self.out)
        self.assertEqual(row(dest, "Audio 1")["colour"], 5)
        self.assertEqual(row(dest, "Audio 2")["colour"], row(THREE, "Audio 2")["colour"])

    def test_hide_then_show(self):
        hidden = written(self, "hide", THREE, "--track", "Audio 3", out=self.out / "hidden")
        self.assertEqual([r["hidden"] for r in rows(hidden)], [False, False, True, False])
        shown = written(self, "hide", hidden, "--track", "Audio 3", "--show", out=self.out / "shown")
        self.assertEqual([r["hidden"] for r in rows(shown)], [False, False, False, False])

    def test_reorder(self):
        dest = written(self, "reorder", THREE, "--move", "Audio 3:before:Audio 1", out=self.out)
        self.assertEqual(names(dest), ["Audio 3", "Audio 1", "Audio 2", "Stereo Out"])

    def test_add_track(self):
        dest = written(self, "add-track", THREE, "--name", "Room", "--after", "Audio 3", out=self.out)
        self.assertEqual(names(dest), ["Audio 1", "Audio 2", "Audio 3", "Room", "Stereo Out"])
        self.assertEqual(count(dest), 4)
        self.assertTrue(row(dest, "Room")["label"].startswith("Audio "))

    def test_add_instrument_track(self):
        dest = written(self, "add-track", THREE, "--name", "Keys", "--after", "Audio 1", "--instrument",
                       out=self.out)
        self.assertEqual(names(dest), ["Audio 1", "Keys", "Audio 2", "Audio 3", "Stereo Out"])
        self.assertTrue(row(dest, "Keys")["label"].startswith("Inst "))

    def test_add_stereo_instrument_track(self):
        from logicxkit.logic.services.mixer.mixer import channel_formats
        mono = written(self, "add-track", THREE, "--name", "Keys", "--after", "Audio 1", "--instrument",
                       out=self.out / "mono")
        stereo = written(self, "add-track", THREE, "--name", "Keys", "--after", "Audio 1", "--instrument",
                         "--stereo", out=self.out / "stereo")
        self.assertEqual(channel_formats(data(mono))[row(mono, "Keys")["owner"]], 1)
        self.assertEqual(channel_formats(data(stereo))[row(stereo, "Keys")["owner"]], 2)

    def test_a_stereo_instrument_tracks_instrument_slot_is_stereo_too(self):
        """Logic takes an instrument channel's width from its instrument slot: over a mono slot
        it re-saved the channel as mono."""
        from logicxkit.logic.services.mixer.channel_alloc import INST_SLOT_WIDTH_AT
        from logicxkit.logic.services.mixer.slots import slot_index_base
        from logicxkit.logic.services.stream.stream import HEADER, project_records
        for flags, width in (((), 1), (("--stereo",), 2)):
            with self.subTest(width):
                dest = written(self, "add-track", THREE, "--name", "Keys", "--after", "Audio 1",
                               "--instrument", *flags, out=self.out / str(width))
                (slot,) = (r.raw[HEADER:] for r in project_records(data(dest))
                           if r.tag == b"UCuA" and r.owner == row(dest, "Keys")["owner"]
                           and r.key == slot_index_base(data(dest)))
                self.assertEqual([slot[at] for at in INST_SLOT_WIDTH_AT], [width, width])

    def test_stack_create(self):
        dest = written(self, "stack-create", THREE, "--name", "Drums", "--track", "Audio 1", "--track", "Audio 2",
                       out=self.out)
        stacks = read_stacks(data(dest), count(dest))
        self.assertEqual([(s.name, len(s.members)) for s in stacks], [("Drums", 2)])
        self.assertEqual(names(dest), ["Drums", "Audio 1", "Audio 2", "Audio 3", "Stereo Out"])
        self.assertEqual(count(dest), 4)

    def test_an_out_that_is_a_file_is_refused_in_a_sentence(self):
        afile = self.out / "afile"
        afile.write_bytes(b"")
        code, text = wrapped("rename", _goldens.path(THREE), "--out", afile, "--track", "Audio 2=Snare")
        self.assertEqual(code, 1, text)
        self.assertIn("is a file, not a directory", text)
        self.assertEqual(afile.read_bytes(), b"")

    def test_a_bundle_without_metadata_is_named_as_no_project(self):
        bundle = self.out / "bare.logicx"
        (bundle / "Alternatives/000").mkdir(parents=True)
        (bundle / "Alternatives/000/ProjectData").write_bytes(data(THREE))
        code, text = wrapped("project", bundle)
        self.assertEqual(code, 1, text)
        self.assertIn("no MetaData.plist", text)
        self.assertIn("not a Logic project", text)

    def test_a_track_that_is_not_there_is_refused_and_nothing_is_written(self):
        code, text = run("rename", _goldens.path(THREE), "--out", self.out, "--track", "Nope=X")
        self.assertEqual(code, 1, text)
        self.assertIn("Nope", text)
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
