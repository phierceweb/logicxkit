"""`strip-silence` with references from the command line: the gate reaches the rule, a silent
reference leaves the mic unchanged, and a spec's groups never hand each other the wrong envelope."""

import json
import re
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import run, written
from _audio import THREE, band_playing, silent, vocal_mic

from logicxkit.utils.swiftrun import swift_available

RATE = 44100


@_goldens.needs(THREE)
@unittest.skipUnless(swift_available(), "the band-limited envelope runs through swift")
class StripSilenceReferencesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        vox, ref, hush = vocal_mic(self.out / "vox.wav"), band_playing(self.out / "ref.wav"), silent(self.out / "hush.wav", 10.0)
        self.take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{vox}", "--audio", f"Audio 2:1:{ref}",
                            "--audio", f"Audio 3:1:{hush}", out=self.out / "take")
        self.common = ["--track", "Audio 1", "--ref", "Audio 2", "--band", "300:3000", "--min-gap", "1", "--min-keep", "0.5", "--pad", "100"]

    def test_the_gate_reaches_the_rule(self):
        code, text = run("strip-silence", self.take, *self.common, "--gate", "3")
        self.assertEqual(code, 0, text)
        self.assertIn("and 9 dB over the bleed", text)
        self.assertEqual(text.count("    keep "), 2, text)
        code, text = run("strip-silence", self.take, *self.common, "--gate", "40")
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"never heard over its bleed floor of -\d+\.\d dBFS: muted")    # nothing clears 40 dB over the floor

    def test_a_reference_that_never_plays_leaves_the_mic_unchanged(self):
        code, text = run("strip-silence", self.take, "--track", "Audio 1", "--ref", "Audio 3", "--band", "300:3000")
        self.assertEqual(code, 0, text)
        self.assertIn("unchanged (no reference plays beside it", text)
        self.assertIn("nothing to cut", text)

    def test_a_peak_group_before_a_reference_group_does_not_lend_it_its_envelope(self):
        """A tone's peak sits 3 dB over its RMS: the ratio the plan names must be the RMS one either way."""
        alone, text = run("strip-silence", self.take, *self.common)
        self.assertEqual(alone, 0, text)
        ratio = re.search(r"bleed from Audio 2 ([-+\d.]+) dB", text)
        self.assertIsNotNone(ratio, text)
        spec = self.out / "spec.json"
        spec.write_text(json.dumps({"groups": [
            {"tracks": ["Audio 2"], "min_gap": 2},
            {"tracks": ["Audio 1"], "ref": ["Audio 2"], "band": "300:3000", "min_gap": 1, "min_keep": 0.5, "pad": 100},
        ]}))
        code, text = run("strip-silence", self.take, "--spec", spec)
        self.assertEqual(code, 0, text)
        self.assertIn(f"bleed from Audio 2 {ratio.group(1)} dB", text)


if __name__ == "__main__":
    unittest.main()
