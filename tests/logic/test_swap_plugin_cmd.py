"""`swap-plugin`'s flags and the names a slot answers to, without a project."""

import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_translate import au_payload, native_payload  # noqa: E402

from logicxkit.logic._swap_plugin_cmd import register, slot_names  # noqa: E402
from logicxkit.logic.services.translate import load_maps  # noqa: E402
from logicxkit.utils.data import PACKAGED  # noqa: E402

MAPS = load_maps([PACKAGED / "translate"])


class SlotNamesTest(unittest.TestCase):
    def test_one_of_logics_own_answers_to_its_name_type_id_and_map_name(self):
        self.assertEqual(slot_names(native_payload([0.0] * 29), MAPS), {"compressor", "154"})

    def test_a_third_party_answers_to_its_code_and_its_map_name(self):
        self.assertEqual(slot_names(au_payload({1: -18.0}), MAPS), {"fabf/fc2p", "pro-c 2"})

    def test_an_unknown_native_answers_to_its_type_id_alone(self):
        self.assertEqual(slot_names(native_payload([0.0] * 5, type_id=9999), MAPS), {"9999"})


class FlagsTest(unittest.TestCase):
    def test_from_and_to_are_required_and_the_rest_default_off(self):
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers())
        args = parser.parse_args(["swap-plugin", "p", "--from", "Pro-C 2", "--to", "Compressor", "--plan"])
        self.assertEqual((args.source, args.target, args.plan, args.out, args.no_translate, args.keep_automation, args.channel),
                         ("Pro-C 2", "Compressor", True, None, False, False, None))
        with self.assertRaises(SystemExit):
            parser.parse_args(["swap-plugin", "p", "--to", "Compressor"])


if __name__ == "__main__":
    unittest.main()
