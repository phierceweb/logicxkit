"""Cloning a channel's plugin slots from one project onto another.

Records move verbatim (AU state is opaque) and are re-stamped for the target. Slot keys run
from 4 up to the project's `.cst`-reference key, which differs per session (9/10/12/13)."""

import struct
import unittest
from _records import chan, proj, rec
from logicxkit.logic.services.transplant import (
    channel_slots,
    remove_slots,
    owner_of,
    property_key_base,
    set_bypass,
    transplant,
)

HDR = 36


def slot(owner: int, key: int, marker: bytes, size: int = 500) -> bytes:
    p = bytearray(size)
    p[6] = key - 4
    p[200:200 + len(marker)] = marker
    return rec(b"UCuA", owner, key, bytes(p), 5)


def ref(owner: int, key: int, name: str = "Guitar SLO.cst") -> bytes:
    p = bytearray(192)
    p[16:16 + len(name)] = name.encode()
    return rec(b"UCuA", owner, key, bytes(p), 5)


def src_project():
    return proj(chan(0, "Audio 20"), slot(0, 4, b"SOLDANO"), ref(0, 13))


def dst_project():
    return proj(chan(3, "Audio 20"), slot(3, 4, b"OLD-A"), slot(3, 5, b"OLD-B"), ref(3, 9),
                chan(5, "Inst 2"), slot(5, 4, b"AD2"), slot(5, 5, b"COMP"))


def stray(owner: int, key: int, size: int = 200) -> bytes:
    """A non-plugin record inside the slot key range: +6 stays 0 (the 'Audio Recording' and
    aux 68-byte records every session carries)."""
    return rec(b"UCuA", owner, key, bytes(size), 5)


class StrayRecordTest(unittest.TestCase):
    def test_a_record_without_its_slot_index_is_not_a_slot(self):
        data = proj(chan(0, "Audio 1"), slot(0, 4, b"EQ"), stray(0, 8), ref(0, 10))
        self.assertEqual([r.key for r in channel_slots(data, 0)], [4])

    def test_bypass_leaves_it_alone(self):
        data = proj(chan(0, "Audio 1"), slot(0, 4, b"EQ"), stray(0, 8), ref(0, 10))
        out, keys = set_bypass(data, 0)
        self.assertEqual(keys, [4])
        self.assertIn(stray(0, 8), out)

    def test_transplant_neither_clones_nor_drops_it(self):
        src = proj(chan(0, "Audio 1"), slot(0, 4, b"EQ"), stray(0, 8), ref(0, 10))
        dst = proj(chan(3, "Audio 1"), slot(3, 4, b"OLD"), stray(3, 8), ref(3, 10))
        out, report = transplant(src, dst, src_owner=0, dst_owner=3)
        self.assertEqual(report["slots"], 1)
        self.assertIn(stray(3, 8), out)
        self.assertEqual([r.key for r in channel_slots(out, 3)], [4])


class RemoveSlotsTest(unittest.TestCase):
    def test_every_slot_goes_and_the_rest_stays(self):
        data = proj(chan(0, "Audio 1"), slot(0, 4, b"EQ"), slot(0, 5, b"COMP"), stray(0, 8), ref(0, 10),
                    chan(3, "Audio 4"), slot(3, 4, b"OTHER"))
        out, keys = remove_slots(data, 0)
        self.assertEqual(keys, [4, 5])
        self.assertEqual(channel_slots(out, 0), [])
        self.assertEqual([r.key for r in channel_slots(out, 3)], [4])
        self.assertIn(stray(0, 8), out)
        self.assertIn(ref(0, 10), out)
        self.assertEqual(len(out), len(data) - len(slot(0, 4, b"EQ")) - len(slot(0, 5, b"COMP")))

    def test_a_channel_without_slots_is_unchanged(self):
        from logicxkit.logic.services.keyflags import sync_key_flags
        data = sync_key_flags(proj(chan(0, "Audio 1"), ref(0, 10)))
        out, keys = remove_slots(data, 0)
        self.assertEqual((out, keys), (data, []))


