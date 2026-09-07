"""Transport modes: the count-in names and the name checks, without a project."""

import unittest

from logicxkit.logic.services.modes import COUNT_IN, COUNT_INS, MODES, count_in_code, set_modes


class ModesTest(unittest.TestCase):
    def test_count_in_codes_are_their_positions(self):
        self.assertEqual(len(COUNT_INS), 16)
        for i, name in enumerate(COUNT_INS):
            self.assertEqual(count_in_code(name), i)
        self.assertEqual(count_in_code(" 2 bars "), 2)
        with self.assertRaises(ValueError):
            count_in_code("7 Bars")

    def test_unknown_mode_is_refused_before_any_parsing(self):
        with self.assertRaises(ValueError):
            set_modes(b"", {"Loop": True})
        self.assertNotIn(COUNT_IN, MODES)


if __name__ == "__main__":
    unittest.main()
