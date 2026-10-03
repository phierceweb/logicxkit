"""A region's event lines as a groovebin Part and back, and the `logic midi` edit specs, without
a real file. The arithmetic is groovebin's; what is tested here is the adapter."""

import re
import struct
import unittest

import _paths  # noqa: F401
from groovebin import transforms as gt
from groovebin.events import Event, Note
from groovebin.song import Part
from logicxkit.logic._edit import CommandError
from logicxkit.logic._midi_edit_cmd import Edit, parse
from logicxkit.logic.services.song.events import BAR_ONE, LINE, PPQ
from logicxkit.logic.services.midi.midi_edit import (edit, from_part, join, meter_map, remap, require_no_poly_aftertouch,
                                                split, tick, to_part)
from logicxkit.logic.services.midi.midi_write import note_lines
from logicxkit.logic.services.song.signature import Meter, TimeSignature

END = bytes.fromhex("f1000000ffffff3f0000000000000000")


def note(at: int, pitch: int = 60, velocity: int = 80, length: int = 240):
    head, ext = note_lines(tick=at, pitch=pitch, velocity=velocity, length=length, channel=1)
    return head, (ext,)


def head(status: int, at: int, d2: int = 0, d1: int = 0) -> bytes:
    h = bytearray(LINE)
    h[0], h[11], h[12], h[15] = status, d2, d1, 0x01
    struct.pack_into("<I", h, 4, at)
    return bytes(h)


def controller(at: int, number: int = 1, value: int = 64):
    ext = bytearray(LINE)
    ext[7] = 0xBB
    return head(0xB0, at, value, number), (bytes(ext),)


def program(at: int, number: int = 0):
    return head(0xC0, at, 0, number), ()


def bend(at: int):
    return head(0xE0, at, 0x40, 0), ()


def summary(lines):
    return [(h[0] & 0xF0, tick(h), h[12], h[11], struct.unpack_from("<I", ls[0], 12)[0] if h[0] & 0xF0 == 0x90 else None)
            for h, ls in lines]


class SplitJoinTest(unittest.TestCase):
    def test_a_payload_round_trips_byte_for_byte(self):
        lines = [program(BAR_ONE), controller(BAR_ONE), note(BAR_ONE), bend(BAR_ONE), note(BAR_ONE + 960, 62)]
        rest = END + b"\x07" * LINE
        payload = join(lines, rest)
        got, tail = split(payload)
        self.assertEqual((got, tail), (lines, rest))
        self.assertEqual(join(got, tail), payload)

    def test_an_empty_sequence_is_only_its_end(self):
        self.assertEqual(split(END), ([], END))

    def test_a_continuation_line_before_any_event_is_refused(self):
        with self.assertRaisesRegex(ValueError, "continuation"):
            split(controller(BAR_ONE)[1][0] + END)


