"""A slot's index at payload +6 and the project's slot index base."""

import struct
import unittest

from test_insert import _chan, proj, rec

from logicxkit.logic import insert_slots, project_records


class SlotIndexTest(unittest.TestCase):
    """Payload +6 is the slot's index within its channel, and Logic writes it as key - 3
    (verified in Logic-written files: keys 4,5,6 -> 1,2,3; keys 3,4 -> 0,1).

    A clone inherits the donor's value, so two slots end up claiming the same index and Logic
    renders only one of them — the snare-bottom EQ vanished behind the Gain this way, and the
    compressor was hidden behind the Enveloper on every three-slot channel.
    """

    def _slot(self, donor_index: int) -> bytes:
        payload = bytearray(200)
        payload[6] = donor_index
        return rec(b"UCuA", 9, 4, bytes(payload))

    def test_index_follows_the_key(self):
        """Default base 4 (Logic 11.2/12): key 4 is index 0."""
        from logicxkit.logic.services.mixer.insert import _stamp
        for key, want in ((4, 0), (5, 1), (6, 2), (7, 3)):
            out = _stamp(self._slot(9), owner=1, key=key, floats=None, limit=0, seed="s")
            self.assertEqual(out[36 + 6], want, f"key {key} must write index {want}")

    def test_four_slots_get_four_distinct_indices(self):
        chan = bytearray(225)
        chan[123] = 1
        data = proj(rec(b"OCuA", 0, 0xFFFF, bytes(chan)))
        donor = self._slot(0)
        out = insert_slots(data, {0: [(donor, k, None, 0) for k in (4, 5, 6, 7)]})
        idx = [r.raw[36 + 6] for r in project_records(out) if r.key in (4, 5, 6, 7)]
        self.assertEqual(idx, [0, 1, 2, 3])
        self.assertEqual(len(set(idx)), 4, "indices must be unique or Logic hides a slot")


class SlotIndexBaseTest(unittest.TestCase):
    """The slot index is the 0-based position among insert slots, but the KEY those slots start
    at moves with the schema — Logic 11.0 writes slots from key 3 (index = key-3) while 11.2/12
    writes them from key 4 (index = key-4). The base is therefore derived from the project's own
    Logic-written slots rather than hardcoded."""

    def _slot(self, key: int, index: int) -> bytes:
        payload = bytearray(200)
        payload[6] = index
        payload[184:184 + 8] = b"GAMETSPP"
        struct.pack_into("<III", payload, 172, 24 + 16, 1, 4)
        struct.pack_into("<I", payload, 192, 236)
        return rec(b"UCuA", 0, key, bytes(payload))

    def test_derives_base_from_existing_slots(self):
        from logicxkit.logic import slot_index_base
        data = proj(rec(b"OCuA", 0, 0xFFFF, _chan(225)), self._slot(4, 0))
        self.assertEqual(slot_index_base(data), 4)
        older = proj(rec(b"OCuA", 0, 0xFFFF, _chan(225)), self._slot(3, 0))
        self.assertEqual(slot_index_base(older), 3)

    def test_defaults_when_the_project_has_no_slots(self):
        from logicxkit.logic import slot_index_base
        self.assertEqual(slot_index_base(proj(rec(b"OCuA", 0, 0xFFFF, _chan(225)))), 4)

    def test_inserted_slots_continue_the_projects_own_numbering(self):
        chan = bytearray(225)
        chan[123] = 1
        data = proj(rec(b"OCuA", 0, 0xFFFF, bytes(chan)),
                    rec(b"OCuA", 1, 0xFFFF, bytes(chan)), self._slot(4, 0))
        donor = self._slot(4, 0)
        out = insert_slots(data, {1: [(donor, k, None, 0) for k in (4, 5, 6)]})
        got = [r.raw[36 + 6] for r in project_records(out)
               if r.owner == 1 and r.tag == b"UCuA"]
        self.assertEqual(got, [0, 1, 2], "must match how Logic numbers this project")


if __name__ == "__main__":
    unittest.main()
