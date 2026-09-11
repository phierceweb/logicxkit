"""`py.typed` must sit inside the package and be declared as package data, or a wheel drops it."""

import unittest
from pathlib import Path

import _paths  # noqa: F401

import logicxkit


class TypedMarkerTest(unittest.TestCase):
    def test_marker_is_in_the_package(self):
        self.assertTrue((Path(logicxkit.__file__).resolve().parent / "py.typed").is_file())

    def test_marker_is_declared_as_package_data(self):
        import tomllib
        pyproject = Path(logicxkit.__file__).resolve().parents[2] / "pyproject.toml"
        if not pyproject.exists():
            self.skipTest("not running from a source tree")
        cfg = tomllib.loads(pyproject.read_text())
        self.assertIn("py.typed", cfg["tool"]["setuptools"]["package-data"]["logicxkit"])
        self.assertIn("Typing :: Typed", cfg["project"]["classifiers"])


if __name__ == "__main__":
    unittest.main()
