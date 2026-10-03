"""The audio import's record builders, on Logic's own record templates."""

import struct
import unittest
import uuid

import _paths  # noqa: F401
from logicxkit.logic.services.regions.audio_regions import FORMAT_AT, NAME_AT, PATH_AT, REGION_NAME_AT, file_name, magic_at, region_name
from logicxkit.logic.services.regions.audio_write import WavInfo, file_record, import_templates, region_record, superseded
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.stream.recbuild import slot_of

INFO = WavInfo(88244, "WAVE", 44, 44100, 44100, 1, 16)


def chain_span(raw: bytes) -> bytes:
    p = raw[HEADER:]
    return p[magic_at(p) + FORMAT_AT:][48:72]


class FileRecordTest(unittest.TestCase):
    def test_ord_and_link_sit_where_logic_writes_them(self):
        raw = file_record(import_templates()["lfua"], name="a.wav", folder="/Media", info=INFO, ordinal=2)
        span = chain_span(raw)
        self.assertEqual(struct.unpack_from("<I", span, 8)[0], 3)
        self.assertEqual(span[14:18], b"\xff" * 4)
        self.assertEqual(span[10:14] + span[18:], bytes(10))
        self.assertEqual(slot_of(raw), 8)

    def test_the_folder_buffer_ends_before_the_template_fields(self):
        lfua = import_templates()["lfua"]
        stereo = WavInfo(88244, "WAVE", 44, 22050, 44100, 2, 16)
        raw = file_record(lfua, name="a.wav", folder="/" + "m" * 254, info=stereo, ordinal=0)
        m, t = HEADER + NAME_AT + 2 * len("a.wav"), HEADER + magic_at(lfua[HEADER:])
        self.assertEqual(raw[m + PATH_AT + 255], 0)
        self.assertEqual(raw[m + PATH_AT + 256:m + 400] + raw[m + 401:m + 406], lfua[t + PATH_AT + 256:t + 400] + lfua[t + 401:t + 406])
        self.assertEqual(raw[m + 400], 2)
        with self.assertRaisesRegex(ValueError, "longer than the record holds"):
            file_record(lfua, name="a.wav", folder="/" + "m" * 255, info=stereo, ordinal=0)

    def test_a_superseded_file_moves_only_its_link_and_current_mark(self):
        raw = file_record(import_templates()["lfua"], name="a.wav", folder="/Media", info=INFO, ordinal=0)
        m = HEADER + NAME_AT + 2 * len("a.wav")
        moved = superseded(raw, link=4)
        self.assertEqual((raw[m + 7], moved[m + 7], struct.unpack_from("<I", moved, m + FORMAT_AT + 62)[0]), (1, 0, 4))
        self.assertEqual({k for k in range(len(raw)) if raw[k] != moved[k]}, {m + 7} | set(range(m + FORMAT_AT + 62, m + FORMAT_AT + 66)))
        self.assertEqual({k for k in range(len(raw)) if raw[k] != superseded(raw)[k]}, {m + 7})


class NameTest(unittest.TestCase):
    def test_names_outside_ascii_read_back_as_written(self):
        t = import_templates()
        for name in ("v040-e\u0301.wav", "v040-\U0001f941.wav", "v040-日本.wav"):
            raw = file_record(t["lfua"], name=name, folder="/Media", info=INFO, ordinal=0)
            self.assertEqual((file_name(raw[HEADER:]), struct.unpack_from("<H", raw, HEADER + 8)[0]), (name, 11))
            self.assertEqual(raw[HEADER + magic_at(raw[HEADER:]):][:4], b"LFUA")
        for name in ("Snare \U0001f941", "Pad — é", "v040-日本"):
            raw = region_record(t["grua"], name=name, frames=10, ordinal=0)
            self.assertEqual((region_name(raw[HEADER:]), len(raw) % 2), (name, len(t["grua"]) % 2))


class RegionRecordTest(unittest.TestCase):
    def test_the_name_is_padded_to_an_even_length(self):
        grua = import_templates()["grua"]
        size = {n: len(region_record(grua, name="x" * n, frames=1, ordinal=0)) for n in (9, 10, 11)}
        self.assertEqual((size[10] - size[9], size[11] - size[10]), (0, 2))
        raw = region_record(grua, name="kick", frames=1, ordinal=0)
        self.assertEqual(raw[HEADER + REGION_NAME_AT:HEADER + REGION_NAME_AT + 6], b"\x04\x00kick")

    def test_a_fresh_uuid_ahead_of_the_terminator(self):
        grua = import_templates()["grua"]
        raw = region_record(grua, name="v030-tone", frames=44100, ordinal=1)
        self.assertEqual(uuid.UUID(bytes=raw[-47:-31]).version, 1)
        self.assertNotEqual(raw[-47:-31], grua[-47:-31])
        self.assertEqual(raw[-31:], grua[-31:])
        self.assertEqual(slot_of(raw), 4)

    def test_a_superseded_region_is_no_longer_current(self):
        raw = region_record(import_templates()["grua"], name="kick", frames=1, ordinal=0)
        self.assertEqual({k for k in range(len(raw)) if raw[k] != superseded(raw)[k]}, {HEADER + 38})

    def test_the_time_keeps_the_templates_distance_from_its_uuid(self):
        grua = import_templates()["grua"]
        raw = region_record(grua, name="v030-tone", frames=44100, ordinal=1)
        clock = lambda r: (struct.unpack_from("<Q", r, HEADER + 42)[0] - uuid.UUID(bytes=r[-47:-31]).time) % 2**64  # noqa: E731
        self.assertEqual(clock(raw), clock(grua))
        self.assertNotEqual(raw[HEADER + 42:HEADER + 50], grua[HEADER + 42:HEADER + 50])


if __name__ == "__main__":
    unittest.main()
