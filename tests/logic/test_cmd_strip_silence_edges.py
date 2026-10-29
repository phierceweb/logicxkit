"""`strip-silence` from the command line at its edges: the refusals by name, a file that is not
the record's, a second region inside the cut one, a tail shorter than a tick, and the piece names a
second run gives."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, refused, run, written
from _audio import RATE, THREE, band_playing, riff, silent, sound_gap_sound

from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.fades import CROSSFADES


@_goldens.needs(THREE)
class StripSilenceEdgesTest(unittest.TestCase):
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

    def test_neither_track_nor_spec_is_refused(self):
        code, text = run("strip-silence", self.take, "--out", self.out / "refused1")
        self.assertEqual(code, 2, text)
        self.assertEqual(sorted((self.out / "refused1").glob("*.logicx")), [], text)
        self.assertIn("--track NAME (repeatable) names what to cut, or --spec FILE.json", text)

    def test_a_file_that_is_not_the_one_the_record_describes_is_refused(self):
        import struct
        wav = self.take / "Media" / "Audio Files" / "take.wav"        # the import's own copy, the one the project plays
        kept = wav.read_bytes()
        fmt = struct.pack("<HHIIHH", 1, 1, 48000, 48000 * 3, 3, 24)
        body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", 300) + bytes(300)
        wav.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
        code, text = self.strip("--track", "Audio 1", out=self.out / "refused2")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused2").glob("*.logicx")), [], text)
        self.assertIn("take.wav is at 48000 Hz but the file record of Audio 1's region 'take' says 44100 Hz", text)
        riff(wav, kept[-300:])
        code, text = self.strip("--track", "Audio 1", out=self.out / "refused3")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused3").glob("*.logicx")), [], text)
        self.assertIn("take.wav holds 100 frames but the file record of Audio 1's region 'take' says", text)
        wav.unlink()
        code, text = self.strip("--track", "Audio 1", out=self.out / "refused4")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused4").glob("*.logicx")), [], text)
        self.assertIn("no audio file for Audio 1's region 'take' (take.wav)", text)

    def test_a_file_at_another_rate_than_the_project_is_refused_though_its_record_agrees(self):
        from logicxkit.logic.orchestrators.strip_silence import Settings, plan_strip
        wav = self.take / "Media" / "Audio Files" / "take.wav"
        with self.assertRaisesRegex(ValueError, "take.wav is at 44100 Hz; the project is at 48000 Hz"):
            plan_strip(data(self.take), ["Audio 1"], lambda _r: wav, rate=48000, settings=Settings(), track_count=count(self.take))

    def test_another_region_starting_inside_the_cut_one_does_not_throw_the_pieces_off(self):
        other = sound_gap_sound(self.out / "other.wav", sound=0.5, gap=0.1)
        take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{self.out / 'take.wav'}", "--audio", f"Audio 1:3:{other}",
                       out=self.out / "twotake")
        was = next(r for r in self.regions_on(take, "Audio 1") if r.name == "other")
        dest = written(self, "strip-silence", take, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                       out=self.out / "cut")
        first, second, kept, third = self.regions_on(dest, "Audio 1")
        self.assertEqual([r.name for r in (first, second, kept, third)], ["take", "take.1", "other", "take.2"])
        self.assertEqual((kept.start, kept.offset, kept.frames, kept.fade, kept.muted), (was.start, was.offset, was.frames, was.fade, was.muted))
        self.assertEqual(first.frames, round(1.1 * RATE))
        self.assertEqual(second.offset, round(3.9 * RATE))
        self.assertEqual(second.frames, round(1.2 * RATE))
        self.assertEqual(third.offset, round(7.9 * RATE))
        self.assertEqual([(r.fade.in_ms, r.fade.out_ms) for r in (first, second, third)], [(0, 20), (20, 20), (20, 0)])

    def test_the_regions_own_fades_stay_on_its_first_and_last_piece(self):
        faded = written(self, "regions", self.take, "--fade-in", "1=50", "--fade-out", "1=80:2:x", out=self.out / "faded")
        (was,) = self.regions_on(faded, "Audio 1")
        self.assertEqual((was.fade.in_ms, was.fade.out_ms, was.fade.out_curve, was.fade.out_type), (50, 80, 2, "x"))
        dest = written(self, "strip-silence", faded, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                       "--fade", "20", out=self.out / "cut")
        first, second, third = self.regions_on(dest, "Audio 1")
        self.assertEqual((first.fade.in_ms, first.fade.out_ms), (50, 20))
        self.assertEqual((second.fade.in_ms, second.fade.out_ms, second.fade.out_type), (20, 20, "out"))
        self.assertEqual((third.fade.in_ms, third.fade.out_ms, third.fade.out_curve, third.fade.out_type), (20, 80, 2, "x"))

    def test_an_end_no_cut_reaches_keeps_its_frames_and_fade_out_off_a_tick_line(self):
        for tail in (5, 12):                                               # under and over half a tick past the file's last tick line
            with self.subTest(tail=tail):
                wav = self.out / f"tail{tail}.wav"
                frames = sound_gap_sound(wav).read_bytes()[44:]
                riff(wav, frames + frames[-3 * tail:])
                take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{wav}", out=self.out / f"tail{tail}")
                faded = written(self, "regions", take, "--fade-out", "1=500:-30", out=self.out / f"tail{tail}faded")
                (was,) = self.regions_on(faded, "Audio 1")
                dest = written(self, "strip-silence", faded, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5",
                               "--pad", "100", out=self.out / f"tail{tail}cut")
                last = self.regions_on(dest, "Audio 1")[-1]
                self.assertEqual(last.offset + last.frames, was.offset + was.frames)
                self.assertEqual((last.fade.out_ms, last.fade.out_curve), (500, -30))

    def test_a_cut_edge_takes_a_plain_fade_whatever_the_parents_was(self):
        """The parent's curve and type stay on the ends this run leaves; a cut edge gets `--fade` ms, plain."""
        idle, sound = [0.001] * (3 * RATE), [0.5 * (1 if i % 2 == 0 else -1) for i in range(RATE)]
        cases = {"head": idle + sound, "tail": sound + idle}
        for name, x in cases.items():
            with self.subTest(name):
                wav = riff(self.out / f"{name}.wav", b"".join(round(v * 8388607).to_bytes(3, "little", signed=True) for v in x))
                take = written(self, "regions", THREE, "--audio", f"Audio 2:1:{wav}", out=self.out / f"{name}take")
                faded = written(self, "regions", take, "--fade-in", "1=50:10:speed-up", "--fade-out", "1=80:5:x", out=self.out / f"{name}faded")
                code, text = run("strip-silence", faded, "--track", "Audio 2", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                                 "--fade", "20", "--out", self.out / f"{name}cut")
                self.assertEqual(code, 0, text)                                     # the head case moves the start, which `written` refuses
                (piece,) = self.regions_on(self.out / f"{name}cut" / faded.name, "Audio 2")
                f = piece.fade
                if name == "head":
                    self.assertEqual((f.in_ms, f.in_curve, f.in_type, f.out_ms, f.out_curve, f.out_type), (20, 0, 0, 80, 5, "x"))
                else:
                    self.assertEqual((f.in_ms, f.in_curve, f.in_type, f.out_ms, f.out_curve, f.out_type), (50, 10, 1, 20, 0, "out"))

    def test_a_kept_fade_longer_than_its_piece_is_shortened_to_fit(self):
        faded = written(self, "regions", self.take, "--fade-in", "1=3000", out=self.out / "longfade")
        dest = written(self, "strip-silence", faded, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                       "--fade", "20", out=self.out / "cut")
        first = self.regions_on(dest, "Audio 1")[0]
        self.assertEqual((first.fade.in_ms, first.fade.out_ms), (1080, 20))                 # 1.1 s piece less the 20 ms out
        long = written(self, "strip-silence", self.take, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                       "--fade", "1000", out=self.out / "longcut")
        first, middle, last = self.regions_on(long, "Audio 1")
        self.assertEqual((middle.fade.in_ms, middle.fade.out_ms), (600, 600))               # a 1.2 s piece: neither side outlasts it
        self.assertEqual((first.fade.in_ms, first.fade.out_ms, last.fade.in_ms, last.fade.out_ms), (0, 1000, 1000, 0))

    def test_kept_spans_that_touch_are_one_so_nothing_is_cut_for_nothing(self):
        code, text = run("strip-silence", self.take, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "1500",
                         "--out", self.out / "none")
        self.assertEqual(code, 0, text)
        self.assertIn("unchanged", text)
        self.assertIn("nothing to cut; no copy written", text)

    def test_a_region_crossfaded_with_another_on_its_track_is_refused(self):
        other = sound_gap_sound(self.out / "other.wav", sound=0.5, gap=0.1)
        take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{self.out / 'take.wav'}", "--audio", f"Audio 1:3:{other}",
                       out=self.out / "pair")
        crossed = written(self, "regions", take, "--crossfade", "1=500", out=self.out / "crossed")
        refused(self, "strip-silence", crossed, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                why="Audio 1's region 'take' is crossfaded into 'other'; cut it by hand", out=self.out / "refused")
        code, text = run("regions", crossed, "--move", "2=9", "--out", self.out / "apart")     # Logic keeps the crossfade's bytes
        self.assertEqual(code, 0, text)
        apart = self.out / "apart" / crossed.name
        self.assertTrue(self.regions_on(apart, "Audio 1")[0].crossfaded)
        refused(self, "strip-silence", apart, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                why="Audio 1's region 'take' carries a crossfade; cut it by hand", out=self.out / "refusedapart")

    def test_a_crossfaded_pair_the_plan_leaves_whole_does_not_stop_the_run(self):
        steady, later = band_playing(self.out / "steady.wav"), band_playing(self.out / "later.wav", 4.0)
        pair = written(self, "regions", THREE, "--audio", f"Audio 2:1:{steady}", "--audio", f"Audio 2:3:{later}",
                       "--audio", f"Audio 1:1:{self.out / 'take.wav'}", out=self.out / "steadypair")
        crossed = written(self, "regions", pair, "--crossfade", "2=500", out=self.out / "steadycrossed")
        self.assertIn(self.regions_on(crossed, "Audio 2")[0].fade.out_type, CROSSFADES)
        dest = written(self, "strip-silence", crossed, "--track", "Audio 1", "--track", "Audio 2", "--min-gap", "2",
                       "--min-keep", "0.5", "--pad", "100", out=self.out / "cut")
        self.assertEqual(len(self.regions_on(dest, "Audio 1")), 3)
        self.assertEqual([r.name for r in self.regions_on(dest, "Audio 2")], ["steady", "later"])

    def test_a_loud_region_shorter_than_a_tick_is_left_as_it_is(self):
        tiny = riff(self.out / "tiny.wav", b"".join((4000000).to_bytes(3, "little", signed=True) for _ in range(10)))
        take = written(self, "regions", THREE, "--audio", f"Audio 2:1:{tiny}", out=self.out / "tinytake")
        code, text = run("strip-silence", take, "--track", "Audio 2", "--out", self.out / "none")
        self.assertEqual(code, 0, text)
        self.assertIn("unchanged (every kept span is shorter than a tick; left as it is)", text)
        self.assertIn("nothing to cut; no copy written", text)
        self.assertFalse((self.out / "none").exists())

    def test_a_band_reaching_half_the_sample_rate_is_refused_before_any_file_is_read(self):
        code, text = self.strip("--track", "Audio 1", "--band", "300:30000", out=self.out / "refused5")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused5").glob("*.logicx")), [], text)
        self.assertIn("band 300:30000 reaches half the sample rate (22050 Hz)", text)

    def test_a_kept_span_shorter_than_a_tick_is_dropped_rather_than_refused(self):
        wav = sound_gap_sound(self.out / "tail.wav", gap=(3.03, 3.0))
        take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{wav}", out=self.out / "tailtake")
        short = written(self, "regions", take, "--trim", f"1=1:{7738 / 3840!r}", out=self.out / "short")      # the region ends 9 frames into the second sound
        dest = written(self, "strip-silence", short, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "0:300",
                       out=self.out / "cut")
        (piece,) = self.regions_on(dest, "Audio 1")
        self.assertEqual(piece.frames, round(1.3 * RATE))

    def test_a_cut_piece_is_numbered_from_its_stem_by_its_piece_number(self):
        wav = sound_gap_sound(self.out / "stem.wav", gap=(3.0, 1.5))
        take = written(self, "regions", THREE, "--audio", f"Audio 2:1:{wav}", out=self.out / "stemtake")
        once = written(self, "strip-silence", take, "--track", "Audio 2", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                       out=self.out / "once")
        self.assertEqual([r.name for r in self.regions_on(once, "Audio 2")], ["stem", "stem.1"])
        twice = written(self, "strip-silence", once, "--track", "Audio 2", "--min-gap", "1", "--min-keep", "0.5", "--pad", "100",
                        out=self.out / "twice")
        self.assertEqual([(r.name, r.piece) for r in self.regions_on(twice, "Audio 2")], [("stem", 0), ("stem.1", 1), ("stem.2", 2)])

    def test_a_piece_name_logic_numbered_ahead_is_never_repeated(self):
        wav = sound_gap_sound(self.out / "stem.wav", gap=(3.0, 1.5))
        take = written(self, "regions", THREE, "--audio", f"Audio 2:1:{wav}", out=self.out / "stemtake")
        once = written(self, "strip-silence", take, "--track", "Audio 2", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                       out=self.out / "once")
        ahead = written(self, "regions", once, "--rename", "2=stem.7", out=self.out / "ahead")      # piece 1, named as Logic's counter might
        self.assertEqual([(r.name, r.piece) for r in self.regions_on(ahead, "Audio 2")], [("stem", 0), ("stem.7", 1)])
        twice = written(self, "strip-silence", ahead, "--track", "Audio 2", "--min-gap", "1", "--min-keep", "0.5", "--pad", "100",
                        out=self.out / "twice")
        self.assertEqual([(r.name, r.piece) for r in self.regions_on(twice, "Audio 2")], [("stem", 0), ("stem.7", 1), ("stem.8", 2)])

    def test_a_parent_named_like_a_piece_keeps_its_name_and_numbers_from_1(self):
        renamed = written(self, "regions", self.take, "--rename", "1=take.9", out=self.out / "renamed")
        dest = written(self, "strip-silence", renamed, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                       out=self.out / "cut")
        self.assertEqual([r.name for r in self.regions_on(dest, "Audio 1")], ["take.9", "take.9.1", "take.9.2"])

    def test_a_copy_reads_its_own_audio_never_the_bundle_it_was_copied_from(self):
        copy = written(self, "strip-silence", self.take, "--track", "Audio 3", out=self.out / "copy")
        wav = copy / "Media" / "Audio Files" / "take.wav"
        kept = wav.read_bytes()
        riff(wav, bytes(len(kept) - kept.index(b"data") - 8))       # silent in the copy, sound in the source
        again = ("strip-silence", copy, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100")
        code, text = run(*again, "--out", self.out / "again")
        self.assertEqual(code, 0, text)
        self.assertIn("silent throughout", text)
        wav.rename(wav.with_name("gone.wav"))
        code, text = run(*again, "--out", self.out / "gone")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "gone").glob("*.logicx")), [], text)
        self.assertIn("no audio file for Audio 1's region 'take' (take.wav)", text)

    def test_a_bad_flag_is_refused_by_name(self):
        for flags, why in ((("--above", "6"), "above is the bleed rule's; it needs ref"),
                           (("--gate", "3"), "gate is the bleed rule's; it needs ref"),
                           (("--band", "3000:300"), "a band is LOW:HIGH"),
                           (("--edge", "-40"), "edge -40 is further under"),
                           (("--threshold", "6"), "threshold 6: 0 or below"),
                           (("--fade", "2.5"), "fade '2.5': whole ms")):
            with self.subTest(flags):
                code, text = self.strip("--track", "Audio 1", *flags)
                self.assertEqual((code, why in text), (2, True), text)


if __name__ == "__main__":
    unittest.main()
