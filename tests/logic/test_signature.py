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


if __name__ == "__main__":
    unittest.main()
