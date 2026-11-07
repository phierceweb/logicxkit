"""`drums-to-midi` on a 3/4 project, over overlapping regions, and Logic's re-save of its notes over a real
take."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from goldens.test_drums_to_midi import TARGET, clicks

from logicxkit.logic.services.regions.audio_write import add_audio_region
from logicxkit.logic.services.midi.drums_to_midi import drums_to_midi
from logicxkit.logic.services.song.events import BAR_ONE, PPQ
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.midi.midi_write import track_regions
from logicxkit.logic.services.song.tempo import project_tempo
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data


@_goldens.needs("signature-meter-3-4-logic")
class ThreeFourTest(unittest.TestCase):
    def test_the_bars_and_the_grid_are_the_projects_meter(self):
        golden = project_data(_goldens.path("signature-meter-3-4-logic"))
        with tempfile.TemporaryDirectory() as d:
            media = Path(d) / "Media"
            wav = clicks(Path(d) / "k.wav", [0.5, 2.8, 4.6, 5.97], [0.5, 0.6, 0.7, 0.8], project_tempo(golden)[1])
            data, _ = add_audio_region(golden, track="Audio 1", start=BAR_ONE, media_folder=media, wav=wav)
            for grid, bars, beats in ((None, 2, None), (2, 3, [0, 3, 5, 6])):
                with self.subTest(grid):
                    out, report = drums_to_midi(data, hits=[("Audio 1", "kick")], target="Inst 1", grid=grid,
                                                wav_of=lambda r: media / r.file.name)
                    (region,) = [r for r in read_midi(out) if r not in read_midi(data)]
                    (placed,) = [r for r in track_regions(out, "Inst 1") if r.start == region.start]
                    self.assertEqual((placed.length, report.bars), (bars * 3 * PPQ, bars))
                    if beats:
                        self.assertEqual(sorted(e.tick - BAR_ONE for e in region.events), [b * PPQ for b in beats])


@_goldens.needs("audio-three-regions-logic")
class OverlapTest(unittest.TestCase):
    def test_hits_that_overlapping_regions_share_count_once(self):
        golden = project_data(_goldens.path("audio-three-regions-logic"))
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            clicks(folder / "v030-tone2.wav", [0.5, 1.5, 3.0], [0.4, 0.9, 0.6], 120.0, seconds=2.0)
            clicks(folder / "v030-tone_1.wav", [0.5, 1.5], [0.4, 0.9], 120.0, seconds=1.0)
            out, report = drums_to_midi(golden, hits=[("Audio 3", "snare")], target=TARGET, wav_of=lambda r: folder / r.file.name)
            (region,) = [r for r in read_midi(out) if r not in read_midi(golden)]
            self.assertEqual((report.hits[0][3], report.merged, len(region.events)), (3, 0, 3))
            self.assertEqual(regressions(golden, out), [])


@_goldens.needs("songb-drums-to-midi-mine", "songb-drums-to-midi-logic")
class LogicResavedTest(unittest.TestCase):
    def test_logic_kept_the_region_and_every_note_written_over_a_real_take(self):
        from logicxkit.logic.services.project.project import project_metadata
        want = _goldens.fact("songb-drums-to-midi-mine", "regions")
        self.assertEqual([(r[0], len(r[2])) for r in want], [("Drums MIDI", 350)])
        for key in ("songb-drums-to-midi-mine", "songb-drums-to-midi-logic"):
            path = _goldens.path(key)
            data, count = project_data(path), project_metadata(path).get("tracks")
            self.assertEqual(validate_project(data), [])
            self.assertEqual([[r.name, r.start, [[e.tick, e.channel, e.pitch, e.velocity, e.length] for e in r.events]] for r in read_midi(data, count)], want)


if __name__ == "__main__":
    unittest.main()
