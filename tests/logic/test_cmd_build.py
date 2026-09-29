"""`build` on the shipped strips example: it runs from a checkout against tests/corpus/strips, and
a missing strip is named with the root it was looked for under."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import run
from _paths import REPO

STRIPS = ("strip-mixing-kick-ours", "strip-mixing-sub-kick-ours", "strip-kit-mics-ours")
SPEC = REPO / "config" / "example-strips.json"


@_goldens.needs(*STRIPS)
class BuildExampleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        before = os.getcwd()
        os.chdir(self.out)                                  # the spec's output_root is relative
        self.addCleanup(os.chdir, before)

    def test_the_example_builds_against_the_corpus_strips(self):
        root = _goldens.path(STRIPS[0]).parents[3]
        with mock.patch.dict(os.environ, {"LOGICXKIT_STRIP_ROOT": str(root)}):
            code, text = run("build", SPEC)
        self.assertEqual(code, 0, text)
        self.assertIn("2 written, 0 skipped, 0 failed", text)
        self.assertEqual(sorted(p.name for p in (self.out / "out/strips/Example Kit/Drums").glob("*.cst")),
                         ["Demo Trk - Kick.cst", "Demo Trk - Sub Kick.cst"])

    def test_a_missing_strip_is_named_with_the_root_it_was_looked_for_under(self):
        empty = self.out / "no-strips"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"LOGICXKIT_STRIP_ROOT": str(empty)}):
            code, text = run("build", SPEC)
        self.assertEqual(code, 1, text)
        self.assertIn("no strip at", text)
        self.assertIn(str(empty), text)
        self.assertIn("LOGICXKIT_STRIP_ROOT", text)
        self.assertNotIn("Errno", text)


if __name__ == "__main__":
    unittest.main()
