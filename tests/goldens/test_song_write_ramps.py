"""Tempo ramps, a tempo change placed by bar in a three-four song, and the arrangement track Logic
makes for a section: ours against Logic's own saves and its re-saves. Skips without the corpus."""

import unittest
import _goldens
from logicxkit.logic.services.song import arrangement_write as w
from logicxkit.logic.services.song.arrangement import read_sections
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.song.tempo import read_tempo_events
from logicxkit.logicx import project_data


EDITS_MINE, EDITS_LOGIC = _goldens.path("section-edits-mine"), _goldens.path("section-edits-logic")
RAMP_LOGIC = _goldens.path("tempo-ramp-logic")
RAMP = _goldens.entry("tempo-ramp-logic") or {"facts": {}}


@unittest.skipUnless(EDITS_LOGIC and RAMP_LOGIC, "no Logic tempo curve save")
class RampTest(unittest.TestCase):
    """Logic's Tempo Operations curve, and ours laid over the same base."""

    def _ours(self):
        from logicxkit.logic.services.song.tempo_write import add_ramp
        f = RAMP["facts"]
        return add_ramp(project_data(EDITS_LOGIC), BAR_ONE + (f["start_bar"] - 1) * 3840, f["base_tempo"],
                        BAR_ONE + (f["end_bar"] - 1) * 3840, f["end_bpm"], per_bar=f["per_bar"])

    def test_reader_sees_logics_curve(self):
        got = read_tempo_events(project_data(RAMP_LOGIC))
        self.assertEqual(len(got), RAMP["facts"]["events"])
        self.assertEqual((got[1].position, got[-1].bpm), (BAR_ONE + (RAMP["facts"]["start_bar"] - 1) * 3840, float(RAMP["facts"]["end_bpm"])))

    def test_ours_matches_logics_ticks_and_tempos(self):
        ours, logic = read_tempo_events(self._ours()), read_tempo_events(project_data(RAMP_LOGIC))
        self.assertEqual([e.position for e in ours], [e.position for e in logic])
        for a, b in zip(ours, logic, strict=True):
            self.assertAlmostEqual(a.bpm, b.bpm, delta=0.0003)

    def test_ours_matches_logics_bytes_but_the_selection_and_stamps(self):
        from logicxkit.logic.services.song.events import events
        from logicxkit.logic.services.stream.stream import HEADER, project_records
        from logicxkit.logic.services.song.tempo import tempo_sequence
        ro, rl = project_records(self._ours()), project_records(project_data(RAMP_LOGIC))
        eo, el = (events(r[tempo_sequence(r)].raw[HEADER:]) for r in (ro, rl))
        self.assertEqual(len(eo), len(el))
        for a, b in zip(eo[1:], el[1:], strict=True):
            self.assertEqual(a.head[:15] + a.head[16:], b.head[:15] + b.head[16:])
            self.assertEqual(a.data[4:8], b.data[4:8])
            self.assertEqual((a.lines[1:], b.lines[1:]), ((), ()))

    def test_refuses_a_ramp_over_existing_events(self):
        from logicxkit.logic.services.song.tempo_write import add_ramp
        with self.assertRaises(ValueError):
            add_ramp(project_data(RAMP_LOGIC), BAR_ONE + 32 * 3840, 176, BAR_ONE + 40 * 3840, 140)


OUR_RAMP_MINE, OUR_RAMP_LOGIC = _goldens.path("our-ramp-mine"), _goldens.path("our-ramp-logic")


