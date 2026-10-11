"""tracking-chains on the corpus's instrument track: the channel's instrument stays whatever it
is; only effects are made native or removed."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, run, source, written

from logicxkit.logic.services.mixer.plugins import slot_payloads

INSTRUMENT = "tracks-instrument-logic"          # Inst 1 holds an Apple AU generator in slot 1
IO = "instrument-fx-io-logic"                   # Inst 1 with Logic's I/O in slot 2: a coded slot, no float block


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


class OwnSlotsAreKeptTest(unittest.TestCase):
    """A slot of Logic's own is kept whatever state it carries: a coded one (a sampler), a `GAME`
    header with no float block (a stateless Remix FX, Alchemy), one with a block."""

    def test_every_kind_of_own_slot_is_kept(self):
        import struct
        from argparse import Namespace
        from test_plugins import HDR, float_block, headed_slot
        from logicxkit.logic._tracking_chains_cmd import _slot_lines
        from logicxkit.logic.services.mixer.plugins import plugin_identity
        args = Namespace(plan=True, keep_lookahead=False, keep_unmapped=False)
        for slot in (headed_slot(0, 2, b"Q-Sampler", b"MELC", 0, b"TRRP", flags=8),
                     headed_slot(0, 4, b"Remix FX", b"GAME", 0, struct.pack("<I", 314)),
                     headed_slot(0, 3, b"Channel EQ", b"GAME", 0, struct.pack("<I", 236), state=float_block(236))):
            payload = slot[HDR:]
            with self.subTest(payload[120:130]):
                self.assertEqual(_slot_lines(b"", 0, 2, payload, plugin_identity(payload), args, {}, [], [], {}, None, None)[1:],
                                 ([], "kept"))


@_goldens.needs(IO)
class TrackingChainsCodedSlotTest(unittest.TestCase):
    """One of Logic's own named by a four-letter code is Logic's own: kept, never removed as a
    third-party with no native analogue."""

    def test_an_io_slot_is_kept(self):
        self.assertEqual(inst_slots(data(IO)), ["appl/afpl", "I/O"])
        code, text = run("tracking-chains", source(IO), "--plan")
        self.assertEqual(code, 0, text)
        self.assertNotIn("removed", text)
        self.assertIn("nothing to change", text)
        with tempfile.TemporaryDirectory() as tmp:
            dest = written(self, "tracking-chains", IO, out=Path(tmp))
            self.assertEqual(inst_slots(data(dest)), ["appl/afpl", "I/O"])


if __name__ == "__main__":
    unittest.main()
