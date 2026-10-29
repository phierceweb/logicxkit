"""A drum's fundamental from its own file: the frequency with the most power at the mic's loudest
moments, searched between 50 and 350 Hz."""

import math
import random
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from _audio import RATE, riff
from logicxkit.logic.services.regions.fundamental import fundamental
from logicxkit.logic.services.regions.silence import peak_envelope


def drum_file(path: Path, hz: float, seconds: float = 6.0, *, channels: int = 1, on: int = 0) -> Path:
    """Quiet noise with a decaying burst of ``hz`` every second, as a tom mic between hits and on
    them; with ``channels`` the burst sits on channel ``on`` alone, noise on every channel."""
    noise = random.Random(3)
    x = [[0.003 * (2 * noise.random() - 1) for _ in range(int(seconds * RATE))] for _ in range(channels)]
    for hit in range(int(seconds)):
        at = int((hit + 0.3) * RATE)
        for i in range(int(0.4 * RATE)):
            x[on][at + i] += 0.5 * math.exp(-i / (0.12 * RATE)) * math.sin(2 * math.pi * hz * i / RATE)
    riff(path, b"".join(max(-8388607, min(8388607, round(v * 8388607))).to_bytes(3, "little", signed=True)
                        for frame in zip(*x, strict=True) for v in frame), channels)
    return path


class FundamentalTest(unittest.TestCase):
    def test_the_note_of_the_loudest_moments_is_found_within_a_few_hz(self):
        with tempfile.TemporaryDirectory() as tmp:
            for hz in (80, 130):
                path = drum_file(Path(tmp) / f"{hz}.wav", hz)
                found = fundamental(path, peak_envelope(path))
                self.assertAlmostEqual(found, hz, delta=5)

    def test_the_channels_are_pooled_so_a_note_on_the_second_channel_alone_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = drum_file(Path(tmp) / "stereo.wav", 130, channels=2, on=1)
            self.assertAlmostEqual(fundamental(path, peak_envelope(path)), 130, delta=5)

    def test_a_note_at_the_searchs_edge_is_refused_rather_than_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = drum_file(Path(tmp) / "sub.wav", 30)
            with self.assertRaisesRegex(ValueError, "peak at the search's edge \\(50 Hz\\)"):
                fundamental(path, peak_envelope(path))

    def test_a_silent_file_is_refused_rather_than_read_as_the_lowest_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = riff(Path(tmp) / "silent.wav", bytes(3 * 2 * RATE))
            with self.assertRaisesRegex(ValueError, "silent at its loudest moments"):
                fundamental(path, peak_envelope(path))


if __name__ == "__main__":
    unittest.main()
