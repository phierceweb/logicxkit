"""`add_plugin` with a donor that is not an audio effect: one of Logic's instruments goes into an
instrument channel's slot 1 as it was saved, the channel record following it; a MIDI effect is
refused."""

import struct
import unittest

from _records import proj
from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.mixer.transplant import channel_slots
from test_add_plugin import OWNER, _project
from test_transplant_ids import MONO, STEREO, mono_chan, native, ref


def _instrument(n: int, fmt: int, type_id: int = 214) -> bytes:
    """A donor as Logic writes an instrument's slot: the header says so (kind 1, `+151` bit 0x08)."""
    raw = bytearray(native(9, 4, n, fmt=fmt))
    p = HEADER
    struct.pack_into("<H", raw, p + 4, 1)
    raw[p + 120:p + 123] = b"ES2"
    raw[p + 132:p + 136] = b"GAME"
    struct.pack_into("<I", raw, p + 140, type_id)
    struct.pack_into("<I", raw, p + 200 + 20, type_id)       # the chunk's own type word
    raw[p + 151] = 0x08
    return bytes(raw)


def _inst_project(fmt: int, *slots: bytes) -> bytes:
    channel = bytearray(mono_chan(OWNER, "Inst 3", fmt))
    channel[HEADER + 78], channel[HEADER + 86] = (0xF3, 0) if fmt == MONO else (0xF7, 1)
    return proj(bytes(channel), *slots, ref(OWNER, 10), mono_chan(5, "Audio 5"), native(5, 4, 50), ref(5, 10))


def _channel_width(data: bytes) -> tuple[int, int, int]:
    record = next(r for r in project_records(data) if r.tag == b"OCuA" and r.owner == OWNER)
    return tuple(record.raw[HEADER + off] for off in (78, 86, 123))


class InstrumentDonorTest(unittest.TestCase):
    """An instrument goes into slot 1 as it was saved and the channel takes its width, as Logic's
    own load from the slot menu does (`instrument-es2-logic` beside `instrument-es-m-logic`)."""

    WIDTH_FIELDS = (81, 84, 116, 117, 118, 119, 156)

    def test_a_stereo_instrument_makes_a_mono_instrument_channel_stereo(self):
        donor = _instrument(7, STEREO)
        out, report = add_plugin(_inst_project(MONO), OWNER, donor, at=1)
        self.assertEqual(_channel_width(out), (0xF7, 1, 2))
        self.assertEqual((report["key"], report["width"]), (4, STEREO))

    def test_a_mono_instrument_makes_a_stereo_instrument_channel_mono(self):
        out, _ = add_plugin(_inst_project(STEREO), OWNER, _instrument(7, MONO), at=1)
        self.assertEqual(_channel_width(out), (0xF3, 0, 1))

    def test_the_instrument_keeps_the_width_it_was_saved_at(self):
        donor = _instrument(7, STEREO)
        out, _ = add_plugin(_inst_project(MONO), OWNER, donor, at=1)
        slot = channel_slots(out, OWNER)[0].raw
        self.assertEqual([slot[HEADER + o] for o in self.WIDTH_FIELDS], [donor[HEADER + o] for o in self.WIDTH_FIELDS])

    def test_with_an_effect_after_it_only_the_input_byte_follows_the_instrument(self):
        """The channel's width is its output's, the end of the chain: Logic left a mono channel
        and its mono effect as they were under a stereo instrument and set `+86`
        (`instrument-es2-over-chromaglow-logic`)."""
        effect = native(OWNER, 5, 60, fmt=MONO)
        out, _ = add_plugin(_inst_project(MONO, effect), OWNER, _instrument(7, STEREO), at=1)
        slots = channel_slots(out, OWNER)
        self.assertEqual(([r.key for r in slots], slots[1].raw), ([4, 5], effect))
        self.assertEqual(_channel_width(out), (0xF3, 1, 1))

    def test_a_mono_instrument_under_a_stereo_chain_clears_the_input_byte_alone(self):
        effect = native(OWNER, 5, 60, fmt=STEREO)
        out, _ = add_plugin(_inst_project(STEREO, effect), OWNER, _instrument(7, MONO), at=1)
        self.assertEqual((channel_slots(out, OWNER)[1].raw, _channel_width(out)), (effect, (0xF7, 0, 2)))

    def test_an_instrument_of_the_channels_width_changes_no_channel_byte(self):
        before = _inst_project(STEREO)
        out, _ = add_plugin(before, OWNER, _instrument(7, STEREO), at=1)
        self.assertEqual(_channel_width(out), _channel_width(before))


class MidiEffectDonorTest(unittest.TestCase):
    def test_a_midi_effect_is_refused_as_an_audio_effect(self):
        donor = bytearray(native(9, 4, 7))
        struct.pack_into("<H", donor, HEADER + 4, 2)             # the kind word of a MIDI FX slot
        donor[HEADER + 132:HEADER + 136] = b"GAME"
        struct.pack_into("<I", donor, HEADER + 140, 300)
        with self.assertRaises(ValueError) as e:
            add_plugin(_project(native(OWNER, 4, 1)), OWNER, bytes(donor))
        self.assertIn("MIDI", str(e.exception))


if __name__ == "__main__":
    unittest.main()
