"""Logic's own settings: the name table, the value reader over a captured set, and the
control bar default's shape."""

import unittest

import _paths  # noqa: F401
from logicxkit.logic.services.prefs import BY_KEY, SETTINGS, controlbar_default, plist_fragment, read_settings


class TableTest(unittest.TestCase):
    def test_every_setting_has_a_unique_key_and_a_pane(self):
        flags = [s for s in SETTINGS if s.kind in ("bit", "databit")]
        self.assertEqual(len(BY_KEY), len(SETTINGS) - len(flags))
        self.assertEqual(len({(s.key, s.offset, s.mask) for s in flags}), len(flags))
        for s in SETTINGS:
            self.assertIn(s.kind, ("bool", "int", "float", "str", "choice", "bit", "databit"))
            self.assertEqual(bool(s.choices), s.kind == "choice")
            self.assertEqual(bool(s.mask), s.kind in ("bit", "databit"))
            if s.values:
                self.assertEqual(len(s.values), len(s.choices))
            self.assertTrue(s.pane)

    def test_names_are_unique(self):
        names = [s.name for s in SETTINGS]
        self.assertEqual(len(set(names)), len(names))


class ReadTest(unittest.TestCase):
    def test_values_as_defaults_prints_them(self):
        values = {"FadeToolClickZones": "1", "MarqueeToolClickZones": "0", "UndoSteps": "100",
                  "SelectRegionsOnTrackSelection_n": "0", "LockPianoRollRegionBorders": "1",
                  "RightButtonFunction": "2", "DefaultMIDIEditor": "0"}
        state = read_settings(values)
        self.assertEqual((state["Fade tool click zones"], state["Marquee tool click zones"]), (True, False))
        self.assertEqual(state["Number of undo steps"], 100)
        self.assertIsNone(state["Quick Swipe and Take Editing click zones"])
        self.assertTrue(state["Select regions on track selection"])          # an inverted key
        self.assertFalse(state["Piano Roll region border trimming"])
        self.assertEqual(state["Right mouse button"], "Opens Shortcut Menu")
        self.assertEqual(state["Double-clicking a MIDI region opens"], "Score Editor")

    def test_flag_and_data_kinds(self):
        from logicxkit.logic.services.prefs import Setting, data_bytes, decode, encode
        bit = Setting("x", "K", "P", "bit", mask=0x10)
        self.assertTrue(decode(bit, "-4"))
        self.assertFalse(decode(bit, "-20"))
        self.assertEqual(encode(bit, False, "-4"), ("-int", "-20"))
        self.assertEqual(encode(bit, True, "-20"), ("-int", "-4"))
        blob = Setting("y", "D", "P", "databit", mask=0x08, offset=1)
        printed = "{length = 16, bytes = 0x071f0000 00000000 00000000 00000000}"
        self.assertEqual(data_bytes(printed)[:2], b"\x07\x1f")
        self.assertTrue(decode(blob, printed))
        self.assertEqual(encode(blob, False, printed), ("-data", "0717" + "00" * 14))
        choice = Setting("z", "C", "P", "choice", choices=("Off", "Ten"), values=(-1, 10))
        self.assertEqual(decode(choice, "10"), "Ten")
        self.assertEqual(decode(choice, "3"), "choice 3")
        self.assertEqual(encode(choice, "Off"), ("-int", "-1"))
        byte = Setting("w", "K", "P", "bit", mask=0x80, width=8)
        self.assertTrue(decode(byte, "-4"))
        self.assertEqual(encode(byte, False, "-4"), ("-int", "124"))
        self.assertEqual(encode(byte, True, "124"), ("-int", "-4"))
        floats = Setting("v", "F", "P", "choice", choices=("800 ms", "Infinite"), values=(0.800000011920929, -1.0))
        self.assertEqual(decode(floats, "-1"), "Infinite")
        self.assertEqual(decode(floats, "0.800000011920929"), "800 ms")
        self.assertEqual(encode(floats, "Infinite"), ("-float", "-1.0"))
        flags = Setting("u", "B", "P", "choice", choices=("Strip", "Global"), values=(False, True))
        self.assertEqual(decode(flags, "1"), "Global")
        self.assertEqual(encode(flags, "Strip"), ("-bool", "NO"))
        absent = Setting("t", "R", "P", "choice", choices=("System Default", "5"), values=(None, 5))
        self.assertEqual(absent.choice_of(None), "System Default")
        self.assertEqual(read_settings({})["Recent Items"], "System Default")
        self.assertEqual(encode(absent, "System Default"), ("-delete", ""))

    def test_values_parse_from_words(self):
        from logicxkit.logic.services.prefs import parse_value
        self.assertIs(parse_value("Fade tool click zones", "off"), False)
        self.assertEqual(parse_value("Number of undo steps", "200"), 200)
        self.assertEqual(parse_value("Right mouse button", "tool menu"), "Opens Tool Menu")
        with self.assertRaises(ValueError):
            parse_value("Right mouse button", "menu")

    def test_the_control_bar_default_keeps_the_project_layout_shape(self):
        values = {"CLgTransportDefaultConfiguration": {"CLgTransportBtnsTransport": [11, 14], "CLgTransportDisplayMode": 0}}
        self.assertEqual(controlbar_default(values), {"CLgTransportBtnsTransport": [11, 14], "CLgTransportDisplayMode": 0})
        self.assertIsNone(controlbar_default({}))


class TextTest(unittest.TestCase):
    def test_a_layout_becomes_a_typed_plist_fragment(self):
        frag = plist_fragment({"CLgTransportBtnsTransport": [11, 14], "CLgTransportDisplayMode": 0})
        self.assertTrue(frag.startswith("<dict>") and frag.endswith("</dict>"))
        self.assertIn("<integer>11</integer>", frag)

    def test_the_text_round_trips_through_defaults_on_a_scratch_domain(self):
        import shutil
        import subprocess
        if not shutil.which("defaults"):
            self.skipTest("no defaults(1)")
        from logicxkit.logic.services.prefs import CONTROLBAR_DEFAULT_KEY, write_controlbar_default, write_settings
        domain = "com.logicxkit.test-prefs"
        layout = {"CLgTransportBtnsViewLeft": [100, 101], "CLgTransportBtnsViewRight": [110],
                  "CLgTransportBtnsTransport": [6, 11, 12, 13, 14, 16, 38], "CLgTransportBtnsDisplay": [18, 19],
                  "CLgTransportBtnsModus": [30, 42], "CLgTransportDisplayMode": 0}
        try:
            write_controlbar_default(layout, domain)
            write_settings({"Marquee tool click zones": True, "Number of undo steps": 42,
                            "Select regions on track selection": True, "Right mouse button": "Opens Tool Menu"}, domain)
            plist = subprocess.run(["defaults", "export", domain, "-"], capture_output=True, check=True).stdout
            import plistlib
            got = plistlib.loads(plist)
            self.assertEqual(got[CONTROLBAR_DEFAULT_KEY], layout)
            self.assertEqual((got["MarqueeToolClickZones"], got["UndoSteps"]), (True, 42))
            self.assertEqual((got["SelectRegionsOnTrackSelection_n"], got["RightButtonFunction"]), (False, 1))
        finally:
            subprocess.run(["defaults", "delete", domain], capture_output=True)


if __name__ == "__main__":
    unittest.main()
