"""The transforms on Logic's own saves: each flag on the two-notes region against hand-computed
values, the seed repeat, a `--track` span leaving another track alone, the events refusal, and
aliases and split pieces refused as every edit refuses them."""

import contextlib
import importlib.util
import io
import random
import shutil
import tempfile
import unittest
from pathlib import Path

import _goldens
from groovebin.transforms import Operation, Range
from logicxkit.cli import main
from logicxkit.logic._edit import bump_track_count
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.midi.midi_edit import copy_region
from logicxkit.logic.services.midi.midi_write import add_note, add_region
from logicxkit.logic.services.midi.midi_transform import Transform, apply_transform
from logicxkit.logic.services.song.signature_write import add_meter_change
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

_spec = importlib.util.spec_from_file_location("goldens_midi_edit", Path(__file__).with_name("test_midi_edit.py"))
_midi_edit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_midi_edit)
aliased = _midi_edit.aliased

TWO, LOOPED, EDITS, SPLIT = "midi-two-notes-logic", "midi-region-looped-logic", "midi-edits-resave-logic", "regions-a10-midi-split-logic"
BEAT = 960


def run(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["logic", "midi", *map(str, argv)])
    return rc, buf.getvalue()


def notes(region) -> list[tuple[int, int, int, int]]:
    return [(e.tick - region.start, e.pitch, e.velocity, e.length) for e in region.events]


