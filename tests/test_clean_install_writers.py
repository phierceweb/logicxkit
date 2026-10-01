"""With the data root empty, every writer that loads a template or a donor writes from the
packaged data."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _goldens

ROOT = Path(__file__).resolve().parents[1]
P = _goldens.path          # public keys resolve to their bundles; file names differ from keys


def run(*argv, out: Path) -> subprocess.CompletedProcess:
    empty = out / "empty-data-root"
    empty.mkdir(exist_ok=True)
    env = {**os.environ, "LOGICXKIT_DATA": str(empty)}
    return subprocess.run([sys.executable, "-m", "logicxkit.cli", "logic", *map(str, argv)],
                          capture_output=True, text=True, env=env, cwd=ROOT)


@_goldens.needs("tracks-three-audio-logic", "levels-resave-logic", "stack-folder-flattened-logic")
class CleanInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _ok(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("MissingData", r.stdout + r.stderr)

    def test_add_track(self):
        self._ok(run("add-track", P("tracks-three-audio-logic"), "--out", self.out / "a",
                     "--name", "Room", "--after", "Audio 3", out=self.out))

    def test_stack_create(self):
        self._ok(run("stack-create", P("stack-folder-flattened-logic"), "--out", self.out / "b",
                     "--name", "Drums", "--track", "Audio 1", "--track", "Audio 2", out=self.out))

    def test_send_add(self):
        self._ok(run("send", P("levels-resave-logic"), "--out", self.out / "c",
                     "--add", "Audio 1=Bus 1", out=self.out))

    def test_arrangement_add(self):
        self._ok(run("arrangement", P("stack-folder-flattened-logic"), "--out", self.out / "d",
                     "--add", "1:8:Intro:verse", out=self.out))

    def test_chains_plan(self):
        self._ok(run("chains", P("tracks-three-audio-logic"), "--config",
                     ROOT / "config" / "example-chains.json", "--plan", out=self.out))


if __name__ == "__main__":
    unittest.main()
