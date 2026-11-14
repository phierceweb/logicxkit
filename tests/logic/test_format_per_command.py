"""The formats a writer takes are its capability row's: Logic 12.3.1's alone unless the row
names more, and a command whose row names another format writes a project of it while every
other command still refuses one."""

import dataclasses
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import wrapped
from _records import chan, proj
from test_format import LOGIC_11_2, MEASURED, NEXT, THREE, restamped, with_stale_alternative

from logicxkit.logic import _capabilities
from logicxkit.logic.services.stream import validate


def stamped(word: int) -> bytes:
    data = bytearray(proj(chan(0, "Audio 1")))
    struct.pack_into("<H", data, 4, word)
    return bytes(data)


class WritingFormatsTest(unittest.TestCase):
    def test_every_row_takes_the_measured_format_and_at_most_logic_13_0s_beside_it(self):
        """A row opened on 13.0 names the measured format first and 2514 after it; `test_format_evidence`
        makes it cite a public 2514 save."""
        for cap in _capabilities.CAPABILITIES:
            with self.subTest(cap.commands[0]):
                self.assertIn(cap.formats, ((MEASURED,), (MEASURED, NEXT)))

    def test_a_row_is_opened(self):
        self.assertEqual(_capabilities.by_command()["regions"].formats, (MEASURED, NEXT))

    def test_inside_a_wider_set_its_format_is_taken(self):
        with validate.writing_formats((LOGIC_11_2, MEASURED)):
            validate.require_measured_format(stamped(LOGIC_11_2))
            validate.require_measured_format(stamped(MEASURED))
        with self.assertRaisesRegex(ValueError, "file format 2511"):
            validate.require_measured_format(stamped(LOGIC_11_2))

    def test_a_format_between_the_set_is_still_an_earlier_one(self):
        with validate.writing_formats((LOGIC_11_2, MEASURED)), \
                self.assertRaisesRegex(ValueError, r"an earlier Logic \(file format 2512.*2511, 2513"):
            validate.require_measured_format(stamped(2512))

    def test_a_later_one_is_still_refused(self):
        with validate.writing_formats((LOGIC_11_2, MEASURED)), \
                self.assertRaisesRegex(ValueError, rf"saved by Logic 13\.0 \(file format {NEXT}"):
            validate.require_measured_format(stamped(NEXT))


class ShownFormatsTest(unittest.TestCase):
    def test_a_row_of_the_measured_format_alone_says_nothing_more(self):
        self.assertEqual(_capabilities.also_writes(_capabilities.by_command()["remove-plugin"]), "")

    def test_a_row_opened_on_logic_11_2_says_so_in_its_catch(self):
        opened = dataclasses.replace(_capabilities.by_command()["rename"], formats=(LOGIC_11_2, MEASURED))
        line = "Also writes Logic 11.2's saves (file format 2511)"
        self.assertEqual(_capabilities.also_writes(opened), line)
        with mock.patch.object(_capabilities, "CAPABILITIES", (opened,)):
            self.assertTrue(_capabilities.catches().endswith(f". {line}."), _capabilities.catches()[-200:])


@_goldens.needs(THREE)
class OneCommandOpenedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "out"
        rows = tuple(dataclasses.replace(cap, formats=(LOGIC_11_2, MEASURED)) if "rename" in cap.commands
                     else cap for cap in _capabilities.CAPABILITIES)
        patch = mock.patch.object(_capabilities, "CAPABILITIES", rows)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_opened_command_writes_a_project_of_that_format(self):
        project = restamped(self.root, THREE, LOGIC_11_2)
        code, text = wrapped("rename", project, "--track", "Audio 2=Snare", "--out", self.out)
        self.assertEqual(code, 0, text)
        written = self.out / "probe.logicx" / "Alternatives" / "000" / "ProjectData"
        self.assertEqual(validate.file_format(written.read_bytes()), LOGIC_11_2)
        self.assertIn(b"Snare", written.read_bytes())

    def test_another_command_still_refuses_it(self):
        code, text = wrapped("route", restamped(self.root, THREE, LOGIC_11_2),
                             "--input", "Audio 1=Input 2", "--out", self.out)
        self.assertEqual(code, 1, text)
        self.assertIn("file format 2511", text)

    def test_an_alternative_of_a_format_outside_the_set_is_left(self):
        project = restamped(self.root, THREE, LOGIC_11_2)
        stale = with_stale_alternative(project, 2512)
        before = stale.read_bytes()
        code, text = wrapped("rename", project, "--track", "Audio 2=Snare", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertEqual((self.out / "probe.logicx" / "Alternatives" / "001" / "ProjectData").read_bytes(), before)
        self.assertIn("Alternatives/001 left as it is: saved by an earlier Logic (file format 2512)", text)


if __name__ == "__main__":
    unittest.main()
