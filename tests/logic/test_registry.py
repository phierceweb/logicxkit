"""gnoS: the object pair, the slot pair, the list stamps and the selection fields."""

import struct
import unittest

import _paths  # noqa: F401
from _records import gnos
from logicxkit.logic.services.insert import HEADER
from logicxkit.logic.services.recbuild import time_fields
from _records import rec
from logicxkit.logic.services.registry import entry_at, register_object, run_entries, set_selection


def entries(payload: bytes, kind: int, stride: int) -> dict[int, bytes]:
    out = {}
    for s in range(0, len(payload) - 8, 4):
        t, i = struct.unpack_from("<II", payload, s)
        if t == kind and (s + stride <= len(payload)):
            out.setdefault(i, payload[s + 8:s + stride])
    return out


class RegisterTest(unittest.TestCase):
    def setUp(self):
        self.base = gnos(88, 92, 504, slots=(20, 24, 28))[HEADER:]
        self.uuid = bytes(range(16))
        self.out = register_object(self.base, object_id=508, top=504, uuid=self.uuid, slot=28)

    def test_both_object_entries_follow_the_top_id(self):
        self.assertEqual(len(self.out) - len(self.base), 40)
        at24 = entry_at(self.out, 0x14, 508, 24)
        self.assertEqual(struct.unpack_from("<II", self.out, at24 - 24), (0x14, 504))
        self.assertEqual(self.out[at24 + 8:at24 + 24], self.uuid)
        at16 = entry_at(self.out, 0x14, 508, 16)
        self.assertEqual(struct.unpack_from("<II", self.out, at16 - 16), (0x14, 504))
        self.assertEqual(self.out[at16 + 8:at16 + 16], time_fields(self.uuid))

    def test_the_slot_pair_is_filled_and_agrees(self):
        at24, at16 = entry_at(self.out, 0x17, 28, 24), entry_at(self.out, 0x17, 28, 16)
        slot_uuid = self.out[at24 + 8:at24 + 24]
        self.assertNotEqual(slot_uuid, bytes(16))
        self.assertEqual(slot_uuid[6] >> 4, 1)                       # a v1 UUID
        self.assertEqual(self.out[at16 + 8:at16 + 16], time_fields(slot_uuid))
        for other in (20, 24):
            at = entry_at(self.out, 0x17, other, 24)
            self.assertEqual(self.out[at + 8:at + 24], bytes(16), other)

    def test_the_lists_are_restamped(self):
        for list_id in (4, 8):
            at = entry_at(self.out, 0x17, list_id, 16)
            self.assertNotEqual(self.out[at + 8:at + 16], bytes(8), list_id)

    def test_a_slot_past_the_runs_extends_both_with_every_skipped_word(self):
        out = register_object(self.base, object_id=508, top=504, uuid=self.uuid, slot=40)
        for stride in (24, 16):
            slots = [i for _at, i in run_entries(out, 0x17, stride)]
            self.assertEqual(slots, [4, 8, 20, 24, 28, 32, 36, 40])
            self.assertNotEqual(out[entry_at(out, 0x17, 40, stride) + 8:][:8], bytes(8))
        at24, at16 = entry_at(out, 0x17, 40, 24), entry_at(out, 0x17, 40, 16)
        self.assertEqual(out[at16 + 8:at16 + 16], time_fields(out[at24 + 8:at24 + 24]))
        self.assertEqual(len(out) - len(self.base), 40 + 3 * 40)

    def test_a_run_missing_the_slot_gains_it_in_place_while_the_other_run_is_stamped(self):
        """The 16-byte run lacks slot 20 while the 24-byte run has it: the 16-byte run gets the
        entry at its sorted place, and both runs agree on the new stamp."""
        base = bytearray(self.base)
        at16 = entry_at(base, 0x17, 20, 16)
        del base[at16:at16 + 16]                                 # drop slot 20 from the 16-byte run only
        self.assertEqual([i for _at, i in run_entries(bytes(base), 0x17, 16)], [4, 8, 24, 28])
        out = register_object(bytes(base), object_id=508, top=504, uuid=self.uuid, slot=20)
        self.assertEqual([i for _at, i in run_entries(out, 0x17, 16)], [4, 8, 20, 24, 28])
        self.assertEqual([i for _at, i in run_entries(out, 0x17, 24)], [4, 8, 20, 24, 28])
        at24, at16 = entry_at(out, 0x17, 20, 24), entry_at(out, 0x17, 20, 16)
        self.assertEqual(out[at16 + 8:at16 + 16], time_fields(out[at24 + 8:at24 + 24]))

    def test_a_uuid_that_looks_like_an_entry_is_not_one(self):
        base = bytearray(self.base)
        at24 = entry_at(base, 0x17, 20, 24)
        base[at24 + 8:at24 + 12] = struct.pack("<I", 0x17)   # the UUID of slot 20 starts with 0x17
        self.assertEqual([i for _at, i in run_entries(bytes(base), 0x17, 16)], [4, 8, 20, 24, 28])
        self.assertEqual([i for _at, i in run_entries(bytes(base), 0x17, 24)], [4, 8, 20, 24, 28])

    def test_slot_errors_name_the_track_triples_past_the_runs(self):
        from _records import env_obj, proj, seq_triple
        from logicxkit.logic.services.registry import slot_errors
        g = rec(b"gnoS", 0xFFFF, 0xFFFF, self.base, 5)
        data = proj(env_obj(88, "Kick"), seq_triple(300, slot=28, object_id=88), seq_triple(301, slot=44, object_id=92),
                    seq_triple(302, slot=48, object_id=0), g)
        self.assertEqual(slot_errors(data), ["object 92: slot 44 has no registry entry"])
        fixed = proj(env_obj(88, "Kick"), seq_triple(300, slot=28, object_id=88), seq_triple(301, slot=44, object_id=92),
                     rec(b"gnoS", 0xFFFF, 0xFFFF, register_object(self.base, object_id=508, top=504, uuid=self.uuid, slot=44), 5))
        self.assertEqual(slot_errors(fixed), [])

    def test_selection_fields(self):
        out = set_selection(self.out, object_id=508, track_number=26)
        self.assertEqual(struct.unpack_from("<I", out, 94)[0], 508)
        self.assertEqual(struct.unpack_from("<H", out, 210)[0], 26)
        self.assertEqual(struct.unpack_from("<I", out, 214)[0], 26)


if __name__ == "__main__":
    unittest.main()
