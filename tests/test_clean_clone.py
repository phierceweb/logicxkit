"""The suite a fresh clone runs — no data root, only the public corpus — must be green. A
machine with both roots populated hides a test that needs one without guarding it."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _paths import REPO, RESOURCES

SUBRUN = "LOGICXKIT_CLEAN_CLONE_SUBRUN"
PUBLIC = RESOURCES / "public"


def _env(resources: str, data: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LOGICXKIT_", "PYTEST_"))}
    env |= {"LOGICXKIT_RESOURCES": resources, "LOGICXKIT_DATA": data, SUBRUN: "1",
            "LOGICXKIT_REQUIRE_GOLDENS": "public"}
    return env


def _passed(stdout: str) -> int:
    m = re.search(r"(\d+) passed", stdout)
    return int(m.group(1)) if m else 0


@unittest.skipIf(os.environ.get(SUBRUN), "the inner run must not recurse")
@unittest.skipUnless(PUBLIC.is_dir(), f"no public corpus staged at {PUBLIC} (bin/run fetch-corpus)")
class CleanCloneTest(unittest.TestCase):
    def test_the_suite_is_green_with_the_public_corpus_and_no_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "resources").mkdir()
            (root / "resources" / "public").symlink_to(PUBLIC.resolve())
            (root / "nodata").mkdir()
            run = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                cwd=REPO, capture_output=True, text=True,
                env=_env(str(root / "resources"), str(root / "nodata")))
        failed = [ln for ln in run.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
        self.assertEqual(run.returncode, 0,
                         "the suite a fresh clone runs is not green:\n" + "\n".join(failed)
                         + "\n" + run.stdout[-2000:])
        self.assertGreater(_passed(run.stdout), 0, run.stdout[-2000:])


class InnerEnvTest(unittest.TestCase):
    def test_the_inner_run_requires_the_public_goldens_and_ignores_pytest_options(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"PYTEST_ADDOPTS": "-k nothing", "PYTEST_PLUGINS": "x",
                                          "LOGICXKIT_REQUIRE_GOLDENS": "1"}):
            env = _env("/r", "/d")
        self.assertEqual(env["LOGICXKIT_REQUIRE_GOLDENS"], "public")
        self.assertFalse({"PYTEST_ADDOPTS", "PYTEST_PLUGINS"} & set(env))

    def test_a_run_that_passed_nothing_counts_as_zero(self):
        self.assertEqual(_passed("5 skipped in 0.1s"), 0)
        self.assertEqual(_passed("752 passed, 153 skipped in 3.8s"), 752)


if __name__ == "__main__":
    unittest.main()
