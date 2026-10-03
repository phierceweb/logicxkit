"""Audio files and regions, read from Logic's own imports of two WAVs onto a blank-born project."""

import unittest
import _goldens
from logicxkit.logic.services.regions.audio_regions import read_audio_files, read_audio_regions
from logicxkit.logicx import project_data


@_goldens.needs("audio-one-region-logic")
class OneRegionTest(unittest.TestCase):
    def test_the_file_and_its_region(self):
        data = project_data(_goldens.path("audio-one-region-logic"))
        (f,) = read_audio_files(data)
        facts = _goldens.entry("audio-one-region-logic")["facts"]
        self.assertEqual((f.name, f.frames, f.rate, f.channels, f.bits, f.format), (facts["file"], facts["frames"], facts["rate"], facts["channels"], facts["bits"], "WAVE"))
        self.assertTrue(f.folder.endswith("/Media/Audio Files"))
        (r,) = read_audio_regions(data)
        self.assertEqual((r.track, r.name, r.start_bar, r.frames, r.file.name), (facts["track"], "v030-tone", facts["start_bar"], facts["frames"], facts["file"]))


@_goldens.needs("audio-three-regions-logic")
class ThreeRegionsTest(unittest.TestCase):
    def test_three_regions_over_three_files(self):
        data = project_data(_goldens.path("audio-three-regions-logic"))
        facts = _goldens.entry("audio-three-regions-logic")["facts"]
        files = read_audio_files(data)
        self.assertEqual([f.name for f in files], facts["files"])
        self.assertEqual([(f.frames, f.channels) for f in files], list(zip(facts["frames"], facts["channels"], strict=True)))
        regions = read_audio_regions(data)
        self.assertEqual([r.track for r in regions], facts["tracks"])
        self.assertEqual([r.file.name for r in regions], ["v030-tone2.wav", "v030-tone_1.wav", "v030-tone.wav"])
        self.assertEqual([r.name for r in regions], ["v030-tone2", "v030-tone_1", "v030-tone"])


if __name__ == "__main__":
    unittest.main()
