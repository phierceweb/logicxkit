"""Environment objects: the `ivnE` records that name tracks and stack folders.

`+16` object id, `+38` parent (u32 — bytes +39..41 are zero on every object in seven sessions,
and 192/196 read back as the id where set), `+154` kind, `+158` u16-length name, and the
instance UUID in the last 16 bytes. Payload length is 463 or 464 plus the name length."""

import struct
import unittest
from _records import env_obj, proj, rec, uuid
from logicxkit.logic.services.environment import (
    CHANNEL_OBJECT,
    COLOUR_AT,
    PARENT_AT,
    channel_objects,
    set_colour,
    set_parent,
)


class ChannelObjectsTest(unittest.TestCase):
    def test_reads_id_name_kind_parent_and_uuid(self):
        data = proj(env_obj(192, "Drums", grouping=True), env_obj(88, "Kick In", parent=192))
        objs = channel_objects(data)
        self.assertEqual(objs[192].name, "Drums")
        self.assertEqual(objs[192].kind, 0)
        self.assertEqual(objs[88].parent, 192)
        self.assertEqual(objs[88].uuid, uuid(88))

    def test_parent_is_a_u32(self):
        data = proj(env_obj(500, "Late", parent=272))
        self.assertEqual(channel_objects(data)[500].parent, 272)

    def test_non_channel_objects_are_skipped(self):
        p = bytearray(300)
        struct.pack_into("<I", p, 0, 956)           # a non-channel constant
        struct.pack_into("<I", p, 16, 7)
        data = proj(rec(b"ivnE", 0xFFFF, 0xFFFF, bytes(p), 12), env_obj(88, "Kick In"))
        self.assertEqual(list(channel_objects(data)), [88])

    def test_logic_11_constant(self):
        data = proj(env_obj(88, "Kick In", ver=11))
        self.assertEqual(channel_objects(data)[88].name, "Kick In")
        self.assertEqual(CHANNEL_OBJECT[11], 1728)


class SetParentTest(unittest.TestCase):
    def test_writes_all_four_bytes(self):
        raw = env_obj(500, "Late")
        out = set_parent(raw, 272)
        self.assertEqual(struct.unpack_from("<I", out, 36 + PARENT_AT)[0], 272)
        self.assertEqual(len(out), len(raw))

    def test_ids_above_255_survive(self):
        out = set_parent(env_obj(88, "Kick In"), 300)
        self.assertEqual(channel_objects(proj(out))[88].parent, 300)


class ColourTest(unittest.TestCase):
    """A recolour of Kick In (2026-09-01) changed one persistent byte: +155, 96 -> 64."""

    def test_read_and_write(self):
        data = proj(env_obj(88, "Kick In"), env_obj(92, "Kick Out"))
        out = set_colour(data, 88, 64)
        objs = channel_objects(out)
        self.assertEqual((objs[88].colour, objs[92].colour), (64, 0))
        diffs = [i for i, (a, b) in enumerate(zip(data, out, strict=True)) if a != b]
        self.assertEqual(len(diffs), 1)
        self.assertEqual(out[diffs[0]], 64)
        self.assertEqual(diffs[0] - 24 - 36, COLOUR_AT)

    def test_unknown_object_is_refused(self):
        with self.assertRaises(ValueError):
            set_colour(proj(env_obj(88, "Kick In")), 99, 1)


class RenameTest(unittest.TestCase):
    def test_the_name_field_changes_and_the_tail_keeps_its_place(self):
        import struct

        from _records import env_obj, proj
        from logicxkit.logic.services.environment import name_end, rename_track
        from logicxkit.logic.services.insert import HEADER, project_records
        raw = bytearray(env_obj(500, "Gtr 2 Amp"))
        struct.pack_into("<H", raw, HEADER + name_end(raw[HEADER:]), 26)      # channel index
        data = proj(bytes(raw))
        for name in ("Guitar Two Amplifier", "Gtr", "Odd"):
            out = rename_track(data, 500, name)
            rec = project_records(out)[0]
            obj = channel_objects(out)[500]
            self.assertEqual((obj.name, obj.uuid), (name, channel_objects(data)[500].uuid))
            self.assertEqual(struct.unpack_from("<H", rec.raw, HEADER + name_end(rec.raw[HEADER:]))[0], 26)
            self.assertEqual(len(rec.raw) - HEADER, 463 + len(name) + len(name) % 2)

    def test_a_stream_the_walk_cannot_finish_is_refused_by_rename_and_colour(self):
        from _records import env_obj, proj
        from logicxkit.logic.services.environment import rename_track, set_colour
        data = proj(env_obj(500, "Gtr 2 Amp")) + bytes(10)
        with self.assertRaises(ValueError):
            rename_track(data, 500, "Gtr")
        with self.assertRaises(ValueError):
            set_colour(data, 500, 3)

    def test_a_non_ascii_name_is_refused(self):
        from _records import env_obj, proj
        from logicxkit.logic.services.environment import rename_track
        with self.assertRaises(ValueError):
            rename_track(proj(env_obj(500, "Gtr 2 Amp")), 500, "Caf\u00e9")

    def test_a_rename_marks_the_name_as_the_users(self):
        from _records import env_obj, proj
        from logicxkit.logic.services.environment import NAMED_BIT, STATE_AT, rename_track
        from logicxkit.logic.services.insert import HEADER, project_records
        raw = bytearray(env_obj(500, "Audio 5"))
        raw[HEADER + STATE_AT] = 2
        out = rename_track(proj(bytes(raw)), 500, "Gtr 2 Amp")
        self.assertEqual(project_records(out)[0].raw[HEADER + STATE_AT], 2 | NAMED_BIT)

    def test_a_clone_is_user_named_unless_told_otherwise(self):
        from _records import env_obj
        from logicxkit.logic.services.environment import NAMED_BIT, STATE_AT, clone_object
        from logicxkit.logic.services.insert import HEADER
        raw = bytearray(env_obj(500, "Gtr 2 Amp"))
        raw[HEADER + STATE_AT] = 3
        named = clone_object(bytes(raw), object_id=504, name="Kick In", owner=0, colour=16)
        auto = clone_object(bytes(raw), object_id=504, name="Audio 5", owner=0, colour=16, named=False)
        self.assertEqual((named[HEADER + STATE_AT], auto[HEADER + STATE_AT]), (NAMED_BIT, 0))

    def test_refuses_an_unknown_object_and_an_empty_name(self):
        from _records import env_obj, proj
        from logicxkit.logic.services.environment import rename_track
        data = proj(env_obj(500, "Gtr 2 Amp"))
        with self.assertRaises(ValueError):
            rename_track(data, 999, "X")
        with self.assertRaises(ValueError):
            rename_track(data, 500, "")
