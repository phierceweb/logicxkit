"""Division and key: the song-record bytes and the key event, against Logic's own edits."""

import unittest
from logicxkit.logic.services.settings import root_semitone
from logicxkit.logic.services.signature import key_number


class NamesTest(unittest.TestCase):
    def test_key_numbers(self):
        self.assertEqual([key_number(k) for k in ("C", "G", "F", "Bb", "F#", "E major")], [7, 8, 6, 5, 13, 11])
        self.assertEqual([key_number(k) for k in ("A minor", "E minor", "Bb minor", "F# minor")], [0x17, 0x18, 0x12, 0x1A])
        for bad in ("H", "C dorian", "H minor"):
            with self.assertRaises(ValueError):
                key_number(bad)

    def test_key_names(self):
        from logicxkit.logic.services.signature import KeySignature
        self.assertEqual([KeySignature(0, n).name for n in (7, 8, 0x17, 0x18, 0x12)], ["C major", "G major", "A minor", "E minor", "Bb minor"])
        self.assertEqual(KeySignature(0, 0x18).root, "E")

    def test_roots(self):
        self.assertEqual([root_semitone(n) for n in ("C", "G", "Bb", "F#", "Cb")], [0, 7, 10, 6, 11])


if __name__ == "__main__":
    unittest.main()
