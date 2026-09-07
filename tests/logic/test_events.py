"""The 16-byte line walk shared by the tempo and arrangement readers."""

import struct
import unittest

from logicxkit.logic.services.events import BAR_ONE, END_TYPE, bar, events

def head(kind, tick, flags=0):
    return struct.pack("<II", kind, tick) + b"\0\0\0\0\x7f\0\0" + bytes([flags])

def cont(kind, body=b""):
    return (body + b"\0" * 7)[:7] + bytes([kind]) + b"\0" * 8

END = head(END_TYPE, 0x3FFFFFFF)


class WalkTest(unittest.TestCase):
    def test_continuations_attach_to_the_event_before_them(self):
        p = head(0x60, BAR_ONE) + cont(0x88, b"\x40\xe8\x1d") + cont(0xB1) + head(0x60, BAR_ONE + 1, 1) + cont(0x88) + END
        got = events(p)
        self.assertEqual([(e.type, e.tick, len(e.lines)) for e in got], [(0x60, BAR_ONE, 2), (0x60, BAR_ONE + 1, 1)])
        self.assertEqual(struct.unpack_from("<I", got[0].data, 0)[0], 1960000)
        self.assertEqual(got[0].line(0xB1)[7], 0xB1)
        self.assertIsNone(got[0].line(0xB4))

    def test_the_end_marker_stops_the_walk(self):
        p = head(0x12, BAR_ONE) + cont(0x88) + END + head(0x60, 5) + cont(0x88)
        self.assertEqual(len(events(p)), 1)

    def test_a_missing_data_line_reads_as_zeros(self):
        self.assertEqual(events(head(0x60, 0) + END)[0].data, b"\0" * 16)

    def test_bar(self):
        self.assertEqual(bar(BAR_ONE), 1.0)
        self.assertEqual(bar(BAR_ONE + 3840 * 96 + 1920), 97.5)
        self.assertEqual(bar(BAR_ONE + 2880, 3), 2.0)


if __name__ == "__main__":
    unittest.main()
