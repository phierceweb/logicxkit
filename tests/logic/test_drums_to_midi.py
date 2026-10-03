"""Drum hits in audio to notes in a MIDI region: the velocity mapping, one note per key, a hit's
peak across a region cut, the file-record refusals, `--threshold`, and the term and spec refusals.
The writer end to end is in tests/goldens/test_drums_to_midi.py."""

import argparse
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from test_onsets import RATE, slow_track, write_wav

from logicxkit.logic._drums_to_midi_cmd import detector_of, parse_hits, parse_velocity, register
from logicxkit.logic._edit import CommandError
from logicxkit.logic.services.regions.audio_regions import AudioFile, AudioRegion
from logicxkit.logic.services.midi.drums_to_midi import SIXTEENTH, _track_hits, note_for, one_per_key, velocities
from logicxkit.logic.services.song.events import BAR_ONE, PPQ
from groovebin.events import Note
from logicxkit.logic.services.regions.onsets import Detector

BPM = 120.0
SAMPLES_PER_TICK = RATE * 60 / BPM / PPQ


class VelocityTest(unittest.TestCase):
    def test_the_quietest_hit_is_1_the_loudest_127_linear_in_db(self):
        self.assertEqual(velocities([0.1, 1.0, 10 ** (-0.5)]), [1, 127, 64])

    def test_one_level_is_127(self):
        self.assertEqual(velocities([0.5, 0.5]), [127, 127])
        self.assertEqual(velocities([0.3]), [127])


class TermTest(unittest.TestCase):
    def test_a_term_resolves_through_the_map(self):
        self.assertEqual((note_for("addictive-drums-2", "kick"), note_for("addictive-drums-2", "snare"),
                          note_for("gm", "hihat closed")), (36, 38, 42))

    def test_an_unknown_term_is_refused_with_valid_ones(self):
        with self.assertRaisesRegex(ValueError, r"no gm drum map term 'kik'; try .*kick.*snare"):
            note_for("gm", "kik")
        with self.assertRaisesRegex(ValueError, r"'hihat clsoed'; try hihat closed"):
            note_for("gm", "hihat clsoed")

    def test_an_unknown_map_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no note map"):
            note_for("xx", "kick")


def note(tick: int, pitch: int, velocity: int) -> Note:
    return Note(tick, SIXTEENTH, 1, pitch, velocity)


class OnePerKeyTest(unittest.TestCase):
    def test_one_note_per_key_and_tick_the_loudest_and_no_overlap_on_a_key(self):
        notes = [note(0, 36, 40), note(0, 36, 90), note(0, 38, 50), note(100, 36, 70)]
        kept, merged = one_per_key(notes)
        self.assertEqual(merged, 1)
        self.assertEqual([(n.tick, n.pitch, n.velocity, n.length) for n in kept],
                         [(0, 36, 90, 100), (0, 38, 50, SIXTEENTH), (100, 36, 70, SIXTEENTH)])


def region(name: str, offset: int, frames: int, file: AudioFile) -> AudioRegion:
    return AudioRegion("Kick", 0, name, BAR_ONE + round(offset / SAMPLES_PER_TICK), frames, file, offset, 1)


def audio_file(name: str, frames: int, rate: int = RATE) -> AudioFile:
    return AudioFile(name, "", 0, "WAVE", 0, frames, rate, 1, 24)


