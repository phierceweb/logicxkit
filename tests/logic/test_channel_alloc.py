"""Channel numbering is a u16 field, and must be read and written as one.

`new_inst_channel` and `shifted_channel` incremented it as a single byte. Above 255 that raises
`byte must be in range(0, 256)`, which is why instrument `add-track` died on every legacy
session — and `apply-template` swallowed the exception and kept writing.
"""

import struct
import unittest

import _paths  # noqa: F401
from _records import rec

HDR = 36
NUMBER_AT, INST_NUMBER2_AT, LABEL_AT, LABEL_LEN = 6, 128, 60, 16


def inst_channel(number: int, *, size: int = 257) -> bytes:
    p = bytearray(size)
    p[24] = p[25] = 1
    struct.pack_into("<H", p, NUMBER_AT, number)
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" Inst {number + 1}".encode().ljust(LABEL_LEN, b"\x00")
    return rec(b"OCuA", 0, 0xFFFF, bytes(p), 7)


def number_of(raw: bytes) -> int:
    return struct.unpack_from("<H", raw, HDR + NUMBER_AT)[0]


def label_of(raw: bytes) -> str:
    at = HDR + LABEL_AT
    return raw[at:at + LABEL_LEN].split(b"\x00")[0].decode().strip()


class InstNumberIsSixteenBitTest(unittest.TestCase):
    def test_a_small_number_still_increments(self):
        from logicxkit.logic.services.channel_alloc import new_inst_channel
        out, number = new_inst_channel(inst_channel(3), owner=9, object_uuid=bytes(16),
                                       output_uuid=None)
        self.assertEqual((number_of(out), number), (4, 5))

    def test_it_crosses_the_byte_boundary(self):
        from logicxkit.logic.services.channel_alloc import new_inst_channel
        out, number = new_inst_channel(inst_channel(255), owner=9, object_uuid=bytes(16),
                                       output_uuid=None)
        self.assertEqual((number_of(out), number), (256, 257))

    def test_the_second_copy_of_the_number_crosses_it_too(self):
        from logicxkit.logic.services.channel_alloc import new_inst_channel
        src = bytearray(inst_channel(10))
        struct.pack_into("<H", src, HDR + INST_NUMBER2_AT, 255)
        out, _ = new_inst_channel(bytes(src), owner=9, object_uuid=bytes(16), output_uuid=None)
        self.assertEqual(struct.unpack_from("<H", out, HDR + INST_NUMBER2_AT)[0], 256)


class ShiftedChannelIsSixteenBitTest(unittest.TestCase):
    def _shift(self, number: int) -> bytes:
        from logicxkit.logic.services.channel_alloc import shifted_channel
        from logicxkit.logic.services.insert import project_records
        from _records import proj
        raw = inst_channel(number)
        record = project_records(proj(raw))[0]
        return shifted_channel(record.raw, record)

    def test_a_small_number_still_shifts(self):
        out = self._shift(3)
        self.assertEqual((number_of(out), label_of(out)), (4, "Inst 5"))

    def test_it_crosses_the_byte_boundary(self):
        out = self._shift(255)
        self.assertEqual((number_of(out), label_of(out)), (256, "Inst 257"))


if __name__ == "__main__":
    unittest.main()
