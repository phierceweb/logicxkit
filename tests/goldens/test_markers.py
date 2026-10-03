"""The marker track read from Logic's own five marker saves, and our edits held to them."""

import unittest

import _goldens
from logicxkit.logic.services.song.arrangement import marker_sequence, read_sections, section_sequence
from logicxkit.logic.services.song.events import BAR_ONE, events
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.song.markers import TO_NEXT, read_markers
from logicxkit.logic.services.song.markers_write import add_marker, delete_marker, move_marker, rename_marker
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

BAR = 3840
KEYS = {20: "regions-a20-crossfade-logic", 21: "markers-a21-created-logic", 22: "markers-a22-renamed-logic",
        23: "markers-a23-second-logic", 24: "markers-a24-moved-logic", 25: "markers-a25-deleted-logic"}


def load(k: int) -> bytes:
    return project_data(_goldens.path(KEYS[k]))


def marker_events(data: bytes) -> list[tuple]:
    """(tick, data line, third line) of each marker event, the head's flag byte aside."""
    records = project_records(data)
    t = marker_sequence(records)
    return [(e.tick, e.lines[0], e.lines[1:]) for e in events(records[t.end].raw[HEADER:])]


@_goldens.needs(*KEYS.values())
class ReadTest(unittest.TestCase):
    def test_logics_five_saves_read_as_the_marker_list_showed(self):
        want = {20: [], 21: [("Marker ##", 4 * BAR, TO_NEXT)], 22: [("Chorus", 4 * BAR, TO_NEXT)],
                23: [("Chorus", 4 * BAR, TO_NEXT), ("Marker ##", 6 * BAR, TO_NEXT)],
                24: [("Chorus", 5 * BAR, TO_NEXT), ("Marker ##", 6 * BAR, TO_NEXT)], 25: [("Chorus", 5 * BAR, TO_NEXT)]}
        for k, markers in want.items():
            with self.subTest(k):
                self.assertEqual([(m.name, m.tick - BAR_ONE, m.length) for m in read_markers(load(k))], markers)

    def test_the_marker_track_is_not_the_arrangement(self):
        records = project_records(load(24))
        self.assertNotEqual(section_sequence(records), marker_sequence(records).end)
        self.assertEqual([s.name for s in read_sections(load(24))], ["Intro", "Verse"])


