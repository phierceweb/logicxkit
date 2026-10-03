"""Setting the bar-1 meter, held against Logic's own edit of a song with a meter change."""

import unittest

import _goldens
import _paths
from logicxkit.logic.services.song.events import BAR_ONE, events
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.integrity import require_no_regression
from logicxkit.logic.services.stream.sequence import sequences
from logicxkit.logic.services.song.signature import KEY_TYPE, TIME_TYPE, read_signatures
from logicxkit.logic.services.song.signature_write import add_key_change, add_meter_change, set_time_signature
from logicxkit.logicx import project_data

MIXES = sorted((_paths.RESOURCES / "mixes").glob("*/*.logicx"))
BASE = _goldens.path("meter-baseline-logic")
THREE = _goldens.path("meter-3-4-logic")


def first_time_event(data):
    recs = project_records(data)
    i = sequences(recs)[0].end
    return next(e for e in events(recs[i].raw[HEADER:]) if e.type == TIME_TYPE)


def signature_events(data):
    recs = project_records(data)
    return events(recs[sequences(recs)[0].end].raw[HEADER:])


def unmarked(head):
    return bytes(b & 0x7F if i == 15 else b for i, b in enumerate(head))


@unittest.skipUnless(MIXES, "no resources mixes")
class SetMeterTest(unittest.TestCase):
    def test_three_four_on_a_four_four_song(self):
        data = project_data(MIXES[0])
        after = set_time_signature(data, 3, 4)
        require_no_regression(data, after)
        times, keys = read_signatures(after)
        self.assertEqual([(t.tick, t.numerator, t.denominator) for t in times], [(960, 3, 4)])
        self.assertEqual(keys, read_signatures(data)[1])

    def test_six_eight_lands_on_a_bar_line_before_bar_one(self):
        after = set_time_signature(project_data(MIXES[0]), 6, 8)
        t = read_signatures(after)[0][0]
        self.assertEqual((t.numerator, t.denominator, t.bar_ticks), (6, 8, 2880))
        self.assertEqual((BAR_ONE - t.tick) % t.bar_ticks, 0)

    def test_refuses_bad_meters(self):
        for n, d in ((0, 4), (3, 5), (40, 4)):
            with self.assertRaises(ValueError):
                set_time_signature(project_data(MIXES[0]), n, d)


@unittest.skipUnless(BASE and THREE, "no Logic meter-edit pair")
class LogicPairTest(unittest.TestCase):
    def test_first_event_matches_logics_edit(self):
        ours = first_time_event(set_time_signature(project_data(BASE), 3, 4, force=True))
        logic = first_time_event(project_data(THREE))
        def unmarked(head):
            return bytes(b & 0x7F if i == 15 else b for i, b in enumerate(head))
        self.assertEqual(unmarked(ours.head), unmarked(logic.head))
        self.assertEqual(ours.lines, logic.lines)

    def test_later_change_is_refused_without_force(self):
        with self.assertRaises(ValueError):
            set_time_signature(project_data(BASE), 3, 4)


@_goldens.needs("signature-list-base-logic", "signature-meter-3-8-bar-6-logic", "signature-key-a-minor-logic")
class LogicListCreateTest(unittest.TestCase):
    """Our later-bar changes against Logic's own Signature List creates: the same events byte for
    byte, but for the selection bit and the data +12 word (Logic's holds the playhead at creation
    on a meter change and 0 on a key change; ours the event's tick)."""

    def _match(self, ours, logic):
        self.assertEqual(unmarked(ours.head), unmarked(logic.head))
        self.assertEqual(ours.lines[0][:12], logic.lines[0][:12])
        self.assertEqual(ours.lines[1:], logic.lines[1:])

    def test_meter_change_matches_logics_create(self):
        base = project_data(_goldens.path("signature-list-base-logic"))
        tick = _goldens.fact("signature-meter-3-8-bar-6-logic", "meter_ticks")[1]
        ours = add_meter_change(base, tick, 3, 8)
        require_no_regression(base, ours)
        logic = project_data(_goldens.path("signature-meter-3-8-bar-6-logic"))
        eo = [e for e in signature_events(ours) if e.type == TIME_TYPE][1]
        el = [e for e in signature_events(logic) if e.type == TIME_TYPE][1]
        self._match(eo, el)
        self.assertEqual(len(signature_events(ours)), len(signature_events(logic)))

    def test_key_change_matches_logics_create(self):
        base = project_data(_goldens.path("signature-meter-3-8-bar-6-logic"))
        tick = _goldens.fact("signature-key-a-minor-logic", "key_ticks")[1]
        ours = add_key_change(base, tick, "A minor")
        require_no_regression(base, ours)
        logic = project_data(_goldens.path("signature-key-a-minor-logic"))
        eo = [e for e in signature_events(ours) if e.type == KEY_TYPE][1]
        el = [e for e in signature_events(logic) if e.type == KEY_TYPE][1]
        self._match(eo, el)
        self.assertEqual([e.type for e in signature_events(ours)], [e.type for e in signature_events(logic)])


if __name__ == "__main__":
    unittest.main()
