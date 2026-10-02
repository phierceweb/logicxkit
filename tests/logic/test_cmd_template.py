"""apply-template and migrate run in-process on two saves of one blank project that differ only
in display state: no record op to run, so the display and settings copies are the whole work."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, run, source

from logicxkit.logic.services.controlbar import alternative_dirs, read_controls
from logicxkit.logic.services.header import read_components
from logicxkit.logic.services.integrity import regressions
from logicxkit.logic.services.modes import TRANSIENT, read_modes
from logicxkit.logic.services.toolbar import read_toolbar

TEMPLATE, SESSION = "controlbar-pause-on", "controlbar-base"


def alt(bundle) -> Path:
    return next(iter(alternative_dirs(source(bundle))))


@_goldens.needs(TEMPLATE, SESSION)
class TemplateCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_apply_template_copies_display_state_and_settings(self):
        self.assertFalse(read_controls(alt(SESSION))["Pause"])
        code, text = run("apply-template", source(TEMPLATE), source(SESSION), "--out", self.out)
        self.assertEqual(code, 0, text)
        dest = self.out / source(SESSION).name
        self.assertTrue(read_controls(alt(dest))["Pause"], text)
        self.assertEqual(read_toolbar(alt(dest)), read_toolbar(alt(TEMPLATE)))
        self.assertEqual(read_components(alt(dest)), read_components(alt(TEMPLATE)))
        lasting = lambda modes: {k: v for k, v in modes.items() if k not in TRANSIENT}  # noqa: E731
        self.assertEqual(lasting(read_modes(data(dest))), lasting(read_modes(data(TEMPLATE))))
        for word in ("header", "controlbar", "toolbar", "modes", "metronome"):
            self.assertIn(word, text)
        self.assertEqual(regressions(data(SESSION), data(dest)), [])

    def test_apply_template_skip_display_leaves_the_display_alone(self):
        code, text = run("apply-template", source(TEMPLATE), source(SESSION), "--out", self.out, "--skip", "display")
        self.assertEqual(code, 0, text)
        self.assertFalse(read_controls(alt(self.out / source(SESSION).name))["Pause"])

    def test_a_plan_says_when_the_run_can_differ_from_it(self):
        replanned = "The channel ops are planned again"
        code, text = run("apply-template", source(TEMPLATE), source(SESSION), "--plan")
        self.assertEqual(code, 0, text)
        self.assertNotIn(replanned, text)
        if _goldens.path("stack-folder-logic") and _goldens.path("nest-three-audio-logic"):
            code, text = run("apply-template", source("stack-folder-logic"), source("nest-three-audio-logic"), "--plan")
            self.assertEqual(code, 0, text)
            self.assertIn("make a stack", text)
            self.assertIn(replanned, text)

    def test_migrate_writes_its_named_copy(self):
        code, text = run("migrate", source(SESSION), "--template", source(TEMPLATE), "--out", self.out)
        self.assertEqual(code, 0, text)
        made = [p.name for p in self.out.iterdir() if p.suffix == ".logicx"]
        self.assertEqual(len(made), 1, text)
        self.assertTrue(made[0].startswith("CLAUDE migrated - "), made)
        self.assertTrue(read_controls(next(iter(alternative_dirs(self.out / made[0]))))["Pause"], text)


if __name__ == "__main__":
    unittest.main()
