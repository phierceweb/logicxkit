"""Logic project analyzer tests — channel-chain + preset + track-name extraction.

Synthetic ``ProjectData`` bytes: a channel is an ``OCuA <ver> 00 0e 00`` header (version
word 06 or 07 by Logic build), a `` Audio N`` label, padding past the 260-byte slot window,
then ``.CuA``-tagged insert slots each carrying a preset filename + plugin name.

The real-file part of tests/logic/test_project.py; skips without the owner's files."""

import os
import unittest
from pathlib import Path
import _goldens
import _paths
from logicxkit.logic.services.project import (
    strip_chain,
)

TRK_TEMPLATE = _goldens.path("tracking-template")
MIX_TEMPLATE = str(_paths.project("Mix"))
SLO_CST = str(_paths.channel_strip("Guitar/Guitar SLO.cst"))


@_goldens.needs("tracking-template")
class GoldenTrackingTemplateTest(unittest.TestCase):
    def test_kick_channel_references_its_strip(self):
        from logicxkit.logic import read_project
        chans = {c["label"]: c for c in read_project(TRK_TEMPLATE)["channels"]}
        self.assertIn("Kick In.cst", chans["Audio 1"].get("cst", []))


@unittest.skipIf(not os.path.isdir(MIX_TEMPLATE), "Mix template not present")
class GoldenMixLabelsTest(unittest.TestCase):
    def test_bus_chains_get_real_labels(self):
        # Logic's "bus" strips are Aux channel objects (the raw Bus objects carry no
        # inserts) — the doc's Drm/Cym/Bass bus chains surface as 'Aux N', never '?'
        from logicxkit.logic import read_project
        labels = {c["label"] for c in read_project(Path(MIX_TEMPLATE))["channels"]}
        self.assertTrue(any(lab.startswith("Aux") for lab in labels), labels)
        self.assertNotIn("?", labels)


@unittest.skipIf(not os.path.exists(SLO_CST), "real Guitar SLO.cst not present")
class GoldenStripChainTest(unittest.TestCase):
    def test_real_strip_chain_extracts(self):
        chain = strip_chain(Path(SLO_CST).read_bytes())
        self.assertTrue(chain, "no chain extracted from real .cst")
        self.assertEqual(chain[0][0], "Soldano")


if __name__ == "__main__":
    unittest.main()
