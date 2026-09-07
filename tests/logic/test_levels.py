"""Channel fader and pan.

Both sit in the `OCuA` channel record: the fader at +85 and +119 (written twice, always equal)
and pan at +89 with 64 as centre. Confirmed against Logic's own mixer display — pan reads out
as `byte - 64`, and every hard-panned stereo pair in the sessions is exactly 0/127.
"""

import struct
import unittest

import _paths  # noqa: F401
from logicxkit.logic.services.levels import (
    PAN_AT,
    PAN_CENTRE,
    UNITY,
    copy_levels,
    read_levels,
    set_levels,
)

HDR = 36


def rec(tag: bytes, owner: int, key: int, payload: bytes, ver: int = 5) -> bytes:
    h = bytearray(HDR)
    h[0:4] = tag
    struct.pack_into("<H", h, 4, ver)
    struct.pack_into("<H", h, 14, owner)
    struct.pack_into("<H", h, 18, key)
    struct.pack_into("<I", h, 28, len(payload))
    return bytes(h) + payload


def proj(*records: bytes) -> bytes:
    body = b"".join(records)
    head = bytearray(24)
    struct.pack_into("<I", head, 0x10, len(body))
    return bytes(head) + body


def chan(owner: int, fader: int = UNITY, pan: int = PAN_CENTRE, size: int = 257) -> bytes:
    p = bytearray(size)
    p[85] = p[119] = fader
    p[PAN_AT] = pan
    return rec(b"OCuA", owner, 0xFFFF, bytes(p))


class ReadLevelsTest(unittest.TestCase):
    def test_reads_fader_and_pan(self):
        got = read_levels(proj(chan(0, 99, 0), chan(1, 47, 127)))
        self.assertEqual({k: got[0][k] for k in ("fader", "pan", "pan_display")},
                         {"fader": 99, "pan": 0, "pan_display": -64})
        self.assertEqual({k: got[1][k] for k in ("fader", "pan", "pan_display")},
                         {"fader": 47, "pan": 127, "pan_display": 63})

    def test_the_exact_fader_is_the_fixed_point_word(self):
        import struct
        raw = bytearray(chan(0, 99, 0))
        struct.pack_into("<I", raw, 36 + 116, (99 << 24) + 0x800000)     # 99.5
        got = read_levels(proj(bytes(raw)))[0]
        self.assertEqual((got["fader"], got["fader_fixed"], got["fader_exact"]), (99, (99 << 24) + 0x800000, 99.5))

    def test_set_levels_writes_the_word_and_both_bytes(self):
        import struct
        out, changed = set_levels(proj(chan(0, 99, 0)), {0: {"fader_fixed": (47 << 24) + 1}})
        p = out[24 + 36:]
        self.assertEqual((p[85], p[119], struct.unpack_from("<I", p, 116)[0]), (47, 47, (47 << 24) + 1))
        out, _ = set_levels(proj(chan(0, 99, 0)), {0: {"fader": 47}})
        self.assertEqual(struct.unpack_from("<I", out[24 + 36:], 116)[0], 47 << 24)

    def test_copy_carries_the_exact_value(self):
        import struct
        src = bytearray(chan(0, 92, 64))
        struct.pack_into("<I", src, 36 + 116, (92 << 24) + 12345)
        out, report = copy_levels(proj(bytes(src)), proj(chan(0, 90, 64)), by="owner")
        self.assertEqual(struct.unpack_from("<I", out[24 + 36:], 116)[0], (92 << 24) + 12345)
        self.assertEqual(report["changed"], [0])

    def test_centre_pan_reads_as_zero(self):
        self.assertEqual(read_levels(proj(chan(0)))[0]["pan_display"], 0)

    def test_a_short_stub_record_is_ignored(self):
        """A channel owns several records; the stubs carry no mixer state."""
        data = proj(rec(b"OCuA", 0, 0xFFFF, bytes(14)), chan(0, 99))
        self.assertEqual(read_levels(data)[0]["fader"], 99)


class SetLevelsTest(unittest.TestCase):
    def test_writes_both_fader_copies(self):
        out, changed = set_levels(proj(chan(0)), {0: {"fader": 99, "pan": 0}})
        self.assertEqual(changed, [0])
        p = out[24 + HDR:]
        self.assertEqual((p[85], p[119], p[PAN_AT]), (99, 99, 0),
                         "both fader copies must move or Logic reloads the stale one")

    def test_an_unchanged_channel_is_not_reported(self):
        _out, changed = set_levels(proj(chan(0, 90, 64)), {0: {"fader": 90, "pan": 64}})
        self.assertEqual(changed, [])

    def test_every_record_of_that_owner_is_rewritten(self):
        """Logic keeps mixer state in each of a channel's records; a stale copy springs back."""
        from logicxkit.logic.services.insert import HEADER, project_records
        data = proj(chan(0, 90, 64, size=257), chan(0, 90, 64, size=253))
        out, _ = set_levels(data, {0: {"fader": 99, "pan": 0}})
        seen = [(r.raw[HEADER + 85], r.raw[HEADER + 119], r.raw[HEADER + PAN_AT])
                for r in project_records(out) if r.owner == 0]
        self.assertEqual(len(seen), 2, "both records of the owner must be present")
        self.assertEqual(seen, [(99, 99, 0), (99, 99, 0)])


class CopyLevelsTest(unittest.TestCase):
    def test_owner_matching_carries_values_across(self):
        src = proj(chan(0, 99, 0), chan(1, 47, 127))
        dst = proj(chan(0), chan(1))
        out, report = copy_levels(src, dst, by="owner")
        got = read_levels(out)
        self.assertEqual((got[0]["fader"], got[0]["pan"]), (99, 0))
        self.assertEqual((got[1]["fader"], got[1]["pan"]), (47, 127))
        self.assertEqual(report["changed"], [0, 1])

    def test_a_channel_already_matching_is_left_alone(self):
        src = proj(chan(0, 99, 0))
        dst = proj(chan(0, 99, 0))
        _out, report = copy_levels(src, dst, by="owner")
        self.assertEqual(report["changed"], [])
        self.assertEqual(report["unchanged"], 1)


class LabelMatchTest(unittest.TestCase):
    def test_sub_strips_pair_by_label(self):
        from _records import chan as bchan
        from logicxkit.logic.services.levels import match_by_label
        src = proj(bchan(378, "Sub 1", fader=70), bchan(0, "Audio 1"))
        dst = proj(bchan(500, "Sub 1"), bchan(3, "Audio 1"))
        self.assertEqual(match_by_label(src, dst), {500: 378, 3: 0})

    def test_copy_by_label_moves_a_stack_fader(self):
        from _records import chan as bchan
        src = proj(bchan(378, "Sub 1", fader=70))
        dst = proj(bchan(500, "Sub 1"))
        out, report = copy_levels(src, dst, by="label")
        self.assertEqual(read_levels(out)[500]["fader"], 70)
        self.assertEqual(report["changed"], [500])


class WriterGateTest(unittest.TestCase):
    def test_set_levels_refuses_a_stream_it_cannot_walk(self):
        data = proj(chan(0)) + b"\x00" * 3
        with self.assertRaises(ValueError):
            set_levels(data, {0: {"fader": 99}})
