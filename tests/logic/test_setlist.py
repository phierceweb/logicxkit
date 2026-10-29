"""A setlist file: songs in order, `break` lines after a song, blanks and comments skipped."""

import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from logicxkit.logic.services.song.setlist import parse_setlist, read_setlist


class SetlistTest(unittest.TestCase):
    def test_songs_breaks_blanks_and_comments(self):
        s = parse_setlist("Opener\nSecond  \n\nBreak\n# the encore block\nThird\nbreak\nLast\n")
        self.assertEqual(s.songs, ("Opener", "Second", "Third", "Last"))
        self.assertEqual(s.breaks, frozenset({2, 3}))
        self.assertEqual(len(s), 4)

    def test_a_hash_inside_a_line_is_the_songs_own(self):
        self.assertEqual(parse_setlist("Song #9\n# the loud one\nC# Blues\n  # indented too\n").songs, ("Song #9", "C# Blues"))

    def test_refusals(self):
        for text, why in (("", "no song"), ("break\nSong", "before the first song"), ("Song\nbreak\nBREAK\n", "two breaks"),
                          ("One\nTw\x00o\n", "line 2: a control character")):
            with self.subTest(text), self.assertRaisesRegex(ValueError, why):
                parse_setlist(text)

    def test_read_names_the_file_in_a_refusal(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "set.txt"
        p.write_text("One\nTwo\n")
        bom = Path(tmp.name) / "bom.txt"
        bom.write_text("# a note\nOne\nTwo\n", encoding="utf-8-sig")
        self.assertEqual(read_setlist(bom).songs, ("One", "Two"))
        bom.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbfOne\nTwo\n")
        self.assertEqual(read_setlist(bom).songs, ("One", "Two"))
        self.assertEqual(read_setlist(p).songs, ("One", "Two"))
        with self.assertRaisesRegex(ValueError, "missing.txt"):
            read_setlist(Path(tmp.name) / "missing.txt")
        latin = Path(tmp.name) / "latin.txt"
        latin.write_bytes("Caf\xe9\n".encode("latin-1"))
        with self.assertRaisesRegex(ValueError, "latin.txt: not UTF-8 text"):
            read_setlist(latin)


if __name__ == "__main__":
    unittest.main()
