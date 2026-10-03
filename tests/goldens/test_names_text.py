"""Marker, section and group names outside ASCII: written here as UTF-8 and kept by Logic's
re-save, and Logic's own renames (RTF text records, a UTF-8 group name) read back. Skips
without the public corpus."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import written

from logicxkit.logic.services.song.arrangement import TEXT_TAG, read_sections
from logicxkit.logic.services.arrange.groups import read_groups
from logicxkit.logic.services.song.markers import read_markers
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.stream.stream import project_records
from logicxkit.logicx import project_data

BASE, OURS, RESAVE, RENAMED = ("markers-edits-resave-logic", "names-text-ours", "names-text-resave-logic",
                               "names-text-renamed-logic")


def names(data: bytes) -> dict:
    """The first marker's, the first section's and the first group's name, with its members."""
    group = read_groups(data)[0]
    members = {r["object_id"]: r["name"] for r in read_tracks(data)}
    return {"marker": read_markers(data)[0].name, "section": read_sections(data)[0].name,
            "group": group.name, "member": ", ".join(members[m] for m in group.members)}


def text_records(data: bytes) -> list[bytes]:
    return [r.raw for r in project_records(data) if r.tag == TEXT_TAG]


@_goldens.needs(BASE, OURS, RESAVE, RENAMED)
class NamesOutsideAsciiTest(unittest.TestCase):
    def facts(self, key: str) -> dict:
        return {k: _goldens.fact(key, k) for k in ("marker", "section", "group", "member")}

    def test_logic_kept_the_names_written_here(self):
        ours, logics = project_data(_goldens.path(OURS)), project_data(_goldens.path(RESAVE))
        self.assertEqual(names(ours), self.facts(OURS))
        self.assertEqual(names(logics), names(ours))
        self.assertEqual(text_records(logics), text_records(ours))

    def test_what_logic_showed_is_what_is_read(self):
        for key in (RESAVE, RENAMED):
            with self.subTest(key):
                shown, read = _goldens.fact(key, "shown"), names(project_data(_goldens.path(key)))
                self.assertEqual((read["marker"], read["group"], read["section"]),
                                 (shown["marker_list_cell"], shown["groups_name_field"], shown["arrangement_track"]))

    def test_logics_own_renames_read_from_rtf_and_utf8(self):
        data = project_data(_goldens.path(RENAMED))
        self.assertEqual(names(data), self.facts(RENAMED))
        self.assertEqual(sum(b"{\\rtf" in raw for raw in text_records(data)), 2)

    def test_the_commands_write_the_records_logic_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, want = Path(tmp), self.facts(OURS)
            a = written(self, "markers", BASE, "--rename", f"1={want['marker']}", out=out / "a")
            b = written(self, "arrangement", a, "--rename", f"1={want['section']}", out=out / "b")
            c = written(self, "group", b, "--create", want["group"], "--track", want["member"], out=out / "c")
            data, ours = project_data(c), project_data(_goldens.path(OURS))
            self.assertEqual(text_records(data), text_records(ours))
            self.assertEqual(names(data), want)

    def test_a_name_logic_wrote_as_rtf_is_renamed_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            a = written(self, "markers", RENAMED, "--rename", "1=Übergang 2", out=out / "a")
            b = written(self, "arrangement", a, "--rename", "1=Coração 2", out=out / "b")
            c = written(self, "group", b, "--group", "1", "--name", "Größe 2", out=out / "c")
            read = names(project_data(c))
            self.assertEqual((read["marker"], read["section"], read["group"]), ("Übergang 2", "Coração 2", "Größe 2"))


if __name__ == "__main__":
    unittest.main()
