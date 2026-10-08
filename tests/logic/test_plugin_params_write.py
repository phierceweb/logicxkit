"""Writing a table parameter: the mirror a Vintage B3 drawbar keeps in float, the one measured
shape of a linked row, and a display that is not linear in the word."""

import unittest

from _fixtures import chunk
from logicxkit.logic.services.mixer.plugin_params import Table, decode, set_by_name


MIRRORED = {"type": 216, "name": "Test Organ", "floats": 3, "opaque": [0],
            "params": [{"offset": 36, "name": "1 LM 16'", "kind": "int", "mirror": 44, "default": 8},
                       {"index": 1, "name": "MM2 Amount", "linked": [2], "default": 0.0},
                       {"index": 0, "name": "Drum Width", "default": 0.0},
                       {"index": 2, "name": "VecEnv Select Point", "linked": [0, 1, 20], "default": 0.0}],
            "evidence": "a synthetic table"}


class MirroredAndLinkedTest(unittest.TestCase):
    """Vintage B3 keeps each lower-manual drawbar as an int32 past the block and the same number
    as a float further on; a write sets both. A row that moved other words too (`linked`) is
    written at its own word alone: Logic's load derives the linked word from it
    (`instrument-set-es2-resave-logic`: word 47 came back as MM2 Amount's value)."""

    def _payload(self) -> bytes:
        import struct
        return chunk(216, [0.0, 0.0, 0.0]) + struct.pack("<i", 8) + bytes(4) + struct.pack("<f", 8.0) + bytes(4)

    def test_a_mirrored_word_is_written_as_the_same_number_in_float(self):
        import struct
        out = set_by_name(Table.from_dict(MIRRORED), self._payload(), {"1 LM 16'": 3})
        self.assertEqual((struct.unpack_from("<i", out, 36)[0], struct.unpack_from("<f", out, 44)[0]), (3, 3.0))
        self.assertEqual(decode(Table.from_dict(MIRRORED), [0.0, 0.0, 0.0]).get("1 LM 16'", None), None)   # the block alone has no offset words

    def test_a_mirror_past_the_record_is_refused(self):
        import struct
        short = chunk(216, [0.0, 0.0, 0.0]) + struct.pack("<i", 8) + bytes(4)        # no room for the mirror
        with self.assertRaisesRegex(ValueError, "mirror offset 44"):
            set_by_name(Table.from_dict(MIRRORED), short, {"1 LM 16'": 3})

    def test_a_linked_row_of_an_unmeasured_shape_is_refused(self):
        """One save shows Logic deriving the next word from an MM Amount; a row that moves four
        other words (ES2's VecEnv Select Point) is not that shape."""
        with self.assertRaisesRegex(ValueError, "VecEnv Select Point.*unmeasured"):
            set_by_name(Table.from_dict(MIRRORED), self._payload(), {"VecEnv Select Point": 1})

    def test_a_parameter_with_linked_words_is_written_at_its_own_word_alone(self):
        from logicxkit.logic._binary import find_blocks, read_block_floats
        out = set_by_name(Table.from_dict(MIRRORED), self._payload(), {"MM2 Amount": 0.5})
        idx, _t, n = find_blocks(out)[0]
        self.assertEqual(list(read_block_floats(out, idx, n)), [0.0, 0.5, 0.0])

    def test_a_non_finite_number_is_refused(self):
        for bad in ("nan", "inf", "-inf"):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "finite"):
                set_by_name(Table.from_dict(MIRRORED), self._payload(), {"Drum Width": bad})

    def test_a_word_for_a_row_with_no_choices_is_refused_by_name(self):
        with self.assertRaisesRegex(ValueError, "Test Organ Drum Width: 'Free' is not a number"):
            set_by_name(Table.from_dict(MIRRORED), self._payload(), {"Drum Width": "Free"})

    def test_a_row_placed_by_order_alone_is_refused(self):
        """Coded series re-tested 411 order placements and moved 13: a word named by
        row order alone is not written."""
        table = Table.from_dict({"type": 222, "name": "Test Sculpture", "floats": 2, "opaque": [0],
                                 "params": [{"index": 0, "name": "Env1 Curve 1", "evidence": "order", "default": 0.0},
                                            {"index": 1, "name": "Env1 Level 0", "evidence": "code", "default": 0.0}]})
        with self.assertRaisesRegex(ValueError, "Env1 Curve 1.*row order"):
            set_by_name(table, chunk(222, [0.0, 0.0]), {"Env1 Curve 1": 0.5})
        set_by_name(table, chunk(222, [0.0, 0.0]), {"Env1 Level 0": 0.5})


