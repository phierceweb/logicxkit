"""`logic donors` into the data root leaves the plug-ins the package ships to the package, since
the package's own donor wins over the root's; into a named `--library` it harvests them all.
Skips without the public corpus."""

import contextlib
import io
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import _goldens
from logicxkit.logic._donors_cmd import cmd_donors
from logicxkit.utils import data

KEY = "inserts-native-all-logic"


def _harvest(library: str | None):
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        code = cmd_donors(Namespace(project=str(_goldens.path(KEY)), library=library, refresh=False, as_name=None))
    return code, text.getvalue()


@_goldens.needs(KEY)
class DonorsIntoTheRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = os.environ.get(data.ENV)
        os.environ[data.ENV] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop(data.ENV, None) if self.old is None else os.environ.__setitem__(data.ENV, self.old))
        self.packaged = {p.stem for p in (data.PACKAGED / "donors").glob("*.slot")}

    def test_the_packages_own_are_left_to_it_and_named(self):
        code, out = _harvest(None)
        self.assertEqual(code, 0, out)
        written = {p.stem for p in (Path(self.tmp.name) / "donors").glob("*.slot")}
        self.assertFalse(written & self.packaged, written & self.packaged)
        self.assertIn("the package's own, not harvested", out)
        self.assertIn("Compressor", out)

    def test_a_named_library_takes_them_all(self):
        lib = Path(self.tmp.name) / "mine"
        code, out = _harvest(str(lib))
        self.assertEqual(code, 0, out)
        self.assertIn("154-v5", {p.stem for p in lib.glob("*.slot")})


if __name__ == "__main__":
    unittest.main()
