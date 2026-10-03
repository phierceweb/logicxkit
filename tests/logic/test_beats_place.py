"""Laying groovebin patterns over a project's meter and planning them over its sections, without
a real file: the arithmetic is groovebin's, the timeline conversion and the command are tested."""

import argparse
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from _beats import BAR, GROUP, KICK, MAP, SNARE, STICKS, TOM, beat, index
from groovebin.events import Note
from groovebin.library.compose import group_patterns
from groovebin.library.pattern import pattern
from groovebin.library.search import find_group
from logicxkit.logic._beats_cmd import register
from logicxkit.logic.services.midi import beats_compose
from logicxkit.logic.services.song.arrangement import Section
from logicxkit.logic.services.midi.beats_compose import plan
from logicxkit.logic.services.midi.beats_place import lay_over, note_part
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.midi.midi_edit import END_TICK
from logicxkit.logic.services.song.signature import Meter, TimeSignature


class IndexedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.db = index(self.tmp)


class FixtureTest(IndexedCase):
    def test_the_folder_index_labels_the_patterns_from_their_paths(self):
        intro, waltz, tail = (pattern(beat(self.db, v, g)) for v, g in (("Intro", GROUP), ("Chorus", GROUP), ("tail", "Tails")))
        self.assertEqual((intro.name, intro.bars, intro.ticks, intro.meter, intro.role, intro.map),
                         ("Intro", ((4, 4), (4, 4)), 2 * BAR, (4, 4), "intro", MAP))
        self.assertEqual([(n.tick, n.length, n.channel, n.pitch, n.velocity) for n in intro.notes],
                         [(0, 480, 10, KICK, 100), (1920, 240, 10, SNARE, 90), (3840, 480, 10, KICK, 100), (5760, 240, 10, SNARE, 110)])
        self.assertEqual((waltz.bars, waltz.ticks), (((3, 4),), 2880))
        self.assertEqual((tail.name, tail.ticks, tail.notes[-1].tick, tail.role), ("tail", BAR, BAR, None))
        self.assertTrue(pattern(beat(self.db, "Fills 01")).is_fill)


