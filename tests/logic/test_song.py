"""The arrangement track (sections) and the tempo track, read from the resources copies."""

import unittest
from logicxkit.logic.services.arrangement import BAR_ONE, PPQ, Section, _text


class TextTest(unittest.TestCase):
    def test_plain_name(self):
        self.assertEqual(_text(b"\0" * 98 + b"Verse\0junk"), "Verse")

    def test_rtf_name(self):
        rtf = b"{\\rtf1\\ansi{\\fonttbl}{\\colortbl;}\\pard\\cf2 Pre Chorus}\n"
        self.assertEqual(_text(b"\0" * 98 + rtf + b"\0"), "Pre Chorus")

    def test_bars(self):
        s = Section("Intro", BAR_ONE + 2 * 4 * PPQ, 8 * 4 * PPQ, 0, 4)
        self.assertEqual(s.bars(), (3.0, 8.0))


if __name__ == "__main__":
    unittest.main()
