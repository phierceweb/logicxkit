"""Logic writes a slot's state block twice on a re-save: the live block, then a same-size copy
whose name label sits outside `identify_plugin`'s window (the logic README, gotcha 1). Readers
report the slot once; writers patch the copy along with the block, or Logic loads the stale one."""

import struct
import unittest

from _records import chan, rec

from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic.services.mixer.insert import _stamp, apply_float_overrides
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.project.project import channel_natives

COMPRESSOR = 154
FLOATS = [0.0, -20.0, 2.0, 0.0, 30.0, 100.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]   # 14, decode_comp's count


def block(type_id: int, floats: list[float]) -> bytes:
    n = len(floats)                                     # total covers the pre-header, tag, type id and floats
    return struct.pack("<III", 4 * n + 24, 0, n) + b"GAMETSPP" + struct.pack("<I", type_id) + struct.pack(f"<{n}f", *floats)


def slot(copies: int = 2, floats: list[float] = FLOATS) -> bytes:
    """A Compressor slot payload: the name in the window of the first block, ``copies`` blocks."""
    p = bytearray(184)
    p[40:52] = b"Compressor\x00\x00"
    body = bytes(p) + b"".join(block(COMPRESSOR, floats) for _ in range(copies))
    return rec(b"UCuA", 0, 4, body, 5)


def blocks_of(raw: bytes) -> list[list[float]]:
    payload = raw[HEADER:]
    return [read_block_floats(payload, idx, n) for idx, _t, n in find_blocks(payload)]


class ReaderTest(unittest.TestCase):
    def test_the_fixture_is_the_shape_logic_writes(self):
        self.assertEqual([(t, n) for _i, t, n in find_blocks(slot()[HEADER:])], [(COMPRESSOR, 14), (COMPRESSOR, 14)])

    def test_a_slot_with_its_state_copy_is_reported_once(self):
        natives = channel_natives(chan(0, "Audio 1") + slot())
        self.assertEqual([name for name, _ in natives], ["Compressor"])
        self.assertEqual(natives[0][1]["threshold"], -20.0)

    def test_two_instances_in_two_records_are_still_two(self):
        natives = channel_natives(chan(0, "Audio 1") + slot(copies=1) + slot(copies=1))
        self.assertEqual([name for name, _ in natives], ["Compressor", "Compressor"])

    def test_two_different_plugins_are_still_two(self):
        two = bytes(184) + block(COMPRESSOR, FLOATS) + block(236, [0.0] * 33)
        self.assertEqual(len(find_blocks(two)), 2)


class WriterTest(unittest.TestCase):
    def test_stamp_patches_the_copy_with_the_block(self):
        dialled = [1.0] * 14
        out = _stamp(slot(), owner=0, key=4, floats=dialled, limit=14, seed="x")
        self.assertEqual(blocks_of(out), [dialled, dialled])

    def test_overrides_reach_the_copy_too(self):
        out = apply_float_overrides(slot(), {1: -6.0, 2: 4.0})
        first, second = blocks_of(out)
        self.assertEqual((first[1], first[2]), (-6.0, 4.0))
        self.assertEqual(first, second)

    def test_a_following_block_of_another_size_or_type_is_not_a_copy(self):
        payload = bytes(184) + block(COMPRESSOR, FLOATS) + block(COMPRESSOR, FLOATS + [0.0]) + block(236, [0.0] * 33)
        out = apply_float_overrides(rec(b"UCuA", 0, 4, payload, 5), {0: 9.0})
        self.assertEqual([b[0] for b in blocks_of(out)], [9.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
