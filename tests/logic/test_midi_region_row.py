"""A MIDI region write flags the destination track's arrange row as holding a region, as Logic's own
save of one does and as `regions --audio` already does: `midi --region` and `beats place` on the
public corpus, the row read back from the written bundle."""

import shutil
import tempfile
import unittest
from pathlib import Path

import _goldens
import _paths  # noqa: F401
from _beats import beat, index
from _cli import data, run, source, written

from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.arrange.tracklist import CONTENT_FLAG, CONTENT_FLAG_AT, CONTENT_MARK, SELECTED_AT, arrange_run, row_object
from logicxkit.logic.services.stream.stream import HEADER, project_records

INSTRUMENT, SPLIT = "tracks-instrument-logic", "regions-a10-midi-split-logic"


def row(d: bytes, label: str) -> bytes:
    """The arrange row of the track whose mixer label is ``label``."""
    object_id = next(t["object_id"] for t in read_tracks(d) if t["label"] == label)
    records = project_records(d)
    return next(records[i].raw for i in arrange_run(records) if row_object(records[i].raw) == object_id)


def name(d: bytes, label: str) -> str:
    return next(t["name"] for t in read_tracks(d) if t["label"] == label)


def flags(raw: bytes) -> tuple[int, int]:
    return raw[HEADER + CONTENT_FLAG_AT] & CONTENT_FLAG, raw[HEADER + SELECTED_AT] & CONTENT_MARK


@_goldens.needs(INSTRUMENT, SPLIT)
class RegionRowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_midi_region_flags_a_bare_instrument_row_and_changes_nothing_else_on_it(self):
        before = row(data(INSTRUMENT), "Inst 1")
        self.assertEqual(flags(before), (0, 0))
        after = row(data(written(self, "midi", INSTRUMENT, "--region", "Inst 1:1:2", out=self.tmp)), "Inst 1")
        self.assertEqual(flags(after), (CONTENT_FLAG, CONTENT_MARK))
        cleared = bytearray(after)
        cleared[HEADER + CONTENT_FLAG_AT] &= ~CONTENT_FLAG & 0xFF
        cleared[HEADER + SELECTED_AT] &= ~CONTENT_MARK & 0xFF
        self.assertEqual(bytes(cleared), before)

    def test_a_row_already_flagged_is_left_as_it_is(self):
        before = row(data(SPLIT), "Inst 1")
        self.assertEqual(flags(before), (CONTENT_FLAG, CONTENT_MARK))
        spec = f"{name(data(SPLIT), 'Inst 1')}:9:1"
        after = row(data(written(self, "midi", SPLIT, "--region", spec, out=self.tmp)), "Inst 1")
        self.assertEqual(after, before)

    def test_a_track_added_beside_a_flagged_row_leaves_its_content_mark(self):
        """A write that selects its new track moves the selected mark alone: the content mark Logic keeps
        on a row holding a region stays (`select_rows`)."""
        self.assertEqual(flags(row(data(SPLIT), "Inst 1")), (CONTENT_FLAG, CONTENT_MARK))
        dest = written(self, "add-track", SPLIT, "--name", "Audio Z", "--after", name(data(SPLIT), "Inst 1"), out=self.tmp)
        self.assertEqual(flags(row(data(dest), "Inst 1")), (CONTENT_FLAG, CONTENT_MARK))

    def test_beats_place_flags_the_row_through_the_same_write(self):
        db = index(self.tmp / "library")
        src = source(INSTRUMENT)
        code, text = run("beats", "place", src, beat(db, "Verse 01")["id"], "--track", "Inst 1", "--bar", "1",
                         "--db", db, "--out", self.tmp)
        self.assertEqual(code, 0, text)
        self.assertEqual(flags(row(data(self.tmp / src.name), "Inst 1")), (CONTENT_FLAG, CONTENT_MARK))


if __name__ == "__main__":
    unittest.main()
