"""The staging tool's gates, against a bundle from the tracked corpus and a hand-built one: a
title without the neutral prefix is refused, a private word in a note is found, and an autosave
never crosses into the corpus."""

import importlib.util
import plistlib
import tempfile
import unittest
from pathlib import Path

from _paths import REPO, tracked

TOOL = REPO / "tools" / "stage_public.py"
if not TOOL.exists():                       # the sdist ships neither the corpus nor its staging tool
    raise unittest.SkipTest(f"no staging tool at {TOOL}")
spec = importlib.util.spec_from_file_location("stage_public", TOOL)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
CORPUS = REPO / "tests" / "corpus"


def _bundle(root: Path, names: dict) -> Path:
    b = root / "x.logicx"
    (b / "Resources").mkdir(parents=True)
    (b / "Resources" / "ProjectInformation.plist").write_bytes(plistlib.dumps({"VariantNames": names}))
    return b


@unittest.skipUnless(CORPUS.is_dir(), "no public corpus")
class TitlesTest(unittest.TestCase):
    def test_every_corpus_bundle_carries_the_neutral_prefix(self):
        bundles = sorted(p for p in CORPUS.glob("*.logicx") if (p / "Resources/ProjectInformation.plist").exists())
        self.assertTrue(bundles)
        for b in bundles:
            with self.subTest(b.name):
                self.assertTrue(stage.titles(b), "the dict of variant names reads as titles")
                self.assertEqual(stage.unneutral(b), [])

    def test_a_title_without_the_prefix_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = _bundle(Path(tmp), {"0": "CLAUDE ok", "1": "My Song"})
            self.assertEqual(stage.unneutral(b), ["My Song"])
            self.assertEqual(stage.unneutral(_bundle(Path(tmp) / "y", {"0": "{PROJECT_NAME}"})), [])


class WordsTest(unittest.TestCase):
    def test_a_private_word_is_found_across_case_and_separators(self):
        self.assertEqual(stage.leaks("the blue-heron take", ["Blue Heron", "other"]), ["Blue Heron"])
        self.assertEqual(stage.leaks("nothing here", ["Blue Heron"]), [])

    def test_autosaves_backups_and_window_images_are_skipped(self):
        skipped = stage.SKIP("x", ["Autosave", "Project File Backups", "WindowImage_1.jpg", "ProjectData",
                                   "DisplayState.plist"])
        self.assertEqual(sorted(skipped), ["Autosave", "Project File Backups", "WindowImage_1.jpg"])


def _bookmark(*items: tuple[int, bytes]) -> bytes:
    """A bookmark blob: header, data section (TOC offset, then length/type/payload items)."""
    import struct
    body = b"".join(struct.pack("<II", len(v), k) + v + bytes(-len(v) % 4) for k, v in items)
    data = struct.pack("<I", 4 + len(body)) + body + struct.pack("<I", 0)
    return b"book" + struct.pack("<III", 16 + len(data), 0x10050000, 16) + data


class BookmarkTest(unittest.TestCase):
    """A macOS bookmark (Space Designer's `Ref_Bookmark`) keeps its path as separate components
    and records the volume: none of it a home-directory string for the word scrub to find."""

    def test_the_account_the_volume_uuid_and_the_ids_are_blanked_at_their_length(self):
        uuid = b"01234567-89AB-4CDE-8F01-23456789ABCD"
        raw = b"lead" + _bookmark((stage.STRING, b"Users"), (stage.STRING, b"someone"), (stage.STRING, b"Music"),
                                  (stage.U64, b"\x11" * 8), (stage.DATE, b"\x22" * 8), (stage.STRING, uuid)) + b"tail"
        clean, n = stage.scrub_bookmarks(raw)
        self.assertEqual((len(clean), n), (len(raw), 4))
        for gone in (b"someone", uuid, b"\x11" * 8, b"\x22" * 8):
            self.assertNotIn(gone, clean)
        self.assertIn(b"xxxxxxx", clean)
        self.assertIn(b"Music", clean)
        self.assertEqual(stage.scrub_bookmarks(clean), (clean, 0))

    @unittest.skipUnless(CORPUS.is_dir(), "no public corpus")
    def test_no_tracked_file_keeps_a_bookmark_field(self):
        files = tracked("tests/corpus", "src/logicxkit/data")
        if files is None:
            self.skipTest("not a git checkout")
        leaky = [f for f in files if stage.bookmark_leaks((REPO / f).read_bytes())]
        self.assertEqual(leaky, [])


if __name__ == "__main__":
    unittest.main()
