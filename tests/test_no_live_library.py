"""`_liveguard` fires on the live library and stays out of the way everywhere else."""

import unittest
from pathlib import Path

import _liveguard
import _paths


class OffendingTest(unittest.TestCase):
    def test_the_live_library_is_refused(self):
        for p in ("~/Music/Audio Music Apps/Channel Strip Settings/Track/L/S.cst",
                  "~/Music/Audio Music Apps/Project Templates/T.logicx",
                  "~/Music/Logic/Song.logicx"):
            with self.subTest(p):
                self.assertIsNotNone(_liveguard.offending(Path(p).expanduser()))

    def test_staged_copies_and_scene_are_allowed(self):
        for p in (_paths.RESOURCES / "templates", _paths.STRIP_ROOT, _paths.SCENE, Path("/tmp/x")):
            with self.subTest(str(p)):
                self.assertIsNone(_liveguard.offending(p))

    def test_a_file_descriptor_is_not_a_path(self):
        self.assertIsNone(_liveguard.offending(3))


class InstalledTest(unittest.TestCase):
    """conftest installs it, so an actual read raises rather than returning bytes."""

    def test_opening_a_live_library_path_raises(self):
        target = Path.home() / "Music/Audio Music Apps/Channel Strip Settings"
        before = list(_liveguard.violations)
        with self.assertRaises(_liveguard.LiveLibraryRead):
            open(target / "Track/Nope.cst", "rb")
        with self.assertRaises(_liveguard.LiveLibraryRead):
            (target / "Track/Nope.cst").read_bytes()
        _liveguard.violations[:] = before          # a fired guard must not fail this run

    def test_a_staged_read_still_works(self):
        self.assertTrue(Path(_paths.__file__).read_bytes().startswith(b'"""'))


class GuardCoverageTest(unittest.TestCase):
    """Each way a test could reach the live library, and the exemption."""

    LIVE = Path.home() / "Music/Audio Music Apps"

    def _refused(self, fn):
        before = list(_liveguard.violations)
        with self.assertRaises(_liveguard.LiveLibraryRead):
            fn()
        _liveguard.violations[:] = before

    def test_a_glob_over_the_live_library_is_refused(self):
        import os
        self._refused(lambda: os.listdir(self.LIVE))
        self._refused(lambda: os.scandir(self.LIVE))

    @unittest.skipUnless(LIVE.exists(), "no live library to read")
    def test_rglob_over_the_live_library_is_refused(self):
        # rglob reaches os.scandir only when the directory exists; with none there it yields
        # nothing and the guard has nothing to intercept.
        self._refused(lambda: list(self.LIVE.rglob("*.cst")))

    def test_shelling_out_at_the_live_library_is_refused(self):
        import subprocess
        self._refused(lambda: subprocess.run(["ls", str(self.LIVE)], capture_output=True))
        self._refused(lambda: subprocess.run(["cp", "-R", str(self.LIVE / "x"), "/tmp/y"]))

    def test_an_unrelated_subprocess_still_runs(self):
        import subprocess
        self.assertEqual(subprocess.run(["true"]).returncode, 0)

    def test_the_scene_stays_reachable(self):
        self.assertIsNone(_liveguard.offending(_paths.SCENE))
        self.assertIsNone(_liveguard.offending(str(_paths.SCENE)))
        # and listing its directory is not the library
        self.assertIsNotNone(_liveguard.offending(_paths.SCENE.parent))


class ManifestContainmentTest(unittest.TestCase):
    """A manifest entry cannot point a golden outside resources/."""

    def test_an_absolute_or_dotdot_path_is_refused(self):
        import _goldens
        for bad in ("/somewhere/else/x.logicx", "../../elsewhere/x.logicx"):
            with self.subTest(bad), self.assertRaises(ValueError):
                _goldens._under_resources("k", bad)

    def test_a_normal_relative_path_passes(self):
        import _goldens
        self.assertEqual(_goldens._under_resources("k", "experiments/1.logicx"),
                         "experiments/1.logicx")


class StagedStripsTest(unittest.TestCase):
    """A rig config whose donors sit outside the live library must fail, not read through."""

    def test_a_live_library_donor_is_rebased(self):
        from logicxkit.logic.services.library import DEFAULT as LIVE
        cfg = {"donors": {"d": {"cst": str(LIVE / "Track/L/D.cst"), "type": 1}}}
        got = _paths.onto_staged_strips(cfg)["donors"]["d"]["cst"]
        self.assertEqual(Path(got), _paths.STRIP_ROOT / "Track/L/D.cst")

    def test_a_relative_donor_is_left_to_the_strip_root(self):
        cfg = {"donors": {"d": {"cst": "Track/L/D.cst", "type": 1}}}
        self.assertEqual(_paths.onto_staged_strips(cfg)["donors"]["d"]["cst"], "Track/L/D.cst")

    def test_a_donor_outside_the_library_is_refused(self):
        for bad in ("/Volumes/AudioDrive/Strips/D.cst", "~/Documents/Strips/D.cst"):
            with self.subTest(bad), self.assertRaises(ValueError):
                _paths.onto_staged_strips({"donors": {"d": {"cst": bad, "type": 1}}})


if __name__ == "__main__":
    unittest.main()
