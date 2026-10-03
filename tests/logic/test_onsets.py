"""Onset detection on drum close-mic audio: hits found where they are, bleed and silence
ignored, positions merged across mics."""

import math
import random
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import _paths  # noqa: F401
from logicxkit.logic.services.regions.onsets import Detector, merge_hits, onsets, read_wav

RATE = 44100


def click(length: int, amplitude: float, decay: float = 0.002) -> list[float]:
    """A decaying burst, ``decay`` seconds to 1/e, starting with a two-sample ramp."""
    out = []
    for i in range(length):
        env = amplitude * math.exp(-i / (decay * RATE))
        out.append(env * (1 if i % 2 == 0 else -0.6) * (min(i, 2) / 2))
    return out


def track(hits: list[tuple[int, float]], seconds: float = 3.0, noise: float = 0.0) -> list[float]:
    x = [0.0] * int(seconds * RATE)
    for pos, amp in hits:
        for i, v in enumerate(click(int(0.05 * RATE), amp)):
            if pos + i < len(x):
                x[pos + i] += v
    if noise:
        x = [v + noise * (((k * 7919) % 1000) / 500 - 1) for k, v in enumerate(x)]
    return x


def slow_track(hits: list[tuple[int, float]], frames: int, attack: int = 132) -> list[float]:
    """Hits whose peak comes ``attack`` samples after their onset."""
    x = [0.0] * frames
    for pos, amp in hits:
        for i in range(4000):
            x[pos + i] += amp * (i / attack if i < attack else 0.999 ** (i - attack)) * (1 if i % 2 == 0 else -1)
    return x


