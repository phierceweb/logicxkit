"""The channel commands run in-process on public corpus bundles, and the bundle they write read
back: send, transplant, bypass, clear-slots, strip-save, width."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import data, owner, run, source, written

from logicxkit.logic.services.binding import channels, output_routing
from logicxkit.logic.services.mixer import channel_formats
from logicxkit.logic.services.slots import slot_bypassed
from logicxkit.logic.services.project import read_project, strip_chain
from logicxkit.logic.services.sends import read_sends
from logicxkit.logic.services.transplant import channel_slots

INSERTS = "inserts-native-logic"        # Audio 1: Channel EQ -> Compressor; Audio 2 and 3 empty
SEND = "send-bus-1-logic"               # Audio 1 sends to Bus 1
LEVELS = "levels-resave-logic"          # Audio 1 alone, no sends
STEREO = "tracks-stereo-pair-logic"     # Audio 4 stereo, Audio 1-3 mono
STACK = "stack-folder-logic"            # Sub 1 holding Audio 1, 2 and 3
LANES = "auto-lanes"                    # Audio 2: Compressor -> Noise Gate -> Pro-C 2, four lanes on insert 3


def chain(bundle, label: str) -> list:
    return next((list(map(tuple, c["chain"])) for c in read_project(source(bundle))["channels"]
                 if c["label"] == label), [])


@_goldens.needs(INSERTS, SEND, LEVELS, STEREO, STACK, LANES, "stack-folder-flattened-logic")
class ChannelCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_route_output(self):
        dest = written(self, "route", "stack-folder-flattened-logic", "--output", "Audio 2=Bus 1", out=self.out)
        after = data(dest)
        self.assertEqual(channels(after)[output_routing(after)[owner(after, "Audio 2")]].label, "Bus 1")
        self.assertEqual(channels(after)[output_routing(after)[owner(after, "Audio 1")]].label, "Output 1-2")

    def test_send_add(self):
        dest = written(self, "send", LEVELS, "--add", "Audio 1=Bus 1", out=self.out)
        after = data(dest)
        self.assertEqual([s.bus for s in read_sends(after)[owner(after, "Audio 1")]], [1])

    def test_send_set_level_mode_and_bypass(self):
        dest = written(self, "send", SEND, "--set", "Audio 1=Bus 1", "--level", "-10", "--mode",
                       "pre-fader", "--bypass", "on", out=self.out)
        (s,) = read_sends(data(dest))[owner(data(dest), "Audio 1")]
        self.assertEqual((round(s.level_db, 1), s.mode, s.bypassed), (-10.0, "pre fader", True))

    def test_send_add_at_a_level(self):
        dest = written(self, "send", LEVELS, "--add", "Audio 1=Bus 1", "--level", "0", out=self.out)
        (s,) = read_sends(data(dest))[owner(data(dest), "Audio 1")]
        self.assertEqual((round(s.level_db, 2), s.mode), (0.0, "post pan"))

    def test_send_set_to_silence(self):
        dest = written(self, "send", SEND, "--set", "Audio 1=Bus 1", "--level=-inf", out=self.out)
        (s,) = read_sends(data(dest))[owner(data(dest), "Audio 1")]
        self.assertIsNone(s.level_db)

    def test_send_set_needs_something_to_set(self):
        code, text = run("send", source(SEND), "--set", "Audio 1=Bus 1", "--out", self.out)
        self.assertEqual(code, 2, text)
        self.assertFalse(any(self.out.iterdir()))

    def test_send_settings_need_an_add_or_a_set(self):
        for extra in ((), ("--remove", "Audio 1")):
            with self.subTest(extra):
                code, text = run("send", source(SEND), "--level=-10", *extra, "--out", self.out)
                self.assertEqual(code, 2, text)
                self.assertIn("go with --add or --set", text)
                self.assertFalse(any(self.out.iterdir()))

    def test_a_level_out_of_range_says_so(self):
        for level, said in (("1e6", "at most 6.0 dB"), ("nan", "a number of dB")):
            with self.subTest(level):
                code, text = run("send", source(SEND), "--set", "Audio 1=Bus 1", f"--level={level}", "--out", self.out)
                self.assertEqual(code, 1, text)
                self.assertIn(said, text)

    def test_levels_sets_a_fader_in_db_and_a_pan(self):
        from logicxkit.logic.services.levels import read_levels
        dest = written(self, "levels", LEVELS, "--fader", "Audio 1=-6", "--pan", "Audio 1=-20",
                       out=self.out)
        lv = read_levels(data(dest))[owner(data(dest), "Audio 1")]
        self.assertEqual((round(lv["fader_db"], 2), lv["pan_display"]), (-6.0, -20))

    def test_levels_lists_faders_in_db(self):
        code, text = run("levels", source("send-level-2-logic"), "--json")
        self.assertEqual(code, 0, text)
        self.assertIn('"fader_db": 0.0', text)

    def test_send_remove(self):
        before = data(SEND)
        self.assertEqual([s.bus for s in read_sends(before)[owner(before, "Audio 1")]], [1])
        dest = written(self, "send", SEND, "--remove", "Audio 1", out=self.out)
        after = data(dest)
        self.assertEqual(read_sends(after).get(owner(after, "Audio 1"), []), [])

    def test_transplant(self):
        src = _goldens.path(INSERTS)
        dest = written(self, "transplant", src, src, "--channel", "Audio 2=Audio 1", out=self.out)
        self.assertEqual(chain(dest, "Audio 2"), chain(INSERTS, "Audio 1"))
        self.assertEqual([p for p, _ in chain(dest, "Audio 2")], ["Channel EQ", "Compressor"])

    def test_bypass_then_enable(self):
        bypassed = written(self, "bypass", INSERTS, "--channel", "Audio 1", out=self.out / "off")
        after = data(bypassed)
        slots = channel_slots(after, owner(after, "Audio 1"))
        self.assertEqual([slot_bypassed(r.raw) for r in slots], [True, True])
        enabled = written(self, "bypass", bypassed, "--channel", "Audio 1", "--enable", out=self.out / "on")
        after = data(enabled)
        self.assertEqual([slot_bypassed(r.raw) for r in channel_slots(after, owner(after, "Audio 1"))], [False, False])

    def test_clear_slots(self):
        dest = written(self, "clear-slots", INSERTS, "--channel", "Audio 1", out=self.out)
        after = data(dest)
        self.assertEqual(channel_slots(after, owner(after, "Audio 1")), [])
        self.assertEqual(chain(dest, "Audio 1"), [])

    def test_strip_save(self):
        cst = self.out / "Audio 1.cst"
        code, text = run("strip-save", _goldens.path(INSERTS), "--channel", "Audio 1", "-o", cst)
        self.assertEqual(code, 0, text)
        self.assertEqual([p for p, _ in strip_chain(cst.read_bytes())], ["Channel EQ", "Compressor"])
        code, text = run("strip-save", _goldens.path(INSERTS), "--channel", "Audio 1", "-o", cst)
        self.assertEqual((code, "--overwrite" in text), (1, True), text)

    def test_strip_save_refuses_logics_own_library_without_install(self):
        library = self.out / "Audio Music Apps"
        target = library / "Channel Strip Settings" / "Track" / "x.cst"
        with mock.patch.dict(os.environ, {"LOGICXKIT_AUDIO_MUSIC_APPS": str(library)}):
            code, text = run("strip-save", _goldens.path(INSERTS), "--channel", "Audio 1", "-o", target)
            self.assertEqual(code, 2, text)
            self.assertIn("--install", text)
            self.assertFalse(target.exists())
            code, text = run("strip-save", _goldens.path(INSERTS), "--channel", "Audio 1", "-o", target, "--install")
            self.assertEqual(code, 0, text)
            self.assertTrue(target.exists())

    def test_width(self):
        dest = written(self, "width", STEREO, "--stereo", "Audio 1", "--mono", "Audio 4", out=self.out)
        after = data(dest)
        formats = channel_formats(after)
        self.assertEqual((formats[owner(after, "Audio 1")], formats[owner(after, "Audio 4")]), (2, 1))

    def test_send_copy_from_another_project(self):
        dest = written(self, "send", LEVELS, "--copy", "Audio 1", "--from", _goldens.path(SEND), out=self.out)
        after = data(dest)
        self.assertEqual([s.bus for s in read_sends(after)[owner(after, "Audio 1")]], [1])

    def test_transplant_onto_a_stack_refuses_a_fan_out_it_cannot_id_unless_forced(self):
        src, dst = _goldens.path(INSERTS), _goldens.path(STACK)
        code, text = run("transplant", src, dst, "--stack", "Sub 1=Audio 1", "--out", self.out / "refused")
        self.assertEqual(code, 1, text)
        self.assertIn("--force", text)
        self.assertFalse((self.out / "refused").exists() and any((self.out / "refused").iterdir()))
        dest = written(self, "transplant", src, dst, "--stack", "Sub 1=Audio 1", "--force", out=self.out / "forced",
                       copied=dst)
        for label in ("Audio 1", "Audio 2", "Audio 3"):
            self.assertEqual([p for p, _ in chain(dest, label)], ["Channel EQ", "Compressor"], label)

    def test_add_plugin_then_remove_it(self):
        added = written(self, "add-plugin", INSERTS, "--plugin", "Compressor", "--channel", "Audio 2", out=self.out / "a")
        self.assertEqual([p for p, _ in chain(added, "Audio 2")], ["Compressor"])
        front = written(self, "add-plugin", added, "--plugin", "Gain", "--channel", "Audio 1", "--at", "1", out=self.out / "b")
        self.assertEqual([p for p, _ in chain(front, "Audio 1")], ["Gain", "Channel EQ", "Compressor"])
        removed = written(self, "remove-plugin", front, "--at", "1", "--channel", "Audio 1", out=self.out / "c")
        self.assertEqual([p for p, _ in chain(removed, "Audio 1")], ["Channel EQ", "Compressor"])

    def test_add_plugin_set_dials_values_through_the_parameter_table(self):
        dest = written(self, "add-plugin", INSERTS, "--plugin", "Compressor", "--channel", "Audio 2",
                       "--set", "Threshold=-20", "--set", "Ratio=4", out=self.out)
        natives = next(c for c in read_project(dest)["channels"] if c["label"] == "Audio 2")["native"]
        params = dict(natives)["Compressor"]
        self.assertEqual((params["threshold"], params["ratio"]), (-20.0, 3.9))   # 4.0 snaps to the knob's position, as Logic's does

    def test_replace_plugin_translate_carries_the_slots_lanes(self):
        dest = written(self, "replace-plugin", LANES, "--at", "3", "--plugin", "Compressor", "--channel", "Audio 2",
                       "--translate", out=self.out)
        self.assertEqual([p for p, _ in chain(dest, "Audio 2")], ["Compressor", "Noise Gate", "Compressor"])
        code, text = run("automation", dest)
        self.assertEqual(code, 0, text)
        self.assertIn("slot 3 Threshold (Compressor, parameter 0): 3 point(s)", text)
        self.assertIn("= -30 dB", text)

    def test_automation_lists_a_parameter_lane_by_the_name_set_takes(self):
        code, text = run("automation", _goldens.path(LANES))
        self.assertEqual(code, 0, text)
        self.assertIn("slot 3 threshold (pro-c 2, parameter 1): 3 point(s)", text.lower())   # the AU table's spelling, or the map's
        dest = written(self, "automation", LANES, "--set", "Audio 2:slot 3 Threshold=-18@1,-6@2", out=self.out)
        code, text = run("automation", dest, "--json")
        lane = next(ln for a in json.loads(text) for ln in a["lanes"] if ln["name"].lower() == "threshold")
        self.assertEqual((lane["plugin"], lane["slot"], lane["param_index"]), ("Pro-C 2", 3, 1))
        self.assertEqual([round(p["in_unit"], 2) for p in lane["points"]], [-18.0, -6.0])

    def test_a_channel_that_is_not_there_is_refused_and_nothing_is_written(self):
        code, text = run("bypass", _goldens.path(INSERTS), "--out", self.out, "--channel", "Audio 9")
        self.assertEqual(code, 1, text)
        self.assertIn("Audio 9", text)
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
