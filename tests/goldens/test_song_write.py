"""Section and tempo edits, checked by reading them back and holding them to the write gate.

The real-file part of tests/logic/test_song_write.py; skips without the owner's files."""

import unittest
import _goldens
import _paths
from logicxkit.logic.services import arrangement_write as w
from logicxkit.logic.services.arrangement import read_sections
from logicxkit.logic.services.events import BAR_ONE, PPQ
from logicxkit.logic.services.integrity import require_no_regression
from logicxkit.logic.services.tempo import project_tempo, read_tempo_events
from logicxkit.logic.services.tempo_write import set_tempo
from logicxkit.logicx import project_data
from _data import needs

MIXES = sorted((_paths.RESOURCES / "mixes").glob("*/*.logicx"))
SONG = next((p for p in MIXES if read_sections(project_data(p))), None)
RAMPED = next((p for p in MIXES if len(read_tempo_events(project_data(p))) > 1), None)
ADD_BASE = _goldens.path("sections-base")
ADD_LOGIC = _goldens.path("add-section-logic")
ADDED = _goldens.entry("add-section-logic") or {"facts": {}}
TEMPO_BASE = _goldens.path("add-section-logic")
TEMPO_LOGIC = _goldens.path("add-tempo-logic")
STEP = _goldens.entry("add-tempo-logic") or {"facts": {}}
OUR_ADDS_LOGIC = _goldens.path("our-adds-logic")
OURS = _goldens.entry("our-adds-logic") or {"facts": {}}


@unittest.skipUnless(SONG, "no resources mix with an arrangement")
class SectionEditTest(unittest.TestCase):
    def setUp(self):
        self.data = project_data(SONG)
        self.before = read_sections(self.data)

    def check(self, after):
        require_no_regression(self.data, after)
        return read_sections(after)

    def test_rename_rebuilds_the_name_plain(self):
        got = self.check(w.rename_section(self.data, 2, "Pre-Chorus"))
        self.assertEqual(got[1].name, "Pre-Chorus")
        self.assertEqual([s.start for s in got], [s.start for s in self.before])
        self.assertEqual([s.name for s in got[2:]], [s.name for s in self.before[2:]])

    def test_move_keeps_time_order(self):
        last = self.before[-1]
        got = self.check(w.move_section(self.data, len(self.before), last.start + 4 * PPQ))
        self.assertEqual(got[-1].start, last.start + 4 * PPQ)
        self.assertEqual(got[-1].name, last.name)

    def test_resize(self):
        got = self.check(w.resize_section(self.data, 1, 3 * 4 * PPQ))
        self.assertEqual((got[0].length, got[0].name), (3 * 4 * PPQ, self.before[0].name))

    def test_delete_leaves_the_others(self):
        got = self.check(w.delete_section(self.data, 2))
        self.assertEqual([s.name for s in got], [s.name for i, s in enumerate(self.before) if i != 1])

    def test_out_of_range_refused(self):
        with self.assertRaises(ValueError):
            w.rename_section(self.data, len(self.before) + 1, "x")
        with self.assertRaises(ValueError):
            w.resize_section(self.data, 1, 0)


@unittest.skipUnless(MIXES, "no resources mixes")
class TempoEditTest(unittest.TestCase):
    def test_single_tempo_song_moves_every_word(self):
        song = next(p for p in MIXES if len(read_tempo_events(project_data(p))) == 1)
        data = project_data(song)
        after = set_tempo(data, 123.5)
        require_no_regression(data, after)
        self.assertEqual(project_tempo(after), (123.5, 123.5))
        self.assertEqual([(e.position, e.bpm) for e in read_tempo_events(after)], [(BAR_ONE, 123.5)])

    @unittest.skipUnless(RAMPED, "no resources mix with tempo changes")
    def test_later_changes_and_the_shown_tempo_stay(self):
        data = project_data(RAMPED)
        shown, first = project_tempo(data)
        before = read_tempo_events(data)
        after = set_tempo(data, first + 1)
        require_no_regression(data, after)
        self.assertEqual(project_tempo(after), (shown, first + 1))
        got = read_tempo_events(after)
        self.assertEqual(got[0].bpm, first + 1)
        self.assertEqual(got[1:], before[1:])

    def test_range(self):
        with self.assertRaises(ValueError):
            set_tempo(project_data(MIXES[0]), 1000)


