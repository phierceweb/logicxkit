"""FabFilter .ffp preset files: 12-byte header + float32-LE parameter table."""
import struct
import unittest

from logicxkit.au.services.ffp import FfpError, parse_ffp


def make_ffp(magic: bytes = b"FC2p", version: int = 2, values=(6.0, -16.0, 0.62)) -> bytes:
    return (magic + struct.pack("<II", version, len(values))
            + b"".join(struct.pack("<f", v) for v in values))


class TestParseFfp(unittest.TestCase):
    def test_parses_header_and_values(self):
        p = parse_ffp(make_ffp())
        self.assertEqual(p.magic, "FC2p")
        self.assertEqual(p.version, 2)
        self.assertEqual(len(p.values), 3)
        self.assertAlmostEqual(p.values[0], 6.0, places=5)
        self.assertAlmostEqual(p.values[1], -16.0, places=5)
        self.assertAlmostEqual(p.values[2], 0.62, places=5)

    def test_rejects_short_file(self):
        with self.assertRaises(FfpError):
            parse_ffp(b"FC2p\x02\x00")

    def test_rejects_truncated_value_table(self):
        data = make_ffp()[:-2]
        with self.assertRaises(FfpError):
            parse_ffp(data)

    def test_rejects_nonascii_magic(self):
        with self.assertRaises(FfpError):
            parse_ffp(make_ffp(magic=b"\x00\x01\x02\x03"))

    def test_rejects_implausible_count(self):
        data = b"FC2p" + struct.pack("<II", 2, 100_000) + b"\x00" * 16
        with self.assertRaises(FfpError):
            parse_ffp(data)


if __name__ == "__main__":
    unittest.main()
