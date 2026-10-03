"""Channel numbering is a u16 field, and must be read and written as one.

`new_inst_channel` and `shifted_channel` incremented it as a single byte. Above 255 that raises
`byte must be in range(0, 256)`, which is why instrument `add-track` died on every legacy
session — and `apply-template` swallowed the exception and kept writing.
"""

import struct
import unittest

import _paths  # noqa: F401
from _records import chan, rec

HDR = 36
NUMBER_AT, INST_NUMBER2_AT, LABEL_AT, LABEL_LEN = 6, 128, 60, 16


def inst_channel(number: int, *, size: int = 257) -> bytes:
    p = bytearray(size)
    p[24] = p[25] = 1
    struct.pack_into("<H", p, NUMBER_AT, number)
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" Inst {number + 1}".encode().ljust(LABEL_LEN, b"\x00")
    return rec(b"OCuA", 0, 0xFFFF, bytes(p), 7)


def sub_channel(number: int, *, size: int = 257) -> bytes:
    """`Sub N` stores N at +6 — 1-based, unlike the other classes (every Sub strip Logic wrote)."""
    p = bytearray(size)
    p[24] = p[25] = 1
    struct.pack_into("<H", p, NUMBER_AT, number)
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" Sub {number}".encode().ljust(LABEL_LEN, b"\x00")
    return rec(b"OCuA", 381, 0xFFFF, bytes(p), 7)


def number_of(raw: bytes) -> int:
    return struct.unpack_from("<H", raw, HDR + NUMBER_AT)[0]


def label_of(raw: bytes) -> str:
    at = HDR + LABEL_AT
    return raw[at:at + LABEL_LEN].split(b"\x00")[0].decode().strip()


class InstNumberIsSixteenBitTest(unittest.TestCase):
    def test_a_small_number_still_increments(self):
        from logicxkit.logic.services.mixer.channel_alloc import new_inst_channel
        out, number = new_inst_channel(inst_channel(3), owner=9, object_uuid=bytes(16),
                                       output_uuid=None)
        self.assertEqual((number_of(out), number), (4, 5))

    def test_it_crosses_the_byte_boundary(self):
        from logicxkit.logic.services.mixer.channel_alloc import new_inst_channel
        out, number = new_inst_channel(inst_channel(255), owner=9, object_uuid=bytes(16),
                                       output_uuid=None)
        self.assertEqual((number_of(out), number), (256, 257))

    def test_the_second_copy_of_the_number_crosses_it_too(self):
        from logicxkit.logic.services.mixer.channel_alloc import new_inst_channel
        src = bytearray(inst_channel(10))
        struct.pack_into("<H", src, HDR + INST_NUMBER2_AT, 255)
        out, _ = new_inst_channel(bytes(src), owner=9, object_uuid=bytes(16), output_uuid=None)
        self.assertEqual(struct.unpack_from("<H", out, HDR + INST_NUMBER2_AT)[0], 256)


class InstWidthTest(unittest.TestCase):
    """`--stereo` on an instrument track: the width bytes of Logic's own stereo instrument
    channel (`sessionplayer-track-logic`), mono as before without it."""

    def _width(self, **kw) -> tuple[int, ...]:
        from logicxkit.logic.services.mixer.channel_alloc import new_inst_channel
        out, _ = new_inst_channel(inst_channel(3), owner=9, object_uuid=bytes(16), output_uuid=None, **kw)
        return tuple(out[HDR + at] for at in (78, 81, 86, 123))

    def test_mono_is_the_default(self):
        self.assertEqual(self._width(), (243, 0, 0, 1))

    def test_stereo_writes_logics_stereo_bytes(self):
        self.assertEqual(self._width(stereo=True), (247, 8, 1, 2))


def with_class(raw: bytes, ver: int) -> bytes:
    buf = bytearray(raw)
    struct.pack_into("<H", buf, 4, ver)
    return bytes(buf)


class InstChannelFollowsItsClassTest(unittest.TestCase):
    MARK, OUT = bytes(range(1, 17)), bytes(range(17, 33))

    def _new(self, template: bytes) -> bytes:
        from logicxkit.logic.services.mixer.channel_alloc import new_inst_channel
        out, _ = new_inst_channel(template, owner=9, object_uuid=self.MARK, output_uuid=self.OUT)
        return out[HDR:]

    def test_class_7_binds_at_len_48_whatever_the_size(self):
        for size in (201, 225, 257):
            with self.subTest(size):
                p = self._new(inst_channel(3, size=size))
                self.assertEqual((p[-48:-32], p[-32:-16], p[-16:]),
                                 (self.MARK, self.OUT, bytes(16)))

    def test_class_6_binds_in_the_last_16_bytes_and_leaves_what_is_before_them(self):
        for size in (225, 233):
            with self.subTest(size):
                template = bytearray(with_class(inst_channel(3, size=size), 6))
                template[-32:-16] = b"\xaa" * 16
                p = self._new(bytes(template))
                self.assertEqual((p[-32:-16], p[-16:]), (b"\xaa" * 16, self.MARK))

    def test_a_class_no_file_here_has_is_refused(self):
        with self.assertRaisesRegex(ValueError, "class-5 channel record keeps no own uuid"):
            self._new(with_class(inst_channel(3), 5))


