"""Logic's own New Software Instrument Track at four mixer layouts: the instrument at the slot base,
the channel's second archive alone at slot base + shown slots + 4, and `add-track` keys its new
instrument channel's archive there too."""

import struct
import unittest

import _goldens
from logicxkit.logicx import project_data
from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.mixer.mixer import CHANNEL_BASE_AT, CHANNEL_TAG
from logicxkit.logic.services.mixer.slots import SHOWN_AT, archive_index, property_key_base, slot_index_base
from logicxkit.logic.services.mixer.transplant import channel_slots, owner_of
from logicxkit.logic.services.stream.stream import HEADER, project_records

ADDS = {"addtrack-inst-shown-3-logic": "inserts-native-logic",
        "addtrack-inst-shown-4-logic": "master-out-adaptive-limiter-logic",
        "addtrack-inst-shown-5-logic": "master-out-limiter-logic",
        "addtrack-inst-base-3-logic": "send-two-base-3-logic"}


def archives(data: bytes, owner: int) -> dict[int, int]:
    return {archive_index(r.raw): r.key for r in project_records(data)
            if r.tag == b"UCuA" and r.owner == owner and archive_index(r.raw)}


def words(data: bytes) -> set[tuple[int, int]]:
    return {(struct.unpack_from("<H", r.raw, HEADER + CHANNEL_BASE_AT)[0], struct.unpack_from("<H", r.raw, HEADER + SHOWN_AT)[0])
            for r in project_records(data) if r.tag == CHANNEL_TAG and len(r.raw) - HEADER >= SHOWN_AT + 2}


@_goldens.needs(*ADDS, *ADDS.values())
class LogicsInstrumentAddTest(unittest.TestCase):
    def test_the_instrument_and_the_lone_archive_sit_where_the_layout_says(self):
        for key in ADDS:
            with self.subTest(key):
                data, facts = project_data(_goldens.path(key)), _goldens.entry(key)["facts"]
                base, shown = facts["slot_base"], facts["shown"]
                owner = owner_of(data, facts["new"])
                self.assertEqual(words(data), {(base, shown)})
                self.assertEqual(slot_index_base(data), base)
                self.assertEqual([r.key for r in channel_slots(data, owner)], [base])
                self.assertEqual(archives(data, owner), {2: facts["archive_key"]})
                self.assertEqual(facts["archive_key"], base + shown + 4)
                self.assertEqual(property_key_base(data), base + shown + 1)

    def test_add_track_keys_the_archive_where_logic_does(self):
        for key, before in ADDS.items():
            with self.subTest(key):
                data = project_data(_goldens.path(before))
                out, report = add_track(data, name="Keys", after=read_tracks(data)[0]["object_id"], kind="instrument")
                self.assertEqual(archives(out, report["owner"]), {2: _goldens.fact(key, "archive_key")})


if __name__ == "__main__":
    unittest.main()
