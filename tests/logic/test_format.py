"""The file format a writer will take. The file header's u16 at +4 names the format, and every
writer is measured on one: a project of another is refused before anything is copied. The
readers still run."""

import json
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import run, wrapped
from _paths import REPO
from _records import chan, proj

THREE = "tracks-three-audio-logic"
BASE = "controlbar-base"
LOGIC_11_2, MEASURED, NEXT = 2511, 2513, 2514


def restamped(root: Path, key: str, word: int) -> Path:
    """A copy of the corpus bundle ``key`` with its file header's format word set to ``word``."""
    dest = root / "in" / "probe.logicx"
    shutil.copytree(_goldens.path(key), dest)
    for data_file in dest.glob("Alternatives/*/ProjectData"):
        data = bytearray(data_file.read_bytes())
        struct.pack_into("<H", data, 4, word)
        data_file.write_bytes(data)
    return dest


class FormatWordTest(unittest.TestCase):
    def setUp(self):
        from logicxkit.logic.services import validate
        self.validate = validate

    def test_the_measured_format_is_logic_12_3_1s(self):
        self.assertEqual(self.validate.MEASURED_FORMAT, MEASURED)

    def test_a_synthetic_project_carries_the_measured_format(self):
        self.assertEqual(self.validate.file_format(proj(chan(0, "Audio 1"))), MEASURED)
        self.validate.require_measured_format(proj(chan(0, "Audio 1")))

    def test_an_earlier_format_is_named_with_what_to_do(self):
        data = bytearray(proj(chan(0, "Audio 1")))
        struct.pack_into("<H", data, 4, LOGIC_11_2)
        with self.assertRaisesRegex(ValueError, r"an earlier Logic \(file format 2511.*open and save it"):
            self.validate.require_measured_format(bytes(data))

    def test_a_later_format_is_named_too(self):
        data = bytearray(proj(chan(0, "Audio 1")))
        struct.pack_into("<H", data, 4, NEXT)
        with self.assertRaisesRegex(ValueError, rf"newer than this release \(file format {NEXT}"):
            self.validate.require_measured_format(bytes(data))

    def test_bytes_that_are_no_project_file_are_called_that(self):
        for data in (b"", b"x", bytes(64), b"\xff" * 5000):
            with self.subTest(len(data)):
                self.assertIsNone(self.validate.file_format(data))
                with self.assertRaisesRegex(ValueError, "not a Logic project file"):
                    self.validate.require_measured_format(data)


@_goldens.needs(THREE, BASE)
class EveryWriterRefusesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "out"

    def refused(self, command: str, project: Path, *rest) -> str:
        code, text = wrapped(command, project, *rest, "--out", self.out)
        self.assertEqual(code, 1, text)
        self.assertFalse(self.out.exists() and any(self.out.iterdir()), f"{text}\nleft: {list(self.out.rglob('*'))[:5]}")
        return text

    def test_a_project_saved_by_logic_11_2_is_refused_before_anything_is_copied(self):
        text = self.refused("route", restamped(self.root, THREE, LOGIC_11_2), "--input", "Audio 1=Input 2")
        self.assertIn("Alternatives/000", text)
        self.assertIn("an earlier Logic (file format 2511", text)

    def test_an_instrument_add_is_refused_like_the_rest(self):
        text = self.refused("add-track", restamped(self.root, THREE, LOGIC_11_2), "--name", "Keys",
                            "--after", "Audio 1", "--instrument")
        self.assertIn("file format 2511", text)

    def test_one_saved_by_a_later_logic_is_refused(self):
        text = self.refused("rename", restamped(self.root, THREE, NEXT), "--track", "Audio 2=Snare")
        self.assertIn(f"file format {NEXT}", text)

    def test_chains_own_copy_refuses(self):
        text = self.refused("chains", restamped(self.root, THREE, LOGIC_11_2),
                            "--config", REPO / "config" / "example-chains.json")
        self.assertIn("file format 2511", text)

    def test_retracks_own_copy_refuses(self):
        spec = REPO / "config" / "example-retrack.json"
        library = self.root / "library" / "Drums"
        library.mkdir(parents=True)
        for entry in json.loads(spec.read_text())["mapping"].values():
            (library / (entry["name"] if isinstance(entry, dict) else entry)).write_bytes(b"")
        with mock.patch.dict(os.environ, {"LOGICXKIT_STRIP_ROOT": str(library.parent)}):
            text = self.refused("retrack", restamped(self.root, THREE, LOGIC_11_2), "--map", spec)
        self.assertIn("file format 2511", text)

    def test_a_display_writer_refuses(self):
        text = self.refused("controlbar", restamped(self.root, BASE, LOGIC_11_2), "--show", "Pause")
        self.assertIn("file format 2511", text)

    def test_an_alternative_that_is_no_project_file_is_refused_by_name(self):
        project = restamped(self.root, THREE, MEASURED)
        stale = project / "Alternatives" / "001"
        stale.mkdir()
        (stale / "ProjectData").write_bytes(b"\x07" * 5000)
        text = self.refused("rename", project, "--track", "Audio 2=Snare")
        self.assertIn("Alternatives/001: not a Logic project file", text)

    def test_the_readers_still_run(self):
        project = restamped(self.root, THREE, LOGIC_11_2)
        for command in (("stacks", "--tracks"), ("project",), ("regions",)):
            with self.subTest(command[0]):
                code, text = run(command[0], project, *command[1:])
                self.assertEqual(code, 0, text)


if __name__ == "__main__":
    unittest.main()
