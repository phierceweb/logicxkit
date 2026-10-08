"""A plug-in slot's header: Logic's short name, the three identity words and the instrument flag."""

import struct
import unittest
import _paths  # noqa: F401
from logicxkit.logic.services.mixer.slot_identity import SlotHeader, slot_header


def slot(name: bytes, maker: bytes, word: bytes, code: bytes, *, flags: int = 0, kind: int = 1, size: int = 192) -> bytes:
    p = bytearray(max(size, 192))
    struct.pack_into("<H", p, 4, kind)
    p[120:120 + len(name)] = name
    p[132:136], p[136:140], p[140:144] = maker, word, code
    p[151] = flags
    return bytes(p[:size])


class SlotHeaderTest(unittest.TestCase):
    def test_a_native_slot_reads_its_type_id_and_variant_word(self):
        payload = slot(b"Echo", b"GAME", struct.pack("<I", 33), struct.pack("<I", 147))
        self.assertEqual(slot_header(payload), SlotHeader("Echo", "EMAG", 33, 147, False))

    def test_a_sampler_family_slot_reads_its_four_letter_code(self):
        payload = slot(b"Drum Kit", b"MELC", struct.pack("<I", 0), b"LMNA", flags=0x08)
        self.assertEqual(slot_header(payload), SlotHeader("Drum Kit", "CLEM", 0, "ANML", True))

    def test_an_audio_unit_slot_reads_its_component(self):
        payload = slot(b"Pro-C 2", b"FbaF", b"xfua", b"p2CF")
        self.assertEqual(slot_header(payload), SlotHeader("Pro-C 2", "FabF", "aufx", "FC2p", False))

    def test_the_name_fills_all_twelve_bytes_without_a_terminator(self):
        payload = slot(b"AUAudioFile\x00", b"lppa", b"ngua", b"lpfa", flags=0x08)
        self.assertEqual(slot_header(payload).name, "AUAudioFile")
        self.assertEqual(slot_header(slot(b"TwelveLetter", b"GAME", bytes(4), bytes(4))).name, "TwelveLetter")

    def test_the_open_window_bit_is_not_the_instrument_flag(self):
        payload = slot(b"Gain", b"GAME", bytes(4), struct.pack("<I", 183), flags=0x10)
        self.assertFalse(slot_header(payload).instrument)
        self.assertTrue(slot_header(slot(b"Klopfgeist", b"GAME", bytes(4), struct.pack("<I", 158), flags=0x18)).instrument)

    def test_a_midi_effects_slot_is_kind_two_with_the_same_header(self):
        payload = slot(b"Arpeggiator", b"GAME", bytes(4), struct.pack("<I", 300), flags=0x02, kind=2)
        head = slot_header(payload)
        self.assertEqual((head.name, head.maker, head.code, head.midi, head.instrument), ("Arpeggiator", "EMAG", 300, True, False))
        self.assertFalse(slot_header(slot(b"Gain", b"GAME", bytes(4), struct.pack("<I", 183))).midi)

    def test_a_record_that_is_not_a_slot_has_no_header(self):
        self.assertIsNone(slot_header(slot(b"Gain", b"GAME", bytes(4), struct.pack("<I", 183), kind=7)))
        self.assertIsNone(slot_header(slot(b"", b"GAME", bytes(4), bytes(4), size=68)))


if __name__ == "__main__":
    unittest.main()
