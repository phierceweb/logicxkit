"""The chains command run in-process: the example config's chains onto a public corpus bundle
whose channels are given the config's strip references (Logic's own record, renamed), against the
strips under tests/corpus."""

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

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.mixer.chains import channel_references
from logicxkit.logic.services.mixer.slots import property_key_base, slot_bypassed
from logicxkit.logic.services.project.project import read_project
from logicxkit.logic.services.arrange.retrack import retrack_channels
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.transplant import channel_slots, copy_reference
from logicxkit.logic.services.stream.stream import project_records

INSERTS = "inserts-native-logic"            # Audio 1: Channel EQ -> Compressor; Audio 2 and 3 empty
REFERENCE = "strip-reference-library-logic"  # a reference record as Logic writes one, renamed per channel
STRIPS = ("strip-kick-ours", "strip-snare-ours", "strip-kit-mics-ours")
CONFIG = REPO / "config" / "example-chains.json"


def chain(bundle, label: str) -> list:
    return next((list(map(tuple, c["chain"])) for c in read_project(source(bundle))["channels"]
                 if c["label"] == label), [])


@_goldens.needs(INSERTS, REFERENCE, *STRIPS)
class ChainsCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bundle = self.out / "in" / source(INSERTS).name
        shutil.copytree(source(INSERTS), self.bundle)
        project_data = self.bundle / "Alternatives/000/ProjectData"
        raw = project_data.read_bytes()
        donor = _goldens.path(REFERENCE).joinpath("Alternatives/000/ProjectData").read_bytes()   # Logic's own record
        for label, name in (("Audio 1", "Kick.cst"), ("Audio 2", "Snare.cst")):       # the config's chain keys
            raw = copy_reference(donor, raw, src_owner=owner(donor, "Audio 1"), dst_owner=owner(raw, label))
            raw, _r = retrack_channels(raw, {owner(raw, label): name})
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
        before = data(self.bundle)                                 # three slots under a reference two keys up: the range grows one
        self.assertEqual((property_key_base(before), property_key_base(after)), (6, 7))
        keyed = lambda d: {o: sorted(r.key for r in project_records(d) if r.tag == b"UCuA" and r.owner == o and r.key >= 6) for o in channels(d)}  # noqa: E731
        self.assertEqual(keyed(after), {o: [k + 1 for k in keys] for o, keys in keyed(before).items()})   # every channel's records above the chain up one
        self.assertEqual(channel_references(after), {owner(after, "Audio 1"): "Kick.cst", owner(after, "Audio 2"): "Snare.cst"})

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
