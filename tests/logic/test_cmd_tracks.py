"""The track commands run in-process on a public corpus bundle, and the bundle they write read
back: reorder, colour, rename, hide, add-track, stack-create."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, run, wrapped, written

from logicxkit.logic.services.stacks import read_stacks, read_tracks

THREE = "tracks-three-audio-logic"          # Audio 1, Audio 2, Audio 3, then the Stereo Out row


def rows(bundle) -> list[dict]:
    return read_tracks(data(bundle), count(bundle))


def names(bundle) -> list[str]:
    return [r["name"] for r in rows(bundle)]


def row(bundle, name: str) -> dict:
    return next(r for r in rows(bundle) if r["name"] == name)


@_goldens.needs(THREE)
class TrackCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_rename(self):
        dest = written(self, "rename", THREE, "--track", "Audio 2=Snare", out=self.out)
        self.assertEqual(names(dest), ["Audio 1", "Snare", "Audio 3", "Stereo Out"])

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
        from logicxkit.logic.services.insert import channel_formats
        mono = written(self, "add-track", THREE, "--name", "Keys", "--after", "Audio 1", "--instrument",
                       out=self.out / "mono")
        stereo = written(self, "add-track", THREE, "--name", "Keys", "--after", "Audio 1", "--instrument",
                         "--stereo", out=self.out / "stereo")
        self.assertEqual(channel_formats(data(mono))[row(mono, "Keys")["owner"]], 1)
        self.assertEqual(channel_formats(data(stereo))[row(stereo, "Keys")["owner"]], 2)

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
