"""The write gate refuses a strip reference that leaves its channel's record run."""

import unittest

from _records import chan, proj, rec
from test_integrity import project, standard

from logicxkit.logic.services.insert import project_records
from logicxkit.logic.services.integrity import regressions, structural_report


def ref(owner: int, key: int, name: str) -> bytes:
    p = bytearray(192)
    p[16:16 + len(name)] = name.encode()
    return rec(b"UCuA", owner, key, bytes(p), 5)


def shell() -> bytes:
    """The 14-byte OCuA shell before Audio 1 and, in a run, past the last channel."""
    return rec(b"OCuA", 0, 0xFFFF, bytes(14), 7)


def session(*, ref_0_at_end: bool = False, size: int = 257) -> bytes:
    """The integrity tests' readable song, with two channels and their references ahead of it."""
    kick = ref(0, 13, "Kick In.cst")
    mixer = [shell(), chan(0, "Audio 1", size=size), *([] if ref_0_at_end else [kick]),
             chan(1, "Audio 2", size=size), ref(1, 13, "Kick Out.cst"),
             shell(), shell(), *([kick] if ref_0_at_end else [])]
    return proj(*mixer, *(r.raw for r in project_records(project(standard()))))


class MisplacedReferenceTest(unittest.TestCase):
    def test_a_reference_past_the_closing_shells_is_named_by_owner(self):
        report = structural_report(session(ref_0_at_end=True))
        self.assertIsNone(report["unreadable"])
        self.assertEqual(report["misplaced_references"], [0])

    def test_references_inside_their_channel_runs_are_not(self):
        self.assertEqual(structural_report(session())["misplaced_references"], [])

    def test_a_channel_record_the_size_of_a_legacy_save_still_counts_as_the_channel(self):
        self.assertEqual(structural_report(session(size=196))["misplaced_references"], [])

    def test_the_gate_refuses_the_move_and_stays_silent_on_one_the_input_had(self):
        moved = session(ref_0_at_end=True)
        found = regressions(session(), moved)
        self.assertEqual(len(found), 1, found)
        self.assertIn("strip reference", found[0])
        self.assertIn("[0]", found[0])
        self.assertEqual(regressions(moved, moved), [])

    def test_bytes_that_are_no_project_read_as_unreadable_with_every_field_empty(self):
        report = structural_report(b"not a project")
        self.assertIsNotNone(report["unreadable"])
        self.assertEqual((report["misplaced_references"], report["validate"], report["regions"]), ([], [], []))
        self.assertTrue(regressions(session(), b"not a project")[0].startswith("the result cannot be read back"))


if __name__ == "__main__":
    unittest.main()
