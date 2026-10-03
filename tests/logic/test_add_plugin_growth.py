"""`add_plugin` on a chain that grows into the two keys Logic keeps under the reference: the
reference, the records under it and the archives above it move up on every channel."""

import struct
import unittest

from _records import proj, rec
from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.stream.stream import HEADER, project_records
from test_transplant_ids import au, mono_chan, native, ref

OWNER = 3


def archive(owner: int, key: int, n: int) -> bytes:
    """One of the two keyed-archive records a channel carries at the reference key + 2 and + 3."""
    from test_smart_controls import archive as keyed_archive
    return keyed_archive([], key=key, owner=owner, index=n)


def stray(owner: int, key: int) -> bytes:
    """A non-slot record under the reference (the 68- and 200-byte ones every session carries)."""
    return rec(b"UCuA", owner, key, bytes(200), 5)


def _keyed(data: bytes, owner: int) -> list[int]:
    return sorted(r.key for r in project_records(data) if r.tag == b"UCuA" and r.owner == owner)


def _shown(data: bytes) -> dict[int, int]:
    from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
    return {r.owner: struct.unpack_from("<H", r.raw, HEADER + 30)[0]
            for r in project_records(data) if r.tag == CHANNEL_TAG}


def _with_shown(data: bytes, shown: int) -> bytes:
    from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
    from logicxkit.logic.services.stream.stream import reassemble
    out = []
    for r in project_records(data):
        raw = bytearray(r.raw)
        if r.tag == CHANNEL_TAG:
            struct.pack_into("<H", raw, HEADER + 30, shown)
        out.append(bytes(raw))
    return reassemble(data, out)


class GrowthTest(unittest.TestCase):
    """Logic keeps two keys between the longest chain and the reference. A chain growing into
    them moves the reference, the records under it and the archives above it — on every
    channel, since one key layout serves the project (the logic README, "The slot key range
    grows"): 4 slots on keys 4..7, reference at 10, the archives at 12 and 13."""

    def _project(self, *slots: bytes) -> bytes:
        return proj(mono_chan(OWNER, "Audio 3"), *slots, stray(OWNER, 9), ref(OWNER, 10),
                    archive(OWNER, 12, 1), archive(OWNER, 13, 2),
                    mono_chan(5, "Audio 5"), native(5, 4, 50), ref(5, 10), archive(5, 12, 1), archive(5, 13, 2))

    def test_a_fifth_slot_pushes_the_layout_up_one_key_on_every_channel(self):
        from logicxkit.logic.services.stream.keyflags import flag_errors
        from logicxkit.logic.services.mixer.slots import property_key_base
        data = self._project(*(native(OWNER, 4 + i, i) for i in range(4)))
        out, report = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual((report["key"], report["grown"]), (8, 1))
        self.assertEqual(_keyed(out, OWNER), [4, 5, 6, 7, 8, 10, 11, 13, 14])
        self.assertEqual(_keyed(out, 5), [4, 11, 13, 14])
        self.assertEqual(property_key_base(out), 11)
        self.assertEqual(flag_errors(out), [])
        self.assertIn(ref(OWNER, 11), out)

    def test_the_projects_own_headroom_is_kept(self):
        """Reference 13 over slots to key 7 is a six-key headroom (the owner's sessions): a
        slot at key 8 moves the reference to 14 and the archives to 16 and 17, as Logic's
        own re-save does; three keys would leave the second archive past the flag words."""
        from logicxkit.logic.services.stream.keyflags import flag_errors
        data = proj(mono_chan(OWNER, "Audio 3"), *(native(OWNER, 4 + i, i) for i in range(4)), ref(OWNER, 13),
                    archive(OWNER, 15, 1), archive(OWNER, 16, 2),
                    mono_chan(5, "Audio 5"), native(5, 4, 50), ref(5, 13), archive(5, 15, 1), archive(5, 16, 2))
        out, report = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual((report["key"], report["grown"]), (8, 1))
        self.assertEqual(_keyed(out, OWNER), [4, 5, 6, 7, 8, 14, 16, 17])
        self.assertEqual(_keyed(out, 5), [4, 14, 16, 17])
        self.assertEqual(flag_errors(out), [])

    def test_a_slot_under_the_projects_highest_key_moves_nothing(self):
        """Channel 3 runs to key 7; a second slot on channel 5 lands at 5, inside the range."""
        data = self._project(*(native(OWNER, 4 + i, i) for i in range(4)))
        out, report = add_plugin(data, 5, au(9, 4, 7))
        self.assertEqual((report["key"], report["grown"]), (5, 0))
        self.assertEqual(_keyed(out, 5), [4, 5, 10, 12, 13])
        self.assertEqual(_keyed(out, OWNER), [4, 5, 6, 7, 9, 10, 12, 13])

    def test_a_front_insert_on_a_full_chain_grows_too(self):
        data = self._project(*(native(OWNER, 4 + i, i) for i in range(4)))
        out, report = add_plugin(data, OWNER, au(9, 4, 7), at=1)
        self.assertEqual((report["moved"], report["grown"]), ([(4, 5), (5, 6), (6, 7), (7, 8)], 1))
        self.assertEqual(_keyed(out, OWNER), [4, 5, 6, 7, 8, 10, 11, 13, 14])

    def test_every_channel_record_shows_the_longest_chain_plus_one(self):
        """Channel record +30: five slots on keys 4..8 show six, on the other channel too."""
        data = self._project(*(native(OWNER, 4 + i, i) for i in range(4)))
        out, _ = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual(_shown(out), {OWNER: 6, 5: 6})

    def test_the_projects_shown_count_is_the_highest_any_record_carries(self):
        from logicxkit.logic.services.mixer.add_plugin import shown_slots
        self.assertEqual(shown_slots(self._project(native(OWNER, 4, 1))), 0)
        self.assertEqual(shown_slots(_with_shown(self._project(native(OWNER, 4, 1)), 9)), 9)

    def test_the_shown_count_never_drops(self):
        data = _with_shown(self._project(native(OWNER, 4, 1)), 9)
        out, _ = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual(_shown(out), {OWNER: 9, 5: 9})

    def test_the_reference_position_is_read_from_the_archives_when_no_channel_names_a_strip(self):
        from logicxkit.logic.services.mixer.slots import property_key_base
        data = proj(mono_chan(OWNER, "Audio 3"), native(OWNER, 6, 1), archive(OWNER, 11, 1), archive(OWNER, 12, 2))
        self.assertEqual(property_key_base(data), 9)
        out, report = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual((report["key"], report["grown"]), (7, 1))
        self.assertEqual(_keyed(out, OWNER), [6, 7, 12, 13])


if __name__ == "__main__":
    unittest.main()
