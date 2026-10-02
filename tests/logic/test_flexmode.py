"""The channel object's flex fields: Q-Reference and the flex mode (the logic README,
"Flex and audio quantize")."""

import unittest

import _paths  # noqa: F401
from _records import env_obj
from logicxkit.logic.services.environment import KIND_AT, name_end
from logicxkit.logic.services.flexmode import (
    FLEX_MODE_AFTER_NAME, MODES, flex_mode, q_reference, set_flex_mode, set_q_reference,
)
from logicxkit.logic.services.stream import HEADER


class QReferenceTest(unittest.TestCase):
    def test_bit_4_of_the_kind_byte_means_off(self):
        raw = env_obj(88, "Kick In")
        self.assertTrue(q_reference(raw))
        off = set_q_reference(raw, False)
        self.assertFalse(q_reference(off))
        self.assertEqual(off[HEADER + KIND_AT], 0x90)
        self.assertEqual(set_q_reference(off, True), raw)
        self.assertEqual([k for k in range(len(raw)) if raw[k] != off[k]], [HEADER + KIND_AT])


class FlexModeTest(unittest.TestCase):
    def test_slicing_and_monophonic_read_and_write_as_measured(self):
        for name in ("Kick In", "Snare Down", "OH L"):
            raw = env_obj(96, name)
            self.assertIsNone(flex_mode(raw))
            at = HEADER + name_end(raw[HEADER:]) + FLEX_MODE_AFTER_NAME
            slicing = set_flex_mode(raw, "Slicing")
            self.assertEqual(slicing[at:at + 3], bytes(MODES["Slicing"]))
            self.assertEqual(flex_mode(slicing), "Slicing")
            self.assertEqual(slicing[HEADER + KIND_AT] & 0x20, 0)
            mono = set_flex_mode(slicing, "Monophonic")
            self.assertEqual(mono[at:at + 3], bytes(MODES["Monophonic"]))
            self.assertEqual((flex_mode(mono), mono[HEADER + KIND_AT] & 0x20), ("Monophonic", 0x20))
            self.assertEqual(flex_mode(set_flex_mode(mono, "Slicing")), "Slicing")
            self.assertEqual(len(slicing), len(raw))

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            set_flex_mode(env_obj(1, "x"), "Rhythmic")


if __name__ == "__main__":
    unittest.main()
