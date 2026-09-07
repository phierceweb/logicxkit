"""Environment overrides: an empty value is unset, not the empty path.

`.env.example` ships every optional key with no value and `bin/run` sources it, so this is the
difference between a golden reading `resources/strips` and reading the repo root.
"""

import os
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401  — puts logicxkit on the path
from logicxkit.utils.env import env_path, env_str

VAR = "LOGICXKIT_TEST_ENV_PROBE"


class EnvStrTest(unittest.TestCase):
    def test_unset_yields_the_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(VAR, None)
            self.assertEqual(env_str(VAR, "fallback"), "fallback")

    def test_present_but_empty_yields_the_default(self):
        with mock.patch.dict(os.environ, {VAR: ""}):
            self.assertEqual(env_str(VAR, "fallback"), "fallback")

    def test_a_real_value_wins(self):
        with mock.patch.dict(os.environ, {VAR: "chosen"}):
            self.assertEqual(env_str(VAR, "fallback"), "chosen")

    def test_no_default_is_none_not_empty(self):
        with mock.patch.dict(os.environ, {VAR: ""}):
            self.assertIsNone(env_str(VAR))


class EnvPathTest(unittest.TestCase):
    def test_an_empty_value_does_not_become_the_working_directory(self):
        with mock.patch.dict(os.environ, {VAR: ""}):
            got = env_path(VAR, "resources/strips")
        self.assertEqual(got, Path("resources/strips"))
        self.assertNotEqual(got, Path(""))

    def test_a_tilde_is_expanded(self):
        with mock.patch.dict(os.environ, {VAR: "~/elsewhere"}):
            self.assertEqual(env_path(VAR, "x"), Path.home() / "elsewhere")

    def test_a_path_default_survives(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(VAR, None)
            self.assertEqual(env_path(VAR, Path("/abs/default")), Path("/abs/default"))


class EveryOverrideGoesThroughItTest(unittest.TestCase):
    """The three src roots and the test roots all fall back rather than collapsing."""

    def test_empty_env_leaves_every_root_at_its_default(self):
        import importlib
        from logicxkit.logic.services import library
        from logicxkit.utils import data
        empty = {"LOGICXKIT_STRIP_ROOT": "", "LOGICXKIT_DATA": "", "LOGICXKIT_RESOURCES": "",
                 "LOGICXKIT_TEMPLATES": "", "LOGICXKIT_LOGIC_PREFS": ""}
        with mock.patch.dict(os.environ, empty):
            self.assertEqual(library.strip_library(), library.DEFAULT)
            self.assertTrue(str(data.data_root()).endswith("resources/data"), data.data_root())
            paths = importlib.reload(_paths)
            self.assertEqual(paths.RESOURCES, paths.REPO / "resources")
            self.assertEqual(paths.TEMPLATES, paths.REPO / "resources/templates")
        importlib.reload(_paths)


if __name__ == "__main__":
    unittest.main()
