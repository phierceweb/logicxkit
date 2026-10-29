"""A region Logic itself moved onto another track: of two pieces of one file, one left on the
singer's track and one dragged onto another by hand and saved by Logic 12.4, the entries differ at
the tick, the track object, the row and the piece number alone, and the records carry the same
colour, mute and fades — a track move is the entry's `+16` and `+20` (`regions.py`)."""

import unittest

import _goldens

from logicxkit.logic._edit import first_project_data
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.regions import ENTRY, song_events
from logicxkit.logic.services.stream.stream import project_records

KEY = "vocal-pieces-moved-logic"
TICK, PIECE = (4, 5, 6, 7), (40, 41)


@_goldens.needs(KEY)
class LogicsOwnTrackMoveTest(unittest.TestCase):
    def test_the_move_is_the_entrys_track_object_and_row(self):
        facts = _goldens.entry(KEY)["facts"]
        data = first_project_data(_goldens.path(KEY))
        regions = {r.record_key: r for r in read_audio_regions(data)}
        self.assertEqual(len(regions), facts["audio_regions"])
        lead, moved = regions[facts["file_slot"], facts["lead_piece"]], regions[facts["file_slot"], facts["moved_piece"]]
        self.assertNotEqual((lead.object_id, lead.row), (moved.object_id, moved.row))
        payload = song_events(project_records(data))
        a, b = payload[lead.at:lead.at + ENTRY], payload[moved.at:moved.at + ENTRY]
        diffs = [i for i in range(ENTRY) if a[i] != b[i]]
        self.assertEqual(diffs, facts["entry_diffs"])
        self.assertLessEqual(set(facts["track_fields"]), set(diffs))
        self.assertLessEqual(set(diffs), {*TICK, *facts["track_fields"], 21, *PIECE})
        self.assertEqual((lead.colour, lead.muted, lead.fade, lead.params), (moved.colour, moved.muted, moved.fade, moved.params))


if __name__ == "__main__":
    unittest.main()
