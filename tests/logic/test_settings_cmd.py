"""The `settings` report's lines: a compressor's items with their units, an EQ's bands with no
vocabulary of its own, a reader's notes, and a slot without a map."""

import unittest

from logicxkit.logic._settings_cmd import _line


class LineTest(unittest.TestCase):
    def test_a_compressor_line_carries_units_and_notes(self):
        e = {"channel": "Audio 2", "slot": 3, "key": 5, "name": "Neutron 5", "side_chain": None, "family": "compressor",
             "settings": {"threshold": -8.06, "ratio": 2.44}, "silent": ["make_up"], "notes": ["Neutron 5's Dynamics 0 is bypassed"]}
        line = _line(e)
        self.assertIn("threshold -8.06 dB", line)
        self.assertIn("ratio 2.44:1", line)
        self.assertTrue(line.endswith("make_up silent, Neutron 5's Dynamics 0 is bypassed"), line)

    def test_an_eq_line_is_its_bands(self):
        e = {"channel": "Audio 2", "slot": 1, "key": 4, "name": "Channel EQ", "side_chain": None, "family": "eq",
             "settings": {}, "silent": [], "bands": ["bell 250 Hz +3.0 dB Q 1.00", "high cut 12 kHz Q 0.71"], "master": 1.5}
        self.assertEqual(_line(e), "  Audio 2          slot  1  Channel EQ (eq): bell 250 Hz +3.0 dB Q 1.00; high cut 12 kHz Q 0.71, master +1.5 dB")

    def test_a_value_of_ten_thousand_or_more_is_written_out(self):
        e = {"channel": "Audio 2", "slot": 2, "key": 4, "name": "Noise Gate", "side_chain": None, "family": "gate",
             "settings": {"low_cut": 20.0, "high_cut": 20000.0, "attack": 10.719999}, "silent": [], "notes": []}
        line = _line(e)
        self.assertIn("high_cut 20000 Hz", line)
        self.assertIn("low_cut 20 Hz", line)
        self.assertIn("attack 10.72 ms", line)
        self.assertNotIn("e+", line)

    def test_a_slot_without_a_map_says_so(self):
        self.assertTrue(_line({"channel": "Audio 2", "slot": 6, "key": 9, "name": "Some/Plug", "side_chain": None, "settings": None}).endswith("Some/Plug: no map for it"))


class ShowTest(unittest.TestCase):
    """Four significant figures, never in exponent form."""

    def test_large_small_and_plain_values(self):
        from logicxkit.logic.services.translate import _show
        for value, unit, want in ((20000.0, "Hz", "20000 Hz"), (10000, "Hz", "10000 Hz"), (12345.6, "Hz", "12350 Hz"),
                                  (16000.0, "Hz", "16000 Hz"), (250000.0, "Hz", "250000 Hz"), (9999.4, "Hz", "9999 Hz"),
                                  (0.00001234, "s", "0.00001234 s"), (-20000.0, "dB", "-20000 dB"),
                                  (10.719999, "ms", "10.72 ms"), (2.1, ":1", "2.1:1"), (80.0, "%", "80%"),
                                  (0, "dB", "0 dB"), (True, "", "on"), (False, "", "off")):
            with self.subTest(value):
                self.assertEqual(_show(value, unit), want)

    def test_the_command_prints_with_the_same_one(self):
        from logicxkit.logic import _settings_cmd
        from logicxkit.logic.services import translate
        self.assertIs(_settings_cmd._show, translate._show)


if __name__ == "__main__":
    unittest.main()
