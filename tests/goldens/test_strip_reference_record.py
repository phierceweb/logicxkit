"""A channel's `.cst` reference as Logic writes one: a library setting loaded onto Audio 1 through the
inspector strip's Setting menu (`strip-reference-library-logic`, Logic 12.4). The record sits at the
project's property key, 192 bytes at `UCuA` v5: a fixed head, the file name at +16, the library
folder at +80, a per-setting word at +154 and a version-1 UUID at +176. Logic also renamed the track
to the setting."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.chains import channel_references
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.mixer.slots import property_key_base
from logicxkit.logic.services.mixer.transplant import reference_record
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logicx import project_data

KEY = "strip-reference-library-logic"
HEAD = bytes.fromhex("c4000000050000000000351200000000")
NAME_AT, FOLDER_AT, WORD_AT, UUID_AT, SIZE = 16, 80, 154, 176, 192


@_goldens.needs(KEY)
class StripReferenceRecordTest(unittest.TestCase):
    def setUp(self):
        self.data = project_data(_goldens.path(KEY))
        self.owner = next(o for o, c in channels(self.data).items() if c.label == _goldens.fact(KEY, "channel"))

    def test_the_reference_reads_and_sits_at_the_property_key(self):
        self.assertEqual(channel_references(self.data), {self.owner: _goldens.fact(KEY, "reference")})
        self.assertEqual(property_key_base(self.data), _goldens.fact(KEY, "reference_key"))

    def test_the_record_layout(self):
        raw = reference_record(self.data, self.owner)
        payload = raw[HEADER:]
        self.assertEqual((len(payload), payload[:NAME_AT]), (SIZE, HEAD))
        self.assertEqual(payload[NAME_AT:FOLDER_AT].rstrip(b"\0").decode(), _goldens.fact(KEY, "reference"))
        self.assertEqual(payload[FOLDER_AT:WORD_AT].rstrip(b"\0").decode(), _goldens.fact(KEY, "folder"))
        self.assertNotEqual(struct.unpack_from("<H", payload, WORD_AT)[0], 0)
        self.assertEqual(payload[WORD_AT + 2:UUID_AT], bytes(UUID_AT - WORD_AT - 2))
        self.assertEqual(payload[UUID_AT + 6] >> 4, 1)                       # a version-1 UUID

    def test_the_track_took_the_settings_name_and_its_chain(self):
        rows = {t["label"]: t["name"] for t in read_tracks(self.data)}
        self.assertEqual(rows[_goldens.fact(KEY, "channel")], _goldens.fact(KEY, "track"))
        names = [r.name for r, _p in slot_payloads(self.data) if r.channel == _goldens.fact(KEY, "channel")]
        self.assertEqual(names, _goldens.fact(KEY, "chain"))


if __name__ == "__main__":
    unittest.main()
