"""Setting the bar-1 meter, held against Logic's own edit of a song with a meter change."""

import unittest

import _goldens
import _paths
from logicxkit.logic.services.events import BAR_ONE, events
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.integrity import require_no_regression
from logicxkit.logic.services.sequence import sequences
from logicxkit.logic.services.signature import TIME_TYPE, read_signatures
from logicxkit.logic.services.signature_write import set_time_signature
from logicxkit.logicx import project_data

MIXES = sorted((_paths.RESOURCES / "mixes").glob("*/*.logicx"))
BASE = _goldens.path("meter-baseline-logic")
THREE = _goldens.path("meter-3-4-logic")


def first_time_event(data):
    recs = project_records(data)
    i = sequences(recs)[0].end
    return next(e for e in events(recs[i].raw[HEADER:]) if e.type == TIME_TYPE)


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


if __name__ == "__main__":
    unittest.main()
