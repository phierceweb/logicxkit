"""Values written into an AU state in place: the pairs and the FabFilter blob re-encoded into
the plist's own base64 span, the record's length and everything around it untouched."""

import base64
import plistlib
import struct
import unittest

from logicxkit.au.services.aupreset import parse_au_state
from logicxkit.au.services.austate_write import patch_ffbs, patch_pairs, replace_data
from logicxkit.au.services.embed import find_au_plists
from logicxkit.au.services.ffp import parse_ffp


def pairs(values: dict[int, float], count: int = 40) -> bytes:
    blob = bytearray(12 + 8 * count)
    struct.pack_into(">I", blob, 8, count)
    for i in range(count):
        struct.pack_into(">If", blob, 12 + 8 * i, i, values.get(i, 0.0))
    return bytes(blob)


def payload_with(**keys) -> bytes:
    plist = plistlib.dumps({"type": 1, "subtype": 2, "manufacturer": 3, "version": 1, "name": "x", **keys},
                           fmt=plistlib.FMT_XML)
    return bytes(180) + plist + b"\x00" * 20


class PatchTest(unittest.TestCase):
    def test_pairs_change_only_the_named_ids(self):
        blob = pairs({1: -18.0, 2: 0.6})
        new = patch_pairs(blob, {1: -30.0, 5: 0.25})
        got = dict(parse_au_state({"type": 1, "subtype": 2, "manufacturer": 3, "data": new}).param_pairs)
        self.assertEqual((got[1], got[5]), (-30.0, 0.25))
        self.assertAlmostEqual(got[2], 0.6, places=6)
        self.assertEqual(len(new), len(blob))
        with self.assertRaises(ValueError):
            patch_pairs(blob, {99: 1.0})

    def test_ffbs_values_by_id(self):
        blob = b"FFBS" + struct.pack("<II", 1, 6) + struct.pack("<6f", *range(6)) + b"trailer"
        new = patch_ffbs(blob, {2: 7.5, 5: -1.0})
        self.assertEqual(list(parse_ffp(new).values), [0.0, 1.0, 7.5, 3.0, 4.0, -1.0])
        self.assertTrue(new.endswith(b"trailer"))
        with self.assertRaises(ValueError):
            patch_ffbs(blob, {6: 0.0})


class ReplaceDataTest(unittest.TestCase):
    def test_the_span_keeps_its_length_and_wrapping(self):
        old = pairs({1: -18.0}, count=60)                        # long enough to wrap over several lines
        payload = payload_with(data=old, other=b"keep me")
        new = replace_data(payload, "data", patch_pairs(old, {1: -30.0, 7: 0.5}))
        self.assertEqual(len(new), len(payload))
        self.assertEqual(new[:180], payload[:180])
        self.assertEqual(new[-20:], payload[-20:])
        a, b = payload.index(b"<data>"), payload.index(b"</data>")
        self.assertEqual([i for i, c in enumerate(payload[a:b]) if c in b" \t\r\n"],
                         [i for i, c in enumerate(new[a:b]) if c in b" \t\r\n"])
        (_off, plist), = find_au_plists(new)
        st = parse_au_state(plist)
        got = dict(st.param_pairs)
        self.assertEqual((got[1], got[7]), (-30.0, 0.5))
        self.assertEqual(plist["other"], b"keep me")

    def test_a_blob_of_another_length_is_refused(self):
        payload = payload_with(data=pairs({}, count=4))
        with self.assertRaises(ValueError):
            replace_data(payload, "data", pairs({}, count=5))
        with self.assertRaises(ValueError):
            replace_data(payload, "missing", b"")

    def test_the_base64_is_what_the_library_would_write(self):
        blob = bytes(range(97))
        payload = payload_with(data=blob)
        new = replace_data(payload, "data", bytes(reversed(blob)))
        a, b = new.index(b"<data>") + 6, new.index(b"</data>")
        self.assertEqual(base64.b64decode(new[a:b]), bytes(reversed(blob)))


if __name__ == "__main__":
    unittest.main()
