"""A fresh channel record from `add-track` carries the project's shown-slot count, not its
template's: a corpus save given ten such tracks with the template's 5 against the project's 9
opened in Logic with every chain gone (2026-09-22). Skips without the public corpus."""

import plistlib
import struct
import unittest

import _goldens
from logicxkit.logic._edit import object_by_name
from logicxkit.logic.services.mixer.add_plugin import SHOWN_AT, shown_slots
from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

KEY = "master-track-limiter-logic"


def _count() -> int:
    with open(_goldens.path(KEY) / "Alternatives" / "000" / "MetaData.plist", "rb") as f:
        return plistlib.load(f)["NumberOfTracks"]


def _counts(data: bytes) -> set[int]:
    owners = set(channels(data))
    return {struct.unpack_from("<H", r.raw, HEADER + SHOWN_AT)[0] for r in project_records(data)
            if r.tag == CHANNEL_TAG and r.owner in owners and len(r.raw) - HEADER > 40}


@_goldens.needs(KEY)
class AddedChannelShownSlotsTest(unittest.TestCase):
    def test_every_channel_record_carries_the_projects_count_after_an_add(self):
        data = project_data(_goldens.path(KEY))
        count = _count()
        before = shown_slots(data)
        self.assertEqual(_counts(data), {before})
        out, _report = add_track(data, name="FX 1", after=object_by_name(data, "Audio 1", count),
                                 kind="audio", input_number=1, stereo=False, track_count=count)
        self.assertEqual(_counts(out), {before})
        self.assertGreater(len(project_records(out)), len(project_records(data)))


if __name__ == "__main__":
    unittest.main()
