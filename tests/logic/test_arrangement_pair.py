"""`arrangement --add` on a song that already carries the arrangement track's two sequences empty,
with no `snrT` after them: the section goes into that pair, and no second pair is made."""

import unittest

import _goldens
import _paths  # noqa: F401
from logicxkit.logic._edit import first_project_data
from logicxkit.logic.services.song.arrangement import read_sections, section_sequence
from logicxkit.logic.services.song.arrangement_write import (
    TEXT_TAG, _anchor, add_section, delete_section, ensure_arrangement_track, has_arrangement_pair,
)
from logicxkit.logic.services.song.signature import BAR_ONE, PPQ
from logicxkit.logic.services.stream.sequence import sequences
from logicxkit.logic.services.stream.stream import project_records, reassemble

TRACK = "arrangement-track-logic"              # the arrangement track shown, no sections, no pair yet
BAR = 4 * PPQ


@_goldens.needs(TRACK)
class EmptyPairTest(unittest.TestCase):
    def _pair_without_snrt(self) -> bytes:
        """The pair as `ensure_arrangement_track` makes it, its `snrT` taken off: the layout a
        Logic 12.4 save carries before its first section."""
        data = ensure_arrangement_track(first_project_data(_goldens.path(TRACK)))
        records = project_records(data)
        anchor = _anchor(records)
        self.assertEqual(records[anchor + 7].tag, b"snrT")
        return reassemble(data, [r.raw for i, r in enumerate(records) if i != anchor + 7])

    def test_the_pair_is_taken_as_the_track(self):
        data = self._pair_without_snrt()
        records = project_records(data)
        self.assertTrue(has_arrangement_pair(records, _anchor(records)))
        self.assertIsNone(section_sequence(records))
        self.assertEqual(ensure_arrangement_track(data), data)

    def test_a_section_lands_in_the_pair(self):
        data = self._pair_without_snrt()
        before = project_records(data)
        added = add_section(data, "Intro", start=BAR_ONE, length=8 * BAR)
        after = project_records(added)
        self.assertEqual(len(sequences(after)), len(sequences(before)))
        self.assertEqual(section_sequence(after), _anchor(before) + 3)
        self.assertEqual([(s.name, s.start) for s in read_sections(added)], [("Intro", BAR_ONE)])

    def test_a_deleted_section_takes_its_text_record_with_it(self):
        """Logic 13.0's re-save of a delete that left the record dropped it."""
        def texts(d: bytes) -> int:
            return sum(r.tag == TEXT_TAG for r in project_records(d))

        data = self._pair_without_snrt()
        added = add_section(data, "Intro", start=BAR_ONE, length=8 * BAR)
        self.assertEqual(texts(added), texts(data) + 1)
        gone = delete_section(added, 1)
        self.assertEqual(read_sections(gone), [])
        self.assertEqual(texts(gone), texts(data))
        self.assertEqual(len(sequences(project_records(gone))), len(sequences(project_records(added))))

    def test_a_song_without_the_pair_still_gets_one(self):
        data = first_project_data(_goldens.path(TRACK))
        records = project_records(data)
        self.assertFalse(has_arrangement_pair(records, _anchor(records)))
        made = project_records(ensure_arrangement_track(data))
        self.assertEqual(len(sequences(made)), len(sequences(records)) + 2)
        self.assertEqual(made[_anchor(made) + 7].tag, b"snrT")


if __name__ == "__main__":
    unittest.main()