class KeyRangeTest(unittest.TestCase):
    def test_property_base_is_the_reference_key(self):
        self.assertEqual(property_key_base(src_project()), 13)
        self.assertEqual(property_key_base(dst_project()), 9)

    def test_reference_record_is_not_a_slot(self):
        self.assertEqual([r.key for r in channel_slots(dst_project(), 3)], [4, 5])

    def test_owner_by_label(self):
        self.assertEqual(owner_of(dst_project(), "Inst 2"), 5)


class TransplantTest(unittest.TestCase):
    def test_target_gets_exactly_the_source_slots(self):
        out, report = transplant(src_project(), dst_project(), src_owner=0, dst_owner=3)
        got = channel_slots(out, 3)
        self.assertEqual([r.key for r in got], [4])
        self.assertIn(b"SOLDANO", got[0].raw)
        self.assertEqual(struct.unpack_from("<H", got[0].raw, 14)[0], 3)   # owner re-stamped
        self.assertEqual(got[0].raw[HDR + 6], 0)                            # slot index
        self.assertEqual(report["replaced"], [4, 5])

    def test_other_channels_and_the_reference_survive(self):
        out, _ = transplant(src_project(), dst_project(), src_owner=0, dst_owner=3)
        self.assertEqual([r.key for r in channel_slots(out, 5)], [4, 5])
        refs = [r for r in __import__("logicxkit.logic.services.insert", fromlist=["x"])
                .project_records(out) if r.owner == 3 and b".cst" in r.raw]
        self.assertEqual(len(refs), 1)

    def test_bypass_flag_sets_the_byte(self):
        out, _ = transplant(src_project(), dst_project(), src_owner=0, dst_owner=3, bypass=True)
        self.assertEqual(channel_slots(out, 3)[0].raw[HDR + 112], 1)

    def test_refuses_an_empty_source(self):
        with self.assertRaises(ValueError):
            transplant(dst_project(), dst_project(), src_owner=99, dst_owner=3)


class BypassTest(unittest.TestCase):
    def test_every_slot_on_the_channel(self):
        out, changed = set_bypass(dst_project(), 5)
        self.assertEqual(changed, [4, 5])
        self.assertTrue(all(r.raw[HDR + 112] == 1 for r in channel_slots(out, 5)))

    def test_length_unchanged(self):
        data = dst_project()
        self.assertEqual(len(set_bypass(data, 5)[0]), len(data))


class KeyFlagTest(unittest.TestCase):
    """One flag word per satellite key from +132 in the channel record; a writer that drops
    or adds a record must keep them in step."""

    def test_remove_clears_the_flags_of_the_dropped_keys(self):
        from logicxkit.logic.services.insert import project_records
        from logicxkit.logic.services.keyflags import flag_errors, key_flags, sync_key_flags
        data = sync_key_flags(proj(chan(0, "Audio 1"), slot(0, 4, b"EQ"), slot(0, 5, b"COMP"), ref(0, 10)))
        self.assertEqual(flag_errors(data), [])
        payload = next(r.raw[HDR:] for r in project_records(data) if r.tag == b"OCuA" and r.owner == 0)
        self.assertEqual([k for k, f in enumerate(key_flags(payload)) if f], [4, 5, 10])
        out, _ = remove_slots(data, 0)
        payload = next(r.raw[HDR:] for r in project_records(out) if r.tag == b"OCuA" and r.owner == 0)
        self.assertEqual([k for k, f in enumerate(key_flags(payload)) if f], [10])
        self.assertEqual(flag_errors(out), [])

    def test_transplant_sets_the_flags_of_the_new_keys(self):
        from logicxkit.logic.services.insert import project_records
        from logicxkit.logic.services.keyflags import flag_errors, key_flags
        src = proj(chan(0, "Audio 1"), slot(0, 4, b"A"), slot(0, 5, b"B"), slot(0, 6, b"C"), ref(0, 10))
        dst = proj(chan(3, "Audio 1"), ref(3, 10))
        out, _ = transplant(src, dst, src_owner=0, dst_owner=3)
        payload = next(r.raw[HDR:] for r in project_records(out) if r.tag == b"OCuA" and r.owner == 3)
        self.assertEqual([k for k, f in enumerate(key_flags(payload)) if f], [4, 5, 6, 10])
        self.assertEqual(flag_errors(out), [])


