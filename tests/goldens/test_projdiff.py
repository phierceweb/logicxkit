"""logic diff — project↔project chain/metadata diff and project↔strip-library drift.

Pure functions tested on synthetic reports; CLI tested on synthetic .logicx bundles;
goldens (skip-if-missing) pin the known tracking-vs-Mix delta (the mix-only Stealth
limiter) on the staged templates.

The real-file part of tests/logic/test_projdiff.py; skips without the owner's files."""

import os
import unittest
from pathlib import Path
import _goldens
import _paths
from logicxkit.logic.services.projdiff import diff_against_library, diff_projects

TRK = _goldens.path("tracking-template")
MIX = str(_paths.project("Mix"))
LIB = os.path.expanduser(str(_paths.STRIP_ROOT))


@unittest.skipIf(not os.path.isdir(MIX), "staged Mix template not present")
@_goldens.needs("tracking-template")
class GoldenTemplateDiffTest(unittest.TestCase):
    def test_tracking_vs_mix_shows_the_mix_only_stealth(self):
        from logicxkit.logic import read_project
        d = diff_projects(read_project(TRK), read_project(Path(MIX)))
        self.assertTrue(d["channels"], "same-session templates should still differ")
        self.assertIn("Stealth", repr(d["channels"]))


@unittest.skipIf(not (os.path.isdir(MIX) and os.path.isdir(LIB)),
                 "real template or strip library not present")
class GoldenLibraryDriftTest(unittest.TestCase):
    def test_runs_against_real_library(self):
        # the Mix template embeds chains AND references strips — the drift check's home turf
        from logicxkit.logic import read_project
        rows = diff_against_library(read_project(Path(MIX)), LIB)
        self.assertTrue(rows)
        self.assertTrue(all(r["status"] in ("match", "drift", "missing") for r in rows))


if __name__ == "__main__":
    unittest.main()
