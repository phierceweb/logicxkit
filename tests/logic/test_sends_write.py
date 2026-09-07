"""Writing sends: `UCuA` keys 0-2, cloned from a send the project already carries.

A new send lands right after its channel's `OCuA` in key order, before the slots (key 4+).
Only the measured fields are set: owner, key, `+4`, `+20`, a fresh instance UUID at `+44`
and the target `Bus N` channel's UUID at `+60`; the level bytes ride along from the template."""

import struct
import unittest
from _records import chan, proj, rec, send, uuid
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.sends import read_sends
from logicxkit.logic.services.sends_write import add_send, copy_sends, remove_sends

SEND_LEN = HEADER + 76

UUID = slice(HEADER + 44, HEADER + 60)

DEST = slice(HEADER + 60, HEADER + 76)


def bus(n: int, *, seed: int = 1000) -> bytes:
    return chan(100 + n, f"Bus {n}", uuid=uuid(seed + n), size=201)


def slot(owner: int, key: int) -> bytes:
    return rec(b"UCuA", owner, key, bytes(300), 5)


def donor_send(owner: int, key: int, bus: int, *, klass: int = 72, level: bytes = b"\x01\x2a",
               word8: int = 0, ver: int = 5) -> bytes:
    """A send shaped like Logic's, with the undecoded words a test can tell apart."""
    p = bytearray(76)
    struct.pack_into("<I", p, 0, klass)
    struct.pack_into("<I", p, 4, key << 16)
    struct.pack_into("<H", p, 8, word8)
    p[16:16 + len(level)] = level
    struct.pack_into("<H", p, 20, bus + 31)
    p[44:60] = uuid(900 + owner * 3 + key)
    p[60:76] = uuid(1000 + bus)
    return rec(b"UCuA", owner, key, bytes(p), ver)


def session(*extra: bytes) -> bytes:
    """Audio 3 with two sends and slots; Audio 4 with slots only; Audio 27 a bare stub."""
    return proj(
        chan(2, "Audio 3", uuid=uuid(96)), donor_send(2, 0, 15, word8=4), donor_send(2, 1, 16, word8=4),
        slot(2, 4), slot(2, 12),
        chan(3, "Audio 4", uuid=uuid(100)), slot(3, 4), slot(3, 12),
        chan(26, "Audio 27", in_use=False, size=253),
        chan(27, "Audio 28", uuid=uuid(104)), slot(27, 4),
        bus(10), bus(15), bus(16), *extra)


def run(data: bytes, owner: int) -> list[tuple[bytes, int]]:
    return [(r.tag, r.key) for r in project_records(data)
            if r.owner == owner and r.tag in (b"OCuA", b"UCuA")]


def send_raw(data: bytes, owner: int, key: int) -> bytes:
    return next(s.raw for s in read_sends(data)[owner] if s.key == key)


