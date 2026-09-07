"""GAMETSPP chunk-container tests.

Real layout (verified against Logic-written .cst/.pst/ProjectData):

    u32 total_size | u32 version | u32 n_floats | "GAMETSPP" | u32 plugin_type_id | float32 * n

The u32 *after* the tag is a plugin TYPE ID (Limiter 199, Channel EQ 236, Compressor 154,
Enveloper 157, Gain 183), NOT a byte size. Deriving the float count from it over-reports
badly — a 13-float Limiter reads as 49 and runs into the next slot.
"""

import struct
import unittest

from logicxkit.logic import find_blocks, read_block_floats

from _fixtures import chunk


class FloatCountTest(unittest.TestCase):
    def test_uses_real_count_not_type_id(self):
        data = chunk(199, [0.0] * 13)                      # Limiter
        (idx, type_id, n), = find_blocks(data)
        self.assertEqual(type_id, 199)
        self.assertEqual(n, 13, "type id 199 must not be read as a 49-float size")

    def test_does_not_read_past_block(self):
        """A count larger than the block must not pull in neighbouring bytes: 13 floats, not 49."""
        data = chunk(199, [1.0] * 13) + b"\xde\xad\xbe\xef" * 40
        idx, _t, n = find_blocks(data)[0]
        self.assertEqual(read_block_floats(data, idx, n), [1.0] * 13)

    def test_channel_eq_and_compressor_counts(self):
        for type_id, count in ((236, 52), (154, 31), (157, 8), (183, 6)):
            (idx, tid, n), = find_blocks(chunk(type_id, [0.0] * count))
            self.assertEqual((tid, n), (type_id, count))

    def test_trailer_after_floats_is_not_counted(self):
        data = chunk(236, [0.0] * 52, trailer=b"x8PL" + b"\x08\x00\x00\x00")
        self.assertEqual(find_blocks(data)[0][2], 52)

    def test_multiple_chunks(self):
        data = chunk(236, [0.0] * 52) + chunk(154, [0.0] * 31)
        self.assertEqual([(t, n) for _i, t, n in find_blocks(data)], [(236, 52), (154, 31)])

    def test_truncated_chunk_clamps_to_available(self):
        full = chunk(236, [0.0] * 52)
        truncated = full[:-80]
        n = find_blocks(truncated)[0][2]
        self.assertLessEqual(n, (len(truncated) - (full.index(b"GAMETSPP") + 12)) // 4)
        read_block_floats(truncated, find_blocks(truncated)[0][0], n)  # must not raise

    def test_block_at_offset_zero_has_no_room_for_header(self):
        """A bare tag with no preceding chunk header must not crash or read negatively."""
        data = b"GAMETSPP" + struct.pack("<I", 236) + struct.pack("<4f", 1, 2, 3, 4)
        idx, _t, n = find_blocks(data)[0]
        self.assertEqual(read_block_floats(data, idx, n), [1.0, 2.0, 3.0, 4.0])


class ChannelHeaderTest(unittest.TestCase):
    """Channel records are `OCuA <class-version> \\x00\\x0e\\x00`. The version varies by the
    Logic build that wrote the file (5, 6 and 7 all occur); pinning it to 6-7 silently
    reports zero channels for older projects instead of failing loudly."""

    def test_matches_all_observed_versions(self):
        from logicxkit.logicx.container import _CHANNEL_HDR
        for ver in (5, 6, 7):
            self.assertTrue(_CHANNEL_HDR.search(b"OCuA" + bytes([ver]) + b"\x00\x0e\x00"),
                            f"class version {ver} must be recognised")

    def test_does_not_match_foreign_class_marker(self):
        from logicxkit.logicx.container import _CHANNEL_HDR
        self.assertIsNone(_CHANNEL_HDR.search(b"OCuA\x06\x00\x17\x00"))