CURVED = {"type": 285, "name": "Test Graphic EQ", "floats": 2, "opaque": [0],
          "params": [{"index": 1, "name": "8.0K", "unit": "dB", "default": 0.0,
                      "curve": [[-12.0, -12.0], [-3.0, -1.5], [0.0, 0.0], [4.0, 2.7], [12.0, 12.0]]}],
          "evidence": "a synthetic table"}


class CurvedDisplayTest(unittest.TestCase):
    """A band whose display is not linear in the word carries the (word, shown) pairs Logic
    showed at measured slider positions; a read interpolates between them and a write inverts."""

    def test_a_read_interpolates_the_measured_points(self):
        table = Table.from_dict(CURVED)
        self.assertEqual(decode(table, [0.0, 4.0])["8.0K"], 2.7)
        self.assertEqual(decode(table, [0.0, 2.0])["8.0K"], 1.35)
        self.assertEqual(decode(table, [0.0, -3.0])["8.0K"], -1.5)
        self.assertEqual(decode(table, [0.0, 20.0])["8.0K"], 12.0)          # past the last point: the end's value

    def test_a_write_inverts_the_curve(self):
        from logicxkit.logic._binary import find_blocks, read_block_floats
        table = Table.from_dict(CURVED)
        out = set_by_name(table, chunk(285, [0.0, 0.0]), {"8.0K": 2.7})
        idx, _t, n = find_blocks(out)[0]
        self.assertEqual(read_block_floats(out, idx, n)[1], 4.0)
        out = set_by_name(table, chunk(285, [0.0, 0.0]), {"8.0K": -0.75})
        self.assertEqual(read_block_floats(out, idx, n)[1], -1.5)


SCALED_CHOICE = {"type": 145, "name": "Test Chorus", "floats": 5, "opaque": [0],
                 "params": [{"index": 4, "name": "D-Mode", "scale": 0.01, "choices": ["Off", "On"], "default": 0.0}],
                 "evidence": "a synthetic table"}


class ScaledChoiceTest(unittest.TestCase):
    """A row shown as a checkbox over a word of 0 and 100 (Chorus's D-Mode): the word times the
    scale is the choice's index, and a choice written by name goes in as index over scale."""

    def test_a_scaled_choice_reads_by_name_and_writes_as_its_word(self):
        from logicxkit.logic._binary import find_blocks, read_block_floats
        table = Table.from_dict(SCALED_CHOICE)
        self.assertEqual(decode(table, [0.0, 0.0, 0.0, 0.0, 100.0])["D-Mode"], "On")
        self.assertEqual(decode(table, [0.0, 0.0, 0.0, 0.0, 0.0])["D-Mode"], "Off")
        out = set_by_name(table, chunk(145, [0.0] * 5), {"D-Mode": "On"})
        idx, _t, n = find_blocks(out)[0]
        self.assertEqual(read_block_floats(out, idx, n)[4], 100.0)


NAMED = {"type": 229, "name": "Test Scanner", "floats": 6, "opaque": [0],
         "params": [{"index": 5, "name": "Stereo Phase", "unit": "", "min": -10.0, "max": 360.0, "named": {"Free": -10.0}, "default": -10.0}],
         "evidence": "a synthetic table"}


class NamedWordTest(unittest.TestCase):
    """Scanner Vibrato's Stereo Phase shows "Free" at word -10 and degrees from 0 to 360: the named
    word reads as its name, is written by it, and the range still holds."""

    def test_a_named_word_reads_and_writes_by_name(self):
        from logicxkit.logic._binary import find_blocks, read_block_floats
        table = Table.from_dict(NAMED)
        self.assertEqual(decode(table, [0.0] * 5 + [-10.0])["Stereo Phase"], "Free")
        self.assertEqual(decode(table, [0.0] * 5 + [170.0])["Stereo Phase"], 170.0)
        out = set_by_name(table, chunk(229, [0.0] * 6), {"Stereo Phase": "Free"})
        idx, _t, n = find_blocks(out)[0]
        self.assertEqual(read_block_floats(out, idx, n)[5], -10.0)
        with self.assertRaisesRegex(ValueError, "outside -10.0..360.0"):
            set_by_name(table, chunk(229, [0.0] * 6), {"Stereo Phase": 400})


if __name__ == "__main__":
    unittest.main()
