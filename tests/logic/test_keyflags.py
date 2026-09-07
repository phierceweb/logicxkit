"""Key flags: `+26` counts the flag words and sizes the channel record (201 + 4 x words);
a writer that needs a higher key grows the record in front of the 69-byte tail."""

import struct
import unittest

from _records import chan, proj, rec, uuid
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.keyflags import (
    BASE_SIZE, KEY_COUNT_AT, flag_errors, flag_words, key_flags, sync_key_flags, with_key_flags,
)


def slot(owner: int, key: int) -> bytes:
    p = bytearray(300)
    p[6] = key - 4
    return rec(b"UCuA", owner, key, bytes(p), 5)


class VersionTest(unittest.TestCase):
    def test_a_version_6_record_is_sized_from_169_and_older_versions_are_left_alone(self):
        from logicxkit.logic.services.keyflags import _is_channel
        from logicxkit.logic.services.insert import project_records
        v6 = bytearray(chan(9, "Audio 10", size=169 + 4 * 5))
        struct.pack_into("<H", v6, 4, 6)
        struct.pack_into("<H", v6, HEADER + KEY_COUNT_AT, 5)
        v5 = bytearray(chan(9, "Audio 10", size=201))
        struct.pack_into("<H", v5, 4, 5)
        data = proj(bytes(v6), slot(9, 4))
        self.assertEqual(flag_errors(data), ["owner 9: flags [] but records [4]"])
        synced = sync_key_flags(data)
        self.assertEqual(flag_errors(synced), [])
        self.assertEqual([k for k, f in enumerate(key_flags(project_records(synced)[0].raw[HEADER:])) if f], [4])
        self.assertFalse(_is_channel(project_records(proj(bytes(v5)))[0]))
        self.assertEqual(flag_errors(proj(bytes(v5), slot(9, 4))), [])


class GrowthTest(unittest.TestCase):
    def test_bare_stub_grows_one_word_per_key_and_keeps_its_tail(self):
        stub = chan(9, "Audio 10", uuid=uuid(9), dest=uuid(80), source=uuid(1), size=201)
        tail = stub[-69:]
        out = with_key_flags(stub, {4, 5, 6})
        payload = out[HEADER:]
        self.assertEqual(len(payload), BASE_SIZE + 4 * 7)
        self.assertEqual(flag_words(payload), 7)
        self.assertEqual(struct.unpack_from("<I", out, 28)[0], len(payload))
        self.assertEqual(out[-69:], tail)
        self.assertEqual([k for k, f in enumerate(key_flags(payload)) if f], [4, 5, 6])

    def test_a_record_with_room_keeps_its_size(self):
        big = chan(0, "Audio 1", size=257)
        out = with_key_flags(big, {4, 13})
        self.assertEqual(len(out), len(big))
        self.assertEqual(flag_words(out[HEADER:]), 14)

    def test_sync_grows_the_stub_a_transplant_landed_on(self):
        data = sync_key_flags(proj(chan(9, "Audio 10", size=201), slot(9, 4), slot(9, 5)))
        payload = project_records(data)[0].raw[HEADER:]
        self.assertEqual((len(payload), flag_words(payload)), (BASE_SIZE + 24, 6))
        self.assertEqual(flag_errors(data), [])

    def test_a_record_shorter_than_its_count_is_an_error_and_is_left_alone(self):
        short = bytearray(chan(9, "Audio 10", size=201))
        struct.pack_into("<H", short, HEADER + KEY_COUNT_AT, 5)          # claims 5 words in 201 bytes
        data = proj(bytes(short), slot(9, 4))
        self.assertEqual(flag_errors(data), ["owner 9: 201 bytes for 5 flag words"])
        self.assertEqual(sync_key_flags(data), data)
        with self.assertRaises(ValueError):
            with_key_flags(bytes(short), {4})


if __name__ == "__main__":
    unittest.main()
