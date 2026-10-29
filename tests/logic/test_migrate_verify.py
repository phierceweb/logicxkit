"""`logic migrate`'s song paths, its checklist, and `--verify`'s gate and row comparison with
Logic's re-save faked."""

import contextlib
import io
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


from logicxkit.logic._migrate_cmd import _report, cmd_migrate
from logicxkit.logic.orchestrators import migrate
from logicxkit.logic.orchestrators.ops import Op
from _migrate import SYNTHETIC_SKIP, Run, bundle, session


class SongPathTest(Run):
    def test_a_missing_template_or_song_is_named_before_anything_is_found(self):
        song, nope = bundle(self.tmp / "s", "Song", session()), self.tmp / "nope.logicx"
        for given, template in ((song, nope), (nope, self.tmpl)):
            with self.subTest(song=given.name, template=template.name):
                rc, text = self.run_cli(given, template=template)
                self.assertEqual(rc, 2, text)
                self.assertIn(f"no project at {nope}", text)
                self.assertNotIn("template:", text)
                self.assertNotIn("session :", text)
                self.assert_nothing_written()

    def test_a_folder_of_several_songs_is_refused(self):
        bundle(self.tmp / "songs" / "A", "A", session())
        bundle(self.tmp / "songs" / "B", "B", session())
        rc, text = self.run_cli(self.tmp / "songs")
        self.assertEqual(rc, 2, text)
        self.assertIn("name the song", text)
        self.assert_nothing_written()

    def test_a_song_whose_folder_holds_another_project_is_refused(self):
        song = bundle(self.tmp / "s" / "Song", "Song", session())
        (song.parent / "Audio Files").mkdir()
        bundle(song.parent, "Song Old", session())
        rc, text = self.run_cli(song)
        self.assertEqual(rc, 2, text)
        self.assertIn("Song Old.logicx", text)
        self.assert_nothing_written()

    def test_a_folder_of_one_song_migrates_that_song(self):
        bundle(self.tmp / "songs" / "A", "A", session({"Test Bounce": "Rhythm"}))
        rc, text = self.run_cli(self.tmp / "songs")
        self.assertEqual(rc, 0, text)
        self.assertEqual([p.relative_to(self.out).as_posix() for p in self.out.rglob("*.logicx")],
                         ["CLAUDE migrated - A/A/CLAUDE migrated - A.logicx"])


class ChecklistTest(unittest.TestCase):
    def test_refusals_session_only_rows_and_the_manual_steps(self):
        ops = [Op("add", "Room (Aux 4)", "add aux track", status="refused", note="no paired row above it"),
               Op("rename", "Vocal (Audio 2)", "-> 'Vox'", status="done")]
        kept = [{"name": "Click", "label": "Audio 9"}]
        lines = migrate.checklist([migrate.Outcome("000", ops, kept)], Path("out/CLAUDE migrated - Song.logicx"))
        text = "\n".join(lines)
        self.assertIn("Room (Aux 4)", text)
        self.assertNotIn("Vocal", text)
        self.assertIn("session-only, left as they are: Click (Audio 9)", text)
        self.assertIn("[ ] open out/CLAUDE migrated - Song.logicx in Logic Pro", text)
        self.assertIn("Save As", text)
        self.assertNotIn("Save As", "\n".join(migrate.checklist([migrate.Outcome("000", ops, kept)],
                                                                 Path("x.logicx"), verify=True)))

    def test_alternatives_are_named_when_there_are_several(self):
        outcomes = [migrate.Outcome("000", [], [{"name": "Click", "label": None}]),
                    migrate.Outcome("001", note="map names a session track that does not exist: 'Gtr'")]
        text = "\n".join(migrate.checklist(outcomes, Path("x.logicx")))
        self.assertIn("000: session-only, left as they are: Click", text)
        self.assertIn("001: left as it was", text)


class VerifyGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.app, self.driver = self.tmp / "Logic Pro.app", self.tmp / "driver"
        self.app.mkdir()
        self.driver.mkdir()
        (self.driver / "saveas.applescript").write_text("")

    def problem(self, **kw):
        base = {"platform": "darwin", "app": self.app, "driver": self.driver, "which": lambda _n: "/bin/x"}
        return migrate.verify_problem(**{**base, **kw})

    def test_every_precondition(self):
        self.assertIsNone(self.problem())
        self.assertIn("macOS", self.problem(platform="linux"))
        self.assertIn("not installed", self.problem(app=self.tmp / "absent.app"))
        self.assertIn("checkout", self.problem(driver=self.tmp / "absent"))
        self.assertIn("PATH", self.problem(which=lambda _n: None))

    def test_the_cli_refuses_before_writing(self):
        with mock.patch.object(migrate, "verify_problem", return_value="Logic Pro is not installed"), \
             contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = cmd_migrate(Namespace(project=str(self.tmp / "absent.logicx"), template=str(self.tmp),
                                       out=str(self.tmp / "out"), map=None, save_map=None, skip=None,
                                       force=False, verify=True))
        self.assertEqual(rc, 2)
        self.assertIn("--verify refused: Logic Pro is not installed", buf.getvalue())
        self.assertFalse((self.tmp / "out").exists())