class AddSendTest(unittest.TestCase):
    def test_the_lowest_free_key_lands_between_its_neighbours(self):
        out, report = add_send(session(), owner=2, bus=10)
        self.assertEqual((report["key"], report["bus"], report["replaced"]), (2, 10, False))
        self.assertEqual(run(out, 2), [(b"OCuA", 0xFFFF), (b"UCuA", 0), (b"UCuA", 1),
                                       (b"UCuA", 2), (b"UCuA", 4), (b"UCuA", 12)])

    def test_a_gap_is_filled_in_key_order(self):
        data = proj(chan(2, "Audio 3"), send(2, 0, 15), send(2, 2, 16), slot(2, 4), bus(10), bus(15))
        out, report = add_send(data, owner=2, bus=10)
        self.assertEqual(report["key"], 1)
        self.assertEqual([k for _t, k in run(out, 2)], [0xFFFF, 0, 1, 2, 4])

    def test_before_the_slots_on_a_channel_without_sends(self):
        out, _ = add_send(session(), owner=3, bus=15)
        self.assertEqual([k for _t, k in run(out, 3)], [0xFFFF, 0, 4, 12])

    def test_right_after_the_channel_record_without_satellites(self):
        out, _ = add_send(session(), owner=26, bus=15)
        records = project_records(out)
        i = next(i for i, r in enumerate(records) if r.tag == b"OCuA" and r.owner == 26)
        self.assertEqual((records[i + 1].tag, records[i + 1].owner, records[i + 1].key),
                         (b"UCuA", 26, 0))
        self.assertEqual((records[i + 2].tag, records[i + 2].owner), (b"OCuA", 27))

    def test_the_measured_fields_and_only_those(self):
        data = session()
        out, _ = add_send(data, owner=3, bus=16)
        new = send_raw(out, 3, 0)
        template = send_raw(data, 2, 0)
        self.assertEqual(len(out), len(data) + SEND_LEN)
        self.assertEqual(struct.unpack_from("<H", new, 14)[0], 3)
        self.assertEqual(struct.unpack_from("<I", new, HEADER + 4)[0], 0)
        self.assertEqual(struct.unpack_from("<H", new, HEADER + 20)[0], 16 + 31)
        self.assertEqual(new[DEST], uuid(1016))
        self.assertNotEqual(new[UUID], template[UUID])
        self.assertEqual((new[HEADER + 44 + 6] >> 4, new[HEADER + 44 + 8] & 0xC0), (1, 0x80))
        self.assertEqual(new[HEADER + 16:HEADER + 20], template[HEADER + 16:HEADER + 20])
        self.assertEqual(new[:14] + new[16:18], template[:14] + template[16:18])
        self.assertEqual([(s.key, s.bus) for s in read_sends(out)[3]], [(0, 16)])

    def test_a_second_send_takes_the_next_key(self):
        out, _ = add_send(session(), owner=3, bus=15)
        out, report = add_send(out, owner=3, bus=16)
        self.assertEqual(report["key"], 1)
        self.assertEqual([(s.key, s.bus) for s in read_sends(out)[3]], [(0, 15), (1, 16)])

    def test_the_template_is_the_channels_own_send_when_it_has_one(self):
        data = session(chan(5, "Audio 6", uuid=uuid(5)), donor_send(5, 0, 10, word8=0))
        out, _ = add_send(data, owner=2, bus=10)
        self.assertEqual(struct.unpack_from("<H", send_raw(out, 2, 2), HEADER + 8)[0], 4)
        out, _ = add_send(data, owner=3, bus=10)                    # no sends: the first one
        self.assertEqual(struct.unpack_from("<H", send_raw(out, 3, 0), HEADER + 8)[0], 4)

    def test_an_explicit_key_replaces_the_send_it_names(self):
        data = session()
        out, report = add_send(data, owner=2, bus=10, key=0)
        self.assertTrue(report["replaced"])
        self.assertEqual(len(out), len(data))
        self.assertEqual([(s.key, s.bus) for s in read_sends(out)[2]], [(0, 10), (1, 16)])

    def test_refuses_a_fourth_send(self):
        data = session(donor_send(2, 2, 10))
        with self.assertRaises(ValueError):
            add_send(data, owner=2, bus=10)

    def test_refuses_a_key_outside_the_send_range(self):
        with self.assertRaises(ValueError):
            add_send(session(), owner=2, bus=10, key=4)

    def test_refuses_without_a_send_to_clone(self):
        data = proj(chan(3, "Audio 4"), slot(3, 4), bus(15))
        with self.assertRaisesRegex(ValueError, "donor"):
            add_send(data, owner=3, bus=15)

    def test_refuses_a_bus_the_project_lacks(self):
        with self.assertRaises(ValueError):
            add_send(session(), owner=3, bus=99)

    def test_refuses_an_unknown_owner(self):
        with self.assertRaises(ValueError):
            add_send(session(), owner=77, bus=15)

    def test_refuses_a_corrupt_stream(self):
        with self.assertRaises(ValueError):
            add_send(session() + b"\x00" * 5, owner=3, bus=15)


def source(*, klass: int = 99, ver: int = 4) -> bytes:
    """Another project: Audio 6 with sends to 15 and 10, its own bus UUIDs and class word."""
    return proj(chan(5, "Audio 6", uuid=uuid(5)),
                donor_send(5, 0, 15, klass=klass, level=b"\x01\x0c", ver=ver),
                donor_send(5, 1, 10, klass=klass, level=b"\x01\x2d", ver=ver),
                bus(10, seed=2000), bus(15, seed=2000))


class DestinationBaseTest(unittest.TestCase):
    def test_a_copy_into_a_twenty_input_project_rebases_the_destination_word(self):
        import struct
        from logicxkit.logic.services.sends_write import copy_sends
        src = proj(chan(5, "Audio 6", uuid=uuid(1)), send(5, 0, 10), chan(130, "Bus 10", uuid=uuid(130), size=201))
        inputs = [chan(256 + k, f"Input {k + 1}", size=201, in_use=False) for k in range(20)]
        dst = proj(chan(2, "Audio 3", uuid=uuid(96)), send(2, 0, 5), chan(585, "Bus 10", uuid=uuid(585), size=201),
                   chan(580, "Bus 5", uuid=uuid(580), size=201), *inputs)
        raw = bytearray(dst)                                             # dst's own send as Logic writes it: 5 + 19
        at = dst.index(send(2, 0, 5))
        struct.pack_into("<I", raw, at + 36 + 20, 5 + 19)
        out, report = copy_sends(src, bytes(raw), src_owner=5, dst_owner=2)
        new = next(r for r in project_records(out) if r.owner == 2 and r.tag == b"UCuA")
        self.assertEqual(struct.unpack_from("<H", new.raw, HEADER + 20)[0], 10 + 19)
        self.assertEqual(report["buses"], [10])


