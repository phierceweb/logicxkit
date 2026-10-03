"""groovebin patterns written into a public blank-born project: one region per placement, the
notes and lengths read back, the meter refusals, compose over the arrangement, a generated
phrase, and the commands on a copy."""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import _goldens
from _beats import BAR, GROUP, HAT, KICK, MAP, SNARE, STICKS, TOM, beat, index
from groovebin.events import Note
from groovebin.library.compose import group_patterns
from groovebin.library.generate import load_pool, phrase
from groovebin.library.pattern import pattern
from groovebin.library.search import find_group
from logicxkit.cli import main
from logicxkit.logic.services.midi.beats_compose import compose, plan
from logicxkit.logic.services.midi.beats_place import place, place_notes, place_phrase
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.midi.midi_edit import END_TICK
from logicxkit.logic.services.midi.midi_write import track_regions
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

TWO, WALTZ = "midi-two-notes-logic", "signature-meter-3-4-logic"
TRACK = "Inst 1"


def notes(region) -> list[tuple]:
    return [(e.tick - region.start, e.pitch, e.velocity, e.length, e.channel) for e in region.events]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.db = index(self.tmp)
        self.data = project_data(_goldens.path(TWO))

    def placed(self, out: bytes, name: str):
        (region,) = [r for r in read_midi(out) if r.name == name]
        (spans,) = [r for r in track_regions(out, TRACK) if r.name == name]
        self.assertEqual((validate_project(out), regressions(self.data, out)), ([], []))
        return region, spans.length


@_goldens.needs(TWO, WALTZ)
class PlaceTest(Case):
    def test_a_pattern_reads_back_on_its_bar_with_its_notes_and_length(self):
        out, report = place(self.data, pattern(beat(self.db, "Intro")), track=TRACK, bar=5, track_count=None)
        region, length = self.placed(out, "Intro")
        self.assertEqual((region.start, length, region.loop), (BAR_ONE + 4 * BAR, 2 * BAR, False))
        self.assertEqual(notes(region), [(0, KICK, 100, 480, 10), (1920, SNARE, 90, 240, 10), (3840, KICK, 100, 480, 10),
                                         (5760, SNARE, 110, 240, 10)])
        self.assertEqual((report["notes"], report["dropped"], report["bars"]), (4, 0, 2))
        self.assertEqual(read_midi(out)[0], read_midi(self.data)[0])

    def test_repeat_fills_one_region_back_to_back(self):
        out, _report = place(self.data, pattern(beat(self.db, "Verse 01")), track=TRACK, bar=9, track_count=None, repeat=3)
        region, length = self.placed(out, "Verse 01")
        self.assertEqual((region.start, length), (BAR_ONE + 8 * BAR, 3 * BAR))
        self.assertEqual([(t, p) for t, p, *_ in notes(region)],
                         [(k * BAR + t, p) for k in range(3) for t, p in ((0, KICK), (0, HAT), (1920, SNARE), (2880, HAT))])

    def test_gm_map_and_velocity_scale_with_the_unmapped_counted(self):
        out, report = place(self.data, pattern(beat(self.db, "Verse 02")), track=TRACK, bar=1, track_count=None,
                            velocity=0.5, remap_maps=(MAP, "gm"))
        region, _length = self.placed(out, "Verse 02")
        self.assertEqual([(t, p, v) for t, p, v, *_ in notes(region)], [(0, KICK, 60), (1920, SNARE, 50), (2880, STICKS, 25)])
        self.assertEqual(report["unmapped"], {STICKS: 1})
        out, _report = place(self.data, pattern(beat(self.db, "Verse 01")), track=TRACK, bar=1, track_count=None, remap_maps=(MAP, "gm"))
        self.assertEqual([p for _t, p, *_ in notes(self.placed(out, "Verse 01")[0])], [KICK, 42, SNARE, 42])

    def test_a_note_rounding_to_the_patterns_end_is_dropped_and_counted(self):
        out, report = place(self.data, pattern(beat(self.db, "tail", "Tails")), track=TRACK, bar=5, track_count=None, repeat=2)
        region, length = self.placed(out, "tail")
        self.assertEqual((length, [t for t, *_ in notes(region)], report["dropped"]), (2 * BAR, [0, BAR], 2))

    def test_place_notes_drops_past_the_region_end_and_never_lengthens(self):
        out, report = place_notes(self.data, track=TRACK, start_tick=BAR_ONE + 4 * BAR,
                                  notes=[Note(0, 100, 10, TOM, 90), Note(BAR, 100, 10, TOM, 90)],
                                  bars_ticks=BAR, name="Toms", track_count=None)
        region, length = self.placed(out, "Toms")
        self.assertEqual((length, len(region.events), report["dropped"]), (BAR, 1, 1))
        with self.assertRaisesRegex(ValueError, "runs past the end of the sequence"):
            place_notes(self.data, track=TRACK, start_tick=BAR_ONE, notes=[], bars_ticks=END_TICK - BAR_ONE, name="Far", track_count=None)
        out, _report = place_notes(self.data, track=TRACK, start_tick=BAR_ONE + 4 * BAR, notes=[], bars_ticks=BAR, name="Pad – é", track_count=None)
        self.placed(out, "Pad – é")

    def test_a_pattern_whose_meter_is_not_the_projects_is_refused(self):
        with self.assertRaisesRegex(ValueError, r"^the pattern's bar 1 is 4/4 but the song is 3/4 at bar 2$"):
            place(project_data(_goldens.path(WALTZ)), pattern(beat(self.db, "Intro")), track=TRACK, bar=2, track_count=None)
        with self.assertRaisesRegex(ValueError, r"^the pattern's bar 1 is 3/4 but the song is 4/4 at bar 1$"):
            place(self.data, pattern(beat(self.db, "Chorus")), track=TRACK, bar=1, track_count=None)