@unittest.skipUnless(OUR_RAMP_MINE and OUR_RAMP_LOGIC, "no re-save of our ramp")
class ReSavedRampTest(unittest.TestCase):
    """Logic's re-save of a ramp our writer laid down kept every event; only stamps moved."""

    def test_events_came_back_as_written(self):
        from logicxkit.logic.services.song.events import events
        from logicxkit.logic.services.stream.stream import HEADER, project_records
        from logicxkit.logic.services.song.tempo import tempo_sequence
        ours, logic = project_data(OUR_RAMP_MINE), project_data(OUR_RAMP_LOGIC)
        self.assertEqual([(e.position, e.bpm) for e in read_tempo_events(ours)], [(e.position, e.bpm) for e in read_tempo_events(logic)])
        ro, rl = project_records(ours), project_records(logic)
        eo, el = (events(r[tempo_sequence(r)].raw[HEADER:]) for r in (ro, rl))
        self.assertEqual([e.head for e in eo], [e.head for e in el])
        self.assertEqual([e.data[:8] + e.data[12:] for e in eo], [e.data[:8] + e.data[12:] for e in el])


@_goldens.needs("meter-3-4-logic")
class BarArgumentMeterTest(unittest.TestCase):
    def test_a_tempo_change_lands_on_the_bar_asked_for_in_three_four(self):
        import tempfile
        from argparse import Namespace
        from pathlib import Path
        from unittest import mock
        from logicxkit.logic._song import cmd_tempo
        from logicxkit.logic.services.song.signature import meter
        with tempfile.TemporaryDirectory() as tmp, mock.patch("builtins.print"):
            rc = cmd_tempo(Namespace(project=str(_goldens.path("meter-3-4-logic")), out=tmp,
                                     set=None, add=["9=151"], ramp=None, density=8))
            self.assertEqual(rc, 0)
            (data_file,) = Path(tmp).rglob("Alternatives/000/ProjectData")
            data = data_file.read_bytes()
        m = meter(data)
        self.assertEqual([m.bar(e.position) for e in read_tempo_events(data) if e.bpm == 151], [9.0])


@_goldens.needs("stack-folder-flattened-logic", "arrangement-first-section-logic")
class ArrangementTrackTest(unittest.TestCase):
    """Adding a section to a song without an arrangement track writes what Logic's own first
    section wrote, less what Logic adds on any load (the click's editor records, the
    transient triple, the MIDI port refresh)."""

    LOAD_NOISE = {(b"UCuA", 1957): 1, (b"UCuA", 867): 1, (b"qeSM", None): 1, (b"karT", 36): 1, (b"qSvE", 52): 1}
    UNSIZED = (b"gnoS", b"qeSM", b"MroC", b"OCuA")   # grow on any load, or carry the project's name

    @classmethod
    def _shape(cls, data: bytes):
        from collections import Counter
        from logicxkit.logic.services.stream.stream import project_records
        return Counter((r.tag, None if r.tag in cls.UNSIZED else len(r.raw)) for r in project_records(data))

    def test_the_section_and_its_track_read_like_logics(self):
        from collections import Counter
        from logicxkit.logic.services.stream.validate import validate_project
        base = project_data(_goldens.path("stack-folder-flattened-logic"))
        logic = project_data(_goldens.path("arrangement-first-section-logic"))
        want = [(s.name, s.start, s.length, s.kind) for s in read_sections(logic)]
        out = w.add_section(base, want[0][0], start=want[0][1], length=want[0][2], kind=want[0][3])
        self.assertEqual([(s.name, s.start, s.length, s.kind) for s in read_sections(out)], want)
        self.assertEqual(validate_project(out), [])
        self.assertEqual(self._shape(out), self._shape(logic) - Counter(self.LOAD_NOISE))


@_goldens.needs("arrangement-ours", "arrangement-resave-logic")
class LogicResavedArrangementTrackTest(unittest.TestCase):
    def test_logic_kept_the_made_track_and_its_section(self):
        ours, logic = (project_data(_goldens.path(k)) for k in ("arrangement-ours", "arrangement-resave-logic"))
        mine = [(s.name, s.start, s.length, s.kind) for s in read_sections(ours)]
        self.assertEqual([n for n, *_ in mine], _goldens.fact("arrangement-ours", "names"))
        self.assertEqual(mine, [(s.name, s.start, s.length, s.kind) for s in read_sections(logic)])


if __name__ == "__main__":
    unittest.main()