class TrackHitsTest(unittest.TestCase):
    FRAMES = 4 * RATE
    LOUD = RATE // 2

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wav = Path(self.tmp.name) / "kick.wav"
        write_wav(self.wav, slow_track([(RATE // 4, 0.5), (self.LOUD, 0.9), (5 * RATE // 4, 0.5)], self.FRAMES))
        self.file = audio_file("kick.wav", self.FRAMES)

    def tearDown(self):
        self.tmp.cleanup()

    def hits(self, regions, wav=None):
        return _track_hits(regions, lambda _r: wav or self.wav, BPM, Detector())

    def test_a_split_just_after_an_onset_keeps_the_hit_whole_in_the_region_holding_its_onset(self):
        whole = self.hits([region("kick", 0, self.FRAMES, self.file)])
        for cut in (24, 40, 100):
            cut_at = self.LOUD + cut
            split = self.hits([region("a", 0, cut_at, self.file), region("b", cut_at, self.FRAMES - cut_at, self.file)])
            with self.subTest(cut):
                self.assertEqual(len(split), 3)
                self.assertEqual(velocities([p for _t, p in split]), velocities([p for _t, p in whole]))
                self.assertEqual([p for _t, p in split], [p for _t, p in whole])

    def test_a_wav_at_another_rate_than_its_record_is_refused_naming_both(self):
        at_48k = region("kick", 0, self.FRAMES, audio_file("kick.wav", self.FRAMES, rate=48000))
        with self.assertRaisesRegex(ValueError, r"kick\.wav.*44100 Hz.*48000 Hz"):
            self.hits([at_48k])

    def test_a_wav_of_another_length_than_its_own_record_is_refused_naming_both(self):
        short = region("kick", 0, RATE, audio_file("kick.wav", 2 * RATE))
        with self.assertRaisesRegex(ValueError, rf"kick\.wav.*{self.FRAMES} frames.*{2 * RATE} frames"):
            self.hits([short])

    def test_another_named_take_is_not_held_to_the_paired_record_length(self):
        other = region("kick", 0, RATE, audio_file("kick#02.wav", 2 * RATE))
        self.assertEqual(len(self.hits([other])), 2)


class ThresholdTest(unittest.TestCase):
    def args(self, *extra):
        ap = argparse.ArgumentParser()
        register(ap.add_subparsers())
        return ap.parse_args(["drums-to-midi", "p.logicx", "--hit", "Kick=kick", "--track", "Inst", *extra])

    def test_the_default_detector_without_the_flag(self):
        self.assertEqual(detector_of(self.args()), Detector())

    def test_the_threshold_is_the_floor_under_the_track_peak(self):
        self.assertEqual(detector_of(self.args("--threshold", "-30")), Detector(floor_db=-30.0))

    def test_a_threshold_above_the_peak_is_refused(self):
        with self.assertRaisesRegex(CommandError, "--threshold"):
            detector_of(self.args("--threshold", "3"))


class SpecTest(unittest.TestCase):
    def test_track_equals_term_with_its_own_floor(self):
        self.assertEqual(parse_hits(["Kick In=kick", "Hi=Hat = Hihat  Closed", "Hi Hat=hihat closed:-30", "Ride=ride:-27.5"]),
                         [("Kick In", "kick", None), ("Hi=Hat", "hihat closed", None), ("Hi Hat", "hihat closed", -30.0), ("Ride", "ride", -27.5)])
        self.assertEqual(parse_hits(["Kick=kick:loud"]), [("Kick", "kick:loud", None)])

    def test_a_bad_spec_names_the_shape(self):
        for spec in ("Kick In", "=kick", "Kick In=", ""):
            with self.subTest(spec), self.assertRaisesRegex(CommandError, r"TRACK=TERM\[:THRESHOLD\]"):
                parse_hits([spec])
        with self.assertRaisesRegex(CommandError, "0 or below"):
            parse_hits(["Kick=kick:3"])

    def test_the_velocity_band(self):
        self.assertEqual(parse_velocity(None), (1, 127, 1.0))
        self.assertEqual(parse_velocity("40..110"), (40, 110, 1.0))
        self.assertEqual(parse_velocity("40..110:1.5"), (40, 110, 1.5))
        for spec in ("40", "110..40", "0..127", "40..128", "40..110:0", "a..b"):
            with self.subTest(spec), self.assertRaisesRegex(CommandError, r"FLOOR\.\.CEILING\[:GAMMA\]"):
                parse_velocity(spec)


if __name__ == "__main__":
    unittest.main()