class OtherMakersFollowTheClassTest(unittest.TestCase):
    MARK = bytes(range(1, 17))

    def test_a_sub_strip_binds_in_the_last_16_bytes_at_class_6(self):
        from logicxkit.logic.services.mixer.channel_alloc import new_sub_channel
        out = new_sub_channel(with_class(sub_channel(4, size=233), 6), number=5, owner=382,
                              uuid=self.MARK)
        self.assertEqual((out[-16:], out[-48:-32]), (self.MARK, bytes(16)))

    def test_an_input_gets_its_own_uuid_there_too(self):
        from logicxkit.logic.services.mixer.channel_alloc import new_input_channel
        template = bytearray(chan(35, "Input 1", uuid=self.MARK, size=205, ver=6))
        template[-32:-16] = b"\xaa" * 16
        out = new_input_channel(bytes(template), number=2, owner=36)
        self.assertEqual(out[-32:-16], b"\xaa" * 16)
        self.assertNotIn(out[-16:], (self.MARK, bytes(16)))

    def test_binding_an_audio_stub_is_refused_at_class_6(self):
        from logicxkit.logic.services.mixer.channel_alloc import bind_audio_stub
        stub = chan(9, "Audio 10", in_use=False, size=233, ver=6)
        with self.assertRaisesRegex(ValueError, "class-6 channel record keeps no input uuid"):
            bind_audio_stub(stub, object_uuid=self.MARK, input_uuid=bytes(range(17, 33)),
                            output_uuid=None)

    def test_a_stub_that_is_routed_keeps_its_output(self):
        from logicxkit.logic.services.mixer.channel_alloc import bind_audio_stub
        routed = bytes(range(33, 49))
        stub = chan(9, "Audio 10", dest=routed, in_use=False, size=265)
        out = bind_audio_stub(stub, object_uuid=self.MARK, input_uuid=bytes(range(17, 33)),
                              output_uuid=bytes(range(49, 65)))
        self.assertEqual((out[-48:-32], out[-32:-16], out[-16:]),
                         (self.MARK, routed, bytes(range(17, 33))))


class DefaultInstrumentRecordsTest(unittest.TestCase):
    """The instrument slot's id is followed by a u32 Logic writes as 0 and refuses a large value
    in; the keyed archive's id is its last 16 bytes."""

    def _records(self) -> tuple[bytes, bytes]:
        from logicxkit.logic.services.mixer.channel_alloc import default_inst_records
        from logicxkit.logic.services.mixer.slots import archive_index
        records = default_inst_records(9, slot_base=2, property_base=10)
        (slot,) = (r for r in records if archive_index(r) != 2)
        (archive,) = (r for r in records if archive_index(r) == 2)
        return slot, archive

    def test_the_slots_closing_word_stays_zero_and_its_id_is_fresh(self):
        made = [self._records() for _ in range(8)]
        for slot, _archive in made:
            self.assertEqual(slot[-4:], bytes(4))
        self.assertEqual(len({slot[-20:-4] for slot, _ in made}), 8)
        self.assertEqual(len({slot[:-20] for slot, _ in made}), 1)

    def test_the_archives_id_is_its_last_16_bytes(self):
        made = [self._records() for _ in range(8)]
        self.assertEqual(len({archive[-16:] for _, archive in made}), 8)
        self.assertEqual(len({archive[:-16] for _, archive in made}), 1)


class ShiftedChannelIsSixteenBitTest(unittest.TestCase):
    def _shift(self, number: int) -> bytes:
        from logicxkit.logic.services.mixer.channel_alloc import shifted_channel
        from logicxkit.logic.services.stream.stream import project_records
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


class ShiftedSubKeepsItsBaseTest(unittest.TestCase):
    def test_a_sub_strip_moves_up_one_in_both_fields(self):
        from logicxkit.logic.services.mixer.channel_alloc import shifted_channel
        from logicxkit.logic.services.stream.stream import project_records
        from _records import proj
        record = project_records(proj(sub_channel(4)))[0]
        out = shifted_channel(record.raw, record, relabel_prefix="Sub ")
        self.assertEqual((number_of(out), label_of(out)), (5, "Sub 5"))


if __name__ == "__main__":
    unittest.main()