@unittest.skipUnless(ADD_BASE and ADD_LOGIC, "no Logic add-section pair")
@needs("logic", "section-text-12.3.1.json")
class AddSectionTest(unittest.TestCase):
    def test_matches_logics_own_add(self):
        from logicxkit.logic.services.arrangement import TEXT_TAG, section_sequence
        from logicxkit.logic.services.events import events
        from logicxkit.logic.services.insert import HEADER, project_records
        from logicxkit.logic.services.recbuild import slot_of
        base = project_data(ADD_BASE)
        f = ADDED["facts"]
        ours = w.add_section(base, f["name"], start=BAR_ONE + (f["start_bar"] - 1) * 3840, length=f["length_bars"] * 3840, kind=f["kind"])
        require_no_regression(base, ours)
        logic = project_data(ADD_LOGIC)
        self.assertEqual(read_sections(ours), read_sections(logic))
        ro, rl = project_records(ours), project_records(logic)
        slot = ADDED["facts"]["new_slot"]
        ko = next(k for k, r in enumerate(ro) if r.tag == TEXT_TAG and slot_of(r.raw) == slot)
        kl = next(k for k, r in enumerate(rl) if r.tag == TEXT_TAG and slot_of(r.raw) == slot)
        def masked(raw):                                    # +27 of the head: 0 on Logic's fresh record, 1 after any re-save
            return raw[:63] + raw[64:]
        self.assertEqual((ko, masked(ro[ko].raw)), (kl, masked(rl[kl].raw)))
        eo = events(ro[section_sequence(ro)].raw[HEADER:])[-1]
        el = events(rl[section_sequence(rl)].raw[HEADER:])[-1]
        self.assertEqual(eo.head[:15] + eo.lines[0] + eo.lines[1], el.head[:15] + el.lines[0] + el.lines[1])

    def test_slot_is_the_lowest_free_multiple_of_four(self):
        from logicxkit.logic.services.insert import project_records
        self.assertEqual(w.free_text_slot(project_records(project_data(ADD_BASE))), ADDED["facts"]["new_slot"])


@unittest.skipUnless(TEMPO_BASE and TEMPO_LOGIC, "no Logic add-tempo pair")
class AddTempoTest(unittest.TestCase):
    def test_reader_sees_logics_added_step(self):
        got = read_tempo_events(project_data(TEMPO_LOGIC))
        base_tempo = float(_goldens.fact("sections-base", "tempo"))
        self.assertEqual([(e.position, e.bpm) for e in got], [(BAR_ONE, base_tempo), (BAR_ONE + (STEP["facts"]["bar"] - 1) * 3840, float(STEP["facts"]["bpm"]))])

    def test_matches_logics_own_add(self):
        from logicxkit.logic.services.events import events
        from logicxkit.logic.services.insert import HEADER, project_records
        from logicxkit.logic.services.tempo import tempo_sequence
        from logicxkit.logic.services.tempo_write import add_tempo
        base = project_data(TEMPO_BASE)
        ours = add_tempo(base, BAR_ONE + (STEP["facts"]["bar"] - 1) * 3840, STEP["facts"]["bpm"])
        require_no_regression(base, ours)
        self.assertEqual([(e.position, e.bpm) for e in read_tempo_events(ours)], [(e.position, e.bpm) for e in read_tempo_events(project_data(TEMPO_LOGIC))])
        ro, rl = project_records(ours), project_records(project_data(TEMPO_LOGIC))
        eo, el = (events(r[tempo_sequence(r)].raw[HEADER:])[1] for r in (ro, rl))
        self.assertEqual(len(ro[tempo_sequence(ro)].raw), len(rl[tempo_sequence(rl)].raw))
        self.assertEqual(eo.head[4:15], el.head[4:15])            # tick and the 0x7f byte; +2 and +15 differ by design
        self.assertEqual(eo.data[:8], el.data[:8])                # the bpm word and `40 88`
        self.assertEqual((eo.lines[1:], el.lines[1:]), ((), ()))

    def test_refuses_a_second_event_on_the_same_tick(self):
        from logicxkit.logic.services.tempo_write import add_tempo
        with self.assertRaises(ValueError):
            add_tempo(project_data(TEMPO_BASE), BAR_ONE, 120)


@unittest.skipUnless(ADD_BASE and OUR_ADDS_LOGIC, "no re-save of our adds")
@needs("logic", "section-text-12.3.1.json")
class ReSavedAddsTest(unittest.TestCase):
    """Logic's re-save of a section and a tempo change our writers added."""

    def test_section_record_and_event_came_back_as_written(self):
        from logicxkit.logic.services.arrangement import TEXT_TAG, section_sequence
        from logicxkit.logic.services.events import BAR_ONE, events
        from logicxkit.logic.services.insert import HEADER, project_records
        from logicxkit.logic.services.recbuild import slot_of
        f = OURS["facts"]
        ours = w.add_section(project_data(ADD_BASE), f["section_name"], start=BAR_ONE + (f["section_bar"] - 1) * 3840, length=f["section_bars"] * 3840, kind=f["section_kind"])
        ro, rl = project_records(ours), project_records(project_data(OUR_ADDS_LOGIC))
        slot = ADDED["facts"]["new_slot"]
        to = next(r.raw for r in ro if r.tag == TEXT_TAG and slot_of(r.raw) == slot)
        tl = next(r.raw for r in rl if r.tag == TEXT_TAG and slot_of(r.raw) == slot)
        self.assertEqual(to, tl)
        eo, el = (events(r[section_sequence(r)].raw[HEADER:])[-1] for r in (ro, rl))
        self.assertEqual((eo.head, eo.lines), (el.head, el.lines))

    def test_tempo_step_came_back_with_only_its_stamp_rewritten(self):
        from logicxkit.logic.services.events import BAR_ONE, events
        from logicxkit.logic.services.insert import HEADER, project_records
        from logicxkit.logic.services.tempo import tempo_sequence
        from logicxkit.logic.services.tempo_write import add_tempo
        ours = add_tempo(project_data(ADD_BASE), BAR_ONE + (OURS["facts"]["tempo_bar"] - 1) * 3840, OURS["facts"]["bpm"])
        ro, rl = project_records(ours), project_records(project_data(OUR_ADDS_LOGIC))
        eo, el = (events(r[tempo_sequence(r)].raw[HEADER:])[1] for r in (ro, rl))
        self.assertEqual(eo.head, el.head)
        self.assertEqual(eo.data[:8], el.data[:8])
        self.assertEqual(eo.data[12:], el.data[12:])


