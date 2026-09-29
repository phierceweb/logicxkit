"""What a chain plan reports it changes on a channel."""

import unittest

from logicxkit.logic.services.chain_report import ChainChange


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


if __name__ == "__main__":
    unittest.main()