class SendFlagTest(unittest.TestCase):
    """The channel's own record mirrors its sends: u32 at +132 + 4 * key."""

    @staticmethod
    def flags(data: bytes, owner: int) -> tuple[int, int, int]:
        p = next(r.raw[HEADER:] for r in project_records(data) if r.tag == b"OCuA" and r.owner == owner
                 and len(r.raw) - HEADER > 200)
        return tuple(struct.unpack_from("<I", p, 132 + 4 * k)[0] for k in range(3))

    def test_add_sets_the_slots_flag(self):
        data = session(chan(5, "Audio 6", uuid=uuid(5)))
        out, _ = add_send(data, owner=5, bus=15)
        self.assertEqual(self.flags(out, 5), (1, 0, 0))
        out, _ = add_send(out, owner=5, bus=16)
        self.assertEqual(self.flags(out, 5), (1, 1, 0))

    def test_remove_clears_them(self):
        data = session(chan(5, "Audio 6", uuid=uuid(5)))
        out, _ = add_send(data, owner=5, bus=15)
        self.assertEqual(self.flags(remove_sends(out, owner=5), 5), (0, 0, 0))

    def test_copy_writes_exactly_the_copied_set(self):
        dst = session(chan(5, "Audio 6", uuid=uuid(5)))
        src = session(chan(5, "Audio 6", uuid=uuid(5)), donor_send(5, 1, 15), donor_send(5, 2, 16))
        out, _ = copy_sends(src, dst, src_owner=5, dst_owner=5)
        self.assertEqual(self.flags(out, 5), (0, 1, 1))


class CopySendsTest(unittest.TestCase):
    def test_the_target_gets_exactly_the_source_set(self):
        out, report = copy_sends(source(), session(), src_owner=5, dst_owner=2)
        self.assertEqual([(s.key, s.bus) for s in read_sends(out)[2]], [(0, 15), (1, 10)])
        self.assertEqual(report, {"keys": [0, 1], "buses": [15, 10], "replaced": [0, 1]})
        self.assertEqual([k for _t, k in run(out, 2)], [0xFFFF, 0, 1, 4, 12])

    def test_level_bytes_come_from_the_source(self):
        out, _ = copy_sends(source(), session(), src_owner=5, dst_owner=3)
        self.assertEqual(send_raw(out, 3, 0)[HEADER + 16:HEADER + 18], b"\x01\x0c")
        self.assertEqual(send_raw(out, 3, 1)[HEADER + 16:HEADER + 18], b"\x01\x2d")

    def test_the_targets_class_word_and_header_win_when_it_has_sends(self):
        out, _ = copy_sends(source(), session(), src_owner=5, dst_owner=3)
        new = send_raw(out, 3, 0)
        self.assertEqual(struct.unpack_from("<I", new, HEADER)[0], 72)
        self.assertEqual(struct.unpack_from("<H", new, 4)[0], 5)

    def test_the_source_class_word_is_kept_when_the_target_has_none(self):
        dst = proj(chan(3, "Audio 4", uuid=uuid(100)), slot(3, 4), bus(10), bus(15))
        out, _ = copy_sends(source(), dst, src_owner=5, dst_owner=3)
        new = send_raw(out, 3, 0)
        self.assertEqual(struct.unpack_from("<I", new, HEADER)[0], 99)
        self.assertEqual(struct.unpack_from("<H", new, 4)[0], 4)

    def test_bus_uuids_are_the_targets_own(self):
        out, _ = copy_sends(source(), session(), src_owner=5, dst_owner=3)
        self.assertEqual(send_raw(out, 3, 0)[DEST], uuid(1015))
        self.assertEqual(send_raw(out, 3, 1)[DEST], uuid(1010))

    def test_instance_uuids_are_minted(self):
        src = source()
        out, _ = copy_sends(src, session(), src_owner=5, dst_owner=3)
        self.assertNotEqual(send_raw(out, 3, 0)[UUID], send_raw(src, 5, 0)[UUID])

    def test_refuses_an_empty_source(self):
        with self.assertRaises(ValueError):
            copy_sends(session(), session(), src_owner=3, dst_owner=2)

    def test_refuses_a_bus_the_target_lacks(self):
        dst = proj(chan(3, "Audio 4", uuid=uuid(100)), bus(15))
        with self.assertRaises(ValueError):
            copy_sends(source(), dst, src_owner=5, dst_owner=3)


class RemoveSendsTest(unittest.TestCase):
    def test_drops_the_owners_sends_and_nothing_else(self):
        data = session()
        out = remove_sends(data, owner=2)
        self.assertEqual(len(out), len(data) - 2 * SEND_LEN)
        self.assertEqual([k for _t, k in run(out, 2)], [0xFFFF, 4, 12])
        self.assertNotIn(2, read_sends(out))

    def test_a_channel_without_sends_is_untouched(self):
        from logicxkit.logic.services.keyflags import sync_key_flags
        data = sync_key_flags(session())
        self.assertEqual(remove_sends(data, owner=3), data)

    def test_refuses_a_corrupt_stream(self):
        with self.assertRaises(ValueError):
            remove_sends(session() + b"\x00" * 5, owner=2)
