"""Smart Control mappings name their plug-in by slot index; a slot move carries them along."""

import plistlib
import struct
import unittest

from _records import rec
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.mixer.smart_controls import mapping_slots, shift_mapping_slots
from logicxkit.logic.services.mixer.slots import archive_index


def archive(slots: list[int], *, key: int = 12, owner: int = 3, index: int = 1) -> bytes:
    """A keyed archive the way Logic writes one: shared int objects, mappings by UID."""
    objects: list = ["$null"]
    ints = {}

    def uid_of(n: int) -> plistlib.UID:
        if n not in ints:
            objects.append(n)
            ints[n] = plistlib.UID(len(objects) - 1)
        return ints[n]

    objects.append({"$classname": "MAPlugInParameterMapping", "$classes": ["MAPlugInParameterMapping", "NSObject"]})
    mapping_class = plistlib.UID(len(objects) - 1)
    mappings = []
    for i, slot in enumerate(slots):
        objects.append({"$class": mapping_class, "slot": uid_of(slot), "parameterIndex_1": uid_of(slot + 20),
                        "kDisplayIndexKey": uid_of(i)})
        mappings.append(plistlib.UID(len(objects) - 1))
    objects.append({"$classname": "NSMutableArray", "$classes": ["NSMutableArray", "NSArray", "NSObject"]})
    array_class = plistlib.UID(len(objects) - 1)
    objects.append({"$class": array_class, "NS.objects": mappings})
    top = plistlib.UID(len(objects) - 1)
    plist = {"$version": 100000, "$archiver": "NSKeyedArchiver", "$top": {"dictionary": top}, "$objects": objects}
    body = plistlib.dumps(plist, fmt=plistlib.FMT_BINARY)
    payload = bytes(4) + b"\x07\x00" + bytes([index, 0]) + bytes(8) + struct.pack("<I", len(body)) + body + bytes(range(16))
    return rec(b"UCuA", owner, key, payload, 7)


class ShiftTest(unittest.TestCase):
    def test_reads_the_slots(self):
        self.assertEqual(mapping_slots(archive([5, 5, 1, 7])), [5, 5, 1, 7])
        self.assertEqual(archive_index(archive([5])), 1)

    def test_moves_the_slots_from_the_position_on(self):
        out = shift_mapping_slots(archive([5, 5, 1, 7]), from_index=5, by=1)
        self.assertEqual(mapping_slots(out), [6, 6, 1, 8])

    def test_shared_ints_elsewhere_are_untouched(self):
        """The int 5 is also every mapping's display index or parameter: only `slot` moves."""
        raw = archive([5, 5, 1, 7])
        out = shift_mapping_slots(raw, from_index=5, by=1)
        objects = plistlib.loads(out[HEADER + 20:HEADER + 20 + struct.unpack_from("<I", out, HEADER + 16)[0]])["$objects"]
        params = [objects[m["parameterIndex_1"].data] for m in objects if isinstance(m, dict) and "slot" in m]
        self.assertEqual(params, [25, 25, 21, 27])

    def test_the_record_sizes_follow_and_the_tail_stays(self):
        raw = archive([5, 5, 1, 7])
        out = shift_mapping_slots(raw, from_index=5, by=1)
        payload = out[HEADER:]
        self.assertEqual(struct.unpack_from("<I", out, 28)[0], len(payload))
        size = struct.unpack_from("<I", payload, 16)[0]
        self.assertEqual(payload[20 + size:], bytes(range(16)))
        self.assertEqual(archive_index(out), 1)

    def test_nothing_to_move_returns_the_record_as_is(self):
        raw = archive([1, 2])
        self.assertIs(shift_mapping_slots(raw, from_index=5, by=1), raw)


if __name__ == "__main__":
    unittest.main()
