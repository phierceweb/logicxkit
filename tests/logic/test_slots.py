"""Record-level slot surgery on a .cst.

A .cst is a flat stream of self-describing records: 36-byte header + payload, payload size at
+28, record key (u16) at +18. Keys 0-2 are sends, keys 4+ are plugin slots, higher keys are
per-channel properties. There is no slot-count field and no file-level length field, so slots
can be replaced or dropped without touching anything else — which is what lets us keep a
channel's own routing AND sends while changing only its chain (a seam graft loses the sends).
"""

import struct
import unittest

from logicxkit.logic import plugin_slots, read_records, replace_slots, write_records


def rec(tag: bytes, key: int, payload: bytes) -> bytes:
    h = bytearray(36)
    h[0:4] = tag
    struct.pack_into("<H", h, 18, key)
    struct.pack_into("<I", h, 28, len(payload))
    return bytes(h) + payload


def strip(*records: bytes) -> bytes:
    return b"".join(records)


class ReadRecordsTest(unittest.TestCase):
    def test_walks_every_record_exactly(self):
        data = strip(rec(b"OCuA", 0xFFFF, b"H" * 20), rec(b"UCuA", 4, b"S" * 8),
                     rec(b"OCuA", 0xFFFF, b"T" * 14))
        got = read_records(data)
        self.assertEqual([r.key for r in got], [0xFFFF, 4, 0xFFFF])
        self.assertEqual(b"".join(r.raw for r in got), data)

    def test_roundtrip_is_byte_exact(self):
        data = strip(rec(b"OCuA", 0xFFFF, b"H" * 20), rec(b"UCuA", 1, b"\x00" * 44))
        self.assertEqual(write_records(read_records(data)), data)

    def test_stops_on_foreign_tag(self):
        self.assertEqual(len(read_records(rec(b"OCuA", 0xFFFF, b"H") + b"JUNKJUNK")), 1)


class PluginSlotTest(unittest.TestCase):
    def setUp(self):
        self.data = strip(
            rec(b"OCuA", 0xFFFF, b"H" * 20),
            rec(b"UCuA", 0, b"send0"), rec(b"UCuA", 1, b"send1"),
            rec(b"UCuA", 4, b"plugA"), rec(b"UCuA", 5, b"plugB"),
            rec(b"UCuA", 12, b"props"),
            rec(b"OCuA", 0xFFFF, b"T" * 14))

    def test_finds_only_plugin_slots(self):
        self.assertEqual([r.key for r in plugin_slots(self.data)], [4, 5])

    def test_replace_keeps_sends_and_properties(self):
        out = replace_slots(self.data, [rec(b"UCuA", 4, b"newplug")])
        self.assertEqual([r.key for r in read_records(out)], [0xFFFF, 0, 1, 4, 12, 0xFFFF])
        self.assertIn(b"send0", out)
        self.assertIn(b"props", out)
        self.assertNotIn(b"plugA", out)

    def test_replacement_slots_are_renumbered_from_four(self):
        out = replace_slots(self.data, [rec(b"UCuA", 9, b"x"), rec(b"UCuA", 3, b"y")])
        self.assertEqual([r.key for r in plugin_slots(out)], [4, 5])

    def test_dropping_all_slots_leaves_a_clean_strip(self):
        out = replace_slots(self.data, [])
        self.assertEqual([r.key for r in read_records(out)], [0xFFFF, 0, 1, 12, 0xFFFF])

    def test_slot_order_is_preserved(self):
        out = replace_slots(self.data, [rec(b"UCuA", 4, b"first"), rec(b"UCuA", 5, b"second")])
        payloads = [r.raw[36:] for r in plugin_slots(out)]
        self.assertEqual(payloads, [b"first", b"second"])


class ReslotSpecTest(unittest.TestCase):
    """`reslot` is the record-level graft: keep the target's routing AND sends, take the
    donor's plugin slots. The seam-level `graft` cannot do this — sends live after the seam,
    so it inherits the donor's."""

    def setUp(self):
        self.target = strip(rec(b"OCuA", 0xFFFF, b"H" * 20),
                            rec(b"UCuA", 0, b"SEND-A"), rec(b"UCuA", 1, b"SEND-B"),
                            rec(b"UCuA", 4, b"HEAVY1"), rec(b"UCuA", 5, b"HEAVY2"),
                            rec(b"UCuA", 12, b"props"), rec(b"OCuA", 0xFFFF, b"T" * 14))
        self.donor = strip(rec(b"OCuA", 0xFFFF, b"D" * 20),
                           rec(b"UCuA", 4, b"NATIVE-EQ"), rec(b"UCuA", 5, b"NATIVE-CMP"),
                           rec(b"OCuA", 0xFFFF, b"T" * 14))
        self.files = {"/t.cst": self.target, "/d.cst": self.donor}

    def _base(self, preset):
        from logicxkit.logic import resolve_base
        return resolve_base({}, preset, lambda p: self.files[str(p)])

    def test_keeps_target_sends_and_takes_donor_slots(self):
        out = self._base({"reslot": {"routing_from": "/t.cst", "chain_from": "/d.cst"}})
        self.assertIn(b"SEND-A", out)
        self.assertIn(b"SEND-B", out)
        self.assertIn(b"NATIVE-EQ", out)
        self.assertNotIn(b"HEAVY1", out)

    def test_drop_all_slots(self):
        out = self._base({"reslot": {"routing_from": "/t.cst", "chain_from": None}})
        self.assertEqual(plugin_slots(out), [])
        self.assertIn(b"SEND-A", out)

    def test_keep_selected_own_slots(self):
        """Removing one plugin from a chain — e.g. keep an amp sim, drop the mix compressor."""
        out = self._base({"reslot": {"routing_from": "/t.cst", "keep_slots": [0]}})
        self.assertIn(b"HEAVY1", out)
        self.assertNotIn(b"HEAVY2", out)

    def test_reslot_conflicts_with_template(self):
        with self.assertRaises(ValueError):
            self._base({"template": "/t.cst", "reslot": {"routing_from": "/t.cst"}})


class SlotGuardTest(unittest.TestCase):
    """Slot keys are positional properties of the channel class, so the range is
    schema-version-dependent (a strip's `.cst` reference record sits at key 12 in a modern
    strip but key 9 in a Logic 12.2 project). Verified across the whole library: no reference
    record falls inside the slot range. If one ever does, refuse rather than silently
    destroying the strip's identity."""

    def test_refuses_to_replace_a_reference_record(self):
        from logicxkit.logic import replace_slots
        data = strip(rec(b"OCuA", 0xFFFF, b"H" * 20),
                     rec(b"UCuA", 4, b"\x00" * 40 + b"Kick In.cst" + b"\x00" * 60),
                     rec(b"OCuA", 0xFFFF, b"T" * 14))
        with self.assertRaises(ValueError):
            replace_slots(data, [])

    def test_normal_slots_still_replace(self):
        from logicxkit.logic import plugin_slots, replace_slots
        data = strip(rec(b"OCuA", 0xFFFF, b"H" * 20), rec(b"UCuA", 4, b"GAMETSPP" + b"\x00" * 40),
                     rec(b"OCuA", 0xFFFF, b"T" * 14))
        self.assertEqual(plugin_slots(replace_slots(data, [])), [])