@_goldens.needs(TWO, WALTZ)
class ComposeTest(Case):
    def test_a_region_per_section_with_a_fill_on_its_last_bar(self):
        plans = plan(self.data, group_patterns(self.db, *find_group(self.db, GROUP)), fills=True)
        out, reports = compose(self.data, plans, track=TRACK, track_count=None)
        self.assertEqual([(r["name"], r["start"], r["length"]) for r in reports], [("Intro", BAR_ONE, 8 * BAR), ("Verse 01", BAR_ONE + 8 * BAR, 8 * BAR)])
        intro, _ = self.placed(out, "Intro")
        verse, _ = self.placed(out, "Verse 01")
        body = [(k * 2 * BAR + t, p) for k in range(4) for t, p in ((0, KICK), (1920, SNARE), (3840, KICK), (5760, SNARE))]
        fill = [(7 * BAR, TOM), (7 * BAR + 960, TOM), (7 * BAR + 1920, SNARE)]
        self.assertEqual([(t, p) for t, p, *_ in notes(intro)], body[:-2] + fill)
        self.assertEqual([(t, p) for t, p, *_ in notes(verse)][-5:], [(6 * BAR + 1920, SNARE), (6 * BAR + 2880, HAT)] + fill)
        self.assertEqual((plans[0].fill_bar, plans[1].fill_bar, plans[1].replaced), (8, 16, 4))

    def test_sections_in_a_meter_the_group_lacks_are_skipped(self):
        plans = plan(project_data(_goldens.path(WALTZ)), group_patterns(self.db, *find_group(self.db, GROUP)))
        self.assertEqual([p.skipped for p in plans], ["no Intro pattern in 3/4; the group's are 4/4",
                                                      "the section does not start on a bar line"])


@_goldens.needs(TWO)
class GenerateTest(Case):
    def test_a_phrase_reads_back_as_one_region_over_the_projects_bars(self):
        ph = phrase(load_pool(self.db, sig=(4, 4), category="rock", fills=True), bars=4, seed=7, fills=True)
        out, report = place_phrase(self.data, ph, track=TRACK, bar=3, track_count=None)
        region, length = self.placed(out, "Generated 7")
        self.assertEqual((region.start, length, len(region.events), report["notes"]), (BAR_ONE + 2 * BAR, 4 * BAR, len(ph.notes), len(ph.notes)))
        self.assertEqual(sorted((t, p, v, length) for t, p, v, length, _ch in notes(region)),
                         sorted((n.tick, n.pitch, n.velocity, max(1, n.length)) for n in ph.notes))
        with self.assertRaisesRegex(ValueError, r"^the phrase's bar 1 is 4/4 but the song is 3/4 at bar 1$"):
            place_phrase(project_data(_goldens.path(WALTZ)), ph, track=TRACK, bar=1, track_count=None)


