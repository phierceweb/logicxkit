"""Embedded AU plist scanning (moved to logicxkit.au; logicxkit.logic re-exports)."""
import plistlib
import unittest

from logicxkit.au.services.embed import find_au_plists, fourcc


def plist_bytes(d: dict) -> bytes:
    return plistlib.dumps(d, fmt=plistlib.FMT_XML)


class TestFindAuPlists(unittest.TestCase):
    def test_finds_dict_plists_with_offsets(self):
        pl = plist_bytes({"manufacturer": 1, "name": "x"})
        data = b"junk" * 5 + pl + b"tail" + plist_bytes({"k": 2})
        hits = find_au_plists(data)
        self.assertEqual(len(hits), 2)
        off, d = hits[0]
        self.assertEqual(data[off:off + 5], b"<?xml")
        self.assertEqual(d["name"], "x")

    def test_skips_broken_xml(self):
        data = b"<?xml nope" + b"x" * 30 + b"</plist>"
        self.assertEqual(find_au_plists(data), [])

    def test_skips_non_dict_plists(self):
        data = plist_bytes(["a", "b"])  # array, not dict
        self.assertEqual(find_au_plists(data), [])


class TestFourcc(unittest.TestCase):
    def test_printable(self):
        self.assertEqual(fourcc(0x46616246), "FabF")

    def test_unprintable_falls_back_to_hex(self):
        self.assertEqual(fourcc(0x00010203), "0x00010203")


class TestLogicReexport(unittest.TestCase):
    def test_neural_module_still_exposes_scanner(self):
        from logicxkit.logic import find_au_plists as legacy
        self.assertIs(legacy, find_au_plists)


if __name__ == "__main__":
    unittest.main()
