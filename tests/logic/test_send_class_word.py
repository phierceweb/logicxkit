"""A send record's class word (`+0`) is the saving Logic's: 72 on 12.x saves, 68 on Logic 13.0's (every 2514 save on
hand). `send --add` clones the packaged 12.x send when the project has none, and writes the project format's word."""

import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, run

from logicxkit.logic.services.mixer.sends import CLASS_AT, is_send
from logicxkit.logic.services.mixer.sends_write import SEND_CLASS_BY_FORMAT
from logicxkit.logic.services.stream.stream import HEADER, project_records

TWELVE, THIRTEEN = "tracks-two-audio-logic", "tracks-two-audio-13-0-logic"       # neither holds a send


def class_words(d: bytes) -> list[int]:
    return [struct.unpack_from("<I", r.raw, HEADER + CLASS_AT)[0] for r in project_records(d) if is_send(r)]


@_goldens.needs(TWELVE, THIRTEEN)
class SendClassWordTest(unittest.TestCase):
    def added(self, key: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run("send", _goldens.path(key), "--add", "Audio 1=Bus 1", "--out", tmp)
            self.assertEqual(code, 0, text)
            return data(next(Path(tmp).glob("*.logicx")))

    def test_the_two_formats_words(self):
        self.assertEqual(SEND_CLASS_BY_FORMAT, {2513: 72, 2514: 68})

    def test_a_send_added_to_a_13_0_save_carries_13_0s_word(self):
        self.assertEqual(class_words(self.added(THIRTEEN)), [68])

    def test_a_send_added_to_a_12_x_save_keeps_the_templates_word(self):
        """The template carries 72 itself; this guards the table's 2513 value."""
        self.assertEqual(class_words(self.added(TWELVE)), [72])


if __name__ == "__main__":
    unittest.main()
