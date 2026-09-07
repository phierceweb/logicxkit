"""Adding a track. Measured against Logic's own adds on 2026-09-01 (those saves are gone); the
real-file golden now holds the output to the invariants every Logic file obeys."""

import struct
import unittest
from logicxkit.logic.services.environment import clone_object
from logicxkit.logic.services.recbuild import fresh_uuid, time_fields


class HelpersTest(unittest.TestCase):
    def test_uuid_is_v1_shaped(self):
        u = fresh_uuid()
        self.assertEqual(u[6] >> 4, 1)
        self.assertEqual(u[8] & 0xC0, 0x80)

    def test_time_fields_match_logics_layout(self):
        uuid = bytes.fromhex("6106b7bca67b11f1a01d211a74f1018b")
        self.assertEqual(time_fields(uuid), bytes.fromhex("bcb706617ba6f101"))

    def test_rename_pads_odd_names_to_even(self):
        from _records import env_obj
        from logicxkit.logic.services.environment import channel_objects
        raw = env_obj(500, "Gtr 2 Amp")                  # 9 chars, padded
        for name, expect in (("Audio 27", 463 + 8), ("Kick In", 463 + 8), ("Test Bounce", 463 + 12)):
            out = clone_object(raw, object_id=508, name=name, colour=16, owner=26)
            self.assertEqual(len(out) - 36, expect, name)
            obj = channel_objects(b"\x00" * 24 + out)[508]
            self.assertEqual((obj.name, obj.colour, obj.parent), (name, 16, 0))
            self.assertEqual(struct.unpack_from("<H", out, 10)[0], 508)
