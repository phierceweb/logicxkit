"""Section and tempo edits, checked by reading them back and holding them to the write gate."""

import struct
import unittest
from logicxkit.logic.services import arrangement_write as w


class TextPayloadTest(unittest.TestCase):
    def test_plain_payload_layout(self):
        p = w.plain_text_payload("Chorus")
        self.assertEqual(len(p), 106)
        self.assertEqual(struct.unpack_from("<IIII", p, 0)[0], 106)
        self.assertEqual(struct.unpack_from("<III", p, 16), (98, 106, 0x01000011))
        self.assertEqual(p[98:], b"Chorus\0\0")
        self.assertEqual(len(w.plain_text_payload("Verse")), 104)
        self.assertEqual(len(w.plain_text_payload("")), 100)


if __name__ == "__main__":
    unittest.main()
