"""Arrangement sections need not touch: Logic 12.4's re-save of a copy whose sections were written
one per song into the empty pair it had saved, the gaps between songs unclaimed, kept every
section's start and length and left the gaps open."""

import unittest

import _goldens

from logicxkit.logic._edit import first_project_data
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.song.arrangement import read_sections

KEY = "arrangement-gaps-resave"


@_goldens.needs(KEY)
class SectionsWithGapsTest(unittest.TestCase):
    def test_the_re_save_keeps_every_section_and_the_gaps_between(self):
        facts = _goldens.entry(KEY)["facts"]
        data = first_project_data(_goldens.path(KEY))
        sections = read_sections(data)
        self.assertEqual(len(sections), facts["sections"])
        self.assertEqual([[s.start, s.length] for s in sections], facts["ticks"])
        gaps = [b.start - (a.start + a.length) for a, b in zip(sections, sections[1:], strict=False)]
        self.assertEqual(sum(1 for g in gaps if g > 0), facts["gaps"])
        self.assertTrue(all(g >= 0 for g in gaps), "no two sections overlap")
        self.assertEqual(len(read_audio_regions(data)), facts["regions"])


if __name__ == "__main__":
    unittest.main()
