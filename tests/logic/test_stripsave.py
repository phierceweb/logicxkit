"""Exporting a channel as a `.cst`: the channel's records verbatim, marker at +8, stub last."""

import struct
import unittest

import _paths  # noqa: F401
from _records import chan, proj, rec, send
from logicxkit.logic.services.records import read_records
from logicxkit.logic.services.stripsave import STRIP_MARKER, export_strip

HDR = 36


def slot(owner, key, size=300):
    p = bytearray(size)
    p[6] = key - 4
    return rec(b"UCuA", owner, key, bytes(p), 5)


class ExportTest(unittest.TestCase):
    def test_records_come_out_in_order_with_marker_and_stub(self):
        data = proj(chan(3, "Audio 1"), slot(3, 5), slot(3, 4), send(3, 0, 15), chan(4, "Audio 2"))
        out = read_records(export_strip(data, 3))
        self.assertEqual([(r.tag, r.key) for r in out],
                         [(b"OCuA", 0xFFFF), (b"UCuA", 0), (b"UCuA", 4), (b"UCuA", 5), (b"OCuA", 0xFFFF)])
        self.assertEqual(struct.unpack_from("<H", out[0].raw, HDR + 8)[0], STRIP_MARKER)
        self.assertEqual([struct.unpack_from("<H", r.raw, 14)[0] for r in out], [0, 0, 0, 0, 1])
        self.assertEqual(len(out[-1].raw) - HDR, 14)

    def test_other_channels_are_excluded(self):
        data = proj(chan(3, "Audio 1"), slot(3, 4), chan(4, "Audio 2"), slot(4, 4))
        self.assertEqual(len(read_records(export_strip(data, 3))), 3)

    def test_refuses_an_unknown_owner(self):
        with self.assertRaises(ValueError):
            export_strip(proj(chan(3, "Audio 1")), 9)
