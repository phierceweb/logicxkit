"""MIDI events inside regions, read from Logic's own saves of a blank project: one note edited a
field at a time in the Event List, then a second note, a pitch bend, a controller and a program
change, then the region looped."""

import unittest
import _goldens
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logicx import project_data


def _region(key: str):
    (region,) = read_midi(project_data(_goldens.path(key)))
    return region


@_goldens.needs("midi-empty-region-logic", "midi-one-note-logic")
class RegionTest(unittest.TestCase):
    def test_an_empty_region_on_the_instrument_track(self):
        r = _region("midi-empty-region-logic")
        self.assertEqual((r.track, r.events), (_goldens.fact("midi-empty-region-logic", "track"), []))
        self.assertEqual(r.start_bar, _goldens.fact("midi-empty-region-logic", "start_bar"))

    def test_the_first_note(self):
        r = _region("midi-one-note-logic")
        (n,) = r.events
        self.assertEqual((n.kind, n.pitch, n.channel, n.length), ("note", _goldens.fact("midi-one-note-logic", "pitch"), 1, 240))
        self.assertEqual(n.bar, 3.0)


class NoteEditsTest(unittest.TestCase):
    def _note(self, key):
        (n,) = _region(key).events
        return n

    @_goldens.needs("midi-note-pitch-62-logic")
    def test_pitch(self):
        self.assertEqual(self._note("midi-note-pitch-62-logic").pitch, 62)

    @_goldens.needs("midi-note-velocity-79-logic")
    def test_velocity(self):
        self.assertEqual(self._note("midi-note-velocity-79-logic").velocity, 79)

    @_goldens.needs("midi-note-length-960-logic")
    def test_length(self):
        self.assertEqual(self._note("midi-note-length-960-logic").length, 960)

    @_goldens.needs("midi-note-beat-2-logic")
    def test_position(self):
        n = self._note("midi-note-beat-2-logic")
        self.assertEqual((n.tick, n.bar), (_goldens.fact("midi-note-beat-2-logic", "tick"), 3.25))

    @_goldens.needs("midi-note-channel-2-logic")
    def test_channel(self):
        self.assertEqual(self._note("midi-note-channel-2-logic").channel, 2)


@_goldens.needs("midi-two-notes-logic", "midi-pitch-bend-logic", "midi-controller-logic", "midi-program-change-logic")
class OtherEventsTest(unittest.TestCase):
    def test_two_notes_in_tick_order(self):
        r = _region("midi-two-notes-logic")
        self.assertEqual([(e.kind, e.pitch, e.tick) for e in r.events],
                         [("note", p, t) for p, t in zip(_goldens.fact("midi-two-notes-logic", "pitches"), _goldens.fact("midi-two-notes-logic", "ticks"), strict=True)])

    def test_pitch_bend_controller_and_program_change(self):
        bend = next(e for e in _region("midi-pitch-bend-logic").events if e.kind == "bend")
        self.assertEqual((bend.channel, bend.value), (1, 8192))
        cc = next(e for e in _region("midi-controller-logic").events if e.kind == "controller")
        self.assertEqual((cc.number, cc.value), (_goldens.fact("midi-controller-logic", "controller"), _goldens.fact("midi-controller-logic", "controller_value")))
        pc = next(e for e in _region("midi-program-change-logic").events if e.kind == "program")
        self.assertEqual(pc.program, _goldens.fact("midi-program-change-logic", "program"))
        self.assertEqual([e.kind for e in _region("midi-program-change-logic").events], ["program", "controller", "note", "bend", "note"])


@_goldens.needs("midi-region-unlooped-logic", "midi-region-looped-logic")
class LoopTest(unittest.TestCase):
    def test_the_loop_flag(self):
        self.assertFalse(_region("midi-region-unlooped-logic").loop)
        self.assertTrue(_region("midi-region-looped-logic").loop)


@_goldens.needs("midi-region-looped-logic", "midi-import-resave-logic")
class LogicImportedExportTest(unittest.TestCase):
    """The .mid `logic midi --export` wrote, imported by Logic into a new project: the events
    read back the same."""

    def test_the_events_survive_export_and_import(self):
        (ours,), (theirs,) = (read_midi(project_data(_goldens.path(k))) for k in ("midi-region-looped-logic", "midi-import-resave-logic"))
        keys = lambda r: [(e.kind, e.tick, e.channel, e.data1, e.data2, e.length) for e in r.events]  # noqa: E731
        self.assertEqual(keys(ours), keys(theirs))
        self.assertEqual(theirs.start, ours.start)


if __name__ == "__main__":
    unittest.main()
