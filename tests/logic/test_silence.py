"""Silence in a long audio file: the peak envelope read from a WAV's top 16 bits, the quiet
stretches under the file's own loud level, and the spans of a region kept around them."""

import math
import struct
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from logicxkit.logic.services.regions.silence import (
    Envelope, keeps, peak_envelope, quiet_stretches, rms_envelope, writable,
)
from logicxkit.utils.swiftrun import swift_available

RATE = 44100
HOP = RATE // 100


def pcm_wav(path: Path, channels: list[list[float]], bits: int) -> Path:
    """A PCM WAV, ``channels`` as floats in -1..1, ``bits`` 16, 24 or 32."""
    width, full = bits // 8, (1 << (bits - 1)) - 1
    frames = b"".join(max(-full, min(full, round(v * full))).to_bytes(width, "little", signed=True)
                      for frame in zip(*channels, strict=True) for v in frame)
    return _riff(path, 1, len(channels), bits, frames)


def float_wav(path: Path, samples: list[float]) -> Path:
    return _riff(path, 3, 1, 32, struct.pack(f"<{len(samples)}f", *samples))


def _riff(path: Path, code: int, channels: int, bits: int, frames: bytes) -> Path:
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", code, channels, RATE, RATE * block, block, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(frames)) + frames
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def burst_then_silence(level: float, seconds: float = 1.0, sound: float = 0.5) -> list[float]:
    """``sound`` seconds at ``level`` (alternating sign), then digital silence."""
    n, on = int(seconds * RATE), int(sound * RATE)
    return [level * (1 if i % 2 == 0 else -1) if i < on else 0.0 for i in range(n)]


class PeakEnvelopeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def check(self, env: Envelope, level: float) -> None:
        self.assertEqual((env.hop, env.rate, env.frames, len(env.peaks)), (HOP, RATE, RATE, 100))
        want = round(level * 32767)
        self.assertTrue(all(abs(p - want) <= 1 for p in env.peaks[:50]), env.peaks[:50])
        self.assertEqual(env.peaks[50:], [0] * 50)

    def test_a_24_bit_file_reads_its_top_16_bits_per_hop(self):
        self.check(peak_envelope(pcm_wav(self.dir / "a.wav", [burst_then_silence(0.5)], 24)), 0.5)

    def test_a_16_bit_file_reads_the_same_way(self):
        self.check(peak_envelope(pcm_wav(self.dir / "a.wav", [burst_then_silence(0.25)], 16)), 0.25)

    def test_a_32_bit_pcm_file_reads_its_top_16_bits(self):
        self.check(peak_envelope(pcm_wav(self.dir / "a.wav", [burst_then_silence(0.5)], 32)), 0.5)

    def test_a_float_file_is_scaled_to_the_same_range(self):
        self.check(peak_envelope(float_wav(self.dir / "a.wav", burst_then_silence(0.5))), 0.5)

    def test_a_stereo_file_takes_the_peak_over_both_channels(self):
        quiet = [0.0] * RATE
        env = peak_envelope(pcm_wav(self.dir / "a.wav", [quiet, burst_then_silence(0.5)], 24))
        self.check(env, 0.5)

    def test_a_tail_shorter_than_a_hop_is_folded_into_the_last_hop(self):
        x = burst_then_silence(0.5)[: 50 * HOP + 7]
        env = peak_envelope(pcm_wav(self.dir / "a.wav", [x], 24))
        self.assertEqual((len(env.peaks), env.frames), (50, 50 * HOP + 7))

    def test_an_8_bit_file_is_refused(self):
        with self.assertRaisesRegex(ValueError, "8-bit"):
            peak_envelope(pcm_wav(self.dir / "a.wav", [burst_then_silence(0.5)], 8))


def envelope(spans: list[tuple[float, int]]) -> Envelope:
    """``(seconds, peak)`` spans laid end to end."""
    peaks = [peak for seconds, peak in spans for _ in range(round(seconds * 100))]
    return Envelope(peaks, HOP, RATE, len(peaks) * HOP)


