"""The time word of an added tempo point, from the tempo map alone."""

import unittest

from logicxkit.logic.services.song.tempo_write import time_word

ORIGIN = (38400, 7_200_000)          # bar 1 at Logic's default SMPTE start, 01:00:00:00


class TimeWordTest(unittest.TestCase):
    def test_constant_tempo(self):
        self.assertEqual(time_word([(38400, 120.0)], *ORIGIN, 55680), 7_218_000)      # 18 beats at 120 = 9 s

    def test_the_origin_itself_and_anything_before_it(self):
        self.assertEqual(time_word([(38400, 120.0)], *ORIGIN, 38400), 7_200_000)
        self.assertEqual(time_word([(38400, 120.0)], *ORIGIN, 0), 7_200_000)

    def test_segments_take_their_own_tempo(self):
        points = [(38400, 120.0), (42240, 60.0)]                 # 4 beats at 120 (2 s), then 60
        self.assertEqual(time_word(points, *ORIGIN, 46080), 7_200_000 + 2000 * (2 + 4))

    def test_rounds_to_the_unit(self):
        self.assertEqual(time_word([(38400, 175.7186)], *ORIGIN, 38400 + 480), 7_200_000 + 341)


if __name__ == "__main__":
    unittest.main()
