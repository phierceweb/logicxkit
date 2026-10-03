"""`logic midi --remap` specs, the listing's `--map`, and the write notice the edit flags earn,
without a real file."""

import contextlib
import io
import re
import unittest
from argparse import Namespace

import _paths  # noqa: F401
from logicxkit.logic import _capabilities as caps
from logicxkit.logic._edit import CommandError
from logicxkit.logic._midi_cmd import _describe
from logicxkit.logic._midi_edit_cmd import Edit, _apply, parse
from logicxkit.logic.cli import main
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.midi.midi_write import note_lines


def note(pitch: int):
    head, ext = note_lines(tick=BAR_ONE, pitch=pitch, velocity=80, length=240, channel=10)
    return head, (ext,)


class RemapSpecTest(unittest.TestCase):
    def test_a_region_number_or_every_region_on_the_track(self):
        self.assertEqual(parse([("remap", "3=addictive-drums-2:gm"), ("remap", "gm:addictive-drums-2")]),
                         [Edit("remap", 3, ("addictive-drums-2", "gm")), Edit("remap", None, ("gm", "addictive-drums-2"))])

    def test_a_bad_spec_names_the_shape(self):
        for spec in ("gm", "1=gm", "1=gm:xx", "gm:gm", "0=gm:addictive-drums-2", "1=", ""):
            with self.subTest(spec), self.assertRaisesRegex(CommandError, re.escape(f"bad --remap '{spec}': [N=]SRC:DST")):
                parse([("remap", spec)])

    def test_the_report_counts_what_had_no_counterpart(self):
        text, lines = _apply(Edit("remap", 1, ("gm", "addictive-drums-2")), None, None, [note(42), note(60), note(60)])
        self.assertEqual(text, "1 of 3 note(s) remapped gm -> addictive-drums-2; no addictive-drums-2 counterpart, pitch kept: 60 x2")
        self.assertEqual([h[12] for h, _ls in lines], [49, 60, 60])

    def test_notes_at_one_tick_rise_in_pitch_again_after_the_remap(self):
        _text, lines = _apply(Edit("remap", 1, ("gm", "addictive-drums-2")), None, None, [note(43), note(44)])
        self.assertEqual([h[12] for h, _ls in lines], [48, 65])

    def test_remap_without_a_number_needs_track_before_anything_is_read(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["midi", "nowhere.logicx", "--out", "somewhere", "--remap", "gm:addictive-drums-2"])
        self.assertEqual(rc, 2)
        self.assertIn("--track NAME", buf.getvalue())


class ListingTest(unittest.TestCase):
    def test_a_note_names_its_stroke_and_an_empty_note_a_dash(self):
        e = Namespace(kind="note", pitch=36, velocity=100, length=240)
        self.assertTrue(_describe(e, "addictive-drums-2").endswith("  Kick"))
        self.assertTrue(_describe(Namespace(**{**vars(e), "pitch": 127}), "gm").endswith("  -"))
        self.assertEqual(_describe(e), "note  36 vel 100 len   240")


class NoticeTest(unittest.TestCase):
    def test_no_midi_write_prints_the_derived_notice_now_that_the_edits_are_confirmed(self):
        for args in (Namespace(edits=[("remap", "gm:addictive-drums-2")], out="copy"), Namespace(edits=None, region=["Inst 1:3:1"], out="copy")):
            self.assertIsNone(caps.notice("midi", args))
        self.assertIsNone(caps.notice("drums-to-midi", Namespace(out="copy")))

if __name__ == "__main__":
    unittest.main()
