"""Channel width — the mono/stereo state of a channel record itself.

A slot's width follows its channel's, so a send return built mono gives every plugin on it a
mono instance. Widening the channel is three bytes, not just the channel count at +123.
"""

import struct
import unittest

import _paths  # noqa: F401
from logicxkit.logic import project_records  # noqa: F401

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


class ChannelWidthTest(unittest.TestCase):
    """Widening a channel is THREE bytes, not just the channel count at +123. Measured by
    taking, in each session, the bytes where every stereo aux agrees and the mono one differs:
    +78 211->215, +86 0->1, +123 1->2. Identical in all ten sessions across both class
    versions, and matched by the one session whose Vox Slapback Logic itself wrote stereo."""

    def _chan(self, width: int) -> bytes:
        p = bytearray(257)
        p[78], p[86], p[123] = (211, 0, 1) if width == 1 else (215, 1, 2)
        p[200] = 0x5A                      # per-channel identity; must survive untouched
        return rec(b"OCuA", 0, 0xFFFF, bytes(p))

    def test_widening_writes_all_three_bytes(self):
        from logicxkit.logic import set_channel_format
        out = set_channel_format(self._chan(1), 2)
        self.assertEqual((out[36 + 78], out[36 + 86], out[36 + 123]), (215, 1, 2))

    def test_widening_reproduces_a_real_stereo_record(self):
        from logicxkit.logic import set_channel_format
        self.assertEqual(set_channel_format(self._chan(1), 2), self._chan(2))

    def test_narrowing_reproduces_a_real_mono_record(self):
        from logicxkit.logic import set_channel_format
        self.assertEqual(set_channel_format(self._chan(2), 1), self._chan(1))

    def test_matching_width_is_a_no_op(self):
        from logicxkit.logic import set_channel_format
        src = self._chan(2)
        self.assertEqual(set_channel_format(src, 2), src)

    def test_nothing_else_in_the_record_moves(self):
        from logicxkit.logic import set_channel_format
        out = set_channel_format(self._chan(1), 2)
        src = self._chan(1)
        moved = {i for i in range(len(src)) if src[i] != out[i]}
        self.assertEqual(moved, {36 + 78, 36 + 86, 36 + 123})

    def test_widen_channels_reports_what_it_changed(self):
        from logicxkit.logic import widen_channels, channel_formats
        data = proj(self._chan(1))
        out, changed = widen_channels(data, {0: 2})
        self.assertEqual(changed, [0])
        self.assertEqual(channel_formats(out)[0], 2)

    def test_widen_channels_skips_a_channel_already_that_width(self):
        from logicxkit.logic import widen_channels
        data = proj(self._chan(2))
        out, changed = widen_channels(data, {0: 2})
        self.assertEqual(changed, [])
        self.assertEqual(out, data)


class WidenGateTest(unittest.TestCase):
    def test_widen_refuses_a_stream_it_cannot_walk(self):
        from _records import chan as bchan
        from _records import proj as bproj
        from logicxkit.logic.services.insert import widen_channels
        data = bproj(bchan(0, "Audio 1")) + b"\x00" * 3
        with self.assertRaises(ValueError):
            widen_channels(data, {0: 1})


class SlotsFollowTheChannelTest(unittest.TestCase):
    """Widening a channel must re-stamp the plugins already on it.

    The Recording template's Vox Slapback aux is a mono return carrying a mono Echo. Widening
    the channel alone leaves that Echo at width 1 on a stereo channel — `validate_project`
    rejects it, so `logic chains` cannot build the tracking template at all.
    """

    ECHO = 147

    def _slot(self, owner: int, key: int, width: int) -> bytes:
        from _fixtures import chunk
        from logicxkit.logic.services.insert import (
            SLOT_BUS_AT, SLOT_CFG_AT, SLOT_COUNT_AT, SLOT_INDEX_AT, SLOT_VARIANT_AT)
        p = bytearray(160)
        p[SLOT_INDEX_AT] = key - 4
        p[SLOT_CFG_AT] = width
        for off in SLOT_COUNT_AT:
            p[off] = width
        struct.pack_into("<H", p, SLOT_VARIANT_AT, 500 + width)
        for off in SLOT_BUS_AT:
            p[off] = width
        return rec(b"UCuA", owner, key, bytes(p) + chunk(self.ECHO, [0.0] * 28), 5)

    def _chan(self, owner: int, width: int) -> bytes:
        p = bytearray(257)
        p[78], p[86], p[123] = (211, 0, 1) if width == 1 else (215, 1, 2)
        return rec(b"OCuA", owner, 0xFFFF, bytes(p))

    def test_widening_also_widens_a_slot_already_on_the_channel(self):
        from logicxkit.logic import widen_channels
        from logicxkit.logic.services.insert import slot_format
        from logicxkit.logic.services.insert import project_records as walk
        data = proj(self._chan(76, 1), self._slot(76, 4, 1))
        out, changed = widen_channels(data, {76: 2})
        self.assertEqual(changed, [76])
        slots = [r for r in walk(out) if r.tag == b"UCuA"]
        self.assertEqual([slot_format(r.raw) for r in slots], [2])

    def test_widening_leaves_slots_on_other_channels_alone(self):
        from logicxkit.logic import widen_channels
        from logicxkit.logic.services.insert import slot_format
        from logicxkit.logic.services.insert import project_records as walk
        data = proj(self._chan(76, 1), self._slot(76, 4, 1),
                    self._chan(77, 1), self._slot(77, 4, 1))
        out, _ = widen_channels(data, {76: 2})
        by_owner = {r.owner: slot_format(r.raw) for r in walk(out) if r.tag == b"UCuA"}
        self.assertEqual(by_owner, {76: 2, 77: 1})
