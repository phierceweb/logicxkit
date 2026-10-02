"""Flex markers and the per-region quantize state, as Logic 12.3.1 wrote them on a quantize
(the logic README, "Flex and audio quantize"): the 80-byte marker block, the two anchors,
the flexed entry's flags, the RBA Sequence triple and the Quantize value code."""

import struct
import unittest

import _paths  # noqa: F401
from _data import needs
from logicxkit.logic.services.flexmarkers import (
    HIT, END_TAIL, MARKER, PPQ, anchors, block_fields, flexed_entry, marker_block, quantize_code,
    rba_triple, samples_per_tick, snap,
)
from logicxkit.logic.services.stream import HEADER
from logicxkit.logic.services.regions import ENTRY

SPB = 13230.0                    # samples per beat at 200 BPM, 44.1 kHz — the measured take


class BlockTest(unittest.TestCase):
    def test_a_hit_block_carries_source_samples_kind_and_target_ticks(self):
        b = marker_block(158968, 11520, HIT)
        self.assertEqual(len(b), MARKER)
        self.assertEqual(struct.unpack_from("<i", b, 0)[0], 158968)
        self.assertEqual(b[6:8], b"\x01\xaa")
        self.assertEqual(struct.unpack_from("<i", b, 12)[0], 11520)
        self.assertEqual(block_fields(marker_block(-5, 7, HIT, 0x8000)), (-5, HIT, 7, 0x8000))
        self.assertEqual([b[k] for k in (23, 39, 55, 71)], [0x88] * 4)
        self.assertEqual(sum(b) - 0x88 * 4 - 0xaa - 1, sum(b[0:4]) + sum(b[12:16]))

    def test_the_anchors_sit_one_beat_before_and_at_the_end_plus_the_tail(self):
        start, end = anchors(frames=2373916, samples_per_beat=SPB)
        self.assertEqual(struct.unpack_from("<i", start, 0)[0], -13230)
        self.assertEqual(start[6:8], b"\x07\xaa")
        self.assertEqual(struct.unpack_from("<i", start, 12)[0], -PPQ)
        self.assertEqual(struct.unpack_from("<i", end, 0)[0], 2373916)      # every quantized save: at the last frame
        self.assertEqual(END_TAIL, 1024)                                  # the unquantized flex shape sits this much later
        self.assertEqual(end[6:8], b"\x03\xaa")
        ticks, fraction = struct.unpack_from("<i", end, 12)[0], struct.unpack_from("<H", end, 10)[0]
        self.assertEqual(ticks, 172256)                       # Logic wrote 172256 with a 0.94 fraction
        self.assertGreater(fraction, 0xf000)

    def test_snapping_goes_to_the_nearest_grid_tick(self):
        spt = samples_per_tick(SPB)
        self.assertAlmostEqual(spt, 13.78125)
        self.assertEqual(snap(158968, spt, 16), 11520)       # 12.016 beats -> beat 12
        self.assertEqual(snap(230964, spt, 16), 16800)       # 17.458 -> 17.5
        self.assertEqual(snap(246295, spt, 16), 17760)       # 18.616 -> 18.5
        self.assertEqual(snap(246295, spt, 4), 18240)        # a quarter grid: 19
        self.assertEqual(snap(0, spt, 16), 0)

    def test_hits_sharing_a_target_keep_the_nearest_one(self):
        from logicxkit.logic.services.flexmarkers import hit_blocks
        spt = samples_per_tick(SPB)
        blocks = hit_blocks([1837344, 1839769, 1853446], spt=spt, grid=16)   # the first two both snap to 133440
        self.assertEqual([(struct.unpack_from("<i", b, 0)[0], struct.unpack_from("<i", b, 12)[0]) for b in blocks],
                         [(1839769, 133440), (1853446, 134400)])

    def test_the_quantize_codes_match_logics_four_values(self):
        self.assertEqual([quantize_code(d) for d in (4, 8, 16, 32)], [-10, -8, -6, -4])
        self.assertEqual(quantize_code(0), 0)
        for grid in (1, 2, 12, 64):                         # the formula's other values are unmeasured
            with self.subTest(grid), self.assertRaisesRegex(ValueError, "1/4, 1/8, 1/16 or 1/32"):
                quantize_code(grid)


class EntryTest(unittest.TestCase):
    def test_a_flexed_quantized_entry_sets_the_measured_bytes(self):
        base = bytearray(ENTRY)
        struct.pack_into("<I", base, 0, 0x24)
        struct.pack_into("<I", base, 32, 0xFFFFFFFF)
        out = flexed_entry(bytes(base), slot=224)
        self.assertEqual(len(out), ENTRY)
        self.assertEqual((out[13], out[15] & 0x10, out[48] & 0x80), (1, 0x10, 0x80))
        self.assertEqual(struct.unpack_from("<I", out, 32)[0], 224)
        untouched = [k for k in range(ENTRY) if k not in (13, 15, 32, 33, 34, 35, 48)]
        self.assertEqual([out[k] for k in untouched], [base[k] for k in untouched])
        self.assertEqual(flexed_entry(out, slot=224), out)


@needs("logic", "rba-sequence-12.3.1.json")
class RbaTest(unittest.TestCase):
    def test_the_triple_carries_id_slot_length_code_object_and_row(self):
        qesm, marker, qsve = rba_triple(seq_id=126, slot=224, length_ticks=172256, fraction=0xf17c,
                                        code=-6, track_object=88, row=8)
        self.assertEqual((qesm[:4], marker[:4], qsve[:4]), (b"qeSM", b"karT", b"qSvE"))
        p = qesm[HEADER:]
        self.assertEqual(len(p), 309)
        self.assertEqual(p[18:30], b"RBA Sequence")
        self.assertEqual(struct.unpack_from("<I", p, 8)[0], 126)
        self.assertEqual(struct.unpack_from("<H", qesm, 10)[0], 224)
        self.assertEqual(struct.unpack_from("<H", marker, 10)[0], 224)
        self.assertEqual((struct.unpack_from("<H", qsve, 10)[0], struct.unpack_from("<H", qsve, 14)[0]), (224, 126))
        self.assertEqual((struct.unpack_from("<H", p, 88)[0], struct.unpack_from("<I", p, 90)[0]), (0xf17c, 172256))
        self.assertEqual(struct.unpack_from("<h", p, 102)[0], -6)
        self.assertEqual((struct.unpack_from("<I", p, 234)[0], struct.unpack_from("<h", p, 242)[0]), (88, -8))
        self.assertEqual(len(qsve) - HEADER, 16)
        self.assertEqual(struct.unpack_from("<I", qesm, 28)[0], 309)


if __name__ == "__main__":
    unittest.main()