if __name__ == "__main__":
    unittest.main()


EDITS_MINE, EDITS_LOGIC = _goldens.path("section-edits-mine"), _goldens.path("section-edits-logic")


@unittest.skipUnless(EDITS_MINE and EDITS_LOGIC, "no re-save of a moved and a deleted section")
class ReSavedMoveDeleteTest(unittest.TestCase):
    """Logic's re-save of a copy with one section deleted and one moved kept every event."""

    def test_events_came_back_as_written(self):
        from logicxkit.logic.services.arrangement import section_sequence
        from logicxkit.logic.services.events import events
        from logicxkit.logic.services.insert import HEADER, project_records
        ours, logic = project_data(EDITS_MINE), project_data(EDITS_LOGIC)
        self.assertEqual(read_sections(ours), read_sections(logic))
        self.assertEqual(len(read_sections(ours)), _goldens.fact("section-edits-mine", "sections"))
        ro, rl = project_records(ours), project_records(logic)
        eo, el = (events(r[section_sequence(r)].raw[HEADER:]) for r in (ro, rl))
        self.assertEqual([(e.head, e.lines) for e in eo], [(e.head, e.lines) for e in el])
        names = [s.name for s in read_sections(ours)]
        self.assertNotIn(_goldens.fact("section-edits-mine", "deleted_name"), names[:3])
        self.assertEqual(read_sections(ours)[-1].bars()[0], float(_goldens.fact("section-edits-mine", "moved_to_bar")))


RAMP_LOGIC = _goldens.path("tempo-ramp-logic")
RAMP = _goldens.entry("tempo-ramp-logic") or {"facts": {}}


@unittest.skipUnless(EDITS_LOGIC and RAMP_LOGIC, "no Logic tempo curve save")
class RampTest(unittest.TestCase):
    """Logic's Tempo Operations curve, and ours laid over the same base."""

    def _ours(self):
        from logicxkit.logic.services.tempo_write import add_ramp
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
        from logicxkit.logic.services.events import events
        from logicxkit.logic.services.insert import HEADER, project_records
        from logicxkit.logic.services.tempo import tempo_sequence
        ro, rl = project_records(self._ours()), project_records(project_data(RAMP_LOGIC))
        eo, el = (events(r[tempo_sequence(r)].raw[HEADER:]) for r in (ro, rl))
        self.assertEqual(len(eo), len(el))
        for a, b in zip(eo[1:], el[1:], strict=True):
            self.assertEqual(a.head[:15] + a.head[16:], b.head[:15] + b.head[16:])
            self.assertEqual(a.data[4:8], b.data[4:8])
            self.assertEqual((a.lines[1:], b.lines[1:]), ((), ()))

    def test_refuses_a_ramp_over_existing_events(self):
        from logicxkit.logic.services.tempo_write import add_ramp
        with self.assertRaises(ValueError):
            add_ramp(project_data(RAMP_LOGIC), BAR_ONE + 32 * 3840, 176, BAR_ONE + 40 * 3840, 140)


OUR_RAMP_MINE, OUR_RAMP_LOGIC = _goldens.path("our-ramp-mine"), _goldens.path("our-ramp-logic")


@unittest.skipUnless(OUR_RAMP_MINE and OUR_RAMP_LOGIC, "no re-save of our ramp")
class ReSavedRampTest(unittest.TestCase):
    """Logic's re-save of a ramp our writer laid down kept every event; only stamps moved."""

    def test_events_came_back_as_written(self):
        from logicxkit.logic.services.events import events
        from logicxkit.logic.services.insert import HEADER, project_records
        from logicxkit.logic.services.tempo import tempo_sequence
        ours, logic = project_data(OUR_RAMP_MINE), project_data(OUR_RAMP_LOGIC)
        self.assertEqual([(e.position, e.bpm) for e in read_tempo_events(ours)], [(e.position, e.bpm) for e in read_tempo_events(logic)])
        ro, rl = project_records(ours), project_records(logic)
        eo, el = (events(r[tempo_sequence(r)].raw[HEADER:]) for r in (ro, rl))
        self.assertEqual([e.head for e in eo], [e.head for e in el])
        self.assertEqual([e.data[:8] + e.data[12:] for e in eo], [e.data[:8] + e.data[12:] for e in el])
