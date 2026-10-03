"""`logic migrate`: the pairing it chooses, the renamed output it never overwrites, the
checklist, and `--verify`'s gate and row comparison with Logic's re-save faked."""

import contextlib
import io
import plistlib
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from _records import chan, count_record, env_obj, gnos, index_entry, marker, proj, send, seq_triple, track, uuid
from test_stack_create import MIXER, TRACKS, sub

from logicxkit.logic._migrate_cmd import _report, cmd_migrate
from logicxkit.logic.orchestrators import migrate
from logicxkit.logic.orchestrators.ops import Op
from logicxkit.logic.services.mixer.pairing import parse_map_full
from logicxkit.logic.services.arrange.stacks import read_tracks

SYNTHETIC_SKIP = "modes,metronome"          # the synthetic records carry no song record to copy them from


def session(rename: dict[str, str] | None = None, shift: int = 0) -> bytes:
    """test_stack_create's session, with tracks renamed and every Environment object id moved
    by ``shift`` — a project of another lineage with the same layout."""
    rename = rename or {}

    def n(name):
        return rename.get(name, name)

    def i(oid):
        return oid + shift
    table = b"".join(index_entry(i(oid), 2 + k, 20 + 4 * k) for k, oid in enumerate(MIXER))
    return proj(
        count_record(12, [6, 0, 2, 1, 1, 0, 3], 12),
        gnos(*sorted(i(o) for o in (88, 92, 152, 192, 196, 212, 216, 504))),
        env_obj(i(192), n("Drums"), grouping=True), env_obj(i(88), n("Kick In")), env_obj(i(92), n("Snare Up")),
        env_obj(i(196), n("Bass"), grouping=True), env_obj(i(152), n("Bass DI")),
        env_obj(i(504), n("Test Bounce")), env_obj(i(212), n("Drums")), env_obj(i(216), n("Cymbals")),
        env_obj(i(80), n("Master"), grouping=True),
        chan(0, "Audio 1", uuid=uuid(i(88)), stack_index=1), chan(2, "Audio 3", uuid=uuid(i(92)), stack_index=1),
        chan(16, "Audio 17", uuid=uuid(i(152)), stack_index=2),
        chan(68, "Aux 2", uuid=uuid(i(212))), chan(69, "Aux 3", uuid=uuid(i(216))), chan(88, "Inst 4", uuid=uuid(i(504))),
        sub(379, 1, uuid=uuid(i(192))), sub(380, 2, uuid=uuid(i(196))),
        chan(381, "Input 1-2", size=201, in_use=False),
        chan(382, "Output 1-2", uuid=uuid(i(80)), size=201), send(382, 0, 5),
        seq_triple(1, big=table),
        track(0, i(192)), track(1, i(88), member=True), track(2, i(92), member=True), track(3, i(196)),
        track(4, i(152), member=True), track(5, i(504)), track(6, i(212)), track(7, i(216)),
        track(8, i(80), flag=3), marker(),
        *(track(k, oid) for k, oid in enumerate([296, 300, 304] + [i(o) for o in MIXER])), marker(),
        *(seq_triple(2 + k, slot=20 + 4 * k, object_id=i(oid), index=2 + k) for k, oid in enumerate(MIXER)),
        seq_triple(11, slot=100, size=341))


def other_lineage() -> bytes:
    return session({"Test Bounce": "Bounce"}, shift=1000)


def bundle(parent: Path, name: str, data: bytes, tracks: int = TRACKS) -> Path:
    return alternative(parent / f"{name}.logicx", "000", data, tracks)


def alternative(project: Path, name: str, data: bytes, tracks: int = TRACKS) -> Path:
    alt = project / "Alternatives" / name
    alt.mkdir(parents=True)
    (alt / "ProjectData").write_bytes(data)
    (alt / "MetaData.plist").write_bytes(plistlib.dumps({"NumberOfTracks": tracks}))
    return project


def names(project: Path) -> list[str]:
    return [r["name"] for r in read_tracks((project / "Alternatives/000/ProjectData").read_bytes(), TRACKS)]


def map_text(song: bytes, lines: list[str]) -> str:
    """Every session row mapped to the template row of the same name, then ``lines``."""
    keys = [f"{r['name']} ({r['label']})" for r in read_tracks(song, TRACKS)]
    return "\n".join([f"{k} -> {k}" for k in keys if k != "Bounce (Inst 4)"] + lines) + "\n"


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.tmpl = bundle(self.tmp / "t", "Tmpl", session())
        self.out = self.tmp / "out"

    def run_cli(self, song: Path, **kw) -> tuple[int, str]:
        args = Namespace(project=str(song), template=str(self.tmpl), out=str(self.out), map=None,
                         save_map=None, skip=SYNTHETIC_SKIP, force=False, verify=False)
        for k, v in kw.items():
            setattr(args, k, str(v) if isinstance(v, Path) else v)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_migrate(args)
        return rc, buf.getvalue()

    def assert_nothing_written(self):
        self.assertFalse(self.out.exists(), sorted(self.out.rglob("*")) if self.out.exists() else None)


