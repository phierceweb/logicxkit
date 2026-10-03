"""The chains command run in-process: the example config's chains onto a public corpus bundle
whose channels are given the config's strip references, against the strips under tests/corpus."""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import data, owner, run, source, written
from _paths import REPO
from _records import chan, proj, rec

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.mixer.slots import slot_bypassed
from logicxkit.logic.services.project.project import read_project
from logicxkit.logic.services.mixer.transplant import channel_slots, copy_reference

INSERTS = "inserts-native-logic"            # Audio 1: Channel EQ -> Compressor; Audio 2 and 3 empty
STRIPS = ("strip-kick-ours", "strip-snare-ours", "strip-kit-mics-ours")
CONFIG = REPO / "config" / "example-chains.json"


def chain(bundle, label: str) -> list:
    return next((list(map(tuple, c["chain"])) for c in read_project(source(bundle))["channels"]
                 if c["label"] == label), [])


@_goldens.needs(INSERTS, *STRIPS)
class ChainsCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bundle = self.out / "in" / source(INSERTS).name
        shutil.copytree(source(INSERTS), self.bundle)
        project_data = self.bundle / "Alternatives/000/ProjectData"
        raw = project_data.read_bytes()
        for label, name in (("Audio 1", "Kick.cst"), ("Audio 2", "Snare.cst")):       # the config's chain keys
            donor = proj(chan(0, label), rec(b"UCuA", 0, 13, bytes(16) + name.encode().ljust(176, b"\0"), 5))
            raw = copy_reference(donor, raw, src_owner=0, dst_owner=owner(raw, label))
        project_data.write_bytes(raw)
        strips = _goldens.path(STRIPS[0]).parents[3]
        env = mock.patch.dict(os.environ, {"LOGICXKIT_STRIP_ROOT": str(strips)})
        env.start()
        self.addCleanup(env.stop)

    def test_plan_names_the_chains_and_what_they_replace(self):
        code, text = run("chains", self.bundle, "--config", CONFIG, "--plan")
        self.assertEqual(code, 0, text)
        self.assertIn("Kick.cst", text)
        self.assertIn("REPLACE", text)
        self.assertIn("1 channel(s) would lose a chain", text)
        self.assertFalse((self.out / "out").exists())

    def test_the_configs_chains_go_on_the_referenced_channels(self):
        dest = written(self, "chains", self.bundle, "--config", CONFIG, out=self.out / "out")
        self.assertEqual(chain(dest, "Audio 1"), [("Channel EQ", "Demo Trk - Kick"), ("Enveloper", "Demo Trk - Kick"),
                                                  ("Compressor", "Demo Trk - Kick")])
        self.assertEqual(chain(dest, "Audio 2"), [("Gain", "Demo Trk - Snare"), ("Channel EQ", "Demo Trk - Snare"),
                                                  ("Compressor", "Demo Trk - Snare")])
        after = data(dest)
        self.assertEqual([slot_bypassed(r.raw) for r in channel_slots(after, owner(after, "Audio 1"))], [False, True, False])
        self.assertEqual(chain(dest, "Audio 3"), [])

    def test_strict_refuses_a_chain_that_differs_from_its_strip_and_writes_nothing(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = logicxkit_main(["logic", "chains", str(self.bundle), "--config", str(CONFIG),
                                   "--out", str(self.out / "strict"), "--strict"])
        self.assertNotEqual(code, 0, buf.getvalue())
        self.assertIn("source strip", buf.getvalue())
        self.assertFalse((self.out / "strict" / self.bundle.name).exists())


if __name__ == "__main__":
    unittest.main()