def write_wav(path: Path, x: list[float], bits: int = 24, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bits // 8)
        w.setframerate(RATE)
        full = (1 << (bits - 1)) - 1
        frames = bytearray()
        for v in x:
            n = max(-full, min(full, int(v * full)))
            frames += n.to_bytes(bits // 8, "little", signed=True) * channels
        w.writeframes(bytes(frames))


class ReadTest(unittest.TestCase):
    def test_reads_24_and_16_bit_and_keeps_the_first_channel(self):
        x = track([(1000, 0.5)], seconds=0.2)
        with tempfile.TemporaryDirectory() as d:
            for bits, channels in ((24, 1), (16, 2), (24, 2)):
                p = Path(d) / f"t{bits}{channels}.wav"
                write_wav(p, x, bits, channels)
                samples, rate = read_wav(p)
                self.assertEqual((rate, len(samples)), (RATE, len(x)), (bits, channels))
                self.assertAlmostEqual(max(samples), max(x), places=3)


FLOAT_RATE = 48000
GUID_TAIL = bytes.fromhex("000000001000800000aa00389b71")


def bursts() -> list[float]:
    """2 s of noise at ±3e-4 with a decaying burst at 0.5, 1.0 and 1.5 s."""
    rng = random.Random(7)
    x = [rng.uniform(-3e-4, 3e-4) for _ in range(2 * FLOAT_RATE)]
    for at in (0.5, 1.0, 1.5):
        for i in range(2000):
            x[int(at * FLOAT_RATE) + i] += 0.8 * math.exp(-i / 300) * math.sin(0.3 * i)
    return x


def riff(path: Path, code: int, bits: int, payload: bytes, ext: bytes | None = None, cb: int = 22) -> Path:
    """A mono RIFF WAVE with a hand-built fmt chunk; ``ext`` is the extensible SubFormat GUID."""
    fmt = struct.pack("<HHIIHH", code, 1, FLOAT_RATE, FLOAT_RATE * bits // 8, bits // 8, bits)
    if ext is not None:
        fmt += struct.pack("<HHI", cb, bits, 4) + ext
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def pcm24(x: list[float]) -> bytes:
    return b"".join(int(v * 8388607).to_bytes(3, "little", signed=True) for v in x)


class FormatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir, self.x = Path(self.tmp.name), bursts()

    def tearDown(self):
        self.tmp.cleanup()

    def hits(self, path: Path) -> list[int]:
        samples, rate = read_wav(path)
        self.assertEqual((rate, len(samples)), (FLOAT_RATE, len(self.x)))
        return onsets(samples, rate)

    def test_int32_pcm_finds_the_three_bursts(self):
        payload = struct.pack(f"<{len(self.x)}i", *(int(v * 2147483647) for v in self.x))
        self.assertEqual(len(self.hits(riff(self.dir / "i32.wav", 1, 32, payload))), 3)

    def test_ieee_float_32_and_64_read_as_floats(self):
        for bits, char in ((32, "f"), (64, "d")):
            p = riff(self.dir / f"f{bits}.wav", 3, bits, struct.pack(f"<{len(self.x)}{char}", *self.x))
            self.assertEqual(len(self.hits(p)), 3, bits)
            self.assertAlmostEqual(read_wav(p)[0][int(0.5 * FLOAT_RATE) + 5], self.x[int(0.5 * FLOAT_RATE) + 5], places=6)

    def test_extensible_resolves_through_its_subformat(self):
        pcm = riff(self.dir / "x24.wav", 0xFFFE, 24, pcm24(self.x), ext=b"\x01\x00" + GUID_TAIL)
        flt = riff(self.dir / "xf.wav", 0xFFFE, 32, struct.pack(f"<{len(self.x)}f", *self.x), ext=b"\x03\x00" + GUID_TAIL)
        self.assertEqual(len(self.hits(pcm)), 3)
        self.assertEqual(len(self.hits(flt)), 3)

    def test_other_codes_and_layouts_are_refused(self):
        refused = {
            "0x0002": riff(self.dir / "adpcm.wav", 2, 16, bytes(4000)),
            "24-bit float": riff(self.dir / "f24.wav", 3, 24, bytes(3000)),
            "SubFormat": riff(self.dir / "xsub.wav", 0xFFFE, 16, bytes(4000), ext=b"\x02\x00" + GUID_TAIL),
            "GUID": riff(self.dir / "xguid.wav", 0xFFFE, 16, bytes(4000), ext=b"\x01\x00" + bytes(14)),
            "cbSize": riff(self.dir / "xcb.wav", 0xFFFE, 16, bytes(4000), ext=b"\x01\x00" + GUID_TAIL, cb=0),
        }
        for named, path in refused.items():
            with self.subTest(named), self.assertRaisesRegex(ValueError, named):
                read_wav(path)


class DetectTest(unittest.TestCase):
    def test_hits_are_found_within_a_millisecond(self):
        want = [4410, 30000, 61200, 100000]
        x = track([(p, 0.8) for p in want])
        got = onsets(x, RATE)
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want, strict=True):
            self.assertLessEqual(abs(g - w), RATE // 1000)

    def test_a_hit_far_below_the_track_peak_is_bleed(self):
        x = track([(10000, 0.9), (50000, 0.9 * 10 ** (-30 / 20)), (90000, 0.9)])
        got = onsets(x, RATE)
        self.assertEqual([round(g / 1000) for g in got], [10, 90])

    def test_the_floor_scales_with_the_track_so_a_quiet_take_still_reads(self):
        x = track([(10000, 0.05), (50000, 0.05), (90000, 0.05)])
        self.assertEqual(len(onsets(x, RATE)), 3)

    def test_a_second_hit_inside_the_gap_is_one_hit(self):
        x = track([(10000, 0.8), (10000 + int(0.02 * RATE), 0.8), (60000, 0.8)])
        self.assertEqual(len(onsets(x, RATE)), 2)

    def test_a_hit_in_the_first_hop_is_found(self):
        for first in (0, 16):
            with self.subTest(first):
                got = onsets(track([(first, 0.8), (30000, 0.8)]), RATE)
                self.assertEqual(len(got), 2)
                self.assertLessEqual(abs(got[0] - first), RATE // 1000)

    def test_silence_and_noise_give_nothing(self):
        self.assertEqual(onsets([0.0] * RATE, RATE), [])
        self.assertEqual(onsets(track([], seconds=1.0, noise=0.01), RATE), [])

    def test_parameters_are_the_measured_defaults(self):
        d = Detector()
        self.assertEqual((d.rise_db, d.floor_db, d.look_ms, d.gap_ms, d.refine_ratio), (24.0, -21.0, 30, 60, 0.12))


class MergeTest(unittest.TestCase):
    def test_hits_from_two_mics_merge_within_the_window(self):
        kick, snare = [1000, 40000, 80000], [1000 + 300, 60000, 80000 - 200]
        self.assertEqual(merge_hits([kick, snare], RATE), [1000, 40000, 60000, 79800])

    def test_offsets_shift_and_out_of_range_hits_drop(self):
        self.assertEqual(merge_hits([[100, 5000, 9000]], RATE, offset=1000, length=7000), [4000])
