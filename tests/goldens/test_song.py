"""The arrangement track (sections) and the tempo track, read from the resources copies.

The real-file part of tests/logic/test_song.py; skips without the owner's files."""

import unittest
import _paths
from logicxkit.logic.services.arrangement import BAR_ONE, PPQ, read_sections
from logicxkit.logic.services.tempo import project_tempo, read_tempo_events
from logicxkit.logicx import project_data

SONGS = sorted(p for d in ("mixes", "legacy") for p in (_paths.RESOURCES / d).glob("*/*.logicx"))


@unittest.skipUnless(SONGS, "no resources copies")
class GoldenTest(unittest.TestCase):
    def test_sections_are_named_ordered_and_in_the_song(self):
        found = 0
        for song in SONGS:
            sections = read_sections(project_data(song))
            if not sections:
                continue
            found += 1
            self.assertEqual(sections, sorted(sections, key=lambda s: s.start), song)
            for s in sections:
                self.assertTrue(s.name, (song, s))
                self.assertGreaterEqual(s.start, BAR_ONE, (song, s))
                self.assertGreater(s.length, 0, (song, s))
                self.assertLess(s.length, 400 * 4 * PPQ, (song, s))
        self.assertGreater(found, 0, "no song with an arrangement track")

    def test_tempo_track_starts_at_bar_one_with_a_project_tempo(self):
        for song in SONGS:
            data = project_data(song)
            shown, first = project_tempo(data)
            events = read_tempo_events(data)
            self.assertTrue(40 <= shown <= 300, (song, shown))
            self.assertTrue(events, song)
            self.assertEqual(events[0].position, BAR_ONE, song)
            self.assertEqual(events[0].bpm, first, song)
            self.assertFalse(events[0].generated, song)
            if len(events) == 1:
                self.assertEqual(shown, first, song)
            self.assertIn(shown, {e.bpm for e in events}, song)


if __name__ == "__main__":
    unittest.main()
