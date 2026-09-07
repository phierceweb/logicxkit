"""Preset/strip decode orchestration — static paths (no AU host needed)."""
import plistlib
import struct
import unittest

from logicxkit.au.services.report import decode_preset_bytes, decode_strip_bytes
from _data import needs


def cc(s: str) -> int:
    v = 0
    for b in s.encode():
        v = (v << 8) | b
    return v


def proc2_aupreset_bytes(pairs) -> bytes:
    blob = struct.pack(">III", 0, 0, len(pairs)) + b"".join(
        struct.pack(">If", i, v) for i, v in pairs)
    return plistlib.dumps({
        "type": cc("aufx"), "subtype": cc("FC2p"), "manufacturer": cc("FabF"),
        "name": "Test Preset", "version": 0, "data": blob,
    }, fmt=plistlib.FMT_XML)


@needs("au")
class TestDecodePresetBytes(unittest.TestCase):
    def test_ffp_decodes_with_table_names(self):
        data = b"FC2p" + struct.pack("<II", 2, 3) + struct.pack("<3f", 0.0, -6.0, 0.4)
        out = decode_preset_bytes(data, suffix=".ffp", host=None)
        self.assertEqual(out["format"], "ffp")
        self.assertEqual(out["plugin"]["subtype"], "FC2p")
        names = [r["name"] for r in out["params"][:3]]
        self.assertEqual(names[1], "Threshold")

    def test_aupreset_static_path_decodes_pairs(self):
        out = decode_preset_bytes(proc2_aupreset_bytes([(1, -6.0), (2, 0.4)]),
                                  suffix=".aupreset", host=None)
        self.assertEqual(out["format"], "aupreset")
        self.assertEqual(out["preset_name"], "Test Preset")
        self.assertEqual(out["params"][0]["name"], "Threshold")
        self.assertTrue(out["params"][0]["changed"])

    def test_unknown_suffix_raises(self):
        with self.assertRaises(ValueError):
            decode_preset_bytes(b"x", suffix=".xyz", host=None)


@needs("au")
class TestDecodeStripBytes(unittest.TestCase):
    def test_finds_and_decodes_embedded_states(self):
        strip = b"OCuA-junk" + proc2_aupreset_bytes([(1, -12.0)]) + b"tail"
        out = decode_strip_bytes(strip, host=None)
        self.assertEqual(len(out), 1)
        st = out[0]
        self.assertEqual(st["plugin"]["manufacturer"], "FabF")
        self.assertEqual(st["decode_path"], "static")
        self.assertEqual(st["params"][0]["name"], "Threshold")

    def test_no_states_is_empty_list(self):
        self.assertEqual(decode_strip_bytes(b"nothing here", host=None), [])


if __name__ == "__main__":
    unittest.main()
