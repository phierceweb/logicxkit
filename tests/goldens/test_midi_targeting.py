"""Which region a note goes into: the one on the track whose span holds the note's tick, chosen
the same way from the service and from `logic midi --note`."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.cli import main
from logicxkit.logic.services.arrange.environment import rename_track
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.midi.midi_write import add_note, add_region
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logicx import project_data

KEY = "midi-empty-region-logic"
BAR = 3840


def _note(data: bytes, bar: float, **kw) -> bytes:
    return add_note(data, track="Inst 1", tick=round(BAR_ONE + (bar - 1) * BAR), pitch=60, velocity=100, length=240, **kw)


@_goldens.needs(KEY)
class ServiceTest(unittest.TestCase):
    def setUp(self):
        base = project_data(_goldens.path(KEY))                   # one one-bar region at bar 3
        self.two, _ = add_region(base, track="Inst 1", start=BAR_ONE + 4 * BAR, length=2 * BAR, name="later")

    def test_each_note_goes_to_the_region_holding_its_tick(self):
        out = _note(_note(self.two, 3.5), 6.25)
        self.assertEqual({r.name: [e.tick for e in r.events] for r in read_midi(out)},
                         {"Inst 1": [BAR_ONE + 2 * BAR + 1920], "later": [BAR_ONE + 5 * BAR + 960]})

    def test_a_tick_outside_every_region_names_the_regions_in_bars(self):
        for bar in (2, 4, 7):                                     # before, between, at the end
            with self.subTest(bar=bar), self.assertRaises(ValueError) as caught:
                _note(self.two, bar)
            msg = str(caught.exception)
            self.assertIn(f"bar {bar}", msg)
            self.assertIn("'Inst 1' at bar 3 for 1 bar(s)", msg)
            self.assertIn("'later' at bar 5 for 2 bar(s)", msg)
            self.assertNotIn("start", msg)

    def test_overlapping_regions_are_named_not_guessed(self):
        out, _ = add_region(self.two, track="Inst 1", start=BAR_ONE + 5 * BAR, length=BAR, name="over")
        with self.assertRaisesRegex(ValueError, r"bar 6\.5 .*'later' at bar 5.*'over' at bar 6"):
            _note(out, 6.5)

    def test_region_start_still_picks_one(self):
        out, _ = add_region(self.two, track="Inst 1", start=BAR_ONE + 5 * BAR, length=BAR, name="over")
        out = _note(out, 6.5, region_start=BAR_ONE + 5 * BAR)
        self.assertEqual({r.name: len(r.events) for r in read_midi(out)}, {"Inst 1": 0, "later": 0, "over": 1})
        with self.assertRaisesRegex(ValueError, "no MIDI region on 'Inst 1' starts at tick 1"):
            _note(out, 3, region_start=1)


@_goldens.needs(KEY)
class SharedNameTest(unittest.TestCase):
    """Two tracks named alike: the regions of both are candidates, and only a real overlap refuses."""

    def setUp(self):
        self.base = project_data(_goldens.path(KEY))
        self.audio = next(t["object_id"] for t in read_tracks(self.base) if t["name"] == "Audio 2")

    def test_the_one_holding_the_tick_takes_the_note(self):
        out = _note(rename_track(self.base, self.audio, "Inst 1"), 3.5)
        self.assertEqual([(r.name, [e.tick for e in r.events]) for r in read_midi(out)], [("Inst 1", [BAR_ONE + 2 * BAR + 1920])])

    @_goldens.needs("sessionplayer-track-logic")
    def test_regions_on_both_holding_the_tick_are_named(self):
        from logicxkit.logic.services.project.project import project_metadata
        p = _goldens.path("sessionplayer-track-logic")                # two instrument tracks
        base, count = project_data(p), project_metadata(p).get("tracks")
        rows = [t for t in read_tracks(base, count) if (t["label"] or "").startswith("Inst ")]
        other, named = rows[-1], next(t for t in rows if t["name"] != rows[-1]["name"])
        data, _ = add_region(base, track=other["name"], start=BAR_ONE + 2 * BAR, length=BAR, name="twin", track_count=count)
        with self.assertRaisesRegex(ValueError, rf"MIDI regions on '{named['name']}': .*'Inst 1' at bar 3.*'twin' at bar 3"):
            add_note(rename_track(data, other["object_id"], named["name"]), track=named["name"], tick=BAR_ONE + 2 * BAR + 1920,
                     pitch=60, velocity=100, length=240, track_count=count)

    def test_a_label_picks_the_instrument_track_a_new_region_goes_on(self):
        shared = rename_track(self.base, self.audio, "Inst 1")
        with self.assertRaisesRegex(ValueError, r"2 tracks named 'Inst 1'; say which: .*Inst 1 \(Audio 2\)"):
            add_region(shared, track="Inst 1", start=BAR_ONE + 8 * BAR, length=BAR)
        out, report = add_region(shared, track="Inst 1 (Inst 1)", start=BAR_ONE + 8 * BAR, length=BAR, name="picked")
        self.assertNotEqual(report["object_id"], self.audio)
        self.assertIn("picked", [r.name for r in read_midi(out)])
        out, report = add_region(shared, track="Inst 1 (Inst 1)", start=BAR_ONE + 8 * BAR, length=BAR)
        self.assertEqual(report["name"], "Inst 1")

    def test_no_such_track(self):
        with self.assertRaisesRegex(ValueError, "no track named 'Nope'"):
            add_note(self.base, track="Nope", tick=BAR_ONE, pitch=60, velocity=100, length=240)


def run(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["logic", "midi", *map(str, argv)])
    return rc, buf.getvalue()


@_goldens.needs(KEY)
class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _written(self) -> bytes:
        (data_file,) = self.out.rglob("Alternatives/*/ProjectData")
        return data_file.read_bytes()

    def test_notes_on_a_track_with_two_regions_land_by_bar(self):
        rc, text = run(_goldens.path(KEY), "--out", self.out, "--region", "Inst 1:5:2:later",
                       "--note", "Inst 1:3.5:60:80:240", "--note", "Inst 1:6:64:100:480")
        self.assertEqual(rc, 0, text)
        self.assertEqual({r.name: [e.pitch for e in r.events] for r in read_midi(self._written())},
                         {"Inst 1": [60], "later": [64]})

    def test_a_note_outside_every_region_exits_1_naming_them(self):
        rc, text = run(_goldens.path(KEY), "--out", self.out, "--note", "Inst 1:8:60:80:240")
        self.assertEqual(rc, 1, text)
        self.assertIn("'Inst 1' at bar 3 for 1 bar(s)", text)
        self.assertNotIn("Traceback", text)
        self.assertEqual(list(self.out.rglob("ProjectData")), [])


if __name__ == "__main__":
    unittest.main()
