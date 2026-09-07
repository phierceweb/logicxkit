"""TR5 Suite chain decode: ValueTree 'Chain' prop -> Session XML -> slots/params."""
import unittest

from logicxkit.au.services.tr5 import decode_tr5

from _juce import tree as _tree, var_bin as _var_bin


XML = (b'<?xml version="1.0"?>\n'
       b'<Session CurrentPreset="/x/A New Touch.tr5p" CurrentSnapshot="0">'
       b'<Slot SnapshotID="0" PresetPath="/x/A New Touch.tr5p">'
       b'<Slot0 Bypass="0" ChainNodeModuleGUID="guid-1">'
       b'<Module ThresholdL="6.9" InputL="1.1"/></Slot0>'
       b'<SlotMasterMatch Bypass="1"><Module/></SlotMasterMatch>'
       b'</Slot></Session>')


class TestDecodeTr5(unittest.TestCase):
    def test_decodes_chain_slots_and_params(self):
        state = _tree("State", [("Chain", _var_bin(XML))])
        out = decode_tr5(state)
        self.assertEqual(out["current_preset"], "/x/A New Touch.tr5p")
        snap = out["snapshots"][0]
        self.assertEqual(snap["snapshot"], "0")
        self.assertEqual(len(snap["slots"]), 1)  # MasterMatch excluded
        slot = snap["slots"][0]
        self.assertEqual(slot["guid"], "guid-1")
        self.assertEqual(slot["params"]["ThresholdL"], "6.9")

    def test_garbage_returns_none(self):
        self.assertIsNone(decode_tr5(b"not a value tree"))
        self.assertIsNone(decode_tr5(_tree("State", [("Chain", _var_bin(b"<Nope/>"))])))


if __name__ == "__main__":
    unittest.main()
