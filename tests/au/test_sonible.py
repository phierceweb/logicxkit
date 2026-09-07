"""sonible jucePluginState: schema-less protobuf field walk (values, no names)."""
import struct
import unittest

from logicxkit.au.services.sonible import decode_sonible


def _varint(field: int, v: int) -> bytes:
    return bytes([(field << 3) | 0]) + bytes([v])  # small values only


def _float(field: int, v: float) -> bytes:
    return bytes([(field << 3) | 5]) + struct.pack("<f", v)


def _ld(field: int, payload: bytes) -> bytes:
    return bytes([(field << 3) | 2, len(payload)]) + payload  # len < 128


class TestDecodeSonible(unittest.TestCase):
    def test_walks_fields_and_nested_message(self):
        params = _varint(1, 0) + _float(2, 50.0) + _float(4, -100.0) + _varint(12, 1)
        state = _ld(1, b"smartGate") + _ld(3, params) + _ld(4, b"\xff" * 100)
        out = decode_sonible(state)
        self.assertEqual(out["fields"]["1"], "smartGate")
        self.assertEqual(out["fields"]["3"]["2"], 50.0)
        self.assertEqual(out["fields"]["3"]["4"], -100.0)
        self.assertEqual(out["fields"]["3"]["12"], 1)

    def test_large_blob_summarized_not_walked(self):
        big = bytes([(4 << 3) | 2, 0x80, 0x40]) + b"\x00" * 8192  # 8192-byte field 4
        state = _ld(1, b"smartGate") + big
        out = decode_sonible(state)
        self.assertEqual(out["fields"]["4"], "bytes[8192]")

    def test_garbage_returns_none(self):
        self.assertIsNone(decode_sonible(b"\xff\xff\xff\xff"))


if __name__ == "__main__":
    unittest.main()
