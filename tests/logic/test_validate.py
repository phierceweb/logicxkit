"""Structural invariants a written project must satisfy.

Every bug that reached the mixer this session was a byte-level invariant violation that the writer
happily produced and no check caught: colliding slot indices hid plugins, a mono instance
landed on a stereo bus, corrupted per-instance ids made a project unopenable. These are
enforced at write time so a broken file cannot leave the tool.
"""

import struct
import unittest

from logicxkit.logic import validate_project

HDR = 36


def rec(tag: bytes, owner: int, key: int, payload: bytes, ver: int = 5) -> bytes:
    h = bytearray(HDR)
    h[0:4] = tag
    struct.pack_into("<H", h, 4, ver)
    struct.pack_into("<H", h, 14, owner)
    struct.pack_into("<H", h, 18, key)
    struct.pack_into("<I", h, 28, len(payload))
    return bytes(h) + payload


def slot(key: int, index: int, fmt: int = 1, type_id: int = 236) -> bytes:
    p = bytearray(220)
    p[6] = index
    for off in (81, 84, 118, 119, 156):
        p[off] = fmt
    p[184:192] = b"GAMETSPP"
    struct.pack_into("<III", p, 172, 24 + 16, 1, 4)
    struct.pack_into("<I", p, 192, type_id)
    return rec(b"UCuA", 0, key, bytes(p))


def third_party_slot(key: int, index: int, fmt: int = 1, size: int = 500) -> bytes:
    """An AU state record: index at +6 and the width bytes, but no `GAMETSPP` chunk."""
    p = bytearray(size)
    p[6] = index
    for off in (81, 84, 118, 119, 156):
        p[off] = fmt
    p[200:207] = b"SOLDANO"
    return rec(b"UCuA", 0, key, bytes(p))


def stray(key: int, size: int = 200) -> bytes:
    """A non-plugin record in the slot key range, +6 left at 0 — the 'Audio Recording' shape."""
    return rec(b"UCuA", 0, key, bytes(size))


def channel(owner: int, fmt: int = 1) -> bytes:
    p = bytearray(225)
    p[123] = fmt
    return rec(b"OCuA", owner, 0xFFFF, bytes(p))


def proj(*records: bytes) -> bytes:
    body = b"".join(records)
    head = bytearray(24)
    struct.pack_into("<I", head, 0x10, len(body))
    return bytes(head) + body


class ValidateProjectTest(unittest.TestCase):
    def test_accepts_a_well_formed_project(self):
        self.assertEqual(validate_project(proj(channel(0), slot(4, 0), slot(5, 1))), [])

    def test_rejects_colliding_slot_indices(self):
        """Two slots claiming one index: Logic renders one and silently drops the other."""
        problems = validate_project(proj(channel(0), slot(4, 0), slot(5, 0)))
        self.assertTrue(any("index" in p for p in problems), problems)

    def test_rejects_duplicate_keys(self):
        problems = validate_project(proj(channel(0), slot(4, 0), slot(4, 1)))
        self.assertTrue(any("key" in p for p in problems), problems)

    def test_rejects_a_mono_instance_on_a_stereo_channel(self):
        """A mono plugin instance on a stereo channel — audibly wrong on a bus."""
        problems = validate_project(proj(channel(0, fmt=2), slot(4, 0, fmt=1)))
        self.assertTrue(any("width" in p or "mono" in p for p in problems), problems)

    def test_rejects_a_bad_header_total(self):
        data = bytearray(proj(channel(0), slot(4, 0)))
        struct.pack_into("<I", data, 0x10, 999)
        self.assertTrue(any("header" in p for p in validate_project(bytes(data))))

    def test_rejects_a_stream_that_does_not_reach_eof(self):
        self.assertTrue(any("walk" in p for p in validate_project(proj(channel(0)) + b"JUNK")))

    def test_a_third_party_slots_width_is_not_judged(self):
        """Logic's own saves carry third-party records whose width bytes disagree with the
        channel, so judging them would refuse files Logic wrote."""
        self.assertEqual(validate_project(proj(channel(0, fmt=2), third_party_slot(4, 0, fmt=1))), [])

    def test_sees_a_third_party_slot_colliding_with_a_native_index(self):
        """Two correct native slots pin the base; a third-party slot at index 2 and a native one
        wrongly claiming index 2 must be reported as a collision, not just a mismatch."""
        problems = validate_project(proj(channel(0), slot(4, 0), slot(5, 1),
                                         third_party_slot(6, 2), slot(7, 2)))
        self.assertTrue(any("colliding" in p for p in problems), problems)

    def test_sees_duplicate_third_party_keys(self):
        problems = validate_project(proj(channel(0), third_party_slot(4, 0), third_party_slot(4, 0)))
        self.assertTrue(any("key" in p for p in problems), problems)

    def test_a_stray_record_in_the_key_range_is_not_a_slot(self):
        """The 200-byte 'Audio Recording' record sits among the slot keys with +6 = 0."""
        self.assertEqual(validate_project(proj(channel(0, fmt=2), slot(4, 0, fmt=2), stray(5))), [])

    def test_reports_every_problem_not_just_the_first(self):
        problems = validate_project(proj(channel(0, fmt=2), slot(4, 0, fmt=1), slot(5, 0, fmt=1)))
        self.assertGreaterEqual(len(problems), 2)


class WriteGuardTest(unittest.TestCase):
    """`insert_slots` refuses to return bytes that violate the invariants, so a broken project
    cannot reach disk even if a caller builds a bad plan."""

    def test_insert_refuses_a_plan_that_would_collide(self):
        from logicxkit.logic import insert_slots
        donor = slot(4, 0)
        data = proj(channel(0))
        with self.assertRaises(ValueError) as cm:
            insert_slots(data, {0: [(donor, 4, None, 0), (donor, 4, None, 0)]})
        self.assertIn("key", str(cm.exception).lower())

    def test_insert_still_succeeds_on_a_valid_plan(self):
        from logicxkit.logic import insert_slots, project_records
        donor = slot(4, 0)
        out = insert_slots(proj(channel(0)), {0: [(donor, 4, None, 0), (donor, 5, None, 0)]})
        idx = [r.raw[HDR + 6] for r in project_records(out) if r.tag == b"UCuA"]
        self.assertEqual(idx, [0, 1])
