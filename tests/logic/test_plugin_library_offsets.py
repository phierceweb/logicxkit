"""A donor's instance-id bytes measured against the library's other instances of its plug-in,
and a v5 native donor retargeted for a v3 project."""

import tempfile
import unittest
from pathlib import Path

from _records import rec

from logicxkit.logic.services.plugin_library import Donor, find_donor, library_offsets, load_library
from logicxkit.utils.data import PACKAGED


def slot(payload: bytes) -> bytes:
    return rec(b"UCuA", 0, 4, payload, 5)


class LibraryOffsetsTest(unittest.TestCase):
    def test_bytes_that_differ_inside_the_id_window_are_the_offsets(self):
        base = bytearray(200)
        other = bytearray(base)
        other[10], other[185], other[190] = 1, 7, 9          # 10 is settings territory, not an id
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a-v5.slot").write_bytes(slot(bytes(base)))
            (Path(tmp) / "b-v5.slot").write_bytes(slot(bytes(other)))
            donor = Donor("a", slot(bytes(base)), "native", 5)
            self.assertEqual(library_offsets(donor, [Path(tmp)]), (185, 190))
            self.assertEqual(library_offsets(donor, [Path(tmp) / "missing"]), ())

    def test_a_library_holding_only_the_donor_itself_measures_nothing(self):
        payload = bytes(200)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a-v5.slot").write_bytes(slot(payload))
            self.assertEqual(library_offsets(Donor("a", slot(payload), "native", 5), [Path(tmp)]), ())


class RetargetTest(unittest.TestCase):
    def test_a_packaged_v5_native_is_retargeted_for_a_v3_project(self):
        donors = load_library([PACKAGED / "donors"])
        v5 = find_donor(donors, "Compressor", width=None, version=5)
        v3 = find_donor(donors, "Compressor", width=None, version=3)
        self.assertEqual((v5.version, v3.version), (5, 3))
        self.assertEqual(v3.key, f"{v5.key}->v3")
        self.assertEqual((v3.type_id, v3.name, v3.kind), (v5.type_id, v5.name, "native"))
        self.assertNotEqual(v3.raw, v5.raw)


if __name__ == "__main__":
    unittest.main()
