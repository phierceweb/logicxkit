"""Data lookup: the package's own files first, the data root for what the package lacks, a named
error third."""

import os
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from logicxkit.utils import data


class LookupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = os.environ.get(data.ENV)
        os.environ[data.ENV] = str(self.root)

    def tearDown(self):
        if self.old is None:
            os.environ.pop(data.ENV, None)
        else:
            os.environ[data.ENV] = self.old
        self.tmp.cleanup()

    def test_the_package_supplies_a_template_the_root_lacks(self):
        p = data.data_file("logic", "audio-channel-12.3.1.json")
        self.assertEqual(p, data.PACKAGED / "logic" / "audio-channel-12.3.1.json")
        self.assertTrue(p.is_file())

    def test_the_package_wins_over_the_roots_file_of_the_same_name(self):
        (self.root / "logic").mkdir()
        (self.root / "logic" / "audio-channel-12.3.1.json").write_text("{}")
        self.assertEqual(data.data_file("logic", "audio-channel-12.3.1.json"),
                         data.PACKAGED / "logic" / "audio-channel-12.3.1.json")

    def test_the_root_supplies_a_file_the_package_lacks(self):
        (self.root / "logic").mkdir()
        mine = self.root / "logic" / "audio-channel-12.4.0.json"
        mine.write_text("{}")
        self.assertEqual(data.data_file("logic", "audio-channel-12.4.0.json"), mine)

    def test_a_packaged_native_donor_shadows_the_roots_copy(self):
        from logicxkit.logic.services.mixer.plugin_library import load_library
        packaged = (data.PACKAGED / "donors" / "154-v5.slot").read_bytes()
        (self.root / "donors").mkdir()
        (self.root / "donors" / "154-v5.slot").write_bytes(packaged[:-1] + bytes([packaged[-1] ^ 1]))
        donor = next(d for d in load_library(data.data_dirs("donors")) if d.key == "154-v5")
        self.assertEqual(donor.raw, packaged)

    def test_a_file_neither_has_names_both_places(self):
        with self.assertRaises(data.MissingData) as e:
            data.data_file("logic", "nope.json")
        self.assertIn(str(self.root), str(e.exception))
        self.assertIn("logicxkit/data", str(e.exception))

    def test_data_dirs_lists_existing_dirs_package_first(self):
        (self.root / "donors").mkdir()
        self.assertEqual(data.data_dirs("donors"), [data.PACKAGED / "donors", self.root / "donors"])
        self.assertEqual(data.data_dirs("au"), [])          # AU tables are never packaged


class WritableRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.pop(data.ENV, None)

    def tearDown(self):
        os.environ.pop(data.ENV, None)
        if self.old is not None:
            os.environ[data.ENV] = self.old
        self.tmp.cleanup()

    def test_an_installed_copy_must_name_its_root(self):
        from unittest import mock
        outside = Path(self.tmp.name) / "lib" / "resources" / "data"          # no resources/ there
        with mock.patch.object(data, "DEFAULT_ROOT", outside):
            with self.assertRaises(data.MissingData) as e:
                data.writable_root()
            self.assertIn(data.ENV, str(e.exception))
            os.environ[data.ENV] = self.tmp.name
            self.assertEqual(data.writable_root(), Path(self.tmp.name))

    def test_a_checkout_writes_to_its_default_root(self):
        from unittest import mock
        checkout = Path(self.tmp.name) / "resources" / "data"
        checkout.parent.mkdir()
        with mock.patch.object(data, "DEFAULT_ROOT", checkout):
            self.assertEqual(data.writable_root(), checkout)


class PackagingTest(unittest.TestCase):
    def test_pyproject_ships_every_packaged_kind(self):
        """A kind `data_dirs` reads from the package but package-data leaves out reads as absent
        in an installed copy, with no error."""
        import fnmatch
        import tomllib
        cfg = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
        globs = cfg["tool"]["setuptools"]["package-data"]["logicxkit"]
        for kind in data.PACKAGED_KINDS:
            files = [p for p in (data.PACKAGED / kind).iterdir() if p.is_file() and not p.name.startswith(".")]
            self.assertTrue(files, kind)
            for p in files:
                rel = f"data/{kind}/{p.name}"
                with self.subTest(rel):
                    self.assertTrue(any(fnmatch.fnmatch(rel, g) for g in globs), rel)

    def test_the_sdist_carries_every_bin_script_a_test_imports(self):
        import re
        root = Path(__file__).resolve().parents[1]
        manifest = (root / "MANIFEST.in").read_text()
        scripts = {p.stem for p in (root / "bin").glob("*.py")}
        imported = {m for f in (root / "tests").rglob("*.py") for m in re.findall(r"^import (\w+)", f.read_text(), re.M)} & scripts
        self.assertTrue(imported)
        for name in sorted(imported):
            self.assertRegex(manifest, rf"(?m)^include\b.*\bbin/{name}\.py\b", name)


class RbaTemplateTest(unittest.TestCase):
    def test_it_carries_no_take_positions(self):
        import json
        t = json.loads(data.data_file("logic", "rba-sequence-12.3.1.json").read_text())
        self.assertEqual(set(t), {"_", "qesm_header", "qesm_payload", "marker", "qsve_header", "qsve_tail", "hit"})
        self.assertEqual(bytes.fromhex(t["hit"])[:16], bytes(16))


if __name__ == "__main__":
    unittest.main()
