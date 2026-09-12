"""Where a project's slot base is read from."""

import unittest

import _paths  # noqa: F401
class SlotBaseFromChannelWordTest(unittest.TestCase):
    """When every channel record carries the same base word at +28, that is the base — a vote
    over slot-shaped records misread a two-send project as base 7 (2026-09-12)."""

    def test_the_unanimous_channel_word_outranks_the_vote(self):
        import struct
        from _records import chan, proj, rec
        from logicxkit.logic.services.insert import HEADER, slot_index_base
        def stamped(raw, base):
            buf = bytearray(raw)
            struct.pack_into("<H", buf, HEADER + 28, base)
            return bytes(buf)
        def slotlike(key, index):
            p = bytearray(300)
            p[6] = index
            p[40:46] = b"<plist"
            return rec(b"UCuA", 8, key, bytes(p), 5)
        data = proj(stamped(chan(0, "Audio 1"), 3), stamped(chan(8, "Inst 1"), 3),
                    slotlike(3, 0), slotlike(9, 2), slotlike(10, 3))      # the vote would say 7
        self.assertEqual(slot_index_base(data), 3)


if __name__ == "__main__":
    unittest.main()