class CompareRowsTest(unittest.TestCase):
    ROW = {"key": 0, "object_id": 88, "name": "Kick In", "colour": 96, "icon": 1, "flag": 1, "hidden": False,
           "on": True, "member": False, "expanded": False, "grouping": False, "owner": 0, "label": "Audio 1",
           "stack_index": 0}

    def test_flag_churn_matches_and_a_real_change_does_not(self):
        churned = {**self.ROW, "flag": 65537}
        self.assertEqual(migrate.compare_rows([self.ROW], [churned]), [])
        self.assertEqual(migrate.compare_rows([self.ROW], [{**self.ROW, "name": "Untitled"}]),
                         ["row 1 Kick In (Audio 1): name 'Kick In' -> 'Untitled'"])

    def test_a_dropped_row_is_named(self):
        vox = {**self.ROW, "key": 1, "name": "Vox", "label": "Audio 20"}
        self.assertEqual(migrate.compare_rows([self.ROW, vox], [self.ROW]),
                         ["2 row(s) in ours, 1 in Logic's save", "row 2 Vox (Audio 20): only in ours"])


class VerifyTest(unittest.TestCase):
    """The driver's calls are faked; the fake Save As writes the re-save the comparison reads."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.ours = bundle(self.tmp, "CLAUDE migrated - Song", session())
        self.calls: list[list[str]] = []

    def fake(self, resave: bytes | None = None, answer: str = "Untitled"):
        def run(argv):
            self.calls.append(argv)
            if argv[:2] == ["osascript", str(migrate.DRIVER / "saveas.applescript")]:
                if resave is not None:
                    bundle(Path(argv[3]), argv[2], resave)
                return 0, answer
            return 0, ""
        return run

    def test_a_faithful_resave_matches(self):
        v = migrate.verify(self.ours, self.tmp, run=self.fake(session()), sleep=lambda _s: None)
        self.assertTrue(v.matched, v)
        self.assertEqual(v.resave, self.tmp / "CLAUDE migrated - Song (Logic save).logicx")
        self.assertEqual(self.calls[0], ["open", "-a", "Logic Pro", str(self.ours)])
        self.assertEqual(self.calls[2][2:], ["CLAUDE migrated - Song (Logic save)", str(self.tmp.resolve())])
        self.assertEqual(len(self.calls), 4)                         # open, dismiss, Save As, close

    def test_a_resave_that_lost_a_name_differs(self):
        v = migrate.verify(self.ours, self.tmp, run=self.fake(session({"Test Bounce": "Untitled"})),
                           sleep=lambda _s: None)
        self.assertFalse(v.matched)
        self.assertEqual(v.differences["000"], ["row 6 Test Bounce (Inst 4): name 'Test Bounce' -> 'Untitled'"])

    def test_no_save_dialog_stops_before_any_comparison(self):
        v = migrate.verify(self.ours, self.tmp, run=self.fake(answer="NO SAVE DIALOG"), sleep=lambda _s: None)
        self.assertIn("NO SAVE DIALOG", v.problem)
        self.assertFalse(v.matched)

    def test_a_save_that_never_appears_is_a_problem(self):
        v = migrate.verify(self.ours, self.tmp, run=self.fake(), sleep=lambda _s: None)
        self.assertIn("no save named", v.problem)

    def test_an_existing_save_name_is_refused_before_logic_is_touched(self):
        (self.tmp / "CLAUDE migrated - Song (Logic save).logicx").mkdir()
        v = migrate.verify(self.ours, self.tmp, run=self.fake(session()), sleep=lambda _s: None)
        self.assertIn("already exists", v.problem)
        self.assertEqual(self.calls, [])

    def test_an_alternative_logic_did_not_save_is_named_as_not_compared(self):
        verdict = migrate.Verdict(resave=self.tmp / "x.logicx", compared=["000"], differences={"000": []},
                                  only_ours=["001"])
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            _report(verdict, 0)
        self.assertIn("001: not compared — Logic's save holds only the open alternative", buf.getvalue())

    def test_the_cli_reports_the_verdict(self):
        song = bundle(self.tmp / "s", "Song", session({"Test Bounce": "Rhythm"}))
        args = Namespace(project=str(song), template=str(bundle(self.tmp / "t", "Tmpl", session())),
                         out=str(self.tmp / "out"), map=None, save_map=None, skip=SYNTHETIC_SKIP,
                         force=False, verify=True)
        with mock.patch.object(migrate, "verify_problem", return_value=None), \
             mock.patch.object(migrate, "_run", self.fake(session({"Test Bounce": "Untitled"}))), \
             mock.patch.object(migrate.time, "sleep"), contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = cmd_migrate(args)
        text = buf.getvalue()
        self.assertEqual(rc, 1, text)
        self.assertIn("000: ROWS DIFFER", text)
        self.assertIn("name 'Test Bounce' -> 'Untitled'", text)
        self.assertNotIn("[ ] open", text)

if __name__ == "__main__":
    unittest.main()
