"""The Swift scripts must resolve from an installed package, not just from a checkout.

`native_dir()` used to walk up to the repo root, which is only correct for an editable install:
from a wheel it pointed at a directory beside `site-packages` that does not exist, and `logic
ocr` surfaced the miss as a Swift compiler error naming an internal path.
"""

import unittest
from pathlib import Path

import _paths  # noqa: F401  — puts logicxkit on the path

import logicxkit
from logicxkit.utils.swiftrun import SwiftRunError, native_dir, run_swift

SCRIPTS = ("auprobe.swift", "aulatency.swift", "vision_ocr.swift")


class NativeDirTest(unittest.TestCase):
    def test_it_sits_inside_the_installed_package(self):
        self.assertEqual(native_dir(), Path(logicxkit.__file__).resolve().parent / "native")

    def test_every_script_is_there(self):
        for name in SCRIPTS:
            with self.subTest(name):
                self.assertTrue((native_dir() / name).is_file(), f"{name} missing from the package")

    def test_the_package_declares_them_as_package_data(self):
        """A wheel that drops native/ resolves the directory and finds it empty."""
        import tomllib
        root = Path(logicxkit.__file__).resolve().parents[2]
        pyproject = root / "pyproject.toml"
        if not pyproject.exists():          # installed, not a checkout — nothing to assert
            self.skipTest("not running from a source tree")
        cfg = tomllib.loads(pyproject.read_text())
        self.assertIn("native/*.swift",
                      cfg["tool"]["setuptools"]["package-data"]["logicxkit"])


class MissingScriptTest(unittest.TestCase):
    def test_a_missing_script_is_refused_before_swift_sees_it(self):
        import shutil
        if shutil.which("swift") is None:
            self.skipTest("no swift toolchain")
        with self.assertRaises(SwiftRunError) as e:
            run_swift(native_dir() / "not_a_script.swift", [], 5)
        self.assertIn("not installed", str(e.exception))


if __name__ == "__main__":
    unittest.main()