@_goldens.needs(TWO)
class ServiceTest(unittest.TestCase):
    """The two-notes region: pitches 60 and 62, velocity 79, a beat long, on beats 1 and 2 of bar 3."""

    def setUp(self):
        self.data = project_data(_goldens.path(TWO))
        (self.region,) = read_midi(self.data)
        self.assertEqual(notes(self.region), [(0, 60, 79, 960), (960, 62, 79, 960)])

    def transformed(self, select, *steps, seed=0):
        out, report = apply_transform(self.data, self.region, Transform(select, tuple(steps)), rng=random.Random(seed))
        (got,) = read_midi(out)
        self.assertEqual((validate_project(out), regressions(self.data, out)), ([], []))
        return notes(got), report

    def test_each_operation_against_a_hand_computed_answer(self):
        cases = {
            ("velocity", "set", 64): [(0, 60, 64, 960), (960, 62, 64, 960)],
            ("velocity", "add", -10): [(0, 60, 69, 960), (960, 62, 69, 960)],
            ("length", "mul", 0.5): [(0, 60, 79, 480), (960, 62, 79, 480)],
            ("velocity", "min", 100): [(0, 60, 100, 960), (960, 62, 100, 960)],
            ("velocity", "max", 50): [(0, 60, 50, 960), (960, 62, 50, 960)],
            ("pitch", "flip", 60): [(0, 60, 79, 960), (960, 58, 79, 960)],
            ("tick", "quantize", 3840): [(0, 60, 79, 960), (0, 62, 79, 960)],
            ("velocity", "crescendo", (40, 120)): [(0, 60, 40, 960), (960, 62, 120, 960)],
            ("velocity", "exp", 2.0): [(0, 60, 49, 960), (960, 62, 49, 960)],
            ("tick", "reverse", None): [(0, 62, 79, 960), (960, 60, 79, 960)],
            ("pitch", "reverse", None): [(0, 62, 79, 960), (960, 60, 79, 960)],
        }
        for (field, op, value), want in cases.items():
            with self.subTest(op=op, field=field):
                got, report = self.transformed({}, ("ops", [Operation(field, op, value)]))
                self.assertEqual(got, want)
                self.assertEqual((report.selected, report.notes), (2, 2))

    def test_random_repeats_with_its_seed_and_stays_in_range(self):
        a, _ = self.transformed({}, ("ops", [Operation("velocity", "random", 12), Operation("tick", "random", 30)]), seed=5)
        b, _ = self.transformed({}, ("ops", [Operation("velocity", "random", 12), Operation("tick", "random", 30)]), seed=5)
        c, _ = self.transformed({}, ("ops", [Operation("velocity", "random", 12), Operation("tick", "random", 30)]), seed=6)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        for (t, _p, v, _l), (t0, _q, v0, _m) in zip(a, notes(self.region), strict=True):
            self.assertLessEqual(abs(v - v0), 12)
            self.assertTrue(0 <= t - t0 <= 30 if t0 == 0 else abs(t - t0) <= 30)

    def test_the_selection_by_position_in_song_bars_and_by_pitch(self):
        got, report = self.transformed({"tick": Range(3.25, 3.25)}, ("ops", [Operation("velocity", "set", 1)]))
        self.assertEqual((got, report.selected), ([(0, 60, 79, 960), (960, 62, 1, 960)], 1))
        got, report = self.transformed({"tick": Range(3, 3)}, ("ops", [Operation("velocity", "set", 1)]))
        self.assertEqual((got, report.selected), ([(0, 60, 1, 960), (960, 62, 1, 960)], 2))
        got, report = self.transformed({"tick": Range(4, None)}, ("ops", [Operation("velocity", "set", 1)]))
        self.assertEqual((got, report.selected), (notes(self.region), 0))
        got, report = self.transformed({"pitch": Range(62, 62)}, ("preset", ("fixed-velocity", 90)))
        self.assertEqual((got, report.selected), ([(0, 60, 79, 960), (960, 62, 90, 960)], 1))

    def test_position_follows_the_signature_track_through_a_meter_change(self):
        """A 2/4 bar 2 puts bar 4 at the region's start: what was bar 3 in 4/4 is bar 4 now."""
        changed = add_meter_change(self.data, BAR_ONE + 3840, 2, 4)
        (region,) = read_midi(changed)
        for bar, count in ((3, 0), (4, 2)):
            with self.subTest(bar=bar):
                _, report = apply_transform(changed, region, Transform({"tick": Range(bar, bar)}, (("ops", [Operation("velocity", "set", 1)]),)),
                                            rng=random.Random(0))
                self.assertEqual(report.selected, count)
        _, report = self.transformed({"tick": Range(4, 4)}, ("ops", [Operation("velocity", "set", 1)]))
        self.assertEqual(report.selected, 0)

    def test_each_preset_against_a_hand_computed_answer(self):
        cases = {
            ("fixed-velocity", 90): [(0, 60, 90, 960), (960, 62, 90, 960)],
            ("velocity-limit", (20, 70)): [(0, 60, 70, 960), (960, 62, 70, 960)],
            ("crescendo", (40, 120)): [(0, 60, 40, 960), (960, 62, 120, 960)],
            ("reverse-position", None): [(0, 62, 79, 960), (960, 60, 79, 960)],
            ("reverse-pitch", None): [(0, 62, 79, 960), (960, 60, 79, 960)],
            ("reverse-pitch", 60): [(0, 60, 79, 960), (960, 58, 79, 960)],
            ("exp-velocity", 1.0): [(0, 60, 79, 960), (960, 62, 79, 960)],
            ("fixed-length", 240): [(0, 60, 79, 240), (960, 62, 79, 240)],
            ("max-length", 480): [(0, 60, 79, 480), (960, 62, 79, 480)],
            ("min-length", 1200): [(0, 60, 79, 1200), (960, 62, 79, 1200)],
            ("double-speed", None): [(0, 60, 79, 480), (480, 62, 79, 480)],
            ("legato", 100.0): [(0, 60, 79, 960), (960, 62, 79, 960)],
            ("legato", 50.0): [(0, 60, 79, 480), (960, 62, 79, 960)],
            ("staccato", 25.0): [(0, 60, 79, 240), (960, 62, 79, 240)],
        }
        for (name, value), want in cases.items():
            with self.subTest(name):
                got, _report = self.transformed({}, ("preset", (name, value)))
                self.assertEqual(got, want)

    def test_swing_puts_the_odd_sixteenth_late_as_logics_did(self):
        moved = apply_transform(self.data, self.region, Transform({}, (("ops", [Operation("tick", "add", 240)]),)), rng=random.Random(0))[0]
        (region,) = read_midi(moved)
        out, _ = apply_transform(moved, region, Transform({}, (("preset", ("swing", (0.6, 16))),)), rng=random.Random(0))
        self.assertEqual([e.tick - region.start for e in read_midi(out)[0].events], [288, 1248])

    def test_humanize_repeats_with_its_seed(self):
        a, _ = self.transformed({}, ("preset", ("humanize", (10, 8, 5))), seed=3)
        b, _ = self.transformed({}, ("preset", ("humanize", (10, 8, 5))), seed=3)
        self.assertEqual(a, b)
        self.assertNotEqual(a, notes(self.region))

    def test_a_note_pushed_past_the_region_end_is_refused_by_the_gate(self):
        got, _ = self.transformed({}, ("preset", ("half-speed", None)))
        self.assertEqual(got, [(0, 60, 79, 1920), (1920, 62, 79, 1920)])
        for steps in ((("preset", ("half-speed", None)), ("preset", ("half-speed", None))), (("ops", [Operation("tick", "add", 3000)]),)):
            with self.subTest(steps[-1][0]), self.assertRaisesRegex(ValueError, "past the end of region"):
                self.transformed({}, *steps)


