"""A project Logic 11.2 saved, set up as a bundle of its own: every writer refuses it and
nothing is copied (skips without the owner's files). Logic 12.4's public save is the format the
writers take."""

import shutil
import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import run, wrapped

KEYS = ("logic-11-2-a", "logic-11-2-b")


def bundle(key: str, root: Path) -> Path:
    source = _goldens.path(key)
    alternative = root / "in" / "probe.logicx" / "Alternatives" / "000"
    alternative.mkdir(parents=True)
    shutil.copy(source, alternative / "ProjectData")
    shutil.copy(source.parent / "MetaData.plist", alternative / "MetaData.plist")
    return alternative.parents[1]


@_goldens.needs(*KEYS)
class Logic112RefusedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_the_saves_are_the_format_this_pins(self):
        for key in KEYS:
            with self.subTest(key):
                data = _goldens.path(key).read_bytes()
                self.assertEqual(struct.unpack_from("<H", data, 4)[0], _goldens.fact(key, "header_word"))

    def test_a_route_is_refused_and_the_channel_keeps_its_uuid(self):
        """`route --input` wrote the last 16 bytes of the channel record, which on this format
        are the channel's own uuid."""
        for key in KEYS:
            with self.subTest(key):
                project, out = bundle(key, self.root / key), self.root / key / "out"
                code, text = wrapped("route", project, "--input", "Audio 1=Input 2", "--out", out)
                self.assertEqual(code, 1, text)
                self.assertIn("an earlier Logic (file format 2511", text)
                self.assertFalse(out.exists(), text)

    def test_it_still_reads(self):
        project = bundle(KEYS[0], self.root)
        code, text = run("project", project)
        self.assertEqual(code, 0, text)
        self.assertIn(f"{_goldens.fact(KEYS[0], 'tracks')} tracks", text)


@_goldens.needs("names-non-ascii-logic")
class Logic124AcceptedTest(unittest.TestCase):
    def test_its_save_is_the_measured_format(self):
        import plistlib

        from logicxkit.logic.services.validate import (
            MEASURED_FORMAT, file_format, require_measured_format)
        project = _goldens.path("names-non-ascii-logic")
        data = (project / "Alternatives" / "000" / "ProjectData").read_bytes()
        with (project / "Resources" / "ProjectInformation.plist").open("rb") as f:
            saved_from = plistlib.load(f)["LastSavedFrom"]
        self.assertEqual(saved_from, f"Logic Pro {_goldens.fact('names-non-ascii-logic', 'logic')}")
        self.assertEqual(file_format(data), MEASURED_FORMAT)
        require_measured_format(data)


if __name__ == "__main__":
    unittest.main()
