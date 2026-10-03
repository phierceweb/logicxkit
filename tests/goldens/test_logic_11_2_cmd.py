"""Commands on a Logic 11.2 project, the owner's backup set up as a bundle of its own: the
readers run, every writer refuses. Skips without the owner's files."""

import shutil
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, run, wrapped

from logicxkit.logic.services.arrange.stacks import read_tracks

KEY = "logic-11-2-a"
IN_LOGIC_12 = "logic-11-2-inst-logic"
CONVERTED = "logic-11-2-a-converted"


def bundle(root: Path) -> Path:
    source = _goldens.path(KEY)
    alternative = root / "in" / "probe.logicx" / "Alternatives" / "000"
    alternative.mkdir(parents=True)
    shutil.copy(source, alternative / "ProjectData")
    shutil.copy(source.parent / "MetaData.plist", alternative / "MetaData.plist")
    return alternative.parents[1]


@_goldens.needs(KEY)
class Logic112CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = bundle(self.root)
        rows = read_tracks(data(self.project), count(self.project))
        self.instrument = next(r["name"] for r in reversed(rows)
                               if (r["label"] or "").startswith("Inst "))
        self.audio = next(r["label"] for r in rows if (r["label"] or "").startswith("Audio "))

    def refused(self, *argv) -> None:
        out = self.root / "out"
        code, text = wrapped(*argv, "--out", out)
        self.assertEqual(code, 1, text)
        self.assertIn("an earlier Logic (file format 2511", text)
        self.assertFalse(out.exists(), text)

    def test_the_tracks_read_by_name(self):
        code, text = run("stacks", self.project, "--tracks")
        self.assertEqual(code, 0, text)
        self.assertIn(self.instrument, text)

    def test_an_instrument_track_is_refused_and_nothing_is_left(self):
        self.refused("add-track", self.project, "--name", "Probe", "--after", self.instrument,
                     "--instrument")

    def test_an_audio_track_is_refused_and_nothing_is_left(self):
        self.refused("add-track", self.project, "--name", "Probe", "--after", self.instrument)

    def test_a_route_is_refused(self):
        self.refused("route", self.project, "--output", f"{self.audio}=Bus 1")


@_goldens.needs(KEY, CONVERTED)
class AsATemplateTest(unittest.TestCase):
    """The Logic 11.2 save as the template, Logic 12.4's conversion of it as the session: the
    routing is the same, so none is planned, and the chains are refused by their class."""

    def test_the_sessions_routing_is_kept_and_the_run_succeeds(self):
        from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = _goldens.path(CONVERTED)
            code, text = run("apply-template", bundle(root), session, "--out", root / "out")
            self.assertEqual(code, 0, text[-600:])
            self.assertNotIn("-> no input", text)
            self.assertIn("0 failed", text)
            before, after = data(session), data(root / "out" / session.name)
            used = [o for o, c in channels(before).items() if c.in_use]
            for labels in (input_labels, output_labels):
                self.assertEqual({o: labels(after)[o] for o in used},
                                 {o: labels(before)[o] for o in used})
            self.assertGreater(sum(1 for o in used if input_labels(after)[o]), 50)


@_goldens.needs(IN_LOGIC_12)
class WhyAnInstrumentAddIsRefusedTest(unittest.TestCase):
    """Logic 12.4's save of the Logic 11.2 project with an instrument track inserted, the write
    `add-track` refuses: the new track is there, and one that was bound has no channel."""

    def test_the_add_cost_an_existing_track_its_strip(self):
        rows = read_tracks(data(_goldens.path(IN_LOGIC_12)), _goldens.fact(IN_LOGIC_12, "tracks"))
        self.assertIn(_goldens.fact(IN_LOGIC_12, "track"), [r["name"] for r in rows])
        self.assertEqual([r["name"] for r in rows if r["name"] and r["owner"] is None],
                         _goldens.fact(IN_LOGIC_12, "lost"))


if __name__ == "__main__":
    unittest.main()
