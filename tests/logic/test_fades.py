"""An entry's fade fields, at the offsets Logic's inspector edits wrote."""

import unittest
from dataclasses import replace

import _paths  # noqa: F401
from logicxkit.logic.services.regions.fades import Fade, check_fade, crossfade_bytes, read_fade, with_fade
from logicxkit.logic.services.regions.regions import ENTRY


class FadeTest(unittest.TestCase):
    def test_the_fields_round_trip_at_logics_offsets(self):
        fade = Fade(500, 50, 1, 500, -30)
        e = with_fade(bytes(ENTRY), fade)
        self.assertEqual(read_fade(e), fade)
        self.assertEqual((e[65], e[72:74], e[75], e[76:78], e[79]), (1, b"\xf4\x01", 0xE2, b"\xf4\x01", 50))
        self.assertEqual({k for k in range(ENTRY) if e[k]}, {65, 72, 73, 75, 76, 77, 79})
        self.assertEqual(str(fade), "in 500 ms curve 50 speed-up, out 500 ms curve -30")
        self.assertEqual(str(Fade()), "")

    def test_a_fade_is_fitted_to_its_piece(self):
        cases = ((3000, 20, 1100, (1080, 20)), (1000, 1000, 1200, (600, 600)), (500, 600, 400, (200, 200)),
                 (20, 20, 0, (0, 0)), (1000, 100, 500, (400, 100)), (1000, 400, 500, (250, 250)), (50, 80, 2000, (50, 80)))
        for in_ms, out_ms, length, expected in cases:
            with self.subTest((in_ms, out_ms, length)):
                fitted = Fade(in_ms=in_ms, out_ms=out_ms, out_curve=3).fitted(length)
                self.assertEqual((fitted.in_ms, fitted.out_ms, fitted.out_curve), (*expected, 3))
                self.assertLessEqual(fitted.in_ms + fitted.out_ms, max(length, 0))

    def test_a_piece_starts_from_its_parents_ends_alone(self):
        parent = Fade(in_ms=50, in_curve=10, in_type=1, out_ms=80, out_curve=5, out_type="x")
        self.assertEqual(Fade.for_piece(parent, first=True, last=False), Fade(in_ms=50, in_curve=10, in_type=1))
        self.assertEqual(Fade.for_piece(parent, first=False, last=True), Fade(out_ms=80, out_curve=5, out_type="x"))
        self.assertEqual(Fade.for_piece(parent, first=False, last=False), Fade())
        self.assertEqual(Fade.for_piece(parent, first=True, last=True), parent)

    def test_the_crossfade_bytes_are_kept_and_the_ranges_held(self):
        e = bytearray(ENTRY)
        e[66:69] = b"\x20\x05\xf9"
        out = with_fade(bytes(e), replace(read_fade(bytes(e)), out_ms=10))
        self.assertEqual(crossfade_bytes(out), b"\x20\x05\xf9")
        self.assertEqual(crossfade_bytes(with_fade(bytes(e), Fade(out_ms=10))), b"\x20\x03\xf9")     # type out under a crossfade
        for bad in (Fade(in_ms=70000), Fade(in_curve=100), Fade(out_curve=-100), Fade(in_type=2)):
            with self.subTest(bad), self.assertRaises(ValueError):
                check_fade(bad)


if __name__ == "__main__":
    unittest.main()
