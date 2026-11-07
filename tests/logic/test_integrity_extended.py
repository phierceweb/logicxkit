"""A song container with an entry that runs past whole 80-byte chunks must come out of a write as it
went in: the writers move entries 80 bytes at a time and would strand the extra row."""

import unittest

from _records import env_obj, proj, track
from test_regions import entry, flat, song

from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.stream.integrity_regions import extended_events
from logicxkit.logic.services.stream.stream import project_records

ROW = bytes(7) + b"\xbe" + bytes(8)
ROWS = [track(0, 10), track(1, 20)]


def project(*entries: bytes) -> bytes:
    return proj(env_obj(10, "a"), env_obj(20, "b"), env_obj(30, "c"), *song(ROWS, list(entries)), *flat(10, 20, 30))


def touched(e: bytes) -> bytes:
    return e[:60] + b"\x01" + e[61:]


class ExtendedEntryTest(unittest.TestCase):
    def test_an_untouched_container_passes(self):
        data = project(entry(10, 1), ROW, entry(20, 2))
        self.assertEqual(regressions(data, data), [])

    def test_an_empty_container_holds_no_extended_entry(self):
        self.assertIsNone(extended_events(project_records(project())))

    def test_a_changed_container_is_refused(self):
        before = project(entry(10, 1), ROW, entry(20, 2))
        found = regressions(before, project(entry(10, 1), ROW, touched(entry(20, 2))))
        self.assertTrue(any("past whole 80-byte chunks" in f for f in found), found)

    def test_a_write_that_makes_a_container_extended_is_refused_too(self):
        before = project(entry(10, 1), entry(20, 2))
        found = regressions(before, project(entry(10, 1), ROW, entry(20, 2)))
        self.assertTrue(any("past whole 80-byte chunks" in f for f in found), found)

    def test_the_same_change_without_the_row_is_not(self):
        before = project(entry(10, 1), entry(20, 2))
        found = regressions(before, project(entry(10, 1), touched(entry(20, 2))))
        self.assertFalse(any("past whole 80-byte chunks" in f for f in found), found)


if __name__ == "__main__":
    unittest.main()
