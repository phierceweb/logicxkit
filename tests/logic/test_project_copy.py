"""Copying a project for an edit: the folder around a bundle comes along, Logic's autosaves stay
behind, and an output that is a previous copy is refused rather than nested."""

import tempfile
import unittest
from pathlib import Path

from test_retrack import project


class ProjectFolderTest(unittest.TestCase):
    """A bundle given by its own path still brings its `Audio Files` along."""

    def test_the_bundle_path_copies_the_folder_around_it(self):
        import tempfile

        from logicxkit.logic.services.arrange.project_copy import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "in/Song"
            bundle = folder / "Song.logicx"
            (bundle / "Alternatives/000").mkdir(parents=True)
            (bundle / "Alternatives/000/ProjectData").write_bytes(project())
            (folder / "Audio Files").mkdir()
            (folder / "Audio Files/take.wav").write_bytes(b"RIFF" + b"\x00" * 64)
            copied = copy_project(bundle, root / "out")
            self.assertEqual(copied["dest"], root / "out/Song/Song.logicx")
            self.assertTrue((root / "out/Song/Audio Files/take.wav").exists())

    def test_a_bundle_without_audio_beside_it_copies_alone(self):
        import tempfile

        from logicxkit.logic.services.arrange.project_copy import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "in/templates/Song.logicx"
            (bundle / "Alternatives/000").mkdir(parents=True)
            (bundle / "Alternatives/000/ProjectData").write_bytes(project())
            copied = copy_project(bundle, root / "out")
            self.assertEqual(copied["dest"], root / "out/Song.logicx")

    def test_logic_autosaves_stay_behind(self):
        """Logic offers an autosave on open, and the source's predates every edit to the copy."""
        from logicxkit.logic.services.arrange.project_copy import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alt = root / "in/Song/Song.logicx/Alternatives/000"
            (alt / "Autosave").mkdir(parents=True)
            (alt / "Autosave/2026-09-25 02:48:04Z.songData").write_bytes(b"before the edit")
            (alt / "ProjectData").write_bytes(project())
            copied = copy_project(root / "in/Song", root / "out")
            self.assertEqual([p.name for p in (copied["dest"] / "Alternatives/000").iterdir()], ["ProjectData"])
            self.assertTrue((alt / "Autosave/2026-09-25 02:48:04Z.songData").exists())

    def test_the_copytree_fallback_leaves_them_too(self):
        import subprocess
        from unittest import mock

        from logicxkit.logic.services.arrange.project_copy import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "in/templates/Song.logicx"
            (bundle / "Alternatives/000/Autosave").mkdir(parents=True)
            (bundle / "Alternatives/000/ProjectData").write_bytes(project())
            with mock.patch("logicxkit.logic.services.arrange.project_copy.subprocess.run",
                            return_value=subprocess.CompletedProcess([], 1)):
                copied = copy_project(bundle, root / "out")
            self.assertEqual([p.name for p in (copied["dest"] / "Alternatives/000").iterdir()], ["ProjectData"])


class NestedOutputTest(unittest.TestCase):
    """`--out` names the directory the copy goes INTO, not the copy itself.

    Aiming it at a previous output nested the new copy inside the stale one, leaving the stale
    build at the path Logic opens — so a correct rebuild looked like it had done nothing.
    """

    def _project(self, root: Path, name: str) -> Path:
        bundle = root / name / f"{name}.logicx"
        (bundle / "Alternatives/000").mkdir(parents=True)
        (bundle / "Alternatives/000/ProjectData").write_bytes(project())
        return root / name

    def test_pointing_out_at_a_previous_copy_is_refused(self):
        from logicxkit.logic.services.arrange.project_copy import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = self._project(root / "in", "Song")
            out = root / "out"
            copy_project(src, out)                       # first build: out/Song
            with self.assertRaises(ValueError) as caught:
                copy_project(src, out / "Song")          # the mistake
            self.assertIn("already a copy", str(caught.exception))

    def test_rebuilding_into_the_same_container_replaces_in_place(self):
        from logicxkit.logic.services.arrange.project_copy import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = self._project(root / "in", "Song")
            out = root / "out"
            first = copy_project(src, out)["dest"]
            second = copy_project(src, out)["dest"]
            self.assertEqual(first, second, "same path, no nesting")
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["Song"])


if __name__ == "__main__":
    unittest.main()
