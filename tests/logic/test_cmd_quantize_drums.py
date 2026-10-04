"""`quantize-drums` from the command line on a blank-born project: two click tracks made here,
imported with `regions --audio`, one the reference, quantized to a 1/16 grid without Logic."""

import math
import tempfile
import unittest
import wave
from pathlib import Path

import _goldens
from _cli import count, data, run, written

from logicxkit.logic.services.arrange.environment import object_record
from logicxkit.logic.services.arrange.groups import group_errors, read_groups
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.flexmode import flex_mode, q_reference
from logicxkit.logic.services.stream.stream import project_records

THREE = "tracks-three-audio-logic"
RATE = 44100
KICK_BEATS, SNARE_BEATS = (0.07, 1.04, 2.0, 2.96, 4.05, 5.0), (1.02, 3.0, 5.03)      # off the grid on purpose


def clicks(path: Path, beats: tuple[float, ...], bpm: float = 120, seconds: float = 6.0) -> Path:
    """A 24-bit mono file with a decaying burst at each beat position."""
    x = [0.0] * int(seconds * RATE)
    for beat in beats:
        at = int(beat * RATE * 60 / bpm)
        for i in range(int(0.05 * RATE)):
            if at + i < len(x):
                x[at + i] += 0.8 * math.exp(-i / (0.003 * RATE)) * (1 if i % 2 == 0 else -0.6) * min(i, 2) / 2
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(RATE)
        w.writeframes(b"".join(max(-8388607, min(8388607, int(v * 8388607))).to_bytes(3, "little", signed=True) for v in x))
    return path


@_goldens.needs(THREE)
class QuantizeDrumsCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        kick, snare = clicks(self.out / "kick.wav", KICK_BEATS), clicks(self.out / "snare.wav", SNARE_BEATS)
        self.take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{kick}", "--audio", f"Audio 2:1:{snare}",
                            out=self.out / "take")

    def quantize(self, *more: str) -> tuple[int, str]:
        return run("quantize-drums", self.take, "--track", "Audio 1", "--track", "Audio 2", "--ref", "Audio 1",
                   *more, "--out", self.out / "quantized")

    def test_the_take_is_quantized_to_the_reference_tracks_hits(self):
        code, text = self.quantize("--grid", "16")
        self.assertEqual(code, 0, text)
        self.assertIn(f"{len(KICK_BEATS)} hit(s) from Audio 1 (kick.wav) on the 1/16 grid", text)
        for track in ("Audio 1", "Audio 2"):
            self.assertIn(f"{track}: {len(KICK_BEATS) + 2} marker(s)", text)          # the hits and two anchors
        dest = self.out / "quantized" / self.take.name
        out = data(dest)
        (group,) = read_groups(out)
        self.assertEqual((len(group.members), "Quantize-Locked (Audio)" in group.settings, group_errors(out)), (2, True, []))
        records = project_records(out)
        track = {r["name"]: object_record(records, r["object_id"]) for r in read_tracks(out, count(dest))}
        self.assertEqual((q_reference(track["Audio 1"]), q_reference(track["Audio 2"])), (True, False))
        self.assertEqual({flex_mode(track[n]) for n in ("Audio 1", "Audio 2")}, {"Slicing"})
        self.assertEqual(sorted(r.name for r in read_audio_regions(out, count(dest))), ["kick", "snare"])

    def test_without_out_nothing_is_written(self):
        code, text = run("quantize-drums", self.take, "--track", "Audio 1", "--track", "Audio 2", "--ref", "Audio 1")
        self.assertFalse((self.out / "quantized").exists(), text)
        self.assertNotIn("Traceback", text)

    def test_a_reference_track_that_is_not_there_is_refused(self):
        code, text = run("quantize-drums", self.take, "--track", "Audio 1", "--ref", "Kick In", "--out", self.out / "quantized")
        self.assertNotEqual(code, 0, text)
        self.assertFalse((self.out / "quantized" / self.take.name).exists(), text)


if __name__ == "__main__":
    unittest.main()
