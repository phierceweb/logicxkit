"""`tracking-chains`' flags and which of a plug-in's families are live, without a project."""

import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_translate import au_payload, native_payload  # noqa: E402

from logicxkit.logic._tracking_chains_cmd import LATENT, live_families, register  # noqa: E402
from logicxkit.logic.services.translate.translate import load_maps  # noqa: E402
from logicxkit.utils.data import PACKAGED  # noqa: E402

MAPS = load_maps([PACKAGED / "translate"])


class LiveFamiliesTest(unittest.TestCase):
    def test_a_one_family_plug_in_is_its_map(self):
        self.assertEqual([m.plugin for m in live_families(au_payload({1: -18.0}), MAPS)], ["Pro-C 2"])
        self.assertEqual(live_families(native_payload([0.0] * 5, type_id=9999), MAPS), [])

    def test_neutrons_live_families_come_eq_first_and_a_bypassed_element_stays_out(self):
        from test_translate import NeutronTest
        t = NeutronTest()
        self.assertEqual([m.family for m in live_families(t.payload(), MAPS)], ["eq", "gate", "compressor"])
        gate_off = t.payload(**{"Gate Expander": {**t.GATE, "Bypass": True}})
        self.assertEqual([m.family for m in live_families(gate_off, MAPS)], ["eq", "compressor"])


class FlagsTest(unittest.TestCase):
    def test_flags_and_the_lookahead_set(self):
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers())
        args = parser.parse_args(["tracking-chains", "p", "--plan", "--keep-unmapped"])
        self.assertEqual((args.plan, args.out, args.keep_unmapped, args.keep_lookahead, args.channel), (True, None, True, False, None))
        self.assertEqual(set(LATENT.values()), {"Linear Phase EQ", "Multipressor", "Adaptive Limiter", "Limiter", "Enveloper"})


if __name__ == "__main__":
    unittest.main()