class OutputTest(Run):
    def test_the_output_is_renamed_and_the_staging_is_gone(self):
        song = bundle(self.tmp / "s", "Song", session({"Test Bounce": "Rhythm"}))
        rc, text = self.run_cli(song)
        self.assertEqual(rc, 0, text)
        self.assertEqual([p.name for p in self.out.iterdir()], ["CLAUDE migrated - Song.logicx"])
        self.assertIn("Test Bounce", names(self.out / "CLAUDE migrated - Song.logicx"))
        self.assertIn("Rhythm", names(song))

    def test_a_song_kept_with_its_recordings_moves_as_a_renamed_folder(self):
        song = bundle(self.tmp / "s" / "Song", "Song", session({"Test Bounce": "Rhythm"}))
        (song.parent / "Audio Files").mkdir()
        rc, text = self.run_cli(song)
        self.assertEqual(rc, 0, text)
        folder = self.out / "CLAUDE migrated - Song"
        self.assertEqual([p.name for p in self.out.iterdir()], [folder.name])
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["Audio Files", "CLAUDE migrated - Song.logicx"])

    def test_an_existing_output_is_refused_untouched(self):
        song = bundle(self.tmp / "s", "Song", session({"Test Bounce": "Rhythm"}))
        existing = self.out / "CLAUDE migrated - Song.logicx"
        existing.mkdir(parents=True)
        (existing / "keep").write_text("mine")
        rc, text = self.run_cli(song)
        self.assertEqual(rc, 2)
        self.assertIn("already exists", text)
        self.assertEqual([p.name for p in self.out.iterdir()], [existing.name])
        self.assertEqual((existing / "keep").read_text(), "mine")


class PairingTest(Run):
    def test_another_lineage_without_a_map_is_refused_with_the_draft_shown(self):
        song = bundle(self.tmp / "s", "Song", other_lineage())
        rc, text = self.run_cli(song)
        self.assertEqual(rc, 2)
        self.assertIn("not the same lineage", text)
        self.assertRegex(text, r"Bounce \(Inst 4\)\s+-> Test Bounce \(Inst 4\)")
        self.assert_nothing_written()

    def test_force_applies_the_draft(self):
        song = bundle(self.tmp / "s", "Song", other_lineage())
        rc, text = self.run_cli(song, force=True)
        self.assertEqual(rc, 0, text)
        self.assertIn("FORCED", text)
        self.assertEqual(names(self.out / "CLAUDE migrated - Song.logicx"), names(self.tmpl))

    def test_a_map_file_pairs_instead_of_the_draft_and_needs_no_force(self):
        song = bundle(self.tmp / "s", "Song", other_lineage())
        map_file = self.tmp / "song.txt"
        map_file.write_text(map_text(other_lineage(), ["Bounce (Inst 4) -> (none)", "- Test Bounce (Inst 4)"]))
        rc, text = self.run_cli(song, map=map_file)
        self.assertEqual(rc, 0, text)
        self.assertNotIn("REFUSING", text)
        self.assertIn("Bounce", names(self.out / "CLAUDE migrated - Song.logicx"))
        self.assertIn("session-only, left as they are: Bounce (Inst 4)", text)

    def test_a_map_naming_a_missing_track_writes_nothing(self):
        song = bundle(self.tmp / "s", "Song", other_lineage())
        map_file = self.tmp / "song.txt"
        map_file.write_text("Gtr (Audio 9) -> Test Bounce (Inst 4)\n")
        rc, text = self.run_cli(song, map=map_file)
        self.assertEqual(rc, 1)
        self.assertIn("map names a session track that does not exist", text)
        self.assert_nothing_written()

    def test_the_same_lineage_pairs_by_object_id_not_by_the_draft(self):
        """The draft cannot pair a renamed track, so applying it would add a second Test Bounce."""
        p = migrate.choose_pairing(session(), session({"Test Bounce": "Rhythm"}),
                                   template_count=TRACKS, session_count=TRACKS)
        self.assertEqual((p.source, p.forced, p.problem), ("object id", None, None))
        self.assertRegex(p.proposal, r"Rhythm \(Inst 4\)\s+-> \(none\)")

    def test_save_map_writes_the_draft_and_never_overwrites(self):
        song = bundle(self.tmp / "s", "Song", other_lineage())
        saved = self.tmp / "maps" / "song.txt"
        saved.parent.mkdir()
        rc, _text = self.run_cli(song, save_map=saved)
        self.assertEqual(rc, 2)                                     # still refused: the lineage differs
        forced, _excluded = parse_map_full(saved.read_text())
        self.assertEqual(forced["Bounce (Inst 4)"], "Test Bounce (Inst 4)")
        saved.write_text("edited")
        rc, text = self.run_cli(song, save_map=saved)
        self.assertEqual((rc, saved.read_text()), (2, "edited"))
        self.assertIn("never overwritten", text)

    def test_save_map_with_map_is_refused(self):
        song = bundle(self.tmp / "s", "Song", other_lineage())
        rc, _text = self.run_cli(song, map=self.tmp / "a.txt", save_map=self.tmp / "b.txt")
        self.assertEqual(rc, 2)
        self.assertFalse((self.tmp / "b.txt").exists())


