"""The level law at every stop Logic has. `data/send-taper.json` is Logic 12.4's send knob read
at each of its stops (the 8.24 word as its Event List shows it, seven significant digits, and
the dB the knob shows); `data/fader-steps.json` its fader's steps, numbered, with the dB each
shows. Read on 2026-10-02; `test_send_level.py` holds the five points the law was drawn on."""

import json
import unittest
from pathlib import Path

from logicxkit.logic.services.mixer.levels import FIXED_ONE, db_position, fader_word, position_db, shown_db

DATA = Path(__file__).resolve().parent / "data"
TAPER = json.loads((DATA / "send-taper.json").read_text())["rows"]
STEPS = json.loads((DATA / "fader-steps.json").read_text())


def slack(word: int) -> int:
    """Half a unit of the readout's last significant digit: the Event List shows seven."""
    return 10 ** max(len(str(word)) - 7, 0) // 2


class SendTaperTest(unittest.TestCase):
    def test_the_readout_is_whole_and_monotone(self):
        self.assertEqual((len(TAPER), TAPER[0], TAPER[-1]), (266, [0, "-∞"], [2130706000, "6.0"]))
        self.assertTrue(all(a[0] < b[0] for a, b in zip(TAPER, TAPER[1:], strict=False)))
        self.assertTrue(all(float(a[1]) < float(b[1]) for a, b in zip(TAPER[1:], TAPER[2:], strict=False)))

    def test_every_stop_reads_as_the_db_logic_shows(self):
        """Logic shows a level rounded down to the tenth, so the law's value sits within a tenth."""
        for word, shown in TAPER[1:]:
            with self.subTest(shown):
                self.assertAlmostEqual(position_db(word / FIXED_ONE), float(shown), delta=0.05)
        self.assertIsNone(position_db(0.0))

    def test_every_shown_db_lands_on_its_stop(self):
        for word, shown in TAPER[1:]:
            with self.subTest(shown):
                self.assertAlmostEqual(db_position(float(shown)), word / FIXED_ONE, delta=0.1)

    def test_every_stop_shows_as_logic_shows_it(self):
        """The word is read to seven digits; where that rounds it under its mark, the next
        unit of the eighth digit shows the same tenth Logic did."""
        for word, shown in TAPER:
            with self.subTest(shown):
                self.assertIn(shown, {shown_db(word / FIXED_ONE), shown_db((word + slack(word)) / FIXED_ONE)})


class FaderStepsTest(unittest.TestCase):
    """The steps carry no word, so these hold their order and the law's round trip at each
    step's dB; where Logic puts a step's word is the taper's test above."""

    def test_the_steps_are_whole_and_monotone(self):
        self.assertEqual(([s for s, _db in STEPS], STEPS[0], STEPS[-1]), (list(range(234)), [0, "-∞"], [233, "6.0"]))
        self.assertTrue(all(float(a) < float(b) for (_i, a), (_j, b) in zip(STEPS[1:], STEPS[2:], strict=False)))

    def test_every_step_round_trips_on_the_law(self):
        """A fader written at a step's dB reads back as that dB."""
        for step, shown in STEPS[1:]:
            with self.subTest(step):
                self.assertAlmostEqual(position_db(fader_word(float(shown)) / FIXED_ONE), float(shown), delta=0.05)
        self.assertEqual((fader_word(float("-inf")), fader_word(6.0)), (0, 127 << 24))


if __name__ == "__main__":
    unittest.main()
