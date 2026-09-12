"""The signature track: time signatures, key numbers and bar arithmetic across a change."""

import unittest
from logicxkit.logic.services.events import BAR_ONE
from logicxkit.logic.services.signature import Meter, TimeSignature


class MeterTest(unittest.TestCase):
    def test_constant_four_four(self):
        m = Meter([TimeSignature(0, 4, 4)])
        self.assertEqual((m.bar(0), m.bar(BAR_ONE), m.bar(BAR_ONE + 3840 * 10 + 1920)), (-9.0, 1.0, 11.5))

    def test_change_of_meter(self):
        m = Meter([TimeSignature(0, 5, 4), TimeSignature(BAR_ONE + 4800 * 10, 4, 4)])
        self.assertEqual(m.bar(0), -7.0)
        self.assertEqual(m.bar(BAR_ONE + 4800 * 10), 11.0)
        self.assertEqual(m.bar(BAR_ONE + 4800 * 10 + 3840), 12.0)
        self.assertEqual(m.bars(4800, BAR_ONE), 1.0)
        self.assertEqual(m.bars(3840, BAR_ONE + 4800 * 10), 1.0)


class BarToTickTest(unittest.TestCase):
    def test_four_four_keeps_the_old_arithmetic(self):
        m = Meter([TimeSignature(0, 4, 4)])
        self.assertEqual((m.tick(9), m.tick(33.5)), (BAR_ONE + 8 * 3840, BAR_ONE + 32 * 3840 + 1920))

    def test_a_three_four_bar_is_three_beats(self):
        m = Meter([TimeSignature(960, 3, 4)])
        self.assertEqual((m.tick(9), m.ticks(8, at=BAR_ONE)), (BAR_ONE + 8 * 2880, 8 * 2880))

    def test_across_a_change_of_meter(self):
        m = Meter([TimeSignature(0, 5, 4), TimeSignature(BAR_ONE + 4800 * 10, 4, 4)])
        self.assertEqual((m.tick(11), m.tick(12)), (BAR_ONE + 48000, BAR_ONE + 48000 + 3840))

    def test_tick_inverts_bar(self):
        m = Meter([TimeSignature(0, 5, 4), TimeSignature(BAR_ONE + 4800 * 10, 3, 4)])
        for bar in (0.5, 1, 4.25, 10.5, 11, 23.75):
            with self.subTest(bar=bar):
                self.assertAlmostEqual(m.bar(m.tick(bar)), bar)


if __name__ == "__main__":
    unittest.main()
