"""A send's level, mode and bypass, and the fader law both the send knob and the channel fader
follow: dB = 40 * log10(position / 90) on the 0-127 position, 8.24 fixed point in the record.
Measured in Logic 12.4: 265 stops of the send knob, and four saved fader positions."""

import struct
import unittest

from _records import chan, proj, uuid
from test_sends_write import bus, donor_send, send_raw

from logicxkit.logic.services.levels import (
    db_position, fader_word, level_word, position_db, shown_db)
from logicxkit.logic.services.sends import read_sends
from logicxkit.logic.services.sends_write import add_send, set_send
from logicxkit.logic.services.stream import HEADER

# (level word, dB shown) as Logic's send knob reported them
KNOB = ((0, None), (5976913, -96.1), (150995100, -40.0), (575290700, -16.8), (1509949696, 0.0),
        (1794578000, 3.0), (2013550000, 5.0), (2130706432, 6.0))


def session(*, level: bytes = b"\x01\x23", extra: bytes = b"") -> bytes:
    return proj(chan(2, "Audio 3", uuid=uuid(96)), donor_send(2, 0, 15, level=level),
                bus(10), bus(15), *([extra] if extra else []))


def fields(raw: bytes) -> tuple[int, int, int, int, int, float]:
    p = raw[HEADER:]
    return p[16], p[17], p[18], p[19], p[22], struct.unpack_from("<I", p, 24)[0] / (1 << 24)


class FaderLawTest(unittest.TestCase):
    def test_a_position_reads_as_the_db_logic_shows(self):
        for word, shown in KNOB:
            with self.subTest(shown):
                db = position_db(word / (1 << 24))
                if shown is None:
                    self.assertIsNone(db)
                else:
                    self.assertAlmostEqual(db, shown, delta=0.051)

    def test_a_db_value_lands_where_logic_puts_the_knob(self):
        for word, shown in KNOB[1:-1]:
            if shown == -16.8:                  # a dragged position, between the knob's stops
                continue
            with self.subTest(shown):
                self.assertAlmostEqual(db_position(shown) * (1 << 24), word, delta=(1 << 24) * 0.03)
        self.assertEqual((db_position(float("-inf")), db_position(0.0), db_position(6.0)),
                         (0.0, 90.0, 127.0))

    def test_logic_shows_a_level_rounded_down_and_the_top_as_6(self):
        for word, shown in KNOB[1:5]:          # the words read to the unit, not to seven digits
            with self.subTest(shown):
                self.assertEqual(shown_db(word / (1 << 24)), f"{shown:.1f}")
        self.assertEqual((shown_db(0.0), shown_db(127.0)), ("-∞", "6.0"))

    def test_a_written_level_sits_above_its_mark_as_logics_own_do(self):
        """Logic shows a level rounded down: its 0 dB is position 90 plus 256 units."""
        self.assertEqual(level_word(0.0), (90 << 24) + 256)
        self.assertEqual(shown_db(level_word(-10.0) / (1 << 24)), "-10.0")
        self.assertEqual((level_word(float("-inf")), level_word(6.0)), (0, 127 << 24))

    def test_a_fader_is_written_on_the_law_as_logics_fader_steps_are(self):
        """Logic's saved steps: -5.3 dB as 1112916049, -16.6 as 580714145, -6.4 as 1044629787."""
        self.assertEqual([fader_word(db) for db in (-5.3, -16.6, -6.4)],
                         [1112916049, 580714145, 1044629787])
        self.assertEqual((fader_word(0.0), fader_word(float("-inf")), fader_word(6.0)),
                         (90 << 24, 0, 127 << 24))

    def test_a_level_above_the_top_is_refused(self):
        for db in (6.1, 1e6, float("inf")):
            with self.subTest(db), self.assertRaisesRegex(ValueError, r"6\.0 dB"):
                db_position(db)
        with self.assertRaisesRegex(ValueError, "a number of dB"):
            db_position(float("nan"))


