"""The coded saves over the effect tables' by-order placements are staged
(`effectcheck-<name>-code-base`, `-code0`…); what they say is read in `CodedSavesTest`."""

import unittest

import _goldens

KEYS = tuple(k for k in sorted(_goldens.manifest()) if k.startswith("effectcheck-") and k.endswith("-code-base"))


@_goldens.needs(*KEYS)
class EffectCheckTest(unittest.TestCase):
    def test_every_coded_check_is_staged(self):
        self.assertEqual(len(KEYS), 6)
        for key in KEYS:
            with self.subTest(key):
                self.assertTrue(_goldens.fact(key, "codes"))



if __name__ == "__main__":
    unittest.main()