class OldSlotBaseTest(unittest.TestCase):
    """Projects made before Logic 11.2 start their slot keys at 2. The slots must be seen
    there and clones must land there, or the new chain lands at 4 beside the old one at 2 and
    Logic loads both."""

    @staticmethod
    def _old_slot(owner: int, key: int, marker: bytes, chunk_too: bool = False) -> bytes:
        from _fixtures import chunk
        p = bytearray(500)
        p[6] = key - 2                                       # +6 = key - the old base
        p[200:200 + len(marker)] = marker
        if chunk_too:                                        # a real chunk pins the base at 2
            gametspp = chunk(154, [0.0] * 4)
            p[300:300 + len(gametspp)] = gametspp
        return rec(b"UCuA", owner, key, bytes(p), 5)

    def _old(self):
        """Two channels, as a real project: the other's native slot still says where the
        base is after the first channel's chain has been replaced."""
        return proj(chan(3, "Audio 20"), self._old_slot(3, 2, b"AMPLITUBE"), self._old_slot(3, 3, b"OLD-B"), ref(3, 13),
                    chan(4, "Audio 21"), self._old_slot(4, 2, b"KEEP", True), ref(4, 13))

    def test_the_old_slots_are_seen(self):
        from logicxkit.logic.services.insert import slot_index_base
        old = self._old()
        self.assertEqual(slot_index_base(old), 2)
        self.assertEqual([r.key for r in channel_slots(old, 3)], [2, 3])

    def test_a_transplant_lands_at_the_old_base_and_drops_the_old_chain(self):
        out, report = transplant(src_project(), self._old(), src_owner=0, dst_owner=3)
        got = channel_slots(out, 3)
        self.assertEqual([r.key for r in got], [2])
        self.assertEqual(got[0].raw[36 + 6], 0)
        self.assertIn(b"SOLDANO", got[0].raw)
        self.assertNotIn(b"AMPLITUBE", out)
        self.assertNotIn(b"OLD-B", out)
        self.assertIn(b"KEEP", out)
        self.assertEqual(report["replaced"], [2, 3])

    def test_remove_slots_clears_them_too(self):
        out, removed = remove_slots(self._old(), 3)
        self.assertEqual(removed, [2, 3])
        self.assertEqual(channel_slots(out, 3), [])


class RebaseTest(unittest.TestCase):
    def test_every_key_from_the_slot_base_moves_by_two_and_sends_stay(self):
        from _records import send
        from logicxkit.logic.services.insert import project_records, slot_index_base
        from logicxkit.logic.services.slotkeys import needs_rebase, rebase
        old = OldSlotBaseTest()
        # the 2020 song: three sends on a channel whose slots start at key 2, so key 2 is both
        data = proj(chan(3, "Audio 20"), send(3, 0, 5), send(3, 1, 6), send(3, 2, 7),
                    old._old_slot(3, 2, b"AMPLITUBE", True), old._old_slot(3, 3, b"OLD-B"),
                    ref(3, 13), chan(4, "Audio 21"), old._old_slot(4, 2, b"KEEP", True), ref(4, 13))
        self.assertTrue(needs_rebase(data))
        out, report = rebase(data)
        self.assertEqual((report["from"], report["to"], report["moved"]), (2, 4, 5))
        self.assertEqual(slot_index_base(out), 4)
        keys = sorted((r.owner, r.key) for r in project_records(out) if r.tag == b"UCuA")
        self.assertEqual(keys, [(3, 0), (3, 1), (3, 2), (3, 4), (3, 5), (3, 15), (4, 4), (4, 15)])
        self.assertEqual([r.key for r in channel_slots(out, 3)], [4, 5])
        self.assertFalse(needs_rebase(out))
        self.assertEqual(rebase(out)[0], out)


