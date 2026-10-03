"""An entry's parameter fields at the offsets Logic's inspector edits wrote — the gain's two-part
encoding above all — the fade-out type codes, and the ranges held."""

import unittest

import _paths  # noqa: F401
from logicxkit.logic.services.regions.fades import CROSS_OUT, Fade, check_fade, read_fade, with_fade
from logicxkit.logic.services.regions.region_params import RegionParams, check_params, read_params, with_params
from logicxkit.logic.services.regions.regions import ENTRY


class ParamsTest(unittest.TestCase):
    def test_gain_is_tens_and_a_signed_five_bit_remainder_as_logic_wrote_it(self):
        for gain, low, tens in ((3, 0x03, 0x00), (-6, 0x1a, 0x00), (30, 0x00, 0x03), (-30, 0x00, 0xfd), (-17, 0x19, 0xff), (0, 0, 0), (17, 0x07, 0x01)):
            with self.subTest(gain):
                e = with_params(bytes(ENTRY), RegionParams(gain=gain))
                self.assertEqual((e[48] & 0x1F, e[52]), (low, tens))
                self.assertEqual(read_params(e).gain, gain)

    def test_every_field_round_trips_and_the_rest_of_the_entry_is_kept(self):
        base = bytearray(ENTRY)
        base[48] = 0x80                                          # the flex bit stays
        p = RegionParams(gain=-17, delay=-120, transpose=-3, fine_tune=-25, reverse=True)
        e = with_params(bytes(base), p)
        self.assertEqual(read_params(e), p)
        self.assertEqual((e[48], e[50], e[52], e[53], e[60:64]), (0x80 | 0x20 | 0x19, 0xe7, 0xff, 0xfd, b"\x88\xff\xff\xff"))
        self.assertEqual({k for k in range(ENTRY) if e[k]}, {48, 50, 52, 53, 60, 61, 62, 63})
        self.assertEqual(read_params(with_params(e, RegionParams())), RegionParams())
        self.assertEqual(with_params(e, RegionParams())[48], 0x80)
        self.assertEqual(str(p), "gain -17 dB, delay -120, transpose -3, fine -25, reverse")
        self.assertEqual(str(RegionParams()), "")

    def test_the_ranges_are_held(self):
        for bad, message in ((RegionParams(gain=31), "gain of 31"), (RegionParams(transpose=-25), "transpose of -25"),
                             (RegionParams(fine_tune=51), "fine tune of 51"), (RegionParams(delay=10**6), "delay of 1000000")):
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                check_params(bad)


class FadeOutTypeTest(unittest.TestCase):
    def test_the_type_codes_read_and_write_and_out_keeps_logics_three_under_a_crossfade(self):
        for kind, code in (("x", 4), ("eqp", 5), ("xs", 6), ("out", 0)):
            with self.subTest(kind):
                e = with_fade(bytes(ENTRY), Fade(out_ms=500, out_type=kind))
                self.assertEqual((e[67], read_fade(e).out_type), (code, kind))
        crossed = bytearray(ENTRY)
        crossed[CROSS_OUT[0]] = CROSS_OUT[1]
        crossed[68] = 0xf9
        e = with_fade(bytes(crossed), Fade(out_ms=500, out_type="out"))
        self.assertEqual((e[66], e[67], e[68]), (0x20, 3, 0xf9))
        self.assertEqual(read_fade(bytes([0] * 67 + [3] + [0] * 12)).out_type, "out")
        self.assertEqual(str(Fade(out_ms=500, out_curve=40, out_type="eqp")), "out 500 ms curve 40 eqp")
        with self.assertRaisesRegex(ValueError, "fade-out type 'loud'"):
            check_fade(Fade(out_type="loud"))


if __name__ == "__main__":
    unittest.main()
