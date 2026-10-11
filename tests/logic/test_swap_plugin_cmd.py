"""`swap-plugin`'s flags and the names a slot answers to, without a project."""

import argparse
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_translate import au_payload, native_payload  # noqa: E402

from logicxkit.logic._swap_plugin_cmd import register, shared_names, slot_names  # noqa: E402
from logicxkit.logic.services.translate.translate import load_maps  # noqa: E402
from logicxkit.utils.data import PACKAGED  # noqa: E402

MAPS = load_maps([PACKAGED / "translate"])


class SlotNamesTest(unittest.TestCase):
    def test_one_of_logics_own_answers_to_its_name_type_id_and_map_name(self):
        self.assertEqual(slot_names(native_payload([0.0] * 29), MAPS), {"compressor", "154"})

    def test_a_third_party_answers_to_its_code_and_its_map_name(self):
        self.assertEqual(slot_names(au_payload({1: -18.0}), MAPS), {"fabf/fc2p", "pro-c 2"})

    def test_an_unknown_native_answers_to_its_type_id_alone(self):
        self.assertEqual(slot_names(native_payload([0.0] * 5, type_id=9999), MAPS), {"9999"})

    def test_a_coded_slot_answers_to_its_code_and_logics_name(self):
        p = bytearray(176)                                       # Quick Sampler: no float block, a MELC header
        struct.pack_into("<H", p, 4, 1)
        p[120:129], p[132:136], p[140:144], p[151] = b"Q-Sampler", b"MELC", b"TRRP", 8
        self.assertEqual(slot_names(bytes(p), MAPS), {"prrt", "quick sampler"})


class SharedNamesTest(unittest.TestCase):
    def test_an_id_several_plug_ins_share_names_them_all(self):
        self.assertEqual(shared_names("inwr"), ["Studio Bass", "Studio Horns", "Studio Piano", "Studio Strings", "Vintage Mellotron"])
        self.assertEqual(shared_names(" 147 "), ["Echo", "Tape Delay"])
        self.assertEqual(len(shared_names("273")), 36)

    def test_an_id_one_plug_in_carries_and_a_name_name_none(self):
        for source in ("PRRT", "154", "Studio Bass", "Pro-C 2"):
            with self.subTest(source):
                self.assertEqual(shared_names(source), [])


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
