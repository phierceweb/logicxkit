"""The write gate: structural invariants checked on the bytes a writer produces.

`validate_project` covers the record walk, the header total and plugin slots — nothing else.
Everything a row-adding writer can break (sequence links, the bound-object index, send flags)
was checked only in tests, so a corrupt write reported success. These are those checks, moved
where production can run them.

Logic's own files are not spotless, so the gate compares a writer's output against the input
it was given rather than demanding zero problems.
"""

import unittest
from pathlib import Path

import _paths  # noqa: F401



def sessions() -> list[Path]:
    """Every session in the reference store: the legacy projects and the finished mixes."""
    return sorted(p for d in ("legacy", "mixes") for p in (_paths.RESOURCES / d).rglob("*.logicx"))


class ProblemsOnRealFilesTest(unittest.TestCase):
    """Every session Logic wrote must survive its own gate, or the gate is too strict to use."""

    def setUp(self):
        self.files = sessions()
        if not self.files:
            self.skipTest("no sessions under resources/legacy or resources/mixes")

    def test_a_logic_written_session_regresses_against_itself_zero_times(self):
        from logicxkit.logic.services.integrity import regressions
        for project in self.files:
            with self.subTest(project.stem):
                data = sorted(project.glob("Alternatives/*/ProjectData"))[0].read_bytes()
                self.assertEqual(regressions(data, data), [])

    def test_the_baseline_is_reported_not_demanded(self):
        """Pre-existing problems are counted, never treated as a failure."""
        from logicxkit.logic.services.integrity import structural_report
        for project in self.files:
            with self.subTest(project.stem):
                data = sorted(project.glob("Alternatives/*/ProjectData"))[0].read_bytes()
                report = structural_report(data)
                self.assertIn("link_errors", report)
                self.assertIsInstance(report["link_errors"], int)


class RegressionDetectionTest(unittest.TestCase):
    def setUp(self):
        self.files = sessions()
        if not self.files:
            self.skipTest("no sessions under resources/legacy or resources/mixes")
        self.project = self.files[0]
        self.data = sorted(self.project.glob("Alternatives/*/ProjectData"))[0].read_bytes()
        from logicxkit.logic.services.project import project_metadata
        self.count = project_metadata(self.project).get("tracks")

    def test_a_new_link_error_is_caught(self):
        import struct

        from logicxkit.logic.services.insert import HEADER, project_records
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.sequence import TABLE_SLOT_AT, index_table, table_entries
        recs = project_records(self.data)
        table_at = index_table(recs)
        start = 24 + sum(len(r.raw) for r in recs[:table_at]) + HEADER
        entries = table_entries(recs[table_at].raw[HEADER:])
        broken = bytearray(self.data)
        # send one entry to a slot no triple occupies
        struct.pack_into("<H", broken, start + entries[0][0] + TABLE_SLOT_AT, 0xEEE)
        found = regressions(self.data, bytes(broken))
        self.assertTrue(found, "a corrupted index table must not pass the gate")

    def test_a_truncated_write_is_caught(self):
        from logicxkit.logic.services.integrity import regressions
        self.assertTrue(regressions(self.data, self.data[:-200]))

    def test_an_untouched_copy_is_clean(self):
        from logicxkit.logic.services.integrity import regressions
        self.assertEqual(regressions(self.data, self.data), [])


if __name__ == "__main__":
    unittest.main()


class DiscardOnRefusalTest(unittest.TestCase):
    """A refused write must leave nothing — a step may already have moved NumberOfTracks, and a
    bundle that opens but disagrees with its own metadata is worse than no bundle."""

    def setUp(self):
        if not sessions():
            self.skipTest("no sessions under resources/legacy or resources/mixes")
        self.src = sessions()[0]

    def test_a_refused_edit_takes_the_whole_copy_with_it(self):
        import tempfile

        from logicxkit.logic._edit import CommandError, bump_track_count, edit_copy
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"

            def wreck(data, count, data_file):
                bump_track_count(data_file, 1)      # the plist moves before the refusal
                return data[:-200]

            with self.assertRaises(CommandError):
                edit_copy(self.src, out, wreck)
            self.assertEqual(list(out.iterdir()) if out.exists() else [], [])

    def test_an_accepted_edit_writes_and_reads_back(self):
        import tempfile

        from logicxkit.logic._edit import edit_copy
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            dest = edit_copy(self.src, out, lambda data, count, f: data)
            landed = sorted(dest.glob("Alternatives/*/ProjectData"))[0].read_bytes()
            original = sorted(self.src.glob("Alternatives/*/ProjectData"))[0].read_bytes()
            self.assertEqual(landed, original)
