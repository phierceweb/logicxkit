"""The channel commands run in-process on public corpus bundles, and the bundle they write read
back: send, transplant, bypass, clear-slots, strip-save, width."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import data, owner, run, source, written

from logicxkit.logic.services.binding import channels, output_routing
from logicxkit.logic.services.insert import channel_formats, slot_bypassed
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
        self.assertIn("insert 3 parameter", text)

    def test_a_channel_that_is_not_there_is_refused_and_nothing_is_written(self):
        code, text = run("bypass", _goldens.path(INSERTS), "--out", self.out, "--channel", "Audio 9")
        self.assertEqual(code, 1, text)
        self.assertIn("Audio 9", text)
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