@_goldens.needs(LOOPED)
class EventsTest(unittest.TestCase):
    def test_retiming_the_notes_refuses_a_region_holding_other_events(self):
        data = project_data(_goldens.path(LOOPED))
        (region,) = read_midi(data)
        self.assertGreater(sum(e.kind != "note" for e in region.events), 0)
        for steps in ((("ops", [Operation("tick", "reverse")]),), (("ops", [Operation("tick", "quantize", 240)]),),
                      (("preset", ("reverse-position", None)),), (("preset", ("swing", (0.6, 16))),)):
            with self.subTest(steps[0][0]), self.assertRaisesRegex(ValueError, "retiming the notes would leave them in place"):
                apply_transform(data, region, Transform({}, steps), rng=random.Random(0))
        out, report = apply_transform(data, region, Transform({}, (("preset", ("fixed-velocity", 50)),)), rng=random.Random(0))
        (got,) = read_midi(out)
        self.assertEqual([e for e in got.events if e.kind != "note"], [e for e in region.events if e.kind != "note"])
        self.assertEqual({e.velocity for e in got.events if e.kind == "note"}, {50})
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))


@_goldens.needs(EDITS, SPLIT)
class ScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_track_span_changes_its_regions_and_leaves_another_track_alone(self):
        """The golden's regions all sit on 'Inst 1'; a second instrument track gets a copy of the first."""
        data = project_data(_goldens.path(EDITS))
        first = read_midi(data)[0]
        anchor = next(t["object_id"] for t in read_tracks(data) if t["name"] == "Inst 1")
        data, _ = add_track(data, name="Inst 2", after=anchor, kind="instrument")
        data, _ = copy_region(data, first.slot, "Inst 2", first.start)
        bundle = self.out / "in" / "song.logicx"
        shutil.copytree(_goldens.path(EDITS), bundle)
        (bundle / "Alternatives" / "000" / "ProjectData").write_bytes(data)
        bump_track_count(bundle / "Alternatives" / "000" / "ProjectData", 1)
        regions = read_midi(data)
        self.assertEqual(sorted({r.track for r in regions}), ["Inst 1", "Inst 2"])
        rc, text = run(bundle, "--track", "Inst 1", "--out", self.out / "span", "--fixed-velocity", "33")
        self.assertEqual(rc, 0, text)
        (project,) = (self.out / "span").rglob("*.logicx")
        got = read_midi(next(project.rglob("Alternatives/*/ProjectData")).read_bytes())
        for before, after in zip(regions, got, strict=True):
            with self.subTest(track=before.track, region=before.name):
                if before.track == "Inst 1":
                    self.assertEqual({e.velocity for e in after.events if e.kind == "note"} - {33}, set())
                    self.assertIn(f"region {regions.index(before) + 1} {before.name!r} on 'Inst 1':", text)
                else:
                    self.assertEqual(after.events, before.events)
        self.assertEqual(text.count("note(s) selected"), 4)

    def test_the_selection_follows_the_notes_through_a_pass_that_reorders_them(self):
        """Keys holds 62, 64, 66, 67, 64, 72: the 62 and both 64s reversed among themselves, then set to velocity 1."""
        data = project_data(_goldens.path(EDITS))
        keys = read_midi(data)[0]
        self.assertEqual([e.pitch for e in keys.events], [62, 64, 66, 67, 64, 72])
        out, report = apply_transform(data, keys, Transform({"pitch": Range(62, 64)}, (("preset", ("reverse-position", None)),
                                                                                       ("preset", ("fixed-velocity", 1)))), rng=random.Random(0))
        got = read_midi(out)[0]
        self.assertEqual(report.selected, 3)
        self.assertEqual(sorted(e.pitch for e in got.events if e.velocity == 1), [62, 64, 64])
        self.assertEqual([(e.tick - got.start, e.pitch) for e in got.events if e.pitch in (62, 64)], [(0, 64), (4920, 64), (5880, 62)])
        self.assertEqual([e.velocity for e in got.events if e.pitch not in (62, 64)], [e.velocity for e in keys.events if e.pitch not in (62, 64)])

    def test_a_position_quantize_snaps_to_the_bar_grid_not_the_region_start(self):
        data = project_data(_goldens.path(EDITS))
        start = BAR_ONE + 5 * 3840 + 1920                                   # bar 6.5, off the bar grid
        data, _ = add_region(data, track="Inst 1", start=start, length=3840, name="off")
        data = add_note(data, track="Inst 1", tick=start + 100, pitch=60, velocity=80, length=240)
        region = next(r for r in read_midi(data) if r.name == "off")
        out, _ = apply_transform(data, region, Transform({}, (("ops", [Operation("tick", "quantize", 3840)]),)), rng=random.Random(0))
        (note,) = next(r for r in read_midi(out) if r.name == "off").events
        self.assertEqual(note.tick, BAR_ONE + 6 * 3840)                    # bar 7's line, 1920 into the region

    def test_numbers_select_regions_and_a_split_piece_or_an_alias_is_refused(self):
        rc, text = run(_goldens.path(SPLIT), "2", "--out", self.out / "piece", "--fixed-velocity", "33")
        self.assertEqual(rc, 1, text)
        self.assertIn("plays its sequence from tick 960", text)
        self.assertEqual(list((self.out / "piece").rglob("ProjectData")), [])
        data = project_data(_goldens.path(EDITS))
        first = read_midi(data)[0]
        alias = aliased(data, first, 20)
        with self.assertRaisesRegex(ValueError, "regions play sequence slot"):
            apply_transform(alias, first, Transform({}, (("preset", ("fixed-velocity", 33)),)), rng=random.Random(0))

    def test_the_command_reports_and_the_seed_is_printed_when_random(self):
        rc, text = run(_goldens.path(EDITS), "1", "--out", self.out / "a", "--select", "velocity>0", "--random-velocity", "3", "--seed", "random")
        self.assertEqual(rc, 0, text)
        self.assertRegex(text, r"(^|\n)  seed \d+\n")
        self.assertIn("note(s) selected; random-velocity 3", text)


@_goldens.needs("midi-transform-ours", "midi-transform-resave-logic")
class LogicResavedTransformsTest(unittest.TestCase):
    """One of every operation and preset on separate regions of one copy, re-saved by Logic: back as written."""

    def test_logic_kept_every_region_and_event(self):
        ours, logic = (read_midi(project_data(_goldens.path(k))) for k in ("midi-transform-ours", "midi-transform-resave-logic"))
        key = lambda r: [r.name, r.start, [[e.tick, e.channel, e.pitch, e.velocity, e.length] for e in r.events]]  # noqa: E731
        self.assertEqual(len(ours), 31)
        self.assertEqual([key(r) for r in ours], _goldens.fact("midi-transform-ours", "regions"))
        self.assertEqual([key(r) for r in logic], [key(r) for r in ours])
        self.assertEqual(validate_project(project_data(_goldens.path("midi-transform-resave-logic"))), [])
        swung = next(r for r in ours if r.name == "T swing")
        self.assertEqual([e.tick - swung.start for e in swung.events], [0, 288, 960, 1920])


if __name__ == "__main__":
    unittest.main()
