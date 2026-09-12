"""Writers leave no partial copy: a gate refusal or a failing step discards it, and a missing
`--out` or an existing image is refused before anything is written."""

import plistlib
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from _records import chan, uuid
from test_stack_create import TRACKS, session

from logicxkit.logic._edit import CommandError, bump_track_count, edit_copy
from logicxkit.logic._inspect import cmd_stacks
from logicxkit.logic.cli import cmd_levels
from logicxkit.logic.services.levels import read_levels
from logicxkit.logic.services.stacks import read_tracks


def bundle(root: Path, name: str, data: bytes) -> Path:
    alt = root / f"{name}.logicx" / "Alternatives" / "000"
    alt.mkdir(parents=True)
    (alt / "ProjectData").write_bytes(data)
    (alt / "MetaData.plist").write_bytes(plistlib.dumps({"NumberOfTracks": TRACKS}))
    return alt.parents[1]


def quiet_fader() -> bytes:
    loud = chan(0, "Audio 1", uuid=uuid(88), stack_index=1)
    return session().replace(loud, chan(0, "Audio 1", uuid=uuid(88), stack_index=1, fader=50))


class LevelsToTest(unittest.TestCase):
    def test_a_refused_result_leaves_no_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst = bundle(root, "Src", session()), bundle(root, "Dst", quiet_fader())
            with mock.patch("logicxkit.logic.cli.copy_levels",
                            side_effect=lambda s, d, by: (d + b"JUNK", {"matched": 0, "changed": [], "unchanged": 0, "unmatched": []})), \
                 mock.patch("builtins.print"):
                rc = cmd_levels(Namespace(project=str(src), to=str(dst), out=str(root / "out"), by="owner", json=False))
            self.assertEqual(rc, 1)
            self.assertFalse((root / "out").exists() and any((root / "out").iterdir()))

    def test_a_clean_copy_lands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst = bundle(root, "Src", session()), bundle(root, "Dst", quiet_fader())
            with mock.patch("builtins.print"):
                rc = cmd_levels(Namespace(project=str(src), to=str(dst), out=str(root / "out"), by="owner", json=False))
            self.assertEqual(rc, 0)
            out = (root / "out/Dst.logicx/Alternatives/000/ProjectData").read_bytes()
            self.assertEqual(read_levels(out)[0]["fader"], 90)


class StacksMoveTest(unittest.TestCase):
    def test_a_refused_result_leaves_no_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = bundle(root, "Song", session())
            with mock.patch("logicxkit.logic.services.stacks.move_to_stack",
                            side_effect=lambda d, *a, **k: d + b"JUNK"), mock.patch("builtins.print"):
                rc = cmd_stacks(Namespace(logicx=str(src), move=["Test Bounce:Drums"], out=str(root / "out")))
            self.assertEqual(rc, 1)
            self.assertFalse((root / "out").exists() and any((root / "out").iterdir()))

    def test_a_clean_move_lands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = bundle(root, "Song", session())
            with mock.patch("builtins.print"):
                rc = cmd_stacks(Namespace(logicx=str(src), move=["Test Bounce:Drums"], out=str(root / "out")))
            self.assertEqual(rc, 0)
            out = (root / "out/Song.logicx/Alternatives/000/ProjectData").read_bytes()
            rows = {r["name"]: r for r in read_tracks(out, TRACKS)}
            self.assertTrue(rows["Test Bounce"]["member"])


class StepRaisesTest(unittest.TestCase):
    def _two_alternatives(self, root: Path) -> Path:
        src = bundle(root, "Song", session())
        alt = src / "Alternatives" / "001"
        alt.mkdir()
        (alt / "ProjectData").write_bytes(session())
        (alt / "MetaData.plist").write_bytes(plistlib.dumps({"NumberOfTracks": TRACKS}))
        return src

    def test_a_step_that_raises_on_a_later_alternative_leaves_no_bundle(self):
        for exc in (CommandError("'Ride': no track by that name"), ValueError("another layout")):
            def step(data, count, data_file, exc=exc):
                if data_file.parent.name == "001":
                    raise exc
                bump_track_count(data_file)
                return data

            with self.subTest(raised=type(exc).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src = self._two_alternatives(root)
                with mock.patch("builtins.print"), self.assertRaises(type(exc)):
                    edit_copy(src, root / "out", step)
                self.assertFalse((root / "out" / "Song.logicx").exists())


if __name__ == "__main__":
    unittest.main()


class LevelsSourceTest(unittest.TestCase):
    def test_a_missing_source_project_is_refused_with_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dst = bundle(root, "Dst", session())
            with mock.patch("builtins.print") as printed:
                rc = cmd_levels(Namespace(project=str(root / "nope.logicx"), to=str(dst), out=str(root / "out"), by="owner", json=False))
            self.assertEqual(rc, 2)
            self.assertTrue(any("nope.logicx" in str(c) for c in printed.call_args_list), printed.call_args_list)


class ApplyTemplateOutTest(unittest.TestCase):
    def test_a_real_run_without_out_is_refused_before_anything_is_read(self):
        from logicxkit.logic.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = bundle(root, "Template", session())
            project = bundle(root, "Song", quiet_fader())
            with mock.patch("builtins.print") as printed:
                rc = main(["apply-template", str(template), str(project)])
            self.assertEqual(rc, 2)
            self.assertTrue(any("--out" in str(c) for c in printed.call_args_list), printed.call_args_list)


class ImageOverwriteTest(unittest.TestCase):
    def _bundle_with_image(self, root: Path) -> Path:
        src = bundle(root, "Song", session())
        (src / "Alternatives/000/WindowImage.jpg").write_bytes(b"\xff\xd8 new")
        return src

    def test_an_existing_file_is_kept_without_overwrite(self):
        from logicxkit.logic.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, out = self._bundle_with_image(root), root / "shot.jpg"
            out.write_bytes(b"mine")
            with mock.patch("builtins.print"):
                self.assertEqual(main(["image", str(src), "-o", str(out)]), 1)
                self.assertEqual(out.read_bytes(), b"mine")
                self.assertEqual(main(["image", str(src), "-o", str(out), "--overwrite"]), 0)
            self.assertEqual(out.read_bytes(), b"\xff\xd8 new")