class MapEdgeTest(Run):
    def test_a_map_that_pairs_nothing_is_refused_as_a_map_not_a_draft(self):
        song = bundle(self.tmp / "s", "Song", other_lineage())
        map_file = self.tmp / "song.txt"
        map_file.write_text("# nothing\n+ Kick In (Audio 1)\n")
        rc, text = self.run_cli(song, map=map_file)
        self.assertEqual(rc, 2, text)
        self.assertIn("pairs no tracks", text)
        self.assertIn("not the same lineage", text)
        for wrong in ("--save-map", "pairing above", "draft"):
            self.assertNotIn(wrong, text)
        self.assert_nothing_written()

    def test_a_track_name_with_a_comment_shape_survives_the_draft(self):
        song = bundle(self.tmp / "s", "Song", session({"Test Bounce": "Kick  #1"}, shift=1000))
        rc, text = self.run_cli(song, force=True)
        self.assertEqual(rc, 0, text)
        self.assertIn('"Kick  #1 (Inst 4)"', text)
        self.assertIn("Test Bounce", names(self.out / "CLAUDE migrated - Song.logicx"))

    def test_a_mapped_sub_row_survives_a_stack_the_apply_makes(self):
        from _records import uuid as uid
        from test_stack_create import session as stacked

        from logicxkit.logic.services.mixer.pairing import row_key
        from logicxkit.logic.services.arrange.stack_create import create_stack
        made, _ = create_stack(stacked(), name="Bounce", members=[504], track_count=TRACKS)
        self.tmpl = bundle(self.tmp / "t2", "Tmpl", made, TRACKS + 1)
        swapped = (other_lineage().replace(sub(379, 1, uuid=uid(1192)), sub(379, 2, uuid=uid(1192)))
                   .replace(sub(380, 2, uuid=uid(1196)), sub(380, 1, uuid=uid(1196))))
        s_keys = [row_key(r) for r in read_tracks(swapped, TRACKS)]
        t_keys = [row_key(r) for r in read_tracks(made, TRACKS + 1) if r["name"] != "Bounce"]
        self.assertIn("Bass (Sub 1)", s_keys)
        map_file = self.tmp / "song.txt"
        map_file.write_text("".join(f"{s} -> {t}\n" for s, t in zip(s_keys, t_keys, strict=True)))
        rc, text = self.run_cli(bundle(self.tmp / "s", "Song", swapped), map=map_file)
        self.assertEqual(rc, 0, text)
        self.assertIn("stack   Bounce (Sub 3)", text)
        self.assertIn("Bounce", names(self.out / "CLAUDE migrated - Song.logicx"))


class AlternativesTest(Run):
    """One map, drafted from the first alternative, over a song with two."""

    MAP = ["Bounce (Inst 4) -> Test Bounce (Inst 4)"]

    def test_a_map_the_first_alternative_does_not_fit_writes_nothing(self):
        other = session({"Test Bounce": "Other"}, shift=1000)
        for k, second in enumerate((other, other_lineage())):
            with self.subTest(second_fits=bool(k)):
                song = alternative(bundle(self.tmp / f"s{k}", "Song", other), "001", second)
                map_file = self.tmp / "song.txt"
                map_file.write_text(map_text(other_lineage(), self.MAP))
                rc, text = self.run_cli(song, map=map_file)
                self.assertEqual(rc, 1, text)
                self.assertIn("map names a session track that does not exist: 'Bounce (Inst 4)'", text)
                self.assertNotIn("checklist", text)
                self.assert_nothing_written()

    def test_another_alternative_the_map_misses_is_left_byte_for_byte(self):
        other = session({"Test Bounce": "Other"}, shift=1000)
        song = alternative(bundle(self.tmp / "s", "Song", other_lineage()), "001", other)
        map_file = self.tmp / "song.txt"
        map_file.write_text(map_text(other_lineage(), self.MAP))
        with mock.patch("logicxkit.logic._migrate_cmd._rebased", lambda d: d.replace(b"Other", b"Otter")):
            rc, text = self.run_cli(song, map=map_file)
        self.assertEqual(rc, 0, text)
        self.assertIn("001: left as it was — map names a session track", text)
        out = self.out / "CLAUDE migrated - Song.logicx" / "Alternatives"
        self.assertEqual((out / "001" / "ProjectData").read_bytes(), other)
        self.assertIn("Test Bounce", names(out.parent))


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