class ChannelBaseWordTest(unittest.TestCase):
    """The slot base every channel record carries at +28 moves with the keys."""

    def test_rebase_stamps_four_into_every_channel(self):
        import struct
        from logicxkit.logic.services.insert import HEADER
        from logicxkit.logic.services.slotkeys import CHANNEL_BASE_AT, channel_bases, rebase
        old = OldSlotBaseTest()
        def stamped(raw):
            buf = bytearray(raw)
            struct.pack_into("<H", buf, HEADER + CHANNEL_BASE_AT, 2)
            return bytes(buf)
        data = proj(stamped(chan(3, "Audio 20")), old._old_slot(3, 2, b"AMP", True), ref(3, 13), stamped(chan(4, "Audio 21")))
        self.assertEqual(channel_bases(data), {2: 2})
        out, report = rebase(data)
        self.assertEqual((channel_bases(out), report["channels"]), ({4: 2}, 2))


class RefusalTest(unittest.TestCase):
    """The two defects `transplant` shipped with, now refusals rather than damage."""

    def test_more_source_slots_than_the_key_range_holds_is_refused(self):
        """The reproduced defect: keys run 4..base, so six slots into a base-9 project reach
        the `.cst` reference key and insert_slots' drop range deletes that record."""
        src = proj(chan(0, "Audio 1"), *[slot(0, 4 + i, b"P%d" % i) for i in range(6)], ref(0, 13))
        dst = proj(chan(3, "Audio 1"), slot(3, 4, b"OLD"), ref(3, 9))
        with self.assertRaises(ValueError) as e:
            transplant(src, dst, src_owner=0, dst_owner=3)
        self.assertIn("5", str(e.exception), "the message names the capacity")

    def test_the_reference_record_survives_a_refused_transplant(self):
        src = proj(chan(0, "Audio 1"), *[slot(0, 4 + i, b"P%d" % i) for i in range(6)], ref(0, 13))
        dst = proj(chan(3, "Audio 1"), slot(3, 4, b"OLD"), ref(3, 9))
        with self.assertRaises(ValueError):
            transplant(src, dst, src_owner=0, dst_owner=3)
        self.assertIn(ref(3, 9), dst)

    def test_force_lets_the_overflow_through(self):
        src = proj(chan(0, "Audio 1"), *[slot(0, 4 + i, b"P%d" % i) for i in range(6)], ref(0, 13))
        dst = proj(chan(3, "Audio 1"), slot(3, 4, b"OLD"), ref(3, 9))
        out, report = transplant(src, dst, src_owner=0, dst_owner=3, force=True)
        self.assertEqual(report["slots"], 6)

    def test_a_class_version_mismatch_is_refused(self):
        """A v3 record cannot be legalised into a v5 project; donors.retarget_version holds
        the only derivable direction and this path never called it."""
        v3 = rec(b"UCuA", 0, 4, _v3_payload(), 3)
        src = proj(chan(0, "Audio 1"), v3, ref(0, 13))
        dst = proj(chan(3, "Audio 1"), slot(3, 4, b"OLD"), ref(3, 9))
        with self.assertRaises(ValueError) as e:
            transplant(src, dst, src_owner=0, dst_owner=3)
        self.assertIn("v3", str(e.exception))
        self.assertIn("v5", str(e.exception))

    def test_force_lets_the_version_mismatch_through(self):
        v3 = rec(b"UCuA", 0, 4, _v3_payload(), 3)
        src = proj(chan(0, "Audio 1"), v3, ref(0, 13))
        dst = proj(chan(3, "Audio 1"), slot(3, 4, b"OLD"), ref(3, 9))
        out, report = transplant(src, dst, src_owner=0, dst_owner=3, force=True)
        self.assertEqual(report["slots"], 1)

    def test_matching_versions_pass_without_force(self):
        out, report = transplant(src_project(), dst_project(), src_owner=0, dst_owner=3)
        self.assertEqual(report["slots"], 1)


def _v3_payload() -> bytes:
    p = bytearray(500)
    p[6] = 0
    p[200:207] = b"SOLDANO"
    return bytes(p)
