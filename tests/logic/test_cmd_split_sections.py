"""`split-sections` from the command line on a blank-born project: a take on Audio 1 cut at the
edges of the sections named, the pieces inside them moved onto Audio 2, the plan first; the
slivers left alone and the runs refused."""

import re
import tempfile
import unittest
from pathlib import Path

import _goldens
from _audio import tone
from _cli import count, data, run, written

from logicxkit.logic.services.regions.audio_regions import AUDIO_ENTRY, read_audio_regions
from logicxkit.logic.services.stream.integrity import regressions, structural_report

THREE = "tracks-three-audio-logic"        # Audio 1, 2 and 3 at 120 bpm, 44100 Hz
INSTRUMENT = "tracks-instrument-logic"    # Audio 1 and Inst 1
RATE = 44100
BAR_ONE, BAR = 38400, 3840                # ticks; a bar is two seconds at 120 bpm
SECOND = RATE


@_goldens.needs(THREE, INSTRUMENT)
class SplitSectionsCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def take(self, key: str = THREE, *sections: str) -> Path:
        """A ten-second take on Audio 1 from bar 1 — five bars — under the sections given as
        `arrangement --add` specs; by default break (bar 1), Song (2-4), break (4), Song 2 (5)."""
        sections = sections or ("1:1:break", "2:2:Song", "4:1:break", "5:1:Song 2")
        take = written(self, "regions", key, "--audio", f"Audio 1:1:{tone(self.out / 'take.wav', 10)}", out=self.out / "take")
        adds = [a for s in sections for a in ("--add", s)]
        return written(self, "arrangement", take, *adds, out=self.out / "sections")

    def on(self, bundle: Path, track: str) -> list[tuple]:
        regions = read_audio_regions(data(bundle), count(bundle))
        return sorted(((r.name, r.start, r.offset, r.frames) for r in regions if r.track == track), key=lambda x: x[1])

    def test_without_out_the_plan_is_printed_and_nothing_written(self):
        proj = self.take()
        code, text = run("split-sections", proj, "--section", "break", "--track", "Audio 1", "--to", "Audio 2")
        self.assertEqual(code, 0, text)
        self.assertEqual(re.findall(r"^ +cut .* bar +([\d.]+)$", text, re.M), ["2.00", "4.00", "5.00"], text)
        self.assertEqual(re.findall(r"^ +move .* bar +([\d.]+) - +([\d.]+) +onto 'Audio 2'$", text, re.M),
                         [("1.00", "2.00"), ("4.00", "5.00")], text)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["sections", "take", "take.wav"])

    def test_the_pieces_inside_the_sections_move_and_the_rest_stay(self):
        proj = self.take()
        before = data(proj)
        (was,) = read_audio_regions(before, count(proj))
        code, text = run("split-sections", proj, "--section", "break", "--track", "Audio 1", "--to", "Audio 2",
                         "--out", self.out / "moved")
        self.assertEqual(code, 0, text)
        dest = self.out / "moved" / proj.name
        after = data(dest)
        self.assertIsNone(structural_report(after)["unreadable"], text)
        self.assertEqual(regressions(before, after, removed=[(was.object_id, was.start, AUDIO_ENTRY)]), [], text)
        self.assertEqual(self.on(dest, "Audio 1"), [("take.1", BAR_ONE + BAR, 2 * SECOND, 4 * SECOND),
                                                    ("take.3", BAR_ONE + 4 * BAR, 8 * SECOND, 2 * SECOND)])
        self.assertEqual(self.on(dest, "Audio 2"), [("take", BAR_ONE, 0, 2 * SECOND),
                                                    ("take.2", BAR_ONE + 3 * BAR, 6 * SECOND, 2 * SECOND)])

    def test_the_regions_fades_stay_at_its_ends_and_the_cuts_carry_none(self):
        proj = self.take()
        faded = written(self, "regions", proj, "--fade-in", "1=100", "--fade-out", "1=300:2:x", out=self.out / "faded")
        code, text = run("split-sections", faded, "--section", "break", "--track", "Audio 1", "--to", "Audio 2", "--out", self.out / "cut")
        self.assertEqual(code, 0, text)                                             # the head moves, which `written` refuses
        dest = self.out / "cut" / faded.name
        regions = {r.name: r for r in read_audio_regions(data(dest), count(dest))}
        self.assertEqual((regions["take"].fade.in_ms, regions["take"].fade.out_ms), (100, 0))
        self.assertEqual((regions["take.1"].fade.in_ms, regions["take.1"].fade.out_ms), (0, 0))
        self.assertEqual((regions["take.2"].fade.in_ms, regions["take.2"].fade.out_ms), (0, 0))
        last = regions["take.3"].fade
        self.assertEqual((last.in_ms, last.out_ms, last.out_curve, last.out_type), (0, 300, 2, "x"))

    def test_without_to_the_pieces_are_cut_and_stay_on_their_track(self):
        proj = self.take()
        dest = written(self, "split-sections", proj, "--section", "break", "--track", "Audio 1", out=self.out / "cut")
        self.assertEqual([n for n, *_rest in self.on(dest, "Audio 1")], ["take", "take.1", "take.2", "take.3"])
        self.assertEqual([s for _n, s, *_rest in self.on(dest, "Audio 1")], [BAR_ONE + k * BAR for k in (0, 1, 3, 4)])
        self.assertEqual(self.on(dest, "Audio 2"), [])

    def test_a_piece_name_logic_numbered_ahead_is_never_repeated(self):
        split = written(self, "regions", self.take(), "--split", "1=5.5", out=self.out / "split")
        ahead = written(self, "regions", split, "--rename", "2=take.5", out=self.out / "ahead")    # piece 1, named as Logic's counter might
        dest = written(self, "split-sections", ahead, "--section", "break", "--track", "Audio 1", out=self.out / "cut")
        self.assertEqual([n for n, *_rest in self.on(dest, "Audio 1")], ["take", "take.6", "take.7", "take.8", "take.5"])

    def test_a_span_shorter_than_min_piece_stays_with_its_neighbour(self):
        proj = self.take(THREE, "1:0.25:break", "1.25:4.75:Song")      # half a second of break at the head
        code, text = run("split-sections", proj, "--section", "break", "--track", "Audio 1", "--to", "Audio 2",
                         "--out", self.out / "none")
        self.assertEqual(code, 0, text)
        self.assertIn("nothing to cut", text)
        self.assertRegex(text, r"(?m)^ +left  0\.5 s ")                       # the sliver is named
        self.assertFalse((self.out / "none" / proj.name).exists())
        code, text = run("split-sections", proj, "--section", "break", "--track", "Audio 1", "--to", "Audio 2",
                         "--min-piece", "0.4", "--out", self.out / "moved")
        self.assertEqual(code, 0, text)
        dest = self.out / "moved" / proj.name
        self.assertEqual(self.on(dest, "Audio 2"), [("take", BAR_ONE, 0, SECOND // 2)])
        self.assertEqual(self.on(dest, "Audio 1"), [("take.1", BAR_ONE + BAR // 4, SECOND // 2, 10 * SECOND - SECOND // 2)])

    def test_a_region_inside_the_section_throughout_is_moved_whole(self):
        proj = self.take(THREE, "1:5:Song")
        code, text = run("split-sections", proj, "--section", "Song", "--track", "Audio 1", "--to", "Audio 2",
                         "--out", self.out / "whole")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.on(self.out / "whole" / proj.name, "Audio 2"), [("take", BAR_ONE, 0, 10 * SECOND)])

    def test_a_region_outside_every_named_section_is_left_and_no_copy_written(self):
        proj = self.take(THREE, "7:2:Song")
        code, text = run("split-sections", proj, "--section", "Song", "--track", "Audio 1", "--to", "Audio 2",
                         "--out", self.out / "outside")
        self.assertEqual(code, 0, text)
        self.assertIn("nothing to cut; no copy written", text)
        self.assertFalse((self.out / "outside").exists())

    def test_an_unknown_section_is_refused_and_nothing_written(self):
        proj = self.take(THREE, "1:5:Song")
        code, text = run("split-sections", proj, "--section", "Verse", "--track", "Audio 1", "--to", "Audio 2",
                         "--out", self.out / "none")
        self.assertEqual(code, 1, text)
        self.assertIn("no section named 'Verse'", text)
        self.assertFalse((self.out / "none").exists())

    def test_a_piece_landing_over_a_region_on_the_destination_is_refused(self):
        proj = self.take()
        busy = written(self, "regions", proj, "--audio", f"Audio 2:1:{tone(self.out / 'other.wav', 1)}", out=self.out / "busy")
        code, text = run("split-sections", busy, "--section", "break", "--track", "Audio 1", "--to", "Audio 2",
                         "--out", self.out / "refused")
        self.assertEqual(code, 1, text)
        self.assertIn("Audio 1's 'take' from 0.0 s would land over 'other' on 'Audio 2'", text)
        self.assertFalse((self.out / "refused" / busy.name).exists())

    def test_two_tracks_moved_onto_one_destination_may_not_land_over_each_other(self):
        proj = self.take()
        both = written(self, "regions", proj, "--audio", f"Audio 3:1:{tone(self.out / 'third.wav', 10)}", out=self.out / "both")
        code, text = run("split-sections", both, "--section", "break", "--track", "Audio 1", "--track", "Audio 3",
                         "--to", "Audio 2", "--to", "Audio 2", "--out", self.out / "refused")
        self.assertEqual(code, 1, text)
        self.assertIn("Audio 3's 'third' from 0.0 s and Audio 1's 'take' from 0.0 s would land over each other on 'Audio 2'", text)
        self.assertFalse((self.out / "refused" / both.name).exists())

    def test_a_region_crossfaded_with_another_on_its_track_is_refused(self):
        proj = self.take()
        pair = written(self, "regions", proj, "--audio", f"Audio 1:3:{tone(self.out / 'later.wav', 2)}", out=self.out / "pair")
        crossed = written(self, "regions", pair, "--crossfade", "1=500", out=self.out / "crossed")
        code, text = run("split-sections", crossed, "--section", "break", "--track", "Audio 1", "--to", "Audio 2", "--out", self.out / "refused1")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused1").glob("*.logicx")), [], text)
        self.assertIn("Audio 1's region 'take' is crossfaded into 'later'; cut it by hand", text)

    def test_the_track_itself_is_not_a_destination(self):
        proj = self.take()
        code, text = run("split-sections", proj, "--section", "break", "--track", "Audio 1", "--to", "Audio 1", "--out", self.out / "refused2")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused2").glob("*.logicx")), [], text)
        self.assertIn("'Audio 1' is the track itself; --to names another track", text)

    def test_a_destination_that_is_not_an_audio_track_is_refused(self):
        proj = self.take(INSTRUMENT)
        code, text = run("split-sections", proj, "--section", "break", "--track", "Audio 1", "--to", "Inst 1",
                         "--out", self.out / "refused")
        self.assertEqual(code, 1, text)
        self.assertIn("'Inst 1' is not an audio track", text)
        self.assertFalse((self.out / "refused" / proj.name).exists())

    def test_to_pairs_with_track_one_for_one(self):
        proj = self.take()
        code, text = run("split-sections", proj, "--section", "break", "--track", "Audio 1", "--track", "Audio 3",
                         "--to", "Audio 2", "--out", self.out / "unpaired")
        self.assertEqual(code, 2, text)
        self.assertFalse((self.out / "unpaired").exists())
        self.assertIn("--to names one track per --track, in the same order", text)
        code, text = run("split-sections", proj, "--section", "break", "--track", "Audio 1", "--min-piece", "-1", "--out", self.out / "refused3")
        self.assertEqual(code, 2, text)
        self.assertEqual(sorted((self.out / "refused3").glob("*.logicx")), [], text)
        self.assertIn("--min-piece -1: seconds, 0 to 86400", text)


if __name__ == "__main__":
    unittest.main()
