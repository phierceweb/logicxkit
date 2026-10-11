"""`plan_step` is `edit_copy` without the copy: every alternative the write edits, the same gate
and loop warning after the step, and a bundle the write refuses refused. Nothing is written."""

import contextlib
import io
import plistlib
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, written, wrapped
from test_stack_create import TRACKS, session

from logicxkit.logic._edit import CommandError, plan_step
from logicxkit.logic.services.arrange.retrack import stale_alternatives

SUMMING = "stack-summing-logic"                         # Sum 1 on Aux 1 fed Bus 1
TEMPLATE = "stack-folder-logic"


def bundle(root: Path, alternatives=("000",)) -> Path:
    for name in alternatives:
        alt = root / "Song.logicx" / "Alternatives" / name
        alt.mkdir(parents=True)
        (alt / "ProjectData").write_bytes(session())
        (alt / "MetaData.plist").write_bytes(plistlib.dumps({"NumberOfTracks": TRACKS}))
    return root / "Song.logicx"


def empty(root: Path) -> Path:
    """A bundle Logic never saved into: an alternative folder with no ProjectData."""
    (root / "empty.logicx" / "Alternatives" / "000" / "Undo Data.nosync").mkdir(parents=True)
    return root / "empty.logicx"


def planned(project: Path, step) -> str:
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        plan_step(project, step)
    return text.getvalue()


class PlanStepTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_every_alternative_the_write_edits_is_planned(self):
        seen = []
        planned(bundle(self.root, ("000", "001")), lambda d, count, f: seen.append((f.parent.name, count)) or d)
        self.assertEqual(seen, [("000", TRACKS), ("001", TRACKS)])

    def test_a_result_the_gate_refuses_is_refused_and_nothing_is_written(self):
        project = bundle(self.root)
        before = (project / "Alternatives/000/ProjectData").read_bytes()
        with self.assertRaisesRegex(CommandError, "^000: "):
            planned(project, lambda d, count, f: d + b"JUNK")
        self.assertEqual((project / "Alternatives/000/ProjectData").read_bytes(), before)

    def test_a_bundle_with_no_project_data_is_refused(self):
        project = empty(self.root)
        for call in (lambda: stale_alternatives(project), lambda: planned(project, lambda d, c, f: d)):
            with self.subTest(call=call), self.assertRaisesRegex(ValueError, "no Alternatives/\\*/ProjectData"):
                call()


@_goldens.needs(SUMMING)
class PlanStepLoopTest(unittest.TestCase):
    def test_a_loop_the_step_closes_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            looped = data(written(self, "send", SUMMING, "--add", "Aux 1=Bus 1", out=Path(tmp)))
        text = planned(_goldens.path(SUMMING), lambda d, count, f: looped)
        self.assertIn("000: warning: this leaves a routing loop: Sum 1 (Aux 1) -> Bus 1 -> Sum 1 (Aux 1)", text)
        self.assertNotIn("warning", planned(_goldens.path(SUMMING), lambda d, count, f: d))


@_goldens.needs(TEMPLATE)
class EmptyBundleTest(unittest.TestCase):
    """Every writer with a `--plan` refuses a bundle with no ProjectData, plan and write alike,
    and leaves no copy."""

    def test_plan_and_write_refuse_it(self):
        config = Path(__file__).resolve().parents[2] / "config" / "example-mastering.json"
        with tempfile.TemporaryDirectory() as tmp:
            project, out = empty(Path(tmp)), Path(tmp) / "out"
            for argv, why in ((("tracking-chains", project), "no Alternatives/*/ProjectData"),
                              (("chains", project, "--config", config), "no Alternatives/*/ProjectData"),
                              (("swap-plugin", project, "--from", "Compressor", "--to", "Noise Gate"), "no slot holds 'Compressor'"),
                              (("apply-template", _goldens.path(TEMPLATE), project), "no project at")):
                for rest in (("--plan",), ("--out", out)):
                    with self.subTest(argv[0], plan=rest == ("--plan",)):
                        code, text = wrapped(*argv, *rest)
                        self.assertEqual(code, 1, text)
                        self.assertIn(why, text)
                        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