class SendSettingsReadTest(unittest.TestCase):
    def _send(self, **bytes_at: int):
        raw = bytearray(donor_send(2, 0, 15))
        struct.pack_into("<I", raw, HEADER + 24, 575290700)
        for at, value in bytes_at.items():
            raw[HEADER + int(at[1:])] = value
        data = proj(chan(2, "Audio 3", uuid=uuid(96)), bytes(raw), bus(15))
        return read_sends(data)[2][0]

    def test_the_level_in_db(self):
        self.assertAlmostEqual(self._send().level_db, -16.8, delta=0.05)

    def test_the_three_modes(self):
        self.assertEqual(self._send(b16=1, b18=0).mode, "post pan")
        self.assertEqual(self._send(b16=0, b18=0).mode, "post fader")
        self.assertEqual(self._send(b16=0, b18=1).mode, "pre fader")

    def test_bypass_and_independent_pan(self):
        s = self._send(b19=1, b22=4)
        self.assertEqual((s.bypassed, s.independent_pan), (True, True))
        self.assertEqual((self._send().bypassed, self._send().independent_pan), (False, False))


class SendSettingsWriteTest(unittest.TestCase):
    def test_set_writes_the_level_word_and_its_position_byte(self):
        out, report = set_send(session(), owner=2, bus=15, level_db=-10.0)
        post_pan, position, pre, bypass, options, level = fields(send_raw(out, 2, 0))
        self.assertEqual((post_pan, position, pre, bypass, options), (1, 50, 0, 0, 0))
        self.assertAlmostEqual(level, 90 * 10 ** (-10 / 40), places=4)
        self.assertEqual((report["key"], report["bus"]), (0, 15))

    def test_minus_infinity_is_position_zero(self):
        out, _ = set_send(session(), owner=2, bus=15, level_db=float("-inf"))
        self.assertEqual(fields(send_raw(out, 2, 0))[1::4], (0, 0.0))

    def test_set_writes_a_mode_and_the_bypass_and_leaves_the_rest(self):
        before = send_raw(session(), 2, 0)
        out, _ = set_send(session(), owner=2, bus=15, mode="pre fader", bypass=True)
        after = send_raw(out, 2, 0)
        self.assertEqual(fields(after)[:4], (0, 0x23, 1, 1))
        changed = [i - HEADER for i in range(len(after)) if after[i] != before[i]]
        self.assertEqual(changed, [16, 18, 19])

    def test_an_unknown_mode_or_a_send_that_is_not_there_is_refused(self):
        with self.assertRaisesRegex(ValueError, "post pan, post fader or pre fader"):
            set_send(session(), owner=2, bus=15, mode="pre pan")
        with self.assertRaisesRegex(ValueError, "no send to Bus 10"):
            set_send(session(), owner=2, bus=10, level_db=0.0)

    def test_an_added_send_takes_the_settings_asked_for(self):
        out, report = add_send(session(), owner=2, bus=10, level_db=0.0, mode="post fader")
        self.assertEqual(fields(send_raw(out, 2, report["key"]))[:3], (0, 90, 0))

    def test_an_added_send_without_them_comes_in_as_logic_adds_one(self):
        pattern = b"\x00\x40\x01\x01\x00\x00\x04"        # pre fader, position 64, bypassed, independent pan
        out, report = add_send(session(level=pattern), owner=2, bus=10)
        self.assertEqual(fields(send_raw(out, 2, report["key"])), (1, 0, 0, 0, 0, 0.0))
        self.assertEqual(fields(send_raw(out, 2, 0))[:5], (0, 0x40, 1, 1, 4))

    def test_a_second_send_to_one_bus_is_refused_but_its_own_key_is_replaced(self):
        with self.assertRaisesRegex(ValueError, r"already sends to Bus 15 \(send 0\)"):
            add_send(session(), owner=2, bus=15)
        out, _ = add_send(session(), owner=2, bus=15, key=0, level_db=-3.0)
        self.assertEqual([(s.key, s.bus) for s in read_sends(out)[2]], [(0, 15)])


if __name__ == "__main__":
    unittest.main()
