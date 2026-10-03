"""Section and tempo edits, checked by reading them back and holding them to the write gate."""

import struct
import unittest
from logicxkit.logic.services.song import arrangement_write as w


class TextPayloadTest(unittest.TestCase):
    def test_plain_payload_layout(self):
        p = w.plain_text_payload("Chorus")
        self.assertEqual(len(p), 106)
        self.assertEqual(struct.unpack_from("<IIII", p, 0)[0], 106)
        self.assertEqual(struct.unpack_from("<III", p, 16), (98, 106, 0x01000011))
        self.assertEqual(p[98:], b"Chorus\0\0")
        self.assertEqual(len(w.plain_text_payload("Verse")), 104)
        self.assertEqual(len(w.plain_text_payload("")), 100)


class NonAsciiNameTest(unittest.TestCase):
    def test_a_name_outside_ascii_is_utf8_and_a_control_character_is_refused(self):
        self.assertEqual(w.plain_text_payload("Café")[98:], "Café".encode() + b"\0")
        for encode in (w.plain_text_payload, w._text_bytes):
            with self.subTest(encode.__name__), self.assertRaisesRegex(ValueError, "control character"):
                encode("Caf\x07")


if __name__ == "__main__":
    unittest.main()
