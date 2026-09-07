"""AU ClassInfo dicts (.aupreset files / .cst-embedded plists) -> typed state."""
import struct
import unittest

from logicxkit.au.services.aupreset import parse_au_state


def cc(s: str) -> int:
    v = 0
    for b in s.encode():
        v = (v << 8) | b
    return v


def make_data_blob(pairs) -> bytes:
    head = struct.pack(">III", 0, 0, len(pairs))
    return head + b"".join(struct.pack(">If", i, v) for i, v in pairs)


def make_plist(**extra) -> dict:
    pl = {"type": cc("aufx"), "subtype": cc("FC2p"), "manufacturer": cc("FabF"),
          "name": "Example - Test", "version": 0}
    pl.update(extra)
    return pl


class TestParseAuState(unittest.TestCase):
    def test_identity_fourccs(self):
        st = parse_au_state(make_plist())
        self.assertEqual((st.type, st.subtype, st.manufacturer), ("aufx", "FC2p", "FabF"))
        self.assertEqual(st.name, "Example - Test")

    def test_data_pairs_decode(self):
        st = parse_au_state(make_plist(data=make_data_blob([(0, 1.5), (5, -3.25)])))
        self.assertEqual(st.param_pairs, [(0, 1.5), (5, -3.25)])

    def test_pair_count_mismatch_is_graceful(self):
        blob = make_data_blob([(0, 1.5)])[:-2]  # truncated
        st = parse_au_state(make_plist(data=blob))
        self.assertIsNone(st.param_pairs)

    def test_non_pair_data_is_kept_raw(self):
        st = parse_au_state(make_plist(FabFilterPluginState=b"FFBS" + b"\x00" * 12))
        self.assertIsNone(st.param_pairs)
        self.assertIn("FabFilterPluginState", st.blobs)

    def test_missing_identity_defaults(self):
        st = parse_au_state({})
        self.assertEqual(st.subtype, "0x00000000")
        self.assertIsNone(st.name)


if __name__ == "__main__":
    unittest.main()
