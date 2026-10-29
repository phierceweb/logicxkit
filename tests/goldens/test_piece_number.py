"""An audio entry's piece number is two bytes at +40: Logic 12.4's own save of a live set keeps a
folder region whose container holds entries numbered well past 255, every one pairing with
its region record by (slot word at +44, u16 at +40), the two bytes after always zero."""

import struct
import unittest

import _goldens

from logicxkit.logic._edit import first_project_data
from logicxkit.logic.services.regions.audio_regions import AUDIO_ENTRY, ENTRY_ORDINAL_AT, ENTRY_PIECE_AT, REGION_TAG, region_key
from logicxkit.logic.services.regions.regions import ENTRY
from logicxkit.logic.services.stream.stream import HEADER, project_records

KEY = "live-set-pieces"
FOLDER_HEAD = 16                     # a folder region's container holds its entries after a 16-byte head


@_goldens.needs(KEY)
class PieceNumberIsTwoBytesTest(unittest.TestCase):
    def test_every_entry_past_255_pairs_with_its_record_read_as_a_u16(self):
        facts = _goldens.entry(KEY)["facts"]
        records = project_records(first_project_data(_goldens.path(KEY)))
        self.assertEqual(len(records), facts["records"])
        keys = {region_key(r.raw) for r in records if r.tag == REGION_TAG}
        folder = max((r for r in records if r.tag == b"qSvE"), key=lambda r: len(r.raw))
        payload = folder.raw[HEADER:]
        entries = [payload[at:at + ENTRY] for at in range(FOLDER_HEAD, len(payload) - ENTRY + 1, ENTRY)]
        audio = [e for e in entries if e[0] == AUDIO_ENTRY]
        pairs = [(struct.unpack_from("<I", e, ENTRY_ORDINAL_AT)[0], struct.unpack_from("<H", e, ENTRY_PIECE_AT)[0]) for e in audio]
        self.assertEqual(len(audio), facts["folder_entries"])
        self.assertTrue(all(p in keys for p in pairs))
        self.assertEqual(sum(1 for _s, p in pairs if p > 255), facts["pieces_past_255"])
        self.assertEqual(max(p for _s, p in pairs), facts["highest_piece"])
        self.assertTrue(all(e[ENTRY_PIECE_AT + 2] == 0 and e[ENTRY_PIECE_AT + 3] == 0 for e in audio))


if __name__ == "__main__":
    unittest.main()
