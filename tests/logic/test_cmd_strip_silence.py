"""`strip-silence` from the command line on a blank-born project: a sound-gap-sound file made
here and imported with `regions --audio`, the gap cut, the cut edges faded, the plan first. The
sounds are a second long, so `--min-keep` is lowered under them."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _audio import RATE, SPT, THREE, band_playing, silent, sound_gap_sound, sound_hum_gap, tom_mic, vocal_mic
from _cli import count, data, run, written

from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logic.services.regions.audio_regions import AUDIO_ENTRY, read_audio_regions
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.regions.regions import ENTRY, song_container
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.utils.swiftrun import swift_available

BAR_ONE = 38400


def entries(bundle: Path, track: str) -> list[tuple[bytes, bytes]]:
    """Every audio region of ``track``: its 80-byte entry and its region record, by start."""
    d, n = data(bundle), count(bundle)
    records = project_records(d)
    payload = records[song_container(records, arrange_run(records, n)).end].raw[HEADER:]
    return [(payload[r.at:r.at + ENTRY], records[r.record].raw)
            for r in sorted(read_audio_regions(d, n), key=lambda r: r.start) if r.track == track]


@_goldens.needs(THREE)
class StripSilenceCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        wav, hush = sound_gap_sound(self.out / "take.wav"), silent(self.out / "hush.wav")
        self.take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{wav}", "--audio", f"Audio 3:1:{hush}",
                            out=self.out / "take")

    def strip(self, *more, out: Path | None = None) -> tuple[int, str]:
        return run("strip-silence", self.take, "--min-gap", "2", "--min-keep", "0.5", "--pad", "100", "--fade", "20", *more,
                   *(["--out", out] if out else []))

    def regions_on(self, bundle: Path, track: str) -> list:
        return sorted((r for r in read_audio_regions(data(bundle), count(bundle)) if r.track == track), key=lambda r: r.start)

    def test_without_out_the_plan_is_printed_and_nothing_written(self):
        code, text = self.strip("--track", "Audio 1")
        self.assertEqual(code, 0, text)
        self.assertEqual(text.count("    keep "), 3, text)
        self.assertIn(": 3 kept, 2 cut", text)
        self.assertIn("silent under", text)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["hush.wav", "take", "take.wav"])

    def test_the_gap_is_cut_and_the_cut_edges_faded(self):
        dest = written(self, "strip-silence", self.take, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5",
                       "--pad", "100", "--fade", "20", out=self.out / "cut")
        first, second, third = self.regions_on(dest, "Audio 1")
        self.assertEqual((first.name, second.name, third.name), ("take", "take.1", "take.2"))
        self.assertEqual((first.start, first.offset), (BAR_ONE, 0))
        self.assertEqual(first.frames, round(1.1 * RATE))
        self.assertEqual(second.offset, round(3.9 * RATE))
        self.assertEqual(second.frames, round(1.2 * RATE))          # padded at both ends
        self.assertEqual(second.start, BAR_ONE + round(second.offset / SPT))
        self.assertEqual(third.offset, round(7.9 * RATE))
        self.assertEqual(third.frames, round(1.1 * RATE))
        self.assertEqual([(r.fade.in_ms, r.fade.out_ms) for r in (first, second, third)], [(0, 20), (20, 20), (20, 0)])
        self.assertEqual(entries(dest, "Audio 3"), entries(self.take, "Audio 3"))             # the other track, byte for byte

    def test_a_region_silent_throughout_is_muted_and_named(self):
        dest = written(self, "strip-silence", self.take, "--track", "Audio 3", "--min-gap", "2", out=self.out / "cut")
        (region,) = self.regions_on(dest, "Audio 3")
        self.assertTrue(region.muted)
        code, text = self.strip("--track", "Audio 3")
        self.assertEqual(code, 0, text)
        self.assertIn("silent throughout", text)

    def test_a_second_run_numbers_its_pieces_past_the_ones_the_track_has(self):
        wav = sound_gap_sound(self.out / "twice.wav", gap=(1.5, 3.0))
        take = written(self, "regions", THREE, "--audio", f"Audio 2:1:{wav}", out=self.out / "twicetake")
        once = written(self, "strip-silence", take, "--track", "Audio 2", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                       out=self.out / "once")
        self.assertEqual([r.name for r in self.regions_on(once, "Audio 2")], ["twice", "twice.1"])
        twice = written(self, "strip-silence", once, "--track", "Audio 2", "--min-gap", "1", "--min-keep", "0.5", "--pad", "100",
                        out=self.out / "twice")
        a, b, c = self.regions_on(twice, "Audio 2")
        self.assertEqual([r.name for r in (a, b, c)], ["twice", "twice.2", "twice.1"])
        self.assertEqual(a.frames, round(1.1 * RATE))
        self.assertEqual(b.offset, round(2.4 * RATE))                 # 1 s sound, 1.5 s gap, 100 ms pad
        self.assertEqual(c.offset, round(6.4 * RATE))
        self.assertEqual([(r.fade.in_ms, r.fade.out_ms) for r in (a, b, c)], [(0, 20), (20, 20), (20, 0)])

    def test_a_track_cannot_be_its_own_reference(self):
        code, text = self.strip("--track", "Audio 1", "--ref", "Audio 1", out=self.out / "refused1")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused1").glob("*.logicx")), [], text)
        self.assertIn("its own reference", text)

    def test_a_gap_shorter_than_min_gap_leaves_nothing_to_cut_and_no_copy(self):
        code, text = self.strip("--track", "Audio 1", "--min-gap", "5", out=self.out / "none")
        self.assertEqual(code, 0, text)
        self.assertIn("nothing to cut", text)
        self.assertFalse((self.out / "none").exists())

    def test_an_unknown_track_is_refused(self):
        code, text = self.strip("--track", "Audio 9", out=self.out / "refused2")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused2").glob("*.logicx")), [], text)
        self.assertIn("no track named 'Audio 9'", text)

    def test_a_track_with_no_audio_regions_is_refused(self):
        code, text = self.strip("--track", "Audio 2", out=self.out / "refused3")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused3").glob("*.logicx")), [], text)
        self.assertIn("'Audio 2' has no audio regions", text)

    def test_the_edges_crop_in_over_hum_under_the_edge_limit(self):
        hummed = sound_hum_gap(self.out / "hummed.wav")
        take = written(self, "regions", THREE, "--audio", f"Audio 2:1:{hummed}", out=self.out / "humtake")
        dest = written(self, "strip-silence", take, "--track", "Audio 2", "--min-gap", "2", "--min-keep", "0.5",
                       "--pad", "100", out=self.out / "cut")
        first, second = self.regions_on(dest, "Audio 2")
        self.assertEqual(first.frames, round(1.1 * RATE))
        self.assertEqual(second.offset, round(5.9 * RATE))
        loose = written(self, "strip-silence", take, "--track", "Audio 2", "--min-gap", "2", "--min-keep", "0.5",
                        "--pad", "100", "--edge", "-30", out=self.out / "loose")
        first, second = self.regions_on(loose, "Audio 2")
        self.assertEqual(first.frames, round(2.1 * RATE))
        self.assertEqual(second.offset, round(4.9 * RATE))

    @unittest.skipUnless(swift_available(), "the band-limited envelope runs through swift")
    def test_a_vocal_mic_is_cut_to_where_the_singer_rises_over_the_bleed(self):
        vox, ref = vocal_mic(self.out / "vox.wav"), band_playing(self.out / "ref.wav")
        take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{vox}", "--audio", f"Audio 2:1:{ref}", out=self.out / "voxtake")
        code, text = run("strip-silence", take, "--track", "Audio 1", "--ref", "Audio 2", "--band", "300:3000",
                         "--min-gap", "1", "--min-keep", "0.5", "--pad", "100")
        self.assertEqual(code, 0, text)
        self.assertIn("bleed floor", text)
        self.assertEqual(text.count("    keep "), 2, text)
        code, text = run("strip-silence", take, "--track", "Audio 1", "--ref", "Audio 2", "--band", "300:3000",
                         "--min-gap", "1", "--min-keep", "0.5", "--pad", "100", "--out", self.out / "voxcut")
        self.assertEqual(code, 0, text)                       # the region's start moves, which `written` would not allow
        (was,) = self.regions_on(take, "Audio 1")
        after = data(self.out / "voxcut" / take.name)
        self.assertEqual(regressions(data(take), after, removed=[(was.object_id, was.start, AUDIO_ENTRY)]), [], text)
        first, second = self.regions_on(self.out / "voxcut" / take.name, "Audio 1")
        for piece in (first, second):
            self.assertEqual((piece.file_slot, piece.params, piece.colour), (was.file_slot, was.params, was.colour))
        self.assertAlmostEqual(first.offset, 1.9 * RATE, delta=441)                   # the rule reads hops: one hop
        self.assertAlmostEqual(first.frames, 2.2 * RATE, delta=441)
        self.assertAlmostEqual(second.offset, 5.9 * RATE, delta=441)
        self.assertAlmostEqual(second.frames, 2.2 * RATE, delta=441)
        self.assertEqual([(r.fade.in_ms, r.fade.out_ms) for r in (first, second)], [(20, 20), (20, 20)])

    def test_a_pad_before_and_after_and_a_window_are_taken(self):
        dest = written(self, "strip-silence", self.take, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5",
                       "--pad", "100:300", "--fade", "20", out=self.out / "cut")
        first, second, third = self.regions_on(dest, "Audio 1")
        self.assertEqual(first.frames, round(1.3 * RATE))                 # 1 s of sound, 300 ms after
        self.assertEqual(second.offset, round(3.9 * RATE))                # 100 ms before
        self.assertEqual(second.frames, round(1.4 * RATE))
        code, text = self.strip("--track", "Audio 1", "--pad", "100:x")
        self.assertEqual((code, "a pad is MS" in text), (2, True), text)
        code, text = self.strip("--track", "Audio 1", "--window", "30")
        self.assertEqual((code, "window is the bleed rule's; it needs ref" in text), (2, True), text)

    @unittest.skipUnless(swift_available(), "the band-limited envelope runs through swift")
    def test_a_tilt_keeps_the_tom_and_drops_the_snare(self):
        tom, ref = tom_mic(self.out / "tom.wav"), band_playing(self.out / "ref.wav", seconds=8.0)
        take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{tom}", "--audio", f"Audio 2:1:{ref}", out=self.out / "tomtake")
        common = ["--track", "Audio 1", "--ref", "Audio 2", "--band", "55:110", "--window", "30", "--above", "12",
                  "--min-gap", "0.5", "--min-keep", "0.05", "--pad", "50:100"]
        code, text = run("strip-silence", take, *common)
        self.assertEqual(code, 0, text)
        self.assertEqual(text.count("    keep "), 2, text)                                  # the tone and the noise both
        code, text = run("strip-silence", take, *common, "--against-band", "400:2000", "--tilt", "0")
        self.assertEqual(code, 0, text)
        self.assertEqual(text.count("    keep "), 1, text)                                  # the tone alone
        self.assertIn("0:01.9", text)
        wide = [a if a != "55:110" else "60:400" for a in common]                      # the level rule on the wide band
        code, text = run("strip-silence", take, *wide, "--tilt-band", "55:110", "--against-band", "400:2000", "--tilt", "0")
        self.assertEqual(code, 0, text)
        self.assertEqual(text.count("    keep "), 1, text)
        code, text = run("strip-silence", take, *wide, "--tilt-band", "auto", "--against-band", "400:2000", "--tilt", "0")
        self.assertEqual(code, 0, text)
        self.assertIn("fundamental 80 Hz, tilt band 56:112", text)                   # the tom's 80 Hz, 0.7 to 1.4 of it
        self.assertEqual(text.count("    keep "), 1, text)
        code, text = self.strip("--track", "Audio 1", "--tilt", "0")
        self.assertEqual((code, "tilt needs against_band" in text), (2, True), text)
        code, text = self.strip("--track", "Audio 1", "--ref", "Audio 2", "--tilt-band", "55:110")
        self.assertEqual((code, "tilt_band needs against_band" in text), (2, True), text)

    def test_a_spec_cuts_several_groups_in_one_copy(self):
        import json
        hummed = sound_hum_gap(self.out / "hummed.wav")
        take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{self.out / 'take.wav'}", "--audio", f"Audio 2:1:{hummed}",
                       out=self.out / "spectake")
        spec = self.out / "spec.json"
        spec.write_text(json.dumps({"groups": [
            {"tracks": ["Audio 1"], "min_gap": 2, "min_keep": 0.5, "pad": 100},
            {"tracks": ["Audio 2"], "min_gap": 2, "min_keep": 0.5, "pad": 100, "edge": -30},
        ]}))
        code, text = run("strip-silence", take, "--spec", spec)
        self.assertEqual(code, 0, text)
        self.assertEqual(text.count("    keep "), 5, text)                                  # three pieces and two
        dest = written(self, "strip-silence", take, "--spec", spec, out=self.out / "speccut")
        self.assertEqual(len(self.regions_on(dest, "Audio 1")), 3)
        first, _second = self.regions_on(dest, "Audio 2")
        self.assertEqual(first.frames, round(2.1 * RATE))                   # the hum kept: edge off
        code, text = run("strip-silence", take, "--spec", spec, "--track", "Audio 1")
        self.assertEqual((code, "--spec is instead of --track" in text), (2, True), text)
        code, text = run("strip-silence", take, "--spec", spec, "--min-gap", "1")
        self.assertEqual((code, "--spec is instead of --track" in text), (2, True), text)

    def test_a_reference_the_project_lacks_is_refused(self):
        code, text = self.strip("--track", "Audio 1", "--ref", "Audio 9", out=self.out / "refused4")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused4").glob("*.logicx")), [], text)
        self.assertIn("no track named 'Audio 9'", text)
        code, text = self.strip("--track", "Audio 1", "--ref", "Audio 2", "--ref", "Audio 2", out=self.out / "refused5")
        self.assertEqual(code, 2, text)
        self.assertEqual(sorted((self.out / "refused5").glob("*.logicx")), [], text)
        self.assertIn("ref 'Audio 2' is named twice", text)


if __name__ == "__main__":
    unittest.main()