LOUD, QUIET = 10000, 100           # -10 dBFS playing, -50 dBFS idle


class QuietStretchesTest(unittest.TestCase):
    def test_a_gap_at_least_min_gap_long_is_found_in_frames(self):
        env = envelope([(10, LOUD), (20, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(10 * RATE, 30 * RATE)])

    def test_a_gap_of_exactly_min_gap_is_found_and_one_hop_less_is_not(self):
        env = envelope([(10, LOUD), (15, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(10 * RATE, 25 * RATE)])
        env = envelope([(10, LOUD), (14.99, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [])

    def test_a_pause_shorter_than_min_gap_is_not(self):
        env = envelope([(10, LOUD), (5, QUIET), (10, LOUD), (20, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(25 * RATE, 45 * RATE)])

    def test_the_threshold_sits_under_the_files_loud_level(self):
        """-30 dB under a -10 dBFS loud level is -40 dBFS: a -36 dBFS hum is playing, -50 is not."""
        hum = round(LOUD / 10 ** (26 / 20))
        env = envelope([(10, LOUD), (20, hum), (20, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-30), [(30 * RATE, 50 * RATE)])
        self.assertEqual(quiet_stretches(env, threshold_db=-20, min_gap_s=15, min_keep_s=5, edge_db=-20), [(10 * RATE, 50 * RATE)])

    def test_gaps_at_the_start_and_the_end_reach_the_files_edges(self):
        env = envelope([(20, QUIET), (10, LOUD), (20, QUIET)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(0, 20 * RATE), (30 * RATE, 50 * RATE)])

    def test_a_file_that_is_silent_throughout_is_one_stretch(self):
        env = envelope([(30, 0)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(0, 30 * RATE)])

    def test_the_loud_level_is_the_95th_percentile_not_the_peak(self):
        """One burst far above the playing does not pull the threshold over the playing."""
        env = envelope([(10, LOUD), (0.5, 32000), (20, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(round(10.5 * RATE), round(30.5 * RATE))])
        self.assertAlmostEqual(env.loud_db, 20 * math.log10(LOUD / 32768), places=3)

    def test_the_loud_level_is_the_95th_percentile_not_a_higher_one(self):
        """Three percent of the hops 6 dB over the playing: at the 95th percentile the playing sets the
        level and a -27 dB stretch is not a gap; at the 98th it would be."""
        env = envelope([(20, round(LOUD / 10 ** (27 / 20))), (9, LOUD), (1, LOUD * 2)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [])

    def test_the_loud_level_is_read_once_per_envelope(self):
        from unittest import mock
        from logicxkit.logic.services.regions import silence
        env = envelope([(10, LOUD), (10, QUIET)])
        with mock.patch.object(silence, "sorted", wraps=sorted, create=True) as sort:
            self.assertEqual((env.loud, env.loud_db, env.loud), (LOUD, env.loud_db, LOUD))
        self.assertEqual(sort.call_count, 1)

    def test_a_sound_of_exactly_min_keep_at_the_files_edge_stays(self):
        env = envelope([(5, LOUD), (20, QUIET), (10, LOUD), (20, QUIET), (5, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20),
                         [(5 * RATE, 25 * RATE), (35 * RATE, 55 * RATE)])

    def test_a_blip_shorter_than_min_keep_between_two_gaps_is_silence_too(self):
        env = envelope([(10, LOUD), (20, QUIET), (1, LOUD), (20, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(10 * RATE, 51 * RATE)])

    def test_a_sound_at_least_min_keep_long_between_two_gaps_is_kept(self):
        env = envelope([(10, LOUD), (20, QUIET), (5, LOUD), (20, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20),
                         [(10 * RATE, 30 * RATE), (35 * RATE, 55 * RATE)])

    def test_a_blip_at_the_files_edges_beside_a_gap_is_silence_too(self):
        env = envelope([(1, LOUD), (20, QUIET), (10, LOUD), (20, QUIET), (2, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(0, 21 * RATE), (31 * RATE, 53 * RATE)])

    def test_a_blip_beside_a_pause_too_short_to_be_a_gap_stays(self):
        """Only a gap absorbs a blip; a 1 s sound between 5 s pauses is playing, not a blip between songs."""
        env = envelope([(10, LOUD), (5, QUIET), (1, LOUD), (5, QUIET), (10, LOUD), (20, QUIET), (10, LOUD)])
        self.assertEqual(quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=-20), [(31 * RATE, 51 * RATE)])


HUM = round(LOUD / 10 ** (22 / 20))        # 22 dB under the playing: over the -30 gap limit, under the -20 edge limit


class EdgeCropTest(unittest.TestCase):
    def stretches(self, env: Envelope, edge_db: float = -20) -> list[tuple[int, int]]:
        return quiet_stretches(env, threshold_db=-30, min_gap_s=15, min_keep_s=5, edge_db=edge_db)

    def test_a_gaps_edges_crop_in_over_sound_under_the_edge_limit(self):
        env = envelope([(10, LOUD), (5, HUM), (20, QUIET), (5, HUM), (10, LOUD)])
        self.assertEqual(self.stretches(env), [(10 * RATE, 40 * RATE)])
        self.assertEqual(self.stretches(env, edge_db=-30), [(15 * RATE, 35 * RATE)])

    def test_a_click_shorter_than_50_ms_does_not_stop_the_crop(self):
        env = envelope([(10, LOUD), (3, HUM), (0.02, LOUD), (2, HUM), (20, QUIET), (10, LOUD)])
        self.assertEqual(self.stretches(env), [(10 * RATE, round(35.02 * RATE))])

    def test_a_sound_of_100_ms_stops_the_crop(self):
        env = envelope([(10, LOUD), (3, HUM), (0.1, LOUD), (2, HUM), (20, QUIET), (10, LOUD)])
        self.assertEqual(self.stretches(env), [(round(13.1 * RATE), round(35.1 * RATE))])

    def test_a_sound_of_exactly_50_ms_stops_the_crop_and_one_hop_less_does_not(self):
        env = envelope([(10, LOUD), (3, HUM), (0.05, LOUD), (2, HUM), (20, QUIET), (10, LOUD)])
        self.assertEqual(self.stretches(env), [(round(13.05 * RATE), round(35.05 * RATE))])
        env = envelope([(10, LOUD), (3, HUM), (0.04, LOUD), (2, HUM), (20, QUIET), (10, LOUD)])
        self.assertEqual(self.stretches(env), [(10 * RATE, round(35.04 * RATE))])

    def test_a_span_cropped_under_min_keep_is_silence(self):
        env = envelope([(10, LOUD), (20, QUIET), (5, HUM), (2, LOUD), (20, QUIET), (10, LOUD)])
        self.assertEqual(self.stretches(env), [(10 * RATE, 57 * RATE)])

    def test_the_crop_stops_at_the_files_edges(self):
        env = envelope([(5, HUM), (20, QUIET), (10, LOUD), (20, QUIET), (5, HUM)])
        self.assertEqual(self.stretches(env), [(0, 25 * RATE), (35 * RATE, 60 * RATE)])


def tone(hz: float, level: float, seconds: float = 1.0) -> list[float]:
    return [level * math.sin(2 * math.pi * hz * i / RATE) for i in range(int(seconds * RATE))]


@unittest.skipUnless(swift_available(), "the band-limited envelope runs through swift")
class RmsEnvelopeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_the_full_band_rms_of_two_tones_is_their_power_sum(self):
        x = [a + b for a, b in zip(tone(1000, 0.5), tone(60, 0.5), strict=True)]
        env = rms_envelope(pcm_wav(self.dir / "a.wav", [x], 24), band=None)
        self.assertEqual((env.hop, env.rate, env.frames, len(env.peaks)), (HOP, RATE, RATE, 100))
        self.assertAlmostEqual(env.peaks[50] / 32768, 0.5, delta=0.02)          # sqrt(0.125 + 0.125)

    def test_the_voice_band_keeps_the_1_khz_tone_and_drops_the_60_hz_one(self):
        x = [a + b for a, b in zip(tone(1000, 0.5), tone(60, 0.5), strict=True)]
        env = rms_envelope(pcm_wav(self.dir / "a.wav", [x], 24), band=(300, 3000))
        self.assertAlmostEqual(env.peaks[50] / 32768, 0.354, delta=0.03)        # the 1 kHz tone alone
        low = rms_envelope(pcm_wav(self.dir / "b.wav", [tone(60, 0.5)], 24), band=(300, 3000))
        self.assertLess(low.peaks[50] / 32768, 0.02)

    def test_a_stereo_file_pools_both_channels(self):
        env = rms_envelope(pcm_wav(self.dir / "a.wav", [tone(1000, 0.5), [0.0] * RATE], 24), band=None)
        self.assertAlmostEqual(env.peaks[50] / 32768, 0.25, delta=0.02)          # half the power of one channel

    def test_a_file_shorter_than_a_hop_reads_as_no_hops(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pcm_wav(Path(tmp) / "short.wav", [[0.5] * (HOP - 1)], 24)
            env = rms_envelope(path, band=None)
            self.assertEqual((env.peaks, env.frames, env.rate), ([], HOP - 1, RATE))
            self.assertEqual(peak_envelope(path).peaks, [])

    def test_the_envelope_agrees_with_the_peak_one_on_length(self):
        x = burst_then_silence(0.5)[: 50 * HOP + 7]
        env, peaks = rms_envelope(pcm_wav(self.dir / "a.wav", [x], 24), band=None), peak_envelope(self.dir / "a.wav")
        self.assertEqual((len(env.peaks), env.frames), (len(peaks.peaks), peaks.frames))


class KeepsTest(unittest.TestCase):
    def test_the_region_minus_its_gaps_widened_by_the_pad(self):
        self.assertEqual(keeps(0, 100000, [(0, 20000), (50000, 80000)], pad=1000), [(19000, 51000), (79000, 100000)])

    def test_a_gap_ending_the_region_trims_its_end(self):
        self.assertEqual(keeps(0, 100000, [(90000, 100000)], pad=1000), [(0, 91000)])

    def test_gaps_outside_the_region_do_not_count(self):
        self.assertEqual(keeps(200000, 100000, [(0, 20000), (350000, 400000)], pad=1000), [(200000, 300000)])

    def test_a_gap_overlapping_the_regions_edge_is_clipped_to_it(self):
        self.assertEqual(keeps(200000, 100000, [(190000, 220000), (290000, 400000)], pad=1000), [(219000, 291000)])

    def test_a_region_silent_throughout_keeps_nothing(self):
        self.assertEqual(keeps(200000, 100000, [(0, 400000)], pad=1000), [])

    def test_the_pad_never_closes_a_gap_entirely(self):
        self.assertEqual(keeps(0, 100000, [(40000, 41000)], pad=1000), [(0, 40500), (40500, 100000)])

    def test_writable_drops_what_is_under_a_tick_joins_what_touches_and_takes_any_order(self):
        self.assertEqual(writable([(2005, 4000), (10, 2000), (0, 10)], 23), [(10, 4000)])
        self.assertEqual(writable([], 23), [])

    def test_half_a_gap_of_odd_length_rounds_down_on_both_sides(self):
        self.assertEqual(keeps(0, 5000, [(1000, 3001)], pad=5000), [(0, 2000), (2001, 5000)])

    def test_a_pad_may_differ_before_and_after(self):
        """A tom rings on after the hit: little before it, more after."""
        self.assertEqual(keeps(0, 100000, [(0, 20000), (50000, 80000)], pad=(500, 3000)), [(19500, 53000), (79500, 100000)])
        self.assertEqual(keeps(0, 100000, [(40000, 41000)], pad=(500, 3000)), [(0, 40500), (40500, 100000)])


if __name__ == "__main__":
    unittest.main()
