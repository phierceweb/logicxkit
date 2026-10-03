"""The MIDI writers' arithmetic and refusals, without a real file."""

import unittest
import _paths  # noqa: F401
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.midi.midi import REGION_BAR_ONE
from logicxkit.logic.services.midi.midi_write import entry_tick, note_lines


class TickTest(unittest.TestCase):
    def test_a_region_entry_stores_bar_1_at_34560(self):
        self.assertEqual(entry_tick(BAR_ONE), REGION_BAR_ONE)
        self.assertEqual(entry_tick(BAR_ONE + 2 * 3840), 42240)

    def test_a_note_is_two_lines_with_the_measured_fields(self):
        head, ext = note_lines(tick=BAR_ONE + 960, pitch=62, velocity=79, length=960, channel=2)
        self.assertEqual((head[0], head[11], head[12], head[15]), (0x91, 79, 62, 0x01))
        self.assertEqual(int.from_bytes(head[4:8], "little"), BAR_ONE + 960)
        self.assertEqual((ext[7], int.from_bytes(ext[12:16], "little")), (0x89, 960))

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "pitch"):
            note_lines(tick=BAR_ONE, pitch=128, velocity=80, length=240, channel=1)
        with self.assertRaisesRegex(ValueError, "channel"):
            note_lines(tick=BAR_ONE, pitch=60, velocity=80, length=240, channel=17)
        with self.assertRaisesRegex(ValueError, "length"):
            note_lines(tick=BAR_ONE, pitch=60, velocity=80, length=0, channel=1)
        with self.assertRaisesRegex(ValueError, "does not fit its 32-bit field"):
            note_lines(tick=BAR_ONE, pitch=60, velocity=80, length=1 << 32, channel=1)


class NameTest(unittest.TestCase):
    def test_a_region_name_outside_ascii_is_utf8_with_its_byte_length(self):
        import struct
        from logicxkit.logic.services.stream.stream import HEADER
        from logicxkit.logic.services.midi.midi import NAME_AT, _name
        from logicxkit.logic.services.midi.midi_write import _template, _with_name
        raw = _with_name(_template()["qesm"], "Pad — é")
        self.assertEqual((_name(raw), struct.unpack_from("<H", raw, HEADER + NAME_AT)[0]), ("Pad — é", 10))


class PlaceEntryTest(unittest.TestCase):
    def test_a_new_entry_lands_between_flexed_entries_with_their_marker_blocks_intact(self):
        import struct
        from logicxkit.logic.services.midi.midi_write import _place_entry
        from logicxkit.logic.services.regions.regions import ENTRY, TAIL, entry_offsets

        def entry(tick: int) -> bytes:
            e = bytearray(ENTRY)
            struct.pack_into("<I", e, 0, 0x24)
            struct.pack_into("<I", e, 4, tick)
            return bytes(e)

        block = bytearray(ENTRY)
        block[6:8] = b"\x01\xaa"
        tail = bytes(TAIL)
        payload = entry(34560) + bytes(block) * 2 + entry(42240) + bytes(block) + tail
        out = _place_entry(payload, entry(38400))
        self.assertEqual(len(out), len(payload) + ENTRY)
        self.assertEqual(entry_offsets(out), [0, 3 * ENTRY, 4 * ENTRY])
        self.assertEqual([struct.unpack_from("<I", out, off + 4)[0] for off in entry_offsets(out)], [34560, 38400, 42240])
        self.assertEqual(out[ENTRY:3 * ENTRY], bytes(block) * 2)           # the first entry keeps both blocks
        self.assertEqual(out[5 * ENTRY:6 * ENTRY], bytes(block))           # and the last keeps its one
        self.assertEqual(out[-TAIL:], tail)


if __name__ == "__main__":
    unittest.main()
