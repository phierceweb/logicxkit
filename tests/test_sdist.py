"""The sdist carries only what MANIFEST.in names: nothing gitignored under docs/ or config/, no
corpus, no golden tests, and no path of a real machine; it and the wheel built from it carry every
packaged data file. The leak gate reads the git index, so this is the only check that sees the
archives themselves. Skips without the `build` package."""

import importlib.util
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from _paths import REPO, tracked

FORBIDDEN_DIRS = ("docs/pf-core/", "config/local/", "tests/corpus/", "tests/goldens/")
# Built from parts so this file's own text carries none of them.
PATH_SHAPES = tuple("/".join(p) for p in (("", "Users", ""), ("~", "projects", ""), ("", "Volumes", "")))
# The guard test names Logic's library paths on purpose; the gate exempts it the same way.
SHAPE_EXEMPT = ("tests/test_no_live_library.py",)


@unittest.skipUnless(importlib.util.find_spec("build"), "the build package is not installed")
class SdistTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        run = subprocess.run([sys.executable, "-m", "build", "--outdir", cls.tmp.name, str(REPO)],
                             capture_output=True, text=True, cwd=REPO)
        if run.returncode != 0:
            raise unittest.SkipTest("the sdist could not be built here:\n" + run.stderr[-1500:])
        (archive,) = Path(cls.tmp.name).glob("*.tar.gz")
        with tarfile.open(archive) as tar:
            cls.members = {m.name.split("/", 1)[1]: tar.extractfile(m).read()
                           for m in tar.getmembers() if "/" in m.name and m.isfile()}
        (wheel,) = Path(cls.tmp.name).glob("*.whl")
        with zipfile.ZipFile(wheel) as whl:
            cls.wheel = set(whl.namelist())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def index(self, *paths: str) -> list[str]:
        names = tracked(*paths)
        if names is None:
            self.skipTest("not a git checkout")
        return names

    def test_every_shipped_file_is_tracked_by_git(self):
        """`recursive-include tests *.py` would take an untracked scratch file along; git's index is
        the list of what may ship."""
        tracked = set(self.index())
        generated = ("PKG-INFO", "setup.cfg")
        untracked = sorted(n for n in self.members
                           if n and n not in tracked and not n.endswith(generated) and ".egg-info/" not in n)
        self.assertEqual(untracked, [])

    def test_nothing_gitignored_or_golden_ships(self):
        for prefix in FORBIDDEN_DIRS:
            with self.subTest(prefix):
                self.assertEqual([n for n in self.members if n.startswith(prefix)], [])

    def test_the_named_files_ship(self):
        for name in ("docs/CAPABILITIES.md", "docs/commands.md", "config/example-mastering.json",
                     "tests/conftest.py", "tests/_goldens.py", "CHANGELOG.md"):
            with self.subTest(name):
                self.assertIn(name, self.members)

    def test_every_packaged_data_file_ships_in_both(self):
        from logicxkit.utils.data import PACKAGED_KINDS
        tracked = [n for n in self.index("src/logicxkit/data") if n.split("/")[3:4] and n.split("/")[3] in PACKAGED_KINDS]
        self.assertTrue(tracked)
        for name in tracked:
            with self.subTest(name):
                self.assertIn(name, self.members)
                self.assertIn(name.removeprefix("src/"), self.wheel)

    def test_nothing_untracked_ships_as_package_data(self):
        """package-data globs whatever sits in the folder; an untracked file there — a donor
        harvested into the package by hand — would ship with no gate having read it."""
        tracked = {n.removeprefix("src/") for n in self.index("src/logicxkit")}
        shipped = {n for n in self.wheel if n.startswith("logicxkit/") and not n.endswith("/")}
        self.assertEqual(sorted(shipped - tracked), [])

    def test_no_member_keeps_a_bookmark_field(self):
        import importlib.util
        tool = REPO / "tools" / "stage_public.py"
        if not tool.exists():
            self.skipTest(f"no staging tool at {tool}")
        spec = importlib.util.spec_from_file_location("stage_public", tool)
        stage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stage)
        self.assertEqual([n for n, raw in self.members.items() if stage.bookmark_leaks(raw)], [])

    def test_no_text_member_names_a_real_path(self):
        for name, raw in self.members.items():
            if name in SHAPE_EXEMPT:
                continue
            try:
                text = raw.decode()
            except UnicodeDecodeError:
                continue
            for shape in PATH_SHAPES:
                with self.subTest(name, shape=shape):
                    self.assertNotIn(shape, text)


if __name__ == "__main__":
    unittest.main()
