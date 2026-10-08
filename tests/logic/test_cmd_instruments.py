"""The commands over Logic's own instruments and MIDI effects, in-process on the public corpus:
`plugins` names and marks them, `donors` files an instrument, `replace-plugin --at 1` and
`transplant` put it on another project's instrument track, and a MIDI effect is refused as an
audio effect."""

import json
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, owner, run, written

from logicxkit.logic.services.mixer.mixer import channel_formats
from logicxkit.logic.services.mixer.plugins import project_plugins

CONTROL, SYNTH, KIT, ARP = ("instrument-control-logic", "instrument-es2-logic",
                            "instrument-drum-kit-designer-logic", "instrument-fx-arpeggiator-logic")


@_goldens.needs(CONTROL, SYNTH, KIT, ARP)
class InstrumentCommandsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def library(self, *keys: str) -> Path:
        for key in keys:
            code, text = run("donors", _goldens.path(key), "--library", self.tmp / "lib")
            self.assertEqual(code, 0, text)
        return self.tmp / "lib"

    def test_plugins_names_an_instrument_with_no_float_block(self):
        code, text = run("plugins", _goldens.path(KIT))
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"Inst 1\s+key\s+2\s+Drum Kit Designer\s+native")

    def test_plugins_marks_a_midi_effect(self):
        code, text = run("plugins", _goldens.path(ARP))
        self.assertRegex(text, r"Inst 1\s+key\s+4\s+Arpeggiator\s+native, MIDI FX")
        code, text = run("plugins", _goldens.path(ARP), "--json")
        slots = {s["name"]: s for s in json.loads(text)[0]["slots"]}
        self.assertEqual((slots["Arpeggiator"]["midi"], slots["Klopfgeist"]["midi"]), (True, False))

    def test_donors_lists_the_instruments_it_filed(self):
        code, text = run("donors", _goldens.path(KIT), "--library", self.tmp / "lib")
        self.assertRegex(text, r"ANML-v5\s+Drum Kit Designer")

    def test_replace_plugin_puts_a_library_instrument_in_slot_one_and_widens_the_channel(self):
        dest = written(self, "replace-plugin", CONTROL, "--at", "1", "--plugin", "ES2", "--channel", "Inst 1",
                       "--library", self.library(SYNTH), out=self.tmp / "out")
        after = data(dest)
        refs = [(r.key, r.name) for r in project_plugins(after) if r.channel == "Inst 1"]
        self.assertEqual(refs, [(2, "ES2")])
        self.assertEqual((channel_formats(data(CONTROL))[owner(after, "Inst 1")], channel_formats(after)[owner(after, "Inst 1")]), (1, 2))

    def test_transplant_brings_an_instrument_with_no_float_block(self):
        dest = written(self, "transplant", KIT, _goldens.path(CONTROL), "--channel", "Inst 1", out=self.tmp / "out", copied=CONTROL)
        after = data(dest)
        self.assertEqual([(r.key, r.name) for r in project_plugins(after) if r.channel == "Inst 1"], [(2, "Drum Kit Designer")])
        self.assertEqual(channel_formats(after)[owner(after, "Inst 1")], 2)

    def test_add_plugin_refuses_a_midi_effect(self):
        code, text = run("add-plugin", _goldens.path(CONTROL), "--plugin", "Arpeggiator", "--channel", "Audio 1",
                         "--library", self.library(ARP), "--out", self.tmp / "out")
        self.assertEqual(code, 1, text)
        self.assertIn("MIDI effect", text)
        self.assertFalse((self.tmp / "out" / _goldens.path(CONTROL).name).exists())


if __name__ == "__main__":
    unittest.main()
