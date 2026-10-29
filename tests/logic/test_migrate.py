"""`logic migrate`: the pairing it chooses, the renamed output it never overwrites, a map's
edges and the alternatives it leaves alone."""

import unittest
from unittest import mock

from test_stack_create import TRACKS, sub

from logicxkit.logic.orchestrators import migrate
from logicxkit.logic.services.mixer.pairing import parse_map_full
from logicxkit.logic.services.arrange.stacks import read_tracks
from _migrate import Run, alternative, bundle, map_text, names, other_lineage, session


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

if __name__ == "__main__":
    unittest.main()
