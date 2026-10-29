"""`songs` from the command line on a blank-born project: two tracks of sound-gap-sound-gap-sound,
three songs on the setlist, the stops and the plan printed, the sections written on a copy; a
setlist of the wrong length writes nothing."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _audio import RATE, riff
from _cli import run, written

from logicxkit.logic._edit import first_project_data
from logicxkit.logic.services.song.arrangement import read_sections

THREE = "tracks-three-audio-logic"            # Audio 1, 2 and 3 at 120 bpm, 44100 Hz
TICKS_PER_SECOND = 120 / 60 * 960
BAR_ONE = 38400
FLAGS = ("--track", "Audio 1", "--track", "Audio 2", "--min-stop", "2", "--merge", "1", "--min-song", "0.5")


def takes(path: Path, *, sound: float = 1.0, gap: float = 3.0, tail: int = 0) -> Path:
    """A 24-bit mono file: three ``sound``-second stretches at -6 dBFS, ``gap`` seconds at -60 dBFS between,
    the last ``tail`` frames longer."""
    x = ([0.5] * int(sound * RATE) + [0.001] * int(gap * RATE)) * 2 + [0.5] * (int(sound * RATE) + tail)
    frames = b"".join((round(v * 8388607) * (1 if i % 2 == 0 else -1)).to_bytes(3, "little", signed=True) for i, v in enumerate(x))
    return riff(path, frames)


@_goldens.needs(THREE)
class SongsCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        bass, drums = takes(self.out / "bass.wav"), takes(self.out / "drums.wav")
        self.set = written(self, "regions", THREE, "--audio", f"Audio 1:1:{bass}", "--audio", f"Audio 2:1:{drums}",
                           out=self.out / "set")
        self.setlist = self.out / "setlist.txt"
        self.setlist.write_text("One\nTwo\nbreak\nThree\n")

    def test_the_plan_lists_the_stops_and_lays_the_setlist_over_the_playing(self):
        code, text = run("songs", self.set, self.setlist, *FLAGS)
        self.assertEqual(code, 0, text)
        self.assertIn("2 stop(s), 3 stretch(es) of playing, 3 song(s)", text)
        self.assertEqual(text.count("  stop "), 2)
        for name in ("One", "Two", "Three"):
            self.assertIn(name, text)
        self.assertIn("break after 'Two': stop", text)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["bass.wav", "drums.wav", "set", "setlist.txt"])

    def test_the_sections_are_written_where_the_songs_play(self):
        dest = written(self, "songs", self.set, self.setlist, *FLAGS, out=self.out / "songs")
        sections = read_sections(first_project_data(dest))
        self.assertEqual([s.name for s in sections], ["One", "Two", "Three"])
        for k, s in enumerate(sections):
            self.assertEqual((s.start, s.length), (BAR_ONE + 4 * k * TICKS_PER_SECOND, TICKS_PER_SECOND))

    def test_a_setlist_of_another_length_writes_nothing(self):
        self.setlist.write_text("One\nTwo\n")
        code, text = run("songs", self.set, self.setlist, *FLAGS, "--out", self.out / "no")
        self.assertEqual(code, 1, text)
        self.assertIn("names 2 song(s), the set holds 3 stretch(es)", text)
        self.assertIn("nothing written", text)
        self.assertFalse((self.out / "no").exists())

    def test_the_defaults_find_no_stop_this_short(self):
        code, text = run("songs", self.set, self.setlist, "--track", "Audio 1", "--track", "Audio 2", "--out", self.out / "refused1")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused1").glob("*.logicx")), [], text)
        self.assertIn("0 stop(s), 0 stretch(es)", text)
        self.assertIn("left out", text)

    def test_refusals(self):
        self.setlist.write_text("\n")
        code, text = run("songs", self.set, self.setlist, *FLAGS, "--out", self.out / "refused2")
        self.assertEqual(code, 2, text)
        self.assertEqual(sorted((self.out / "refused2").glob("*.logicx")), [], text)
        self.assertIn("names no song", text)
        self.setlist.write_text("One\n")
        code, text = run("songs", self.set, self.setlist, "--track", "Audio 9", "--out", self.out / "refused3")
        self.assertEqual(code, 1, text)
        self.assertEqual(sorted((self.out / "refused3").glob("*.logicx")), [], text)
        self.assertIn("no track named 'Audio 9'", text)
        code, text = run("songs", self.set, self.setlist, "--out", self.out / "refused4")
        self.assertEqual(code, 2, text)
        self.assertEqual(sorted((self.out / "refused4").glob("*.logicx")), [], text)
        self.assertIn("--track NAME (repeatable) names the tracks that go quiet between songs", text)
        code, text = run("songs", self.set, self.setlist, "--track", "Audio 1", "--min-stop", "-1", "--out", self.out / "refused5")
        self.assertEqual(code, 2, text)
        self.assertEqual(sorted((self.out / "refused5").glob("*.logicx")), [], text)
        self.assertIn("--min-stop -1: 0 or more seconds", text)
        for flag, value in (("--min-gap", "nan"), ("--min-song", "inf"), ("--merge", "x")):
            code, text = run("songs", self.set, self.setlist, "--track", "Audio 1", flag, value, "--out", self.out / "refused6")
            self.assertEqual(code, 2, text)
            self.assertEqual(sorted((self.out / "refused6").glob("*.logicx")), [], text)
            self.assertIn(f"{flag} '{value}': a number", text)


    def test_breaks_fill_the_stops_so_the_sections_run_contiguous(self):
        dest = written(self, "songs", self.set, self.setlist, *FLAGS, "--breaks", "break", out=self.out / "breaks")
        sections = read_sections(first_project_data(dest))
        self.assertEqual([s.name for s in sections], ["One", "break", "Two", "break", "Three"])
        for a, b in zip(sections, sections[1:], strict=False):
            self.assertEqual(a.start + a.length, b.start)

    def test_a_second_run_on_the_songs_copy_is_refused_and_names_the_section(self):
        once = written(self, "songs", self.set, self.setlist, *FLAGS, out=self.out / "once")
        code, text = run("songs", once, self.setlist, *FLAGS, "--breaks", "break", "--out", self.out / "twice")
        self.assertEqual(code, 1, text)
        self.assertIn("3 section(s) already where the songs play, 'One' at bar 1.00 first: nothing written", text)
        self.assertFalse((self.out / "twice").exists())

    def test_the_last_break_runs_to_the_last_region_on_any_track(self):
        vocal = takes(self.out / "vocal.wav", sound=3.0)            # 15 s, past the named tracks' 9 s
        with_vocal = written(self, "regions", self.set, "--audio", f"Audio 3:1:{vocal}", out=self.out / "vocal")
        dest = written(self, "songs", with_vocal, self.setlist, *FLAGS, "--breaks", "break", out=self.out / "breaks")
        last = read_sections(first_project_data(dest))[-1]
        self.assertEqual(last.name, "break")
        self.assertAlmostEqual(last.start + last.length, BAR_ONE + 15 * TICKS_PER_SECOND, delta=1)

    def test_an_empty_breaks_name_is_refused(self):
        code, text = run("songs", self.set, self.setlist, *FLAGS, "--breaks", " ", "--out", self.out / "blank")
        self.assertEqual(code, 2, text)
        self.assertIn("--breaks names the stops' sections; give it a name", text)
        self.assertFalse((self.out / "blank").exists())

    def test_a_song_playing_to_the_last_frame_is_followed_by_no_break(self):
        bass, drums = takes(self.out / "bass2.wav", tail=200), takes(self.out / "drums2.wav", tail=200)    # 200 frames into a hop
        tailed = written(self, "regions", THREE, "--audio", f"Audio 1:1:{bass}", "--audio", f"Audio 2:1:{drums}", out=self.out / "tailed")
        dest = written(self, "songs", tailed, self.setlist, *FLAGS, "--breaks", "Gap", out=self.out / "tailbreaks")
        self.assertEqual(read_sections(first_project_data(dest))[-1].name, "Three")


if __name__ == "__main__":
    unittest.main()
