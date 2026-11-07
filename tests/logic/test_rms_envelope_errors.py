"""What the RMS envelope does when its swift helper is missing or answers wrong, run without the
toolchain: each failure is a refusal naming the file, and `strip-silence --band` exits 1."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import wrapped, written
from _audio import THREE, sound_gap_sound
from test_silence import HOP, pcm_wav

from logicxkit.logic.services.regions import silence
from logicxkit.logic.services.regions.silence import peak_envelope, rms_envelope


class RmsHelperAnswersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wav = pcm_wav(Path(tmp.name) / "a.wav", [[0.5] * (4 * HOP)], 24)

    def answer(self, code: int, out: str, err: str = "") -> str:
        with mock.patch.object(silence, "run_swift", return_value=(code, out, err)), self.assertRaises(ValueError) as caught:
            rms_envelope(self.wav, band=None)
        return str(caught.exception)

    def test_a_failed_helper_is_refused_with_its_message(self):
        self.assertIn("a.wav: no such band", self.answer(1, "", "no such band"))
        self.assertIn("a.wav: the envelope helper failed", self.answer(1, ""))

    def test_a_missing_toolchain_is_refused_naming_the_file(self):
        with mock.patch("logicxkit.utils.swiftrun.shutil.which", return_value=None), \
                self.assertRaisesRegex(ValueError, "a.wav: swift toolchain not available"):
            rms_envelope(self.wav, band=None)

    def test_no_frames_read_from_a_file_that_holds_some_is_refused(self):
        self.assertIn("read no frames from it", self.answer(0, "44100 441 0 0\n"))

    def test_fewer_hops_than_the_helper_announced_are_refused(self):
        self.assertIn("wrote 2 of 4 hops", self.answer(0, "44100 441 1764 4\n0.1 0.2\n"))

    def test_the_peak_envelope_of_a_file_shorter_than_a_hop_has_no_hops(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(peak_envelope(pcm_wav(Path(tmp) / "short.wav", [[0.5] * (HOP - 1)], 24)).peaks, [])


@_goldens.needs(THREE)
class NoSwiftTest(unittest.TestCase):
    def test_a_band_without_the_toolchain_exits_1_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{sound_gap_sound(out / 'take.wav')}", out=out / "take")
            with mock.patch("logicxkit.utils.swiftrun.shutil.which", return_value=None):
                code, text = wrapped("strip-silence", take, "--track", "Audio 1", "--band", "300:3000", "--out", out / "cut")
            self.assertEqual(code, 1, text)
            self.assertIn("swift toolchain not available", text)
            self.assertFalse((out / "cut" / take.name).exists())


if __name__ == "__main__":
    unittest.main()
