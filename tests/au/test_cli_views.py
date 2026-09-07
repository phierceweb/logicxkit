"""au CLI: offline subcommands route; views render changed-only vs full."""
import unittest

from logicxkit.au._views import format_preset, format_strip
from logicxkit.cli import main as logicxkit_main

OUT = {
    "format": "aupreset", "decode_path": "au-host",
    "plugin": {"manufacturer": "FabF", "subtype": "FC2p",
               "component": "FabFilter: Pro-C 2"},
    "preset_name": "Example - Test", "blobs": {},
    "params": [
        {"id": 1, "name": "Threshold", "unit": "generic", "value": -6.5,
         "default": -18.0, "display": "-6.50 dB", "changed": True},
        {"id": 2, "name": "Ratio", "unit": "generic", "value": 0.6,
         "default": 0.6, "display": "2.00:1", "changed": False},
    ],
}


class TestViews(unittest.TestCase):
    def test_format_preset_changed_only_by_default(self):
        text = format_preset(OUT, all_rows=False)
        self.assertIn("FabFilter: Pro-C 2", text)
        self.assertIn("Threshold", text)
        self.assertIn("-6.50 dB", text)
        self.assertNotIn("Ratio", text)

    def test_format_preset_all_rows(self):
        text = format_preset(OUT, all_rows=True)
        self.assertIn("Ratio", text)

    def test_format_strip_includes_channel_and_offset(self):
        st = dict(OUT, offset=1234, channel="Audio 3")
        text = format_strip([st], all_rows=False)
        self.assertIn("Audio 3", text)
        self.assertIn("Threshold", text)


class TestCliRouting(unittest.TestCase):
    def test_au_tables_lists_checked_in_tables(self):
        self.assertEqual(logicxkit_main(["au", "tables"]), 0)


if __name__ == "__main__":
    unittest.main()