class PartTest(unittest.TestCase):
    LINES = [note(BAR_ONE - 100, 40), program(BAR_ONE, 5), controller(BAR_ONE, 7, 100), note(BAR_ONE, 60, 90, 480),
             bend(BAR_ONE), note(BAR_ONE + 960, 62, 70, 240)]

    def test_every_field_reads_into_the_part_and_the_lines_come_back_byte_for_byte(self):
        part = to_part(self.LINES)
        self.assertEqual([(n.tick, n.length, n.channel, n.pitch, n.velocity) for n in part.notes],
                         [(-100, 240, 1, 40, 80), (0, 480, 1, 60, 90), (960, 240, 1, 62, 70)])
        self.assertEqual([(e.tick, e.kind, e.data) for e in part.events],
                         [(0, "program", b"\xc0\x05"), (0, "control", b"\xb0\x07\x64"), (0, "bend", b"\xe0\x00\x40")])
        self.assertEqual(from_part(part), self.LINES)

    def test_an_edit_rewrites_only_the_fields_it_changed(self):
        out = edit([controller(BAR_ONE, 7, 100), note(BAR_ONE, 60)], lambda p: gt.transpose(p, 5))
        self.assertEqual(summary(out), [(0xB0, BAR_ONE, 7, 100, None), (0x90, BAR_ONE, 65, 80, 240)])
        self.assertEqual(out[0], controller(BAR_ONE, 7, 100))

    def test_a_note_made_from_nothing_becomes_logics_two_lines_and_an_event_is_refused(self):
        part = Part(PPQ, (Note(960, 0, 2, 64, 100),), ())
        (h, ls), = from_part(part)
        self.assertEqual((h[0], tick(h), h[12], h[11], struct.unpack_from("<I", ls[0], 12)[0]), (0x91, BAR_ONE + 960, 64, 100, 1))
        with self.assertRaisesRegex(ValueError, "new control event is unmeasured"):
            from_part(Part(PPQ, (), (Event(0, b"\xb0\x01\x40"),)))

    def test_a_tick_outside_the_sequence_is_refused(self):
        with self.assertRaisesRegex(ValueError, "before the start of the sequence"):
            edit([note(100)], lambda p: gt.shift(p, -101))
        with self.assertRaisesRegex(ValueError, "past the end of the sequence"):
            edit([note(BAR_ONE)], lambda p: gt.shift(p, 0x3FFFFFFF))

    def test_an_unmeasured_kind_beside_others_at_one_tick_is_refused(self):
        aftertouch = (head(0xA0, BAR_ONE, 10, 60), ())
        with self.assertRaisesRegex(ValueError, "0xa0"):
            from_part(to_part([note(BAR_ONE), aftertouch]))
        self.assertEqual(from_part(to_part([aftertouch, note(BAR_ONE + 1)])), [aftertouch, note(BAR_ONE + 1)])

    def test_same_tick_order_is_program_controller_notes_low_to_high_bend(self):
        lines = [note(BAR_ONE, 64), bend(BAR_ONE), note(BAR_ONE, 60, velocity=90), controller(BAR_ONE),
                 note(BAR_ONE, 60, velocity=70), program(BAR_ONE), note(BAR_ONE + 1, 30)]
        self.assertEqual([(s[0], s[2], s[3]) for s in summary(from_part(to_part(lines)))],
                         [(0xC0, 0, 0), (0xB0, 1, 64), (0x90, 60, 90), (0x90, 60, 70), (0x90, 64, 80), (0xE0, 0, 0x40),
                          (0x90, 30, 80)])


class AftertouchTest(unittest.TestCase):
    def test_a_pitch_edit_refuses_polyphonic_aftertouch(self):
        lines = [note(BAR_ONE, 60), (head(0xA0, BAR_ONE + 10, 10, 60), ())]
        for what in ("a transpose", "a delete"):
            with self.assertRaisesRegex(ValueError, f"polyphonic aftertouch.*{what}"):
                require_no_poly_aftertouch(lines, what)
        with self.assertRaisesRegex(ValueError, "polyphonic aftertouch"):
            remap(lines, "gm", "addictive-drums-2")


class QuantizeTest(unittest.TestCase):
    """The grid counts from the song's bar lines: Logic's signatures folded onto groovebin's map."""

    def test_the_grid_counts_from_each_bar_line_after_a_meter_change(self):
        m = Meter([TimeSignature(960, 3, 4), TimeSignature(BAR_ONE + 2880, 4, 4)])      # bar 2 at 41280
        meters = meter_map(m)
        self.assertEqual(meters.changes, ((0, 3, 4), (2880, 4, 4)))
        (h, _ls), = edit([note(BAR_ONE + 3000)], lambda p: gt.quantize(p, 3840, meters))      # 120 into bar 2
        self.assertEqual(tick(h), BAR_ONE + 2880)
        region = BAR_ONE + 2880
        (h, _ls), = edit([note(BAR_ONE + 1500)], lambda p: gt.quantize(p, 1920, meters, start=region - BAR_ONE))
        self.assertEqual(tick(h), BAR_ONE + 1920)

    def test_a_note_snapping_before_the_region_start_is_refused(self):
        meters = meter_map(Meter([TimeSignature(0, 4, 4)]))
        with self.assertRaisesRegex(ValueError, "before the part's start"):
            edit([note(BAR_ONE + 10)], lambda p: gt.quantize(p, 960, meters, start=100))


