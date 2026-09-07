"""Selecting a track moves all four of Logic's selection marks and clears the old holder."""

import struct
import unittest

import _paths  # noqa: F401
from _records import chan, env_obj, gnos, marker, proj, track, uuid
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.selection import select_track
from logicxkit.logic.services.tracklist import ROW_TYPE


def session() -> bytes:
    rows = [track(0, 88), track(1, 92), track(2, 504)]
    inst = bytearray(rows[2])
    inst[HEADER + 51] = ROW_TYPE["instrument"]
    inst[HEADER + 40] = 0xA0                       # 504 starts out selected and expanded
    inst[HEADER + 43] = 0x40
    struct.pack_into("<I", inst, HEADER, 0x10001)
    obj504 = bytearray(env_obj(504, "Test Bounce"))
    obj504[HEADER + 80] = 1
    return proj(gnos(88, 92, 504), env_obj(88, "Kick In"), env_obj(92, "Snare Up"), bytes(obj504),
                chan(0, "Audio 1", uuid=uuid(88)), chan(2, "Audio 3", uuid=uuid(92)),
                chan(88, "Inst 4", uuid=uuid(504)),
                rows[0], rows[1], bytes(inst), marker())


def row(data: bytes, object_id: int) -> bytes:
    return next(r.raw[HEADER:] for r in project_records(data) if r.tag == b"karT" and len(r.raw) > HEADER
                and struct.unpack_from("<I", r.raw, HEADER + 8)[0] == object_id)


def obj(data: bytes, object_id: int) -> bytes:
    return next(r.raw[HEADER:] for r in project_records(data) if r.tag == b"ivnE"
                and struct.unpack_from("<I", r.raw, HEADER + 16)[0] == object_id)


class SelectTest(unittest.TestCase):
    def test_the_row_is_marked_and_the_old_one_cleared(self):
        out = select_track(session(), 92, track_count=2)
        new, old = row(out, 92), row(out, 504)
        self.assertEqual((new[40] & 0x20, new[43]), (0x20, 0x40))
        self.assertEqual((old[40], old[43], struct.unpack_from("<I", old, 0)[0]), (0x80, 0, 0x1))

    def test_an_instrument_row_gets_its_flag_bit(self):
        out = select_track(select_track(session(), 92, track_count=2), 504, track_count=2)
        self.assertEqual(struct.unpack_from("<I", row(out, 504), 0)[0], 0x10001)
        self.assertEqual(struct.unpack_from("<I", row(out, 92), 0)[0], 0x1)

    def test_the_object_flag_moves(self):
        out = select_track(session(), 92, track_count=2)
        self.assertEqual((obj(out, 92)[80], obj(out, 504)[80], obj(out, 88)[80]), (1, 0, 0))

    def test_gnos_points_at_the_row(self):
        out = select_track(session(), 92, track_count=2)
        g = next(r.raw[HEADER:] for r in project_records(out) if r.tag == b"gnoS")
        self.assertEqual(struct.unpack_from("<I", g, 94)[0], 92)
        self.assertEqual((struct.unpack_from("<H", g, 210)[0], struct.unpack_from("<I", g, 214)[0]), (2, 2))

    def test_refuses_an_object_off_the_list(self):
        with self.assertRaises(ValueError):
            select_track(session(), 999, track_count=2)


if __name__ == "__main__":
    unittest.main()
