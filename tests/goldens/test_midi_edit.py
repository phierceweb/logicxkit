"""MIDI edits on Logic's own saves of a blank project: a region transposed, quantized and
merged in place, a region copied to another bar, and `logic midi` doing it on a copy."""

import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import _goldens
from logicxkit.cli import main
from logicxkit.logic.services.events import BAR_ONE
from logicxkit.logic.services.stream import HEADER, project_records, reassemble
from logicxkit.logic.services.integrity import regressions
from logicxkit.logic.services.midi import ENTRY_TICK_AT, read_midi
from groovebin import transforms as gt
from logicxkit.logic.services.midi_edit import (_located, _written, copy_notes, copy_region, edit, edit_region, meter_map,
                                                to_part)
from logicxkit.logic.services.midi_write import _place_entry, add_region, entry_tick
from logicxkit.logic.services.recbuild import rec
from logicxkit.logic.services.regions import ENTRY, entry_offsets, song_container
from logicxkit.logic.services.signature import meter
from logicxkit.logic.services.tracklist import arrange_run
from logicxkit.logic.services.validate import validate_project
from logicxkit.logicx import project_data

TWO, RESAVE, LOOPED, NAMES = "midi-two-notes-logic", "midi-write-resave-logic", "midi-region-looped-logic", "midi-names-resave-logic"
BAR = 3840


def at_tick(head: bytes, at: int) -> bytes:
    return head[:4] + at.to_bytes(4, "little") + head[8:]


def keys(region) -> list[tuple]:
    return [(e.kind, e.tick, e.channel, e.data1, e.data2, e.length) for e in region.events]


def aliased(data: bytes, region, bars: int) -> bytes:
    """A second song-container entry playing ``region``'s sequence, ``bars`` later."""
    records = project_records(data)
    song = song_container(records, arrange_run(records, None))
    payload = records[song.end].raw[HEADER:]
    off = next(o for o in entry_offsets(payload) if int.from_bytes(payload[o + 4:o + 8], "little") == entry_tick(region.start))
    entry = bytearray(payload[off:off + ENTRY])
    entry[ENTRY_TICK_AT:ENTRY_TICK_AT + 4] = entry_tick(region.start + bars * BAR).to_bytes(4, "little")
    out = [r.raw for r in records]
    out[song.end] = rec(b"qSvE", records[song.end].raw, _place_entry(payload, bytes(entry)))
    return reassemble(data, out)