@_goldens.needs(*KEYS.values())
class WriteTest(unittest.TestCase):
    def like(self, ours: bytes, logic: bytes, before: bytes):
        self.assertEqual(validate_project(ours), [])
        self.assertEqual(regressions(before, ours), [])
        self.assertEqual([(m.name, m.tick, m.length) for m in read_markers(ours)], [(m.name, m.tick, m.length) for m in read_markers(logic)])
        self.assertEqual(marker_events(ours), marker_events(logic))

    def test_add_rename_second_move_delete(self):
        self.like(add_marker(load(20), "Marker ##", tick=BAR_ONE + 4 * BAR), load(21), load(20))
        self.like(rename_marker(load(21), 1, "Chorus"), load(22), load(21))
        self.like(add_marker(load(22), "Marker ##", tick=BAR_ONE + 6 * BAR), load(23), load(22))
        self.like(move_marker(load(23), 1, BAR_ONE + 5 * BAR), load(24), load(23))
        self.like(delete_marker(load(24), 2), load(25), load(24))

    def test_two_markers_on_one_bar_are_moved_and_deleted_one_at_a_time(self):
        data = add_marker(add_marker(load(25), "Verse", tick=BAR_ONE + 8 * BAR), "Riff", tick=BAR_ONE + 8 * BAR)
        names = lambda d: [(m.name, m.tick) for m in read_markers(d)]  # noqa: E731
        self.assertEqual(names(data)[1:], [("Verse", BAR_ONE + 8 * BAR), ("Riff", BAR_ONE + 8 * BAR)])
        moved = move_marker(data, 3, BAR_ONE + 10 * BAR)
        self.assertEqual(names(moved)[1:], [("Verse", BAR_ONE + 8 * BAR), ("Riff", BAR_ONE + 10 * BAR)])
        gone = delete_marker(data, 2)
        self.assertEqual(names(gone)[1:], [("Riff", BAR_ONE + 8 * BAR)])
        self.assertEqual(sum(r.tag == b"qSxT" for r in project_records(gone)), sum(r.tag == b"qSxT" for r in project_records(data)) - 1)

    def test_command_line_edits_keep_the_inputs_numbers(self):
        from argparse import Namespace
        from logicxkit.logic._markers_cmd import _edits, _targets
        args = Namespace(edits=[("delete", "1"), ("rename", "2=Renamed"), ("add", "9:Outro: end")])
        out = _edits(args, load(24), _targets(args, load(24)), "000")
        self.assertEqual([(m.name, m.tick) for m in read_markers(out)], [("Renamed", BAR_ONE + 6 * BAR), ("Outro: end", BAR_ONE + 8 * BAR)])
        args = Namespace(edits=[("delete", "1"), ("add", "20:Bridge"), ("rename", "1=Renamed")])
        from logicxkit.logic._edit import CommandError
        with self.assertRaisesRegex(CommandError, "marker 1 was deleted by an earlier edit"):
            _edits(args, load(24), _targets(args, load(24)), "000")
        args = Namespace(edits=[("delete", "1"), ("add", "20:Bridge")])
        out = _edits(args, load(24), _targets(args, load(24)), "000")
        self.assertEqual([m.name for m in read_markers(out)], ["Marker ##", "Bridge"])

    def test_a_number_names_the_same_marker_in_every_alternative(self):
        import contextlib
        import io
        import shutil
        import tempfile
        from pathlib import Path
        from logicxkit.cli import main

        def run(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(["logic", "markers", *map(str, argv)])
            return rc, out.getvalue()

        def with_second(tmp: Path, second) -> Path:
            bundle = tmp / "two.logicx"
            shutil.copytree(_goldens.path(KEYS[24]), bundle)
            other = bundle / "Alternatives" / "001"
            shutil.copytree(sorted((bundle / "Alternatives").iterdir())[0], other)
            (other / "ProjectData").write_bytes(second((other / "ProjectData").read_bytes()))
            return bundle

        with tempfile.TemporaryDirectory() as tmp:
            bundle = with_second(Path(tmp), lambda d: add_marker(d, "Early", tick=BAR_ONE))
            rc, text = run(bundle, "--out", Path(tmp, "out"), "--delete", "2")
            self.assertEqual(rc, 0, text)
            (project,) = Path(tmp, "out").rglob("*.logicx")
            got = {p.parent.name: [m.name for m in read_markers(p.read_bytes())] for p in sorted(project.rglob("Alternatives/*/ProjectData"))}
            self.assertEqual(got, {"000": ["Chorus"], "001": ["Early", "Chorus"]})
            bundle = with_second(Path(tmp, "b"), lambda d: rename_marker(d, 2, "Other"))
            rc, text = run(bundle, "--out", Path(tmp, "b", "out"), "--delete", "2")
            self.assertEqual(rc, 1)
            self.assertIn("alternative 001 has no marker 'Marker ##' at bar 7", text)

    def test_a_marker_with_a_length_and_the_refusals(self):
        out = add_marker(load(25), "Bridge", tick=BAR_ONE + 8 * BAR, length=2 * BAR)
        self.assertEqual([(m.name, m.tick, m.length) for m in read_markers(out)][-1], ("Bridge", BAR_ONE + 8 * BAR, 2 * BAR))
        with self.assertRaisesRegex(ValueError, "the song has 1 marker"):
            rename_marker(load(25), 2, "x")
        with self.assertRaisesRegex(ValueError, "line separator"):
            add_marker(load(25), "Chorus\u2028é", tick=BAR_ONE)
        self.assertIn("Chorus — é", [m.name for m in read_markers(add_marker(load(25), "Chorus — é", tick=BAR_ONE))])


@_goldens.needs("markers-edits-ours", "markers-edits-resave-logic")
class LogicResavedTest(unittest.TestCase):
    def test_logic_kept_the_added_renamed_moved_and_deleted_markers(self):
        ours, logic = (project_data(_goldens.path(k)) for k in ("markers-edits-ours", "markers-edits-resave-logic"))
        self.assertEqual((validate_project(ours), validate_project(logic)), ([], []))
        want = [tuple(m) for m in _goldens.fact("markers-edits-ours", "markers")]
        self.assertEqual(want, [("Chorus A", BAR_ONE + 4 * BAR, TO_NEXT), ("Outro", BAR_ONE + 9 * BAR, 2 * BAR)])
        for data in (ours, logic):
            self.assertEqual([(m.name, m.tick, m.length) for m in read_markers(data)], want)
        self.assertEqual(marker_events(ours), marker_events(logic))


if __name__ == "__main__":
    unittest.main()
