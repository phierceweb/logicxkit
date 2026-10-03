"""The read-only commands run in-process on public corpus bundles: recdiff, manifest, plugins,
capabilities, sessionplayer, decode, prefs; and retrack, the one writer outside the gate."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import data, owner, run, source, written
from _records import chan, proj, rec
from test_patch import bundle as patch_bundle

from logicxkit.logic.services.mixer.chains import channel_references
from logicxkit.logic.services.mixer.transplant import copy_reference

BASE, PAUSE = "controlbar-base", "controlbar-pause-on"
INSERTS = "inserts-native-logic"
ALL_NATIVE = "inserts-native-all-logic"
PLAYER = "sessionplayer-track-logic"
PATCH = "patch-built-loaded-logic"
MARKERS = "markers-a21-created-logic"
LOGIC_PREFS = Path.home() / "Library/Preferences/com.apple.logic10.plist"


@_goldens.needs(BASE, PAUSE, INSERTS, ALL_NATIVE, PLAYER, PATCH, MARKERS)
class ReaderCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_recdiff_exits_1_on_a_difference_and_0_without(self):
        code, text = run("recdiff", source(BASE), source(PAUSE))
        self.assertEqual(code, 1, text)
        self.assertIn("changed 1", text)
        code, text = run("recdiff", source(BASE), source(PAUSE), "--json")
        self.assertEqual(code, 1, text)
        json.loads(text)
        code, text = run("recdiff", source(BASE), source(BASE))
        self.assertEqual(code, 0, text)

    def test_manifest(self):
        code, text = run("manifest", source(INSERTS))
        self.assertEqual(code, 0, text)
        self.assertIn("Channel EQ", text)
        code, text = run("manifest", source(INSERTS), "--json")
        self.assertIn("tracks", json.loads(text))

    def test_plugins(self):
        code, text = run("plugins", source(INSERTS))
        self.assertEqual(code, 0, text)
        self.assertIn("Channel EQ", text)
        code, text = run("plugins", source(INSERTS), "--json")
        self.assertEqual(code, 0, text)
        json.loads(text)

    def test_project_prints_values_without_float_noise(self):
        """The Gain plug-in stores its 0 dB as a float a hair above zero; the listing reads 0.0."""
        code, text = run("project", source(ALL_NATIVE))
        self.assertEqual(code, 0, text)
        self.assertIn("'Gain': 0.0", text)
        self.assertNotIn("e-1", text)
        code, text = run("project", source(ALL_NATIVE), "--json")
        self.assertEqual(code, 0, text)
        json.loads(text)

    def test_capabilities(self):
        code, text = run("capabilities")
        self.assertEqual(code, 0, text)
        self.assertIn("apply-template", text)
        code, verbose = run("capabilities", "--verbose")
        self.assertGreater(len(verbose), len(text))

    def test_sessionplayer(self):
        code, text = run("sessionplayer", source(PLAYER))
        self.assertEqual(code, 0, text)
        self.assertIn("Pop Rock", text)
        code, text = run("sessionplayer", source(PLAYER), "--json")
        self.assertEqual(code, 0, text)
        json.loads(text)

    def test_decode_a_saved_strip(self):
        cst = self.out / "Audio 1.cst"
        code, text = run("strip-save", source(INSERTS), "--channel", "Audio 1", "-o", cst)
        self.assertEqual(code, 0, text)
        code, text = run("decode", cst)
        self.assertEqual(code, 0, text)
        self.assertIn("Channel EQ", text)

    def test_patch_scans_a_folder_of_bundles(self):
        patch_bundle(self.out, "Drums")
        code, text = run("patch", self.out)
        self.assertEqual(code, 0, text)
        self.assertIn("Drums", text)
        code, text = run("patch", self.out, "--json")
        self.assertEqual(code, 0, text)
        self.assertTrue(json.loads(text))

    def test_markers(self):
        code, text = run("markers", source(MARKERS))
        self.assertEqual(code, 0, text)
        self.assertIn("bar", text)
        code, text = run("markers", source(MARKERS), "--json")
        self.assertEqual(code, 0, text)
        self.assertTrue(json.loads(text))

    def test_retrack_one_channel(self):
        """No public save carries a strip reference, so Audio 1 is given one first."""
        bundle = self.out / "in" / source(INSERTS).name
        shutil.copytree(source(INSERTS), bundle)
        project_data = bundle / "Alternatives/000/ProjectData"
        before = project_data.read_bytes()
        target = owner(before, "Audio 1")
        donor = proj(chan(0, "Audio 1"), rec(b"UCuA", 0, 13, bytes(16) + b"Old Strip.cst".ljust(176, b"\0"), 5))
        project_data.write_bytes(copy_reference(donor, before, src_owner=0, dst_owner=target))
        self.assertEqual(channel_references(project_data.read_bytes())[target], "Old Strip.cst")
        library = self.out / "library" / "Drums"                # retrack refuses a strip the library lacks
        library.mkdir(parents=True)
        (library / "Kick In.cst").write_bytes(b"")
        with mock.patch.dict(os.environ, {"LOGICXKIT_STRIP_ROOT": str(library.parent)}):
            dest = written(self, "retrack", bundle, "--channel", "Audio 1=Kick In.cst", out=self.out / "out")
            code, text = run("retrack", bundle, "--channel", "Audio 1=Missing.cst", "--out", self.out / "no")
        self.assertEqual(channel_references(data(dest))[target], "Kick In.cst")
        self.assertEqual((code, "Missing.cst" in text), (1, True), text)

    @unittest.skipUnless(LOGIC_PREFS.exists(), "no Logic preferences on this machine")
    def test_prefs_reads(self):
        code, text = run("prefs")
        self.assertEqual(code, 0, text)
        self.assertTrue(text.strip())
        code, text = run("prefs", "--export", self.out / "prefs.json")
        self.assertEqual(code, 0, text)
        json.loads((self.out / "prefs.json").read_text())
        code, text = run("prefs", "--pane", "View")
        self.assertEqual(code, 0, text)
        self.assertIn("View", text)


if __name__ == "__main__":
    unittest.main()
