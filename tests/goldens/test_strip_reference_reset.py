"""Reset Channel Strip on a channel carrying a library setting (`strip-reference-reset-logic`, from
`strip-reference-library-logic`): every `UCuA` record of the channel goes — the reference, the slots
and both Smart Controls archives — with their key flags, the channel record's +80 goes 4 to 0, and the
track is named for its channel again."""

import unittest

import _goldens

from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.chains import channel_references
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.stream.keyflags import FLAGS_AT, key_flags
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

LOADED, RESET = "strip-reference-library-logic", "strip-reference-reset-logic"
LOADED_AT = 80


def channel_record(data: bytes, owner: int) -> bytes:
    return max((r.raw[HEADER:] for r in project_records(data) if r.tag == CHANNEL_TAG and r.owner == owner), key=len)


@_goldens.needs(LOADED, RESET)
class ResetChannelStripTest(unittest.TestCase):
    def setUp(self):
        self.loaded, self.reset = project_data(_goldens.path(LOADED)), project_data(_goldens.path(RESET))
        self.owner = next(o for o, c in channels(self.reset).items() if c.label == _goldens.fact(RESET, "channel"))

    def test_every_record_of_the_channel_and_its_flags_go(self):
        self.assertEqual([r.key for r in project_records(self.loaded) if r.tag == b"UCuA" and r.owner == self.owner], [2, 3, 7, 9, 10])
        self.assertEqual([r for r in project_records(self.reset) if r.tag == b"UCuA" and r.owner == self.owner], [])
        self.assertEqual(channel_references(self.reset), {})
        self.assertNotIn(True, key_flags(channel_record(self.reset, self.owner)))
        self.assertEqual(validate_project(self.reset), [])

    def test_the_channel_record_differs_at_80_alone_beside_the_flags(self):
        before, after = channel_record(self.loaded, self.owner), channel_record(self.reset, self.owner)
        self.assertEqual((before[LOADED_AT], after[LOADED_AT]), (4, 0))
        self.assertEqual([i for i in range(len(before)) if before[i] != after[i] and i < FLAGS_AT], [LOADED_AT])

    def test_the_track_is_named_for_its_channel_again(self):
        names = {t["label"]: t["name"] for t in read_tracks(self.reset)}
        self.assertEqual(names.get(_goldens.fact(RESET, "channel")), _goldens.fact(RESET, "track"))


if __name__ == "__main__":
    unittest.main()
