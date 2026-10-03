"""tracking-chains on the corpus's instrument track: the channel's instrument stays whatever it
is; only effects are made native or removed."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, run, source, written

from logicxkit.logic.services.mixer.plugins import slot_payloads

INSTRUMENT = "tracks-instrument-logic"          # Inst 1 holds an Apple AU generator in slot 1


def inst_slots(bundle_data: bytes) -> list[str]:
    return [r.name for r, _p in slot_payloads(bundle_data) if r.channel == "Inst 1"]


@_goldens.needs(INSTRUMENT)
class TrackingChainsInstrumentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_the_instrument_channel_keeps_its_instrument(self):
        self.assertEqual(inst_slots(data(INSTRUMENT)), ["appl/afpl"])
        dest = written(self, "tracking-chains", INSTRUMENT, out=self.out)
        self.assertEqual(inst_slots(data(dest)), ["appl/afpl"])

    def test_the_plan_says_so(self):
        code, text = run("tracking-chains", source(INSTRUMENT), "--plan")
        self.assertEqual(code, 0, text)
        self.assertIn("slot 1: appl/afpl kept: the channel's instrument", text)
        self.assertNotIn("removed", text)


if __name__ == "__main__":
    unittest.main()
