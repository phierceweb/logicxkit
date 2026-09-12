"""The goldens' own unit tests must leave the run's tally and env vars as they found them."""

import io
import unittest
from unittest import mock

import _goldens

MODULES = ("test_goldens_resolution", "test_goldens_report")


def _run(name: str) -> unittest.TestResult:
    module = __import__(name)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    return unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)


class TallySurvivesTest(unittest.TestCase):
    def test_the_goldens_unit_tests_leave_the_run_tally_alone(self):
        sentinel = {"sentinel-found": True, "sentinel-missing": False}
        with mock.patch.dict(_goldens.asked, sentinel, clear=True):
            for name in MODULES:
                _run(name)
            self.assertEqual(dict(_goldens.asked), sentinel)

    def test_the_line_still_reports_after_they_have_run(self):
        with mock.patch.dict(_goldens.asked, {"sentinel-found": True}, clear=True):
            for name in MODULES:
                _run(name)
            self.assertEqual(_goldens.report(), "goldens: 1 of 1 keys found")


class RequireEnvTest(unittest.TestCase):
    def test_the_goldens_unit_tests_pass_under_the_require_env(self):
        with mock.patch.dict("os.environ", {_goldens.REQUIRE: "1"}):
            for name in MODULES:
                with self.subTest(module=name):
                    result = _run(name)
                    self.assertEqual(
                        (len(result.failures), len(result.errors)), (0, 0),
                        "\n".join(t for _, t in result.failures + result.errors))

    def test_they_leave_the_require_env_as_they_found_it(self):
        with mock.patch.dict("os.environ", {_goldens.REQUIRE: "1"}):
            for name in MODULES:
                _run(name)
            import os
            self.assertEqual(os.environ.get(_goldens.REQUIRE), "1")


if __name__ == "__main__":
    unittest.main()