class RemapTest(unittest.TestCase):
    def test_pitches_translate_and_the_unmapped_are_counted_and_kept(self):
        lines, unmapped = remap([note(BAR_ONE, 42), note(BAR_ONE, 60), note(BAR_ONE, 60)], "gm", "addictive-drums-2")
        self.assertEqual(([h[12] for h, _ls in lines], dict(unmapped)), ([49, 60, 60], {60: 2}))


class SpecTest(unittest.TestCase):
    def test_each_shape(self):
        specs = [("transpose", "1=-12"), ("velocity", "2=0.8"), ("velocity", "2=+10"), ("velocity", "2=-10"),
                 ("move", "3=240"), ("delete", "4"), ("delete", "4:36"), ("quantize", "5=1/16"),
                 ("copy-region", "6=Inst 1:9"), ("copy-notes", "7=5.5"), ("copy-notes", "7=Keys: 2:5")]
        self.assertEqual(parse(specs), [
            Edit("transpose", 1, -12), Edit("velocity", 2, (0.8, 0)), Edit("velocity", 2, (1.0, 10)),
            Edit("velocity", 2, (1.0, -10)), Edit("move", 3, 240), Edit("delete", 4, None), Edit("delete", 4, 36),
            Edit("quantize", 5, 240), Edit("copy-region", 6, ("Inst 1", 9.0)), Edit("copy-notes", 7, (None, 5.5)),
            Edit("copy-notes", 7, ("Keys: 2", 5.0))])

    def test_a_bad_spec_names_the_shape(self):
        for flag, spec, shape in [("transpose", "1", "N=SEMITONES"), ("transpose", "0=3", "N=SEMITONES"),
                                  ("velocity", "1=-0.5", "N=SCALE|N=+OFFSET"), ("velocity", "1=", "N=SCALE"),
                                  ("move", "x=3", "N=TICKS"), ("delete", "1:200", "N[:PITCH]"),
                                  ("quantize", "1=1/12", "N=1/16"), ("quantize", "1=2/16", "N=1/16"),
                                  ("copy-region", "1=9", "N=TRACK:BAR"), ("copy-notes", "1=Inst 1:x", "N=[TRACK:]BAR"),
                                  ("velocity", "1=1e308", "N=SCALE"), ("velocity", "1=128", "N=SCALE"),
                                  ("velocity", "1=+128", "N=SCALE"), ("velocity", "1=-9" + "9" * 400, "N=SCALE")]:
            with self.subTest(spec), self.assertRaisesRegex(CommandError, re.escape(f"bad --{flag} '{spec}': {shape}")):
                parse([(flag, spec)])


class ChannelEditTest(unittest.TestCase):
    """A note read from a file keeps its own lines; a channel edit has to reach the status byte."""

    def test_a_tagged_notes_channel_lands_in_the_status_byte(self):
        from dataclasses import replace
        from logicxkit.logic.services.midi.midi_edit import from_part, to_part
        from logicxkit.logic.services.midi.midi_write import note_lines
        head, ext = note_lines(tick=38400, pitch=60, velocity=100, length=240, channel=1)
        part = to_part([(head, (ext,))])
        moved = replace(part, notes=tuple(replace(n, channel=5) for n in part.notes))
        (new_head, _ls), = from_part(moved)
        self.assertEqual(new_head[0] & 0x0F, 4)
        self.assertEqual(new_head[0] & 0xF0, head[0] & 0xF0)
        self.assertEqual([n.channel for n in to_part(from_part(moved)).notes], [5])


class NoteOffLineTest(unittest.TestCase):
    def test_a_note_off_line_is_refused_by_name(self):
        from logicxkit.logic.services.midi.midi_edit import to_part
        off = head(0x80, 38400, 0, 60)
        with self.assertRaises(ValueError) as e:
            to_part([(off, ())])
        self.assertIn("note-off line (0x80)", str(e.exception))


if __name__ == "__main__":
    unittest.main()
