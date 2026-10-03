"""A persistent donor library.

Cloning a plugin requires a real Logic-written slot record of that plugin at the right class
version. Sourcing those from whichever project happens to be open is fragile — the Enveloper
exists in no session at all, and native reverbs existed nowhere until the user saved some. The
library keeps harvested records in the repo so any project can be given any plugin.

Records are version-tagged because a donor only drops cleanly into a project of the same class
version.
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from logicxkit.logic import donor_key, harvest_donors, load_donor_library
from logicxkit.logic.services.mixer.donors import MANIFEST
from logicxkit.logic.services.mixer.slot_width import SLOT_COUNT_AT

HDR = 36


def rec(tag: bytes, owner: int, key: int, payload: bytes, ver: int = 5) -> bytes:
    h = bytearray(HDR)
    h[0:4] = tag
    struct.pack_into("<H", h, 4, ver)
    struct.pack_into("<H", h, 14, owner)
    struct.pack_into("<H", h, 18, key)
    struct.pack_into("<I", h, 28, len(payload))
    return bytes(h) + payload


def slot(type_id: int, ver: int = 5, n: int = 8, variant: int | None = None, width: int | None = None,
         blocks: int = 1, extra: int = 0) -> bytes:
    p = bytearray(220 + extra + (blocks - 1) * (24 + n * 4))
    if variant is not None:                     # config index 1 at +81, the variant id at +116
        p[81] = 1
        struct.pack_into("<H", p, 116, variant)
    if width is not None:
        for at in SLOT_COUNT_AT:
            p[at] = width
    struct.pack_into("<III", p, 172, 24 + n * 4, 1, n)
    for b in range(blocks):                     # a second block: the compare state a used window leaves
        at = 184 + b * (24 + n * 4)
        p[at:at + 8] = b"GAMETSPP"
        struct.pack_into("<I", p, at + 8, type_id)
    return rec(b"UCuA", 0, 4, bytes(p), ver)


def proj(*records: bytes) -> bytes:
    body = b"".join(records)
    head = bytearray(24)
    struct.pack_into("<I", head, 0x10, len(body))
    return bytes(head) + body


class DonorKeyTest(unittest.TestCase):
    def test_key_includes_type_and_version(self):
        self.assertEqual(donor_key(287, 5), "287-v5")

    def test_same_plugin_different_versions_do_not_collide(self):
        self.assertNotEqual(donor_key(287, 2), donor_key(287, 5))


class HarvestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_record_with_a_compare_block_is_not_a_width_sibling(self):
        """The other width's record is filed beside the first only when it is longer for its
        width, not for the compare block a used plug-in window leaves in it."""
        clean_mono, edited_stereo = slot(154, width=1), slot(154, width=2, blocks=2)
        self.assertEqual(harvest_donors(proj(clean_mono, edited_stereo), self.root), ["154-v5"])
        manifest = json.loads((self.root / MANIFEST).read_text())
        self.assertEqual((manifest["154-v5"]["blocks"], manifest["154-v5"].get("fixed_width")), (1, None))
        longer_stereo = slot(154, width=2, extra=48)
        self.assertEqual(harvest_donors(proj(longer_stereo), self.root), ["154-stereo-v5"])
        manifest = json.loads((self.root / MANIFEST).read_text())
        self.assertTrue(manifest["154-v5"]["fixed_width"] and manifest["154-stereo-v5"]["fixed_width"])

    def test_a_shorter_record_of_the_other_width_is_a_sibling_even_after_a_two_block_first(self):
        """BPM Counter's never-opened mono record carries two blocks and its stereo one a single
        shorter block: both are Logic's, and both are filed."""
        two_block_mono, stereo = slot(242, width=1, blocks=2), slot(242, width=2)
        self.assertEqual(harvest_donors(proj(two_block_mono, stereo), self.root), ["242-stereo-v5", "242-v5"])

    def test_a_second_plug_in_of_a_shared_block_type_files_beside_the_first(self):
        data = proj(slot(147, variant=217), slot(147, variant=201), slot(147, variant=217))
        keys = harvest_donors(data, self.root, {147: "Echo", (147, 200): "Tape Delay"})
        self.assertEqual(keys, ["147-v5", "147v200-v5"])
        manifest = json.loads((self.root / MANIFEST).read_text())
        self.assertEqual((manifest["147-v5"]["variant"], manifest["147-v5"]["plugin"]), (216, "Echo"))
        self.assertEqual((manifest["147v200-v5"]["variant"], manifest["147v200-v5"]["plugin"]), (200, "Tape Delay"))

    def test_a_named_member_files_by_variant_whichever_comes_first(self):
        """The type's own name (its `PLUGIN_NAMES` entry) marks the member that keeps the plain key."""
        data = proj(slot(147, variant=201), slot(147, variant=217))
        keys = harvest_donors(data, self.root, {147: "Echo", (147, 200): "Tape Delay", (147, 216): "Echo"})
        self.assertEqual(keys, ["147-v5", "147v200-v5"])
        manifest = json.loads((self.root / MANIFEST).read_text())
        self.assertEqual((manifest["147-v5"]["plugin"], manifest["147v200-v5"]["plugin"]), ("Echo", "Tape Delay"))

    def test_harvests_one_record_per_plugin_version(self):
        data = proj(slot(287, 5), slot(150, 5), slot(287, 5))
        written = harvest_donors(data, self.root)
        self.assertEqual(sorted(written), ["150-v5", "287-v5"])
        self.assertTrue((self.root / "287-v5.slot").exists())

    def test_round_trips_through_the_library(self):
        data = proj(slot(287, 5))
        harvest_donors(data, self.root)
        lib = load_donor_library(self.root)
        self.assertIn("287-v5", lib)
        raw, type_id, ver = lib["287-v5"]
        self.assertEqual((type_id, ver), (287, 5))
        self.assertEqual(raw, [r for r in [slot(287, 5)]][0])

    def test_does_not_overwrite_an_existing_donor(self):
        harvest_donors(proj(slot(287, 5, n=8)), self.root)
        first = (self.root / "287-v5.slot").read_bytes()
        harvest_donors(proj(slot(287, 5, n=12)), self.root)
        self.assertEqual((self.root / "287-v5.slot").read_bytes(), first)

    def test_ignores_records_with_no_parameter_chunk(self):
        self.assertEqual(harvest_donors(proj(rec(b"UCuA", 0, 4, b"\x00" * 40)), self.root), [])

    def test_empty_library_loads_empty(self):
        self.assertEqual(load_donor_library(self.root / "nope"), {})