class LayTest(unittest.TestCase):
    def test_bars_laid_over_the_project_meter_and_refused_where_it_differs(self):
        m = Meter([TimeSignature(0, 4, 4), TimeSignature(BAR_ONE + 4 * BAR, 3, 4)])
        self.assertEqual(lay_over(m, 1, ((4, 4), (4, 4))), (BAR_ONE, 2 * BAR))
        self.assertEqual(lay_over(m, 5, ((3, 4),), 3), (BAR_ONE + 4 * BAR, 3 * 2880))
        with self.assertRaisesRegex(ValueError, r"^the pattern's bar 2 is 4/4 but the song is 3/4 at bar 5$"):
            lay_over(m, 4, ((4, 4), (4, 4)))
        with self.assertRaisesRegex(ValueError, "past 4096 bars"):
            lay_over(m, 1, ((4, 4),), 4097)
        with self.assertRaisesRegex(ValueError, "past the end of the sequence"):
            lay_over(Meter([TimeSignature(0, 4, 4)]), END_TICK // BAR - 8, ((4, 4),), 4096)

    def test_notes_scaled_and_remapped(self):
        part, unmapped = note_part([Note(0, 0, 10, 42, 100), Note(960, 60, 10, STICKS, 20)], velocity=0.5, remap_maps=(MAP, "gm"))
        self.assertEqual([(n.tick, n.pitch, n.velocity, n.length) for n in part.notes], [(0, 37, 50, 0), (960, STICKS, 10, 60)])
        self.assertEqual(dict(unmapped), {STICKS: 1})
        with self.assertRaisesRegex(ValueError, "before the pattern's start"):
            note_part([Note(-1, 10, 10, KICK, 100)])
        for scale in (-0.5, float("inf"), float("nan")):
            with self.subTest(scale), self.assertRaisesRegex(ValueError, "not a finite number of 0 or more"):
                note_part([Note(0, 10, 10, KICK, 100)], velocity=scale)


def sections(*spec: tuple[str, int, int]) -> list[Section]:
    return [Section(name, BAR_ONE + bar * BAR, bars * BAR, 0, 0) for name, bar, bars in spec]


class PlanTest(IndexedCase):
    """Logic's sections and signatures reach groovebin's planner on its own timeline."""

    def plans(self, found: list[Section], fills: bool = False, times=(TimeSignature(0, 4, 4),)):
        patterns = group_patterns(self.db, *find_group(self.db, GROUP))
        with mock.patch.object(beats_compose, "read_sections", return_value=found), \
             mock.patch.object(beats_compose, "meter", return_value=Meter(list(times))):
            return plan(b"", patterns, fills=fills)

    def test_names_pick_patterns_and_verses_cycle_in_number_order(self):
        got = self.plans(sections(("Intro", 0, 4), ("verse A", 4, 2), ("VERSE", 6, 3), ("Verse", 9, 1), ("Pre-Chorus", 10, 1),
                                  ("Chorus", 11, 2), ("Outro", 13, 1), ("", 14, 1)))
        self.assertEqual([(p.beat.name if p.beat else None, p.copies) for p in got],
                         [("Intro", 2), ("Verse 01", 2), ("Verse 02", 3), ("Verse 01", 1), (None, 0), (None, 0), (None, 0), (None, 0)])
        self.assertEqual([p.skipped for p in got[4:]], [
            "no Pre-Chorus pattern in the group", "no Chorus pattern in 4/4; the group's are 3/4",
            "no Outro pattern in the group", "'an unnamed section' is not an intro, verse, pre-chorus, chorus, bridge or outro"])
        self.assertEqual((got[0].section.start, got[0].start_bar, got[1].section.start), (0, 1, 4 * BAR))
        self.assertEqual([n.tick for n in got[2].notes],
                         [0, 1920, 2880, BAR, BAR + 1920, BAR + 2880, 2 * BAR, 2 * BAR + 1920, 2 * BAR + 2880])

    def test_a_fill_replaces_the_last_bar(self):
        (intro, verse) = self.plans(sections(("Intro", 0, 4), ("Verse", 4, 1)), fills=True)
        self.assertEqual((intro.fill.name, intro.fill_bar, intro.replaced), ("Fills 01", 4, 2))
        self.assertEqual([(n.tick, n.pitch) for n in intro.notes[-4:]],
                         [(3 * BAR - 1920, SNARE), (3 * BAR, TOM), (3 * BAR + 960, TOM), (3 * BAR + 1920, SNARE)])
        self.assertEqual([(n.tick, n.pitch) for n in verse.notes], [(0, TOM), (960, TOM), (1920, SNARE)])

    def test_a_change_inside_a_start_off_the_bar_line_and_no_room_are_skipped(self):
        waltz = (TimeSignature(0, 4, 4), TimeSignature(BAR_ONE + 2 * BAR, 3, 4))
        got = self.plans([*sections(("Intro", 0, 2), ("Verse", 1, 2)), Section("Chorus", BAR_ONE + 2 * BAR, 2880 * 2, 2, 0),
                          Section("Bridge", BAR_ONE + 2 * BAR + 960, 2880, 3, 0)], fills=True, times=waltz)
        self.assertEqual([p.skipped for p in got], [None, "the meter changes inside the section", None,
                                                    "the section does not start on a bar line"])
        self.assertEqual((got[0].no_fill, got[2].beat.name), (None, "Chorus"))
        self.assertTrue(got[2].no_fill)
        last_line = BAR_ONE + (END_TICK - BAR_ONE) // BAR * BAR
        (far,) = self.plans([Section("Intro", last_line, 2 * BAR, 0, 0)])
        self.assertEqual((far.beat, far.skipped), (None, f"a section of {2 * BAR} ticks from tick {last_line} has no room for a region"))


class GroupTest(IndexedCase):
    def test_a_folder_index_has_no_library_and_the_group_reads_by_name(self):
        self.assertEqual((find_group(self.db, "test kit"), find_group(self.db, "kit two")), ((None, GROUP), (None, GROUP + " Two")))
        self.assertEqual([p.variant for p in group_patterns(self.db, None, GROUP)], ["Chorus", "Fills 01", "Intro", "Verse 01", "Verse 02"])


class CommandTest(IndexedCase):
    def run_beats(self, *argv):
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers())
        args, out = parser.parse_args(["beats", *map(str, argv)]), io.StringIO()
        with contextlib.redirect_stdout(out):
            return args.func(args), out.getvalue()

    def test_a_bad_id_or_group_is_refused_before_any_project_is_read(self):
        out = self.tmp / "out"
        rc, text = self.run_beats("place", self.tmp / "none.logicx", "ffffff", "--out", out, "--track", "Inst 1", "--bar", 1, "--db", self.db)
        self.assertEqual((rc, "ffffff" in text), (1, True), text)
        rc, text = self.run_beats("compose", self.tmp / "none.logicx", "--out", out, "--track", "Inst 1", "--group", "Kit", "--db", self.db)
        self.assertEqual((rc, text.startswith("  2 groups match 'Kit'")), (1, True), text)
        rc, text = self.run_beats("generate", self.tmp / "none.logicx", "--out", out, "--track", "Inst 1", "--bar", 0,
                                  "--meter", "4/4", "--bars", 4, "--db", self.db)
        self.assertEqual((rc, text), (2, "  --bar 0: bars start at 1\n"))
        for argv, message in ((("--meter", "4/5", "--bars", 4), "bad meter '4/5': N/D with D a power of two"),
                              (("--meter", "4/4", "--bars", 4, "--category", "Polka"), "no beat bars in the index for category 'Polka', meter 4/4")):
            rc, text = self.run_beats("generate", self.tmp / "none.logicx", "--out", out, "--track", "Inst 1", "--bar", 1, "--db", self.db, *argv)
            self.assertEqual((rc, text.startswith(f"  {message}")), (1, True), text)
        self.assertFalse(out.exists())


class DefaultDbTest(unittest.TestCase):
    """`logic beats` and `groovebin index` must land on one file. groovebin owns the rule; this
    pins that we hand it the variable rather than resolving it ourselves, empty reading as unset
    (`bin/run` sources `.env`, where an optional key carries no value)."""

    def db(self, value=None):
        from logicxkit.logic._beats_cmd import default_db
        env = {k: v for k, v in os.environ.items() if k == "HOME"}    # the expected paths read it
        if value is not None:
            env["XDG_CACHE_HOME"] = value
        with mock.patch.dict("os.environ", env, clear=True):
            return default_db()

    def test_the_cache_root_is_groovebins_own_with_an_empty_value_read_as_unset(self):
        home = Path.home() / ".cache" / "groovebin" / "library.sqlite"
        for value, want in ((None, home), ("", home), ("/cache-root", Path("/cache-root/groovebin/library.sqlite")),
                            ("~/elsewhere", Path.home() / "elsewhere" / "groovebin" / "library.sqlite")):
            with self.subTest(value):
                self.assertEqual(self.db(value), want)

    def test_it_is_the_path_groovebin_itself_would_use(self):
        from groovebin.library import default_db as groovebins
        self.assertEqual(self.db("/cache-root"), groovebins("/cache-root"))


if __name__ == "__main__":
    unittest.main()
