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


class TableEntryFallbackTest(unittest.TestCase):
    """The pattern track's index-table entry is stale: the clone comes from the highest object
    of the same kind with a sound entry, before any other kind."""

    def test_the_fallback_keeps_to_the_pattern_kind(self):
        from types import SimpleNamespace
        from unittest import mock

        from logicxkit.logic.services import addtrack
        objs = dict.fromkeys((100, 104, 108))
        owners_of = {100: 1, 104: 2, 108: 30}
        chans = {1: SimpleNamespace(label="Audio 1"), 2: SimpleNamespace(label="Audio 2"),
                 30: SimpleNamespace(label="Aux 1")}
        sound = {100, 108}                               # 104, the pattern, is stale
        records = [SimpleNamespace(raw=b"")]
        with mock.patch("logicxkit.logic.services.sequence.index_table", return_value=0), \
                mock.patch("logicxkit.logic.services.sequence.sequences", return_value=[]), \
                mock.patch.object(addtrack, "_sound_entry", lambda r, t, s, oid: oid in sound):
            self.assertEqual(addtrack._with_table_entry(records, objs, owners_of, chans, "Audio ", 104), 100)
            self.assertEqual(addtrack._with_table_entry(records, objs, owners_of, chans, "Inst ", 104), 108)


class Logic112AddTest(unittest.TestCase):
    """A track add is measured on Logic 12's channel records: an audio or aux track needs their
    input field, and an instrument add on a Logic 11.2 project cost another track its strip."""

    def test_every_kind_is_refused_with_the_reason(self):
        from _records import chan, env_obj, proj, uuid
        from logicxkit.logic.services.addtrack import add_track
        data = proj(env_obj(88, "Piano", type_value=1760),
                    chan(5, "Inst 1", uuid=uuid(88), size=233, ver=6))
        for kind in ("audio", "instrument", "aux"):
            with self.subTest(kind):
                with self.assertRaisesRegex(ValueError, "this project's are class 6"):
                    add_track(data, name="Probe", after=88, kind=kind)