@_goldens.needs(TWO)
class InPlaceTest(unittest.TestCase):
    def setUp(self):
        self.data = project_data(_goldens.path(TWO))
        (self.region,) = read_midi(self.data)
        self.meter = meter(self.data)

    def test_a_transposed_region_reads_back_with_only_its_pitches_moved(self):
        out = edit_region(self.data, self.region.slot, lambda lines: edit(lines, lambda p: gt.transpose(p, 3)))
        (got,) = read_midi(out)
        self.assertEqual([e.pitch for e in got.events], [p + 3 for p in _goldens.fact(TWO, "pitches")])
        self.assertEqual(got.events, [replace(e, data1=e.data1 + 3) for e in self.region.events])
        self.assertEqual((validate_project(out), regressions(self.data, out)), ([], []))

    def test_moved_off_the_grid_and_quantized_back(self):
        moved = edit_region(self.data, self.region.slot, lambda lines: edit(lines, lambda p: gt.shift(p, 100)))
        self.assertEqual([e.tick for e in read_midi(moved)[0].events], [t + 100 for t in _goldens.fact(TWO, "ticks")])
        out = edit_region(moved, self.region.slot, lambda lines: edit(lines, lambda p: gt.quantize(p, 960, meter_map(self.meter), start=self.region.start - BAR_ONE)))
        (got,) = read_midi(out)
        self.assertEqual(got.events, self.region.events)
        self.assertEqual((validate_project(out), regressions(self.data, out)), ([], []))

    def test_a_transposition_past_127_writes_nothing(self):
        with self.assertRaisesRegex(ValueError, "outside 0-127"):
            edit_region(self.data, self.region.slot, lambda lines: edit(lines, lambda p: gt.transpose(p, 127)))

    def test_an_event_pushed_to_the_region_end_is_refused_by_bar(self):
        with self.assertRaisesRegex(ValueError, r"^an event would move to bar 4, past the end of region 'Inst 1' on 'Inst 1' "
                                                r"\(bar 3 to 4\); moving an event out of its region is not supported$"):
            edit_region(self.data, self.region.slot, lambda lines: edit(lines, lambda p: gt.shift(p, BAR - 960)))

    def test_an_event_already_outside_the_region_may_move(self):
        _r, t, lines = _located(self.data, self.region.slot, None)
        (first, first_ls), (second, second_ls) = lines
        for hidden_at, (move, quantized) in {BAR_ONE + BAR + 110: (10, BAR), BAR_ONE - 100: (10, 0)}.items():
            with self.subTest(hidden_at=hidden_at):
                hidden = _written(self.data, t, sorted([(first, first_ls), (at_tick(second, hidden_at), second_ls)],
                                                       key=lambda line: int.from_bytes(line[0][4:8], "little")))
                pitch = self.region.events[1].pitch
                moved = edit_region(hidden, self.region.slot, lambda lines, move=move: edit(lines, lambda p: gt.shift(p, move)))
                self.assertIn(hidden_at + move - BAR_ONE, [e.tick - self.region.start for e in read_midi(moved)[0].events])
                out = edit_region(hidden, self.region.slot, lambda lines: edit(lines, lambda p: gt.quantize(p, 240, meter_map(self.meter), start=self.region.start - BAR_ONE)))
                self.assertIn((quantized, pitch), [(e.tick - self.region.start, e.pitch) for e in read_midi(out)[0].events])
                self.assertEqual((validate_project(out), regressions(hidden, out)), ([], []))
        with self.assertRaisesRegex(ValueError, "past the end of region"):
            edit_region(hidden, self.region.slot, lambda lines: edit(lines, lambda p: gt.shift(p, BAR)))

    def test_the_notes_merged_half_a_bar_later(self):
        out, report = copy_notes(self.data, self.region.slot, self.region.start + BAR // 2)
        (got,) = read_midi(out)
        placed = [replace(e, tick=e.tick + BAR // 2) for e in self.region.events]
        self.assertEqual(report["events"], 2)
        self.assertEqual(got.events, sorted(self.region.events + placed, key=lambda e: e.tick))
        self.assertEqual((validate_project(out), regressions(self.data, out)), ([], []))
        with self.assertRaisesRegex(ValueError, "past the end of region"):
            copy_notes(self.data, self.region.slot, self.region.start + 3 * BAR // 4)

    def test_an_unknown_slot_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no MIDI region plays sequence slot 3"):
            edit_region(self.data, 3, lambda lines: lines)


@_goldens.needs(RESAVE, LOOPED)
class CopyRegionTest(unittest.TestCase):
    def test_the_copy_holds_the_sources_events_shifted_by_the_bars(self):
        data = project_data(_goldens.path(RESAVE))
        (source,) = read_midi(data)
        out, report = copy_region(data, source.slot, source.track, source.start + 2 * BAR)
        first, copy = read_midi(out)
        self.assertEqual(first, source)
        self.assertEqual((copy.track, copy.name, copy.start, copy.loop, report["events"]),
                         (source.track, source.name, source.start + 2 * BAR, False, 2))
        self.assertEqual(copy.events, [replace(e, tick=e.tick + 2 * BAR) for e in source.events])
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_every_event_kind_copies_and_the_loop_flag_stays_behind(self):
        data = project_data(_goldens.path(LOOPED))
        (source,) = read_midi(data)
        out, report = copy_region(data, source.slot, "Inst 1", source.start + 4 * BAR)
        _, copy = read_midi(out)
        self.assertEqual((report["loop"], copy.loop, copy.track), (True, False, "Inst 1"))
        self.assertEqual(keys(copy), [(k, t + 4 * BAR, *rest) for k, t, *rest in keys(source)])
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_a_midi_region_goes_only_onto_a_software_instrument_track(self):
        data = project_data(_goldens.path(LOOPED))
        (source,) = read_midi(data)
        with self.assertRaisesRegex(ValueError, r"^'Audio 2' is an audio track \(Audio 2\); a MIDI region goes only "
                                                r"on a software instrument track$"):
            copy_region(data, source.slot, "Audio 2", source.start + 4 * BAR)
        with self.assertRaisesRegex(ValueError, r"^no MIDI region on 'Stereo Out' holds bar"):
            copy_notes(data, source.slot, source.start, track="Stereo Out")

    def test_a_source_two_regions_play_is_copied_but_not_edited(self):
        data = project_data(_goldens.path(RESAVE))
        (source,) = read_midi(data)
        alias = aliased(data, source, 4)
        self.assertEqual([r.slot for r in read_midi(alias)], [source.slot] * 2)
        out, report = copy_region(alias, source.slot, source.track, source.start + 8 * BAR)
        self.assertEqual((report["events"], [len(r.events) for r in read_midi(out)]), (2, [2, 2, 2]))
        target, _ = add_region(alias, track=source.track, start=source.start + 8 * BAR, length=BAR, name="target")
        out, report = copy_notes(target, source.slot, source.start + 8 * BAR)
        self.assertEqual((report["region"], [len(r.events) for r in read_midi(out)]), ("target", [2, 2, 2]))
        with self.assertRaisesRegex(ValueError, "2 regions play sequence slot"):
            edit_region(alias, source.slot, lambda lines: edit(lines, lambda p: gt.transpose(p, 1)))


@_goldens.needs(NAMES)
class TwoRegionsTest(unittest.TestCase):
    def test_one_regions_notes_merged_into_the_other_at_a_bar(self):
        data = project_data(_goldens.path(NAMES))
        keys_, pad = read_midi(data)
        out, report = copy_notes(data, keys_.slot, pad.start + BAR // 2)
        a, b = read_midi(out)
        self.assertEqual((a, report["region"]), (keys_, pad.name))
        moved = [replace(e, tick=e.tick - keys_.start + pad.start + BAR // 2) for e in keys_.events]
        self.assertEqual(b.events, sorted(pad.events + moved, key=lambda e: (e.tick, e.pitch)))
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_merge_keeps_lines_verbatim(self):
        data = project_data(_goldens.path(NAMES))
        _keys, pad = read_midi(data)
        out = edit_region(data, pad.slot, lambda lines: edit(lines, lambda p: gt.merge(p, to_part([]), 0)))
        self.assertEqual(out, data)


@_goldens.needs("midi-edits-ours", "midi-edits-resave-logic")
class LogicResavedEditsTest(unittest.TestCase):
    """Every edit flag and --remap on one copy, re-saved by Logic: the regions come back as written."""

    def test_logic_kept_every_region_and_event(self):
        ours, logic = (read_midi(project_data(_goldens.path(k))) for k in ("midi-edits-ours", "midi-edits-resave-logic"))
        key = lambda r: [r.name, r.start, [[e.tick, e.channel, e.pitch, e.velocity, e.length] for e in r.events]]  # noqa: E731
        self.assertEqual([key(r) for r in ours], _goldens.fact("midi-edits-ours", "regions"))
        self.assertEqual([key(r) for r in logic], [key(r) for r in ours])
        self.assertEqual(validate_project(project_data(_goldens.path("midi-edits-resave-logic"))), [])


def run(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["logic", "midi", *map(str, argv)])
    return rc, buf.getvalue()


@_goldens.needs(TWO)
class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        (self.source,) = read_midi(project_data(_goldens.path(TWO)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_edits_run_in_place_first_and_copies_last(self):
        rc, text = run(_goldens.path(TWO), "--out", self.out / "copy", "--copy-region", "1=Inst 1:5",
                       "--transpose", "1=2", "--move", "1=30", "--quantize", "1=1/16", "--velocity", "1=+100")
        self.assertEqual(rc, 0, text)
        self.assertIn("region 1 'Inst 1' on 'Inst 1': 2 note(s) transposed +2", text)
        self.assertIn("region 1 'Inst 1' copied to 'Inst 1' at bar 5: 2 event(s)", text)
        (project,) = (self.out / "copy").rglob("*.logicx")
        (data_file,) = project.rglob("Alternatives/*/ProjectData")
        first, copy = read_midi(data_file.read_bytes())
        edited = [replace(e, data1=e.data1 + 2, data2=127) for e in self.source.events]
        self.assertEqual(first.events, edited)
        self.assertEqual(copy.events, [replace(e, tick=e.tick + 2 * BAR) for e in edited])
        rc, text = run(project, "--track", "Inst 1")
        self.assertEqual(rc, 0, text)
        self.assertRegex(text, r"\n\s+1\s+Inst 1\s+'Inst 1'\s+bar\s+3.00.*\n(.*\n)*\s+2\s+Inst 1\s+'Inst 1'\s+bar\s+5.00")

    def test_drum_notes_remapped_by_number_and_by_track_and_named_in_the_listing(self):
        rc, text = run(_goldens.path(TWO), "--out", self.out / "copy", "--transpose", "1=-18", "--remap", "1=gm:addictive-drums-2",
                       "--track", "Inst 1", "--remap", "addictive-drums-2:gm")
        self.assertEqual(rc, 0, text)
        self.assertIn("region 1 'Inst 1' on 'Inst 1': 2 of 2 note(s) remapped gm -> addictive-drums-2", text)
        self.assertIn("region 1 'Inst 1' on 'Inst 1': 2 of 2 note(s) remapped addictive-drums-2 -> gm", text)
        (project,) = (self.out / "copy").rglob("*.logicx")
        (data_file,) = project.rglob("Alternatives/*/ProjectData")
        (got,) = read_midi(data_file.read_bytes())
        self.assertEqual(got.events, [replace(e, data1=e.data1 - 18) for e in self.source.events])
        rc, text = run(project, "--map", "gm")
        self.assertEqual(rc, 0, text)
        self.assertRegex(text, r"note  42 vel  79 len   960  Closed Hi Hat\n.*note  44 vel  79 len   960  Pedal Hi-Hat")

    def test_notes_with_no_counterpart_keep_their_pitch_and_are_counted(self):
        rc, text = run(_goldens.path(TWO), "--out", self.out / "copy", "--remap", "1=gm:addictive-drums-2")
        self.assertEqual(rc, 0, text)
        self.assertIn("0 of 2 note(s) remapped gm -> addictive-drums-2; no addictive-drums-2 counterpart, pitch kept: 60 x1, 62 x1", text)
        (project,) = (self.out / "copy").rglob("*.logicx")
        rc, text = run(project, "--track", "Nobody", "--out", self.out / "again", "--remap", "gm:addictive-drums-2")
        self.assertEqual((rc, "--remap: no MIDI region on track 'Nobody'" in text), (1, True), text)

    def test_a_bad_spec_or_number_exits_1_and_leaves_no_copy(self):
        rc, text = run(_goldens.path(TWO), "--out", self.out / "a", "--quantize", "1=1/12")
        self.assertEqual(rc, 1, text)
        self.assertIn("bad --quantize '1=1/12': N=1/16", text)
        rc, text = run(_goldens.path(TWO), "--out", self.out / "b", "--delete", "2")
        self.assertEqual(rc, 1, text)
        self.assertIn("--delete 2: the song has 1 MIDI region(s)", text)
        self.assertNotIn("Traceback", text)
        for flag, spec, said in [("--copy-region", "1=Inst 1:1e300", "--copy-region 1: bar 1e+300 is past the end of the sequence"),
                                 ("--copy-region", "1=Inst 1:1e308", "--copy-region 1: bar 1e+308 is past the end of the sequence"),
                                 ("--copy-notes", "1=-1e308", "--copy-notes 1: bar -1e+308 is before the start of the sequence"),
                                 ("--velocity", "1=1e308", "bad --velocity '1=1e308'"),
                                 ("--region", "Inst 1:1e300:1", "bad region bar '1e300': bar 1e+300 is past the end of the sequence"),
                                 ("--region", "Inst 1:nan:1", "bad region bar 'nan'"),
                                 ("--region", "Inst 1:5:1e300", "bad region length '1e300': past the end of the sequence"),
                                 ("--note", "Inst 1:3:60:100:99999999999", "a note's length of 99999999999 ticks does not fit")]:
            with self.subTest(spec):
                rc, text = run(_goldens.path(TWO), "--out", self.out / "c", flag, spec)
                self.assertEqual((rc, said in text, "logicxkit logic:" in text), (1, True, False), text)
        self.assertEqual(list(self.out.rglob("ProjectData")), [])


@_goldens.needs("regions-a10-midi-split-logic")
class SplitPieceTest(unittest.TestCase):
    def test_copy_notes_takes_only_what_the_region_plays(self):
        data = project_data(_goldens.path("regions-a10-midi-split-logic"))
        parent = read_midi(data)[0]
        self.assertEqual((len(parent.events), parent.played), (2, []))
        out, report = copy_notes(data, parent.slot, parent.start)
        self.assertEqual(report["events"], 0)
        self.assertEqual(read_midi(out), read_midi(data))

    def test_a_piece_playing_from_an_offset_is_refused_by_every_edit(self):
        data = project_data(_goldens.path("regions-a10-midi-split-logic"))
        piece = read_midi(data)[1]
        self.assertEqual(piece.offset, 960)
        for act in (lambda: copy_notes(data, piece.slot, BAR_ONE), lambda: copy_region(data, piece.slot, "Untitled", BAR_ONE + 20 * 3840),
                    lambda: edit_region(data, piece.slot, lambda have: have)):
            with self.assertRaisesRegex(ValueError, "plays its sequence from tick 960"):
                act()


if __name__ == "__main__":
    unittest.main()
