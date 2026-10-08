"""What a chain plan reports it changes on a channel."""

import unittest

from logicxkit.logic.services.mixer.chain_report import ChainChange


def change(before: list[str], after: list[str], replaced: list[str] = ()) -> ChainChange:
    return ChainChange(owner=0, ref="Kick.cst", before=list(before), after=list(after), replaced=list(replaced))


class ChainChangeTest(unittest.TestCase):
    def test_the_same_plugins_in_another_order_is_a_reorder(self):
        c = change(["Channel EQ", "Compressor"], ["Compressor", "Channel EQ"])
        self.assertTrue(c.reordered)
        self.assertIn("REORDER", c.line())

    def test_other_plugins_are_a_replace_naming_both_chains(self):
        c = change(["Channel EQ"], ["Compressor"], replaced=["Channel EQ"])
        self.assertFalse(c.reordered)
        self.assertIn("REPLACE  Channel EQ  ==>  Compressor", c.line())

    def test_an_empty_channel_just_gains_the_chain(self):
        c = change([], ["Channel EQ", "Compressor"])
        self.assertFalse(c.reordered)
        self.assertEqual(c.line(), f"{'Kick.cst':26s} + Channel EQ -> Compressor")


class SlotNameTest(unittest.TestCase):
    """What a report calls a slot it is about to replace: Logic's own plug-in by its header."""

    def slot(self, name: bytes, maker: bytes, code: bytes, preset: bytes = b"") -> bytes:
        import struct
        p = bytearray(192)
        struct.pack_into("<H", p, 4, 1)
        p[14:14 + len(preset)] = preset
        p[120:120 + len(name)] = name
        p[132:136], p[140:144] = maker, code
        return bytes(p)

    def test_an_instrument_with_no_float_block_is_named(self):
        from logicxkit.logic.services.mixer.chain_report import _slot_name
        self.assertEqual(_slot_name(self.slot(b"Drum Kit", b"MELC", b"LMNA")), "Drum Kit Designer")

    def test_the_header_wins_over_a_plugin_name_in_the_preset_string(self):
        import struct
        from logicxkit.logic.services.mixer.chain_report import _slot_name
        payload = self.slot(b"Compressor", b"GAME", struct.pack("<I", 154), preset=b"Gain Staging.pst")
        self.assertEqual(_slot_name(payload), "Compressor")


if __name__ == "__main__":
    unittest.main()
