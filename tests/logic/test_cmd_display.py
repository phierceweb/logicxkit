"""The display and settings commands run in-process on public corpus bundles, and the copy read
back: controlbar, toolbar and header write DisplayState; modes and metronome write records."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, run, source, written

from logicxkit.logic.services.song.controlbar import alternative_dirs, read_controls
from logicxkit.logic.services.stream.header import read_components
from logicxkit.logic.services.song.metronome import read_metronome
from logicxkit.logic.services.song.modes import TRANSIENT, read_modes
from logicxkit.logic.services.song.toolbar import BUTTONS, read_toolbar

BASE, PAUSE = "controlbar-base", "controlbar-pause-on"
TOOLBAR, HEADER = "toolbar-all-logic", "header-00"
MODES, CYCLE = "modes-base-logic", "modes-cycle-logic"
METRO_ON = "metronome-simple-on-logic"


def alt(bundle) -> Path:
    return next(iter(alternative_dirs(source(bundle))))


@_goldens.needs(BASE, PAUSE, TOOLBAR, HEADER, MODES, CYCLE, METRO_ON)
class DisplayCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_controlbar_show(self):
        self.assertFalse(read_controls(alt(BASE))["Pause"])
        dest = written(self, "controlbar", BASE, "--show", "Pause", out=self.out)
        self.assertTrue(read_controls(alt(dest))["Pause"])

    def test_controlbar_from_another_project(self):
        dest = written(self, "controlbar", BASE, "--from", source(PAUSE), out=self.out)
        self.assertEqual(read_controls(alt(dest)), read_controls(alt(PAUSE)))

    def test_toolbar_hide_then_show(self):
        self.assertIn(BUTTONS["Crop"], read_toolbar(alt(TOOLBAR)))
        hidden = written(self, "toolbar", TOOLBAR, "--hide", "Crop", out=self.out / "hidden")
        self.assertNotIn(BUTTONS["Crop"], read_toolbar(alt(hidden)))
        shown = written(self, "toolbar", hidden, "--show", "Crop", out=self.out / "shown")
        self.assertEqual(sorted(read_toolbar(alt(shown))), sorted(read_toolbar(alt(TOOLBAR))))

    def test_a_source_with_no_display_state_is_refused_by_each_from(self):
        bare = self.out / "bare.logicx" / "Alternatives" / "000"
        bare.mkdir(parents=True)
        (bare / "ProjectData").write_bytes(data(BASE))
        for command in ("toolbar", "controlbar", "header"):
            with self.subTest(command):
                code, text = run(command, source(BASE), "--from", str(bare.parents[1]), "--out", str(self.out / command))
                self.assertEqual(code, 2, text)
                self.assertIn("no alternative carries a DisplayState.plist", text)

    def test_header_reads_the_components_without_out(self):
        code, text = run("header", source(HEADER))
        self.assertEqual(code, 0, text)
        self.assertIn("Mute", text)

    def test_header_flips_one_component_and_keeps_the_rest(self):
        before = read_components(alt(HEADER))
        flag = "--hide" if before["Mute"] else "--show"
        dest = written(self, "header", HEADER, flag, "Mute", out=self.out)
        after = read_components(alt(dest))
        self.assertEqual(after["Mute"], not before["Mute"])
        self.assertEqual({k: v for k, v in after.items() if k != "Mute"}, {k: v for k, v in before.items() if k != "Mute"})

    def test_modes_set(self):
        self.assertFalse(read_modes(data(MODES))["Cycle"])
        dest = written(self, "modes", MODES, "--set", "Cycle=on", "--set", "Count-in=1 Bar", out=self.out)
        after = read_modes(data(dest))
        self.assertEqual((after["Cycle"], after["Count-in"]), (True, "1 Bar"))

    def test_modes_from_another_project(self):
        dest = written(self, "modes", MODES, "--from", source(CYCLE), out=self.out)
        lasting = lambda modes: {k: v for k, v in modes.items() if k not in TRANSIENT}  # noqa: E731
        self.assertEqual(lasting(read_modes(data(dest))), lasting(read_modes(data(CYCLE))))

    def test_metronome_set(self):
        self.assertTrue(read_metronome(data(METRO_ON))["Simple mode"])
        dest = written(self, "metronome", METRO_ON, "--set", "Simple mode=off", out=self.out)
        self.assertFalse(read_metronome(data(dest))["Simple mode"])

    def test_metronome_from_another_project(self):
        self.assertFalse(read_metronome(data(BASE))["Simple mode"])
        dest = written(self, "metronome", BASE, "--from", source(METRO_ON), out=self.out)
        self.assertTrue(read_metronome(data(dest))["Simple mode"])


if __name__ == "__main__":
    unittest.main()
