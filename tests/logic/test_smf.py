"""`logic midi --export`: the regions as a Standard MIDI File through groovebin, read back with it."""

import unittest
from unittest import mock

import _paths  # noqa: F401
from groovebin.midi import read
from logicxkit.logic.services.song.events import BAR_ONE, PPQ
from logicxkit.logic.services.midi.midi import MidiEvent, MidiRegion
from logicxkit.logic.services.midi.smf import tempo_map, write_smf
from logicxkit.logic.services.song.tempo import TempoEvent

FOUR_FOUR = [(BAR_ONE, 4, 4)]


def region(*events, name="Inst 1", track="Inst 1", start=BAR_ONE + 2 * 4 * PPQ):
    return MidiRegion(track, 2, name, start, False, list(events))


def metas(part) -> list[tuple[int, int, bytes]]:
    return [(e.tick, e.meta_type, e.payload) for e in part.events if e.kind == "meta" and e.meta_type != 0x03]


class FileTest(unittest.TestCase):
    def test_header_tempo_meter_and_one_track_per_region(self):
        song = read(write_smf([region(), region(name="Second")], tempos=[(BAR_ONE, 120.0)], meters=[(960, 3, 4)]))
        self.assertEqual((song.format, song.ppq, len(song.tracks)), (1, PPQ, 3))
        self.assertEqual(metas(song.tracks[0]), [(0, 0x51, (60_000_000 // 120).to_bytes(3, "big")), (0, 0x58, b"\x03\x02\x18\x08")])
        self.assertEqual([t.name for t in song.tracks[1:]], ["Inst 1: Inst 1", "Inst 1: Second"])

    def test_tempo_changes_and_meter_changes_at_their_ticks_from_bar_1(self):
        song = read(write_smf([], tempos=[(BAR_ONE, 120.0), (BAR_ONE + 4 * PPQ, 90.0), (BAR_ONE + 4 * PPQ + 1, 140.0)],
                              meters=[(0, 4, 4), (BAR_ONE + 8 * PPQ, 7, 8)]))
        self.assertEqual(metas(song.tracks[0]), [
            (0, 0x51, (500000).to_bytes(3, "big")), (0, 0x58, b"\x04\x02\x18\x08"),
            (4 * PPQ, 0x51, round(60_000_000 / 90).to_bytes(3, "big")),
            (4 * PPQ + 1, 0x51, round(60_000_000 / 140).to_bytes(3, "big")), (8 * PPQ, 0x58, b"\x07\x03\x18\x08")])

    def test_a_note_becomes_on_and_off_at_region_relative_times(self):
        start = BAR_ONE + 2 * 4 * PPQ
        song = read(write_smf([region(MidiEvent("note", start + PPQ, 2, 62, 79, length=480))],
                              tempos=[(BAR_ONE, 120.0)], meters=FOUR_FOUR))
        (n,) = song.tracks[1].notes
        self.assertEqual((n.tick, n.length, n.channel, n.pitch, n.velocity, n.off_velocity), (2 * 4 * PPQ + PPQ, 480, 2, 62, 79, 64))

    def test_controller_program_and_bend(self):
        evs = [MidiEvent("program", BAR_ONE, 1, 5, 0), MidiEvent("controller", BAR_ONE, 1, 1, 100),
               MidiEvent("bend", BAR_ONE, 1, 0x00, 0x40)]
        song = read(write_smf([region(*evs, start=BAR_ONE)], tempos=[(BAR_ONE, 100.0)], meters=FOUR_FOUR))
        self.assertEqual(sorted((e.tick, e.data) for e in song.tracks[1].events if e.kind != "meta"),
                         [(0, b"\xb0\x01\x64"), (0, b"\xc0\x05"), (0, b"\xe0\x00\x40")])


class TempoMapTest(unittest.TestCase):
    def test_ramp_points_logic_generated_are_tempo_events_too(self):
        track = [TempoEvent(BAR_ONE, 120.0, False), TempoEvent(BAR_ONE + PPQ, 125.0, True), TempoEvent(BAR_ONE + 2 * PPQ, 130.0, False)]
        with mock.patch("logicxkit.logic.services.midi.smf.read_tempo_events", return_value=track):
            self.assertEqual(tempo_map(b""), [(BAR_ONE, 120.0), (BAR_ONE + PPQ, 125.0), (BAR_ONE + 2 * PPQ, 130.0)])


class BeforeBarOneTest(unittest.TestCase):
    def test_a_region_starting_before_bar_1_with_its_events_after_it_exports(self):
        note = MidiEvent("note", BAR_ONE, 1, 60, 100, length=240)
        song = read(write_smf([region(note, start=BAR_ONE - 4 * PPQ)], tempos=[(BAR_ONE, 120.0)], meters=FOUR_FOUR))
        self.assertEqual([(n.tick, n.pitch) for n in song.tracks[1].notes], [(0, 60)])

    def test_an_event_before_bar_1_is_refused_naming_its_region(self):
        note = MidiEvent("note", BAR_ONE - PPQ, 1, 60, 100, length=240)
        with self.assertRaisesRegex(ValueError, "'pickup' on 'Inst 1'.*before bar 1"):
            write_smf([region(note, name="pickup", start=BAR_ONE - 4 * PPQ)], tempos=[(BAR_ONE, 120.0)], meters=FOUR_FOUR)

    def test_a_tempo_event_before_bar_1_is_refused(self):
        with self.assertRaisesRegex(ValueError, "tempo event .*before bar 1"):
            write_smf([], tempos=[(BAR_ONE - PPQ, 120.0)], meters=FOUR_FOUR)


if __name__ == "__main__":
    unittest.main()