class HarvestFromStripTest(unittest.TestCase):
    """Some plugins only exist in saved .cst strips (Enveloper, Gain, Limiter). A .cst has no
    24-byte file header, so the record stream starts at 0."""

    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_harvests_from_a_strip(self):
        strip = rec(b"OCuA", 0, 0xFFFF, b"\x00" * 40) + slot(157, 5)
        self.assertEqual(harvest_donors(strip, self.root, start=0), ["157-v5"])

    def test_project_offset_still_default(self):
        self.assertEqual(harvest_donors(proj(slot(199, 5)), self.root), ["199-v5"])

    def test_a_key_to_skip_is_not_written_and_is_reported(self):
        skipped: list[str] = []
        written = harvest_donors(proj(slot(199, 5), slot(157, 5)), self.root, skip={"199-v5"}, skipped=skipped)
        self.assertEqual((written, skipped), (["157-v5"], ["199-v5"]))
        self.assertFalse((self.root / "199-v5.slot").exists())


class BaseDonorFallbackTest(unittest.TestCase):
    """A project can contain no Channel EQ at all, so the in-project donor search returns None
    and every chain wanting an EQ is silently degraded. The donor library holds a record at the
    right class version — it must be used rather than dropping the plugin."""

    def _eq_slot(self, ver: int) -> bytes:
        payload = bytearray(200)
        payload[184:192] = b"GAMETSPP"
        struct.pack_into("<III", payload, 172, 24 + 16, 1, 4)
        struct.pack_into("<I", payload, 192, 236)
        h = bytearray(36)
        h[0:4] = b"UCuA"
        struct.pack_into("<H", h, 4, ver)
        struct.pack_into("<H", h, 14, 0)
        struct.pack_into("<H", h, 18, 4)
        struct.pack_into("<I", h, 28, len(payload))
        return bytes(h) + bytes(payload)

    def test_library_supplies_an_eq_the_project_lacks(self):
        from logicxkit.logic import base_donors

        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            (lib / "236-v3.slot").write_bytes(self._eq_slot(3))
            empty = bytes(24)          # a project with no slot records at all
            eq, _comp, from_lib = base_donors(empty, 3, lib)
            self.assertIsNotNone(eq, "the library's v3 Channel EQ must be used")
            self.assertIn("Channel EQ", from_lib)

    def test_a_project_donor_still_wins_over_the_library(self):
        from logicxkit.logic import base_donors

        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            (lib / "236-v3.slot").write_bytes(self._eq_slot(3))
            own = self._eq_slot(3)
            head = bytearray(24)
            struct.pack_into("<I", head, 0x10, len(own))
            eq, _comp, from_lib = base_donors(bytes(head) + own, 3, lib)
            self.assertEqual(eq, own)
            self.assertEqual(from_lib, [])

    def test_no_library_match_at_the_projects_version_yields_none(self):
        from logicxkit.logic import base_donors

        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            (lib / "236-v5.slot").write_bytes(self._eq_slot(5))
            eq, _comp, _from_lib = base_donors(bytes(24), 3, lib)
            self.assertIsNone(eq, "a v5 record must not be transplanted into a v3 project")


class MergedLibrariesTest(unittest.TestCase):
    def test_the_first_library_shadows_the_second_and_both_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp, "a"), Path(tmp, "b")
            first.mkdir()
            second.mkdir()
            (first / "147-v5.slot").write_bytes(slot(147, ver=5, n=8))
            (second / "147-v5.slot").write_bytes(slot(147, ver=5, n=9))
            (second / "150-v5.slot").write_bytes(slot(150, ver=5))
            lib = load_donor_library([first, second])
            self.assertEqual(sorted(lib), ["147-v5", "150-v5"])
            self.assertEqual(lib["147-v5"][0], slot(147, ver=5, n=8))

    def test_a_single_path_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "150-v5.slot").write_bytes(slot(150, ver=5))
            self.assertEqual(list(load_donor_library(Path(tmp))), ["150-v5"])
