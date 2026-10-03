"""A bundle whose first alternative an earlier Logic saved: a plan, and the listing a write prints
after itself, read the alternative the write edits, not the one it leaves."""

import shutil
import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import run

THREE = "tracks-three-audio-logic"          # Audio 1-3, no stack, no plug-in
FOLDER = "stack-folder-logic"               # Audio 1-3 in folder `Sub 1`
PLUGGED = "auto-lanes-resave-logic"         # a Compressor on Audio 2
OLD = 2511


def mixed(root: Path, stale_key: str) -> Path:
    """THREE as `Alternatives/001`, ``stale_key``'s alternative restamped to ``OLD`` as `000`."""
    project = root / "in" / "probe.logicx"
    shutil.copytree(_goldens.path(THREE), project)
    alts = project / "Alternatives"
    (alts / "000").rename(alts / "001")
    shutil.copytree(_goldens.path(stale_key) / "Alternatives" / "000", alts / "000")
    data = bytearray((alts / "000" / "ProjectData").read_bytes())
    struct.pack_into("<H", data, 4, OLD)
    (alts / "000" / "ProjectData").write_bytes(data)
    return project


@_goldens.needs(THREE, FOLDER, PLUGGED)
class StalePlansTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_the_stacks_listing_reads_the_current_alternative(self):
        code, text = run("stacks", mixed(self.root, FOLDER))
        self.assertEqual(code, 0, text)
        self.assertIn("0 stack(s)", text)

    def test_the_listing_after_a_write_reads_what_was_written(self):
        project = mixed(self.root, FOLDER)
        code, text = run("stack-create", project, "--name", "D", "--track", "Audio 1", "--out", self.root / "a")
        self.assertEqual(code, 0, text)
        code, text = run("stacks", self.root / "a" / project.name, "--move", "Audio 2:D", "--out", self.root / "b")
        self.assertEqual(code, 0, text)
        listed = text.split("Audio 2 -> D", 1)[1]
        self.assertIn("D: Audio 1, Audio 2", listed)
        self.assertNotIn("Sub 1", listed)

    def test_a_swap_plan_reads_the_alternative_the_run_edits(self):
        code, text = run("swap-plugin", mixed(self.root, PLUGGED), "--from", "Compressor", "--to", "Noise Gate",
                         "--plan")
        self.assertEqual(code, 1, text)
        self.assertIn("no slot holds 'Compressor'", text)
        self.assertNotIn("000:", text)


if __name__ == "__main__":
    unittest.main()