@_goldens.needs("beats-place-generate-ours", "beats-place-generate-resave-logic", "beats-compose-ours", "beats-compose-resave-logic")
class LogicResavedTest(unittest.TestCase):
    def test_logic_kept_every_placed_composed_and_generated_region(self):
        for ours_key in ("beats-place-generate-ours", "beats-compose-ours"):
            with self.subTest(ours_key):
                ours, logic = (project_data(_goldens.path(k)) for k in (ours_key, ours_key.replace("-ours", "-resave-logic")))
                self.assertEqual((validate_project(ours), validate_project(logic)), ([], []))
                want = _goldens.fact(ours_key, "regions")
                for data in (ours, logic):
                    self.assertEqual([[r.name, r.start, [[e.tick, e.channel, e.pitch, e.velocity, e.length] for e in r.events]] for r in read_midi(data)], want)
                self.assertEqual({r.name for r in read_midi(logic)} - {TRACK}, {"Verse 02", "Generated 3"} if "place" in ours_key else {"Intro", "Verse 01"})


def run(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = main(["logic", "beats", *map(str, argv)])
    return rc, out.getvalue(), err.getvalue()


@_goldens.needs(TWO, WALTZ)
class CliTest(Case):
    def written(self, out: Path) -> bytes:
        (project,) = out.rglob("*.logicx")
        (data_file,) = project.rglob("Alternatives/*/ProjectData")
        return data_file.read_bytes()

    def test_place_on_a_copy(self):
        beat_id = beat(self.db, "Verse 02")["id"]
        rc, text, _err = run("place", _goldens.path(TWO), beat_id, "--out", self.tmp / "placed", "--track", TRACK, "--bar", 3,
                             "--repeat", 2, "--map", "gm", "--velocity", 0.5, "--db", self.db)
        self.assertEqual(rc, 0, text)
        self.assertIn(f"'{TRACK}' region 'Verse 02' at bar 3 for 2 bar(s): 6 note(s), slot ", text)
        self.assertIn(f"; remapped {MAP} -> gm, no gm counterpart, pitch kept: 75 x2", text)
        self.placed(self.written(self.tmp / "placed"), "Verse 02")

    def test_compose_and_generate_on_a_copy_and_the_refusals_leave_no_copy(self):
        rc, text, _err = run("compose", _goldens.path(TWO), "--out", self.tmp / "composed", "--track", TRACK, "--group", "test kit",
                             "--fills", "--db", self.db)
        self.assertEqual(rc, 0, text)
        self.assertRegex(text, r"Intro\s+bar 1-9\s+'Intro' \(\w+\) x4: 17 note\(s\), fill 'Fills 01' \(\w+\) on bar 8 in place of 2 note\(s\)")
        self.assertEqual([r.name for r in read_midi(self.written(self.tmp / "composed"))], ["Intro", TRACK, "Verse 01"])
        rc, text, _err = run("generate", _goldens.path(TWO), "--out", self.tmp / "generated", "--track", TRACK, "--bar", 5,
                             "--meter", "4/4", "--bars", 2, "--seed", 3, "--category", "rock", "--db", self.db)
        self.assertEqual(rc, 0, text)
        self.assertIn(f"seed 3: 2 bar(s) of 4/4 in {MAP}", text)
        self.assertIn("region 'Generated 3' at bar 5 for 2 bar(s)", text)
        self.placed(self.written(self.tmp / "generated"), "Generated 3")
        rc, text, _err = run("compose", _goldens.path(WALTZ), "--out", self.tmp / "waltz", "--track", TRACK, "--group", GROUP, "--db", self.db)
        self.assertEqual(rc, 1, text)
        self.assertIn(f"no section has a pattern in group '{GROUP}': nothing written", text)
        rc, text, _err = run("place", _goldens.path(WALTZ), beat(self.db, "Intro")["id"], "--out", self.tmp / "waltz", "--track", TRACK,
                             "--bar", 1, "--db", self.db)
        self.assertEqual((rc, text), (1, "  the pattern's bar 1 is 4/4 but the song is 3/4 at bar 1\n"))
        self.assertFalse((self.tmp / "waltz").exists())


if __name__ == "__main__":
    unittest.main()
