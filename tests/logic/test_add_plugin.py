"""`add_plugin`: a donor slot into one slot of a channel, the slots after it moved down a key.

Keys run from the slot base (4, or 2 in old projects) up to the channel's `.cst` reference key;
a slot's payload +6 is its index, key minus the base. Existing slot bytes must not change beyond
those two fields."""

import struct
import unittest

from _records import proj
from logicxkit.logic.services.add_plugin import add_plugin
from logicxkit.logic.services.insert import HEADER, KEY_OFF, SLOT_INDEX_AT, project_records
from logicxkit.logic.services.transplant import channel_slots
from test_transplant_ids import MONO, STEREO, TAIL, au, mono_chan, native, ref

OWNER = 3


def _project(*slots: bytes, base: int = 10, fmt: int = MONO) -> bytes:
    return proj(mono_chan(OWNER, "Audio 3", fmt), *slots, ref(OWNER, base),
                mono_chan(5, "Audio 5"), native(5, 4, 50), ref(5, base))


def _keys(data: bytes) -> list[int]:
    return [r.key for r in channel_slots(data, OWNER)]


def _indexes(data: bytes) -> list[int]:
    return [r.raw[HEADER + SLOT_INDEX_AT] for r in channel_slots(data, OWNER)]


def _marker(raw: bytes) -> bytes:
    """The bytes that tell one fixture slot from another: everything but key and index."""
    buf = bytearray(raw)
    struct.pack_into("<H", buf, KEY_OFF, 0)
    buf[HEADER + SLOT_INDEX_AT] = 0
    return bytes(buf)


class AppendTest(unittest.TestCase):
    def test_lands_after_the_last_slot(self):
        data = _project(native(OWNER, 4, 1), native(OWNER, 5, 2))
        out, report = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual(_keys(out), [4, 5, 6])
        self.assertEqual(_indexes(out), [0, 1, 2])
        self.assertEqual(report["key"], 6)
        self.assertEqual(report["moved"], [])

    def test_existing_slots_keep_every_other_byte(self):
        data = _project(native(OWNER, 4, 1), native(OWNER, 5, 2))
        before = [r.raw for r in channel_slots(data, OWNER)]
        out, _ = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual([r.raw for r in channel_slots(out, OWNER)][:2], before)

    def test_an_empty_channel_takes_the_first_key(self):
        data = _project()
        out, report = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual((_keys(out), report["key"]), ([4], 4))

    def test_the_other_channel_and_the_reference_survive(self):
        data = _project(native(OWNER, 4, 1))
        out, report = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual([r.key for r in channel_slots(out, 5)], [4])
        self.assertIn(ref(OWNER, 10 + report["grown"]), out)
        self.assertEqual(len(project_records(out)), len(project_records(data)) + 1)


class InsertAtTest(unittest.TestCase):
    def test_at_the_front_moves_every_slot_down(self):
        data = _project(native(OWNER, 4, 1), native(OWNER, 5, 2))
        out, report = add_plugin(data, OWNER, au(9, 4, 7), at=1)
        self.assertEqual(_keys(out), [4, 5, 6])
        self.assertEqual(_indexes(out), [0, 1, 2])
        got = [_marker(r.raw) for r in channel_slots(out, OWNER)]
        self.assertEqual(got[1:], [_marker(native(OWNER, 4, 1)), _marker(native(OWNER, 5, 2))])
        self.assertEqual(report["moved"], [(4, 5), (5, 6)])

    def test_in_the_middle(self):
        data = _project(native(OWNER, 4, 1), native(OWNER, 5, 2))
        out, report = add_plugin(data, OWNER, au(9, 4, 7), at=2)
        got = [_marker(r.raw) for r in channel_slots(out, OWNER)]
        self.assertEqual(got[0], _marker(native(OWNER, 4, 1)))
        self.assertEqual(got[2], _marker(native(OWNER, 5, 2)))
        self.assertEqual((report["key"], report["moved"]), (5, [(5, 6)]))

    def test_records_sit_in_key_order(self):
        data = _project(native(OWNER, 4, 1), native(OWNER, 5, 2))
        out, _ = add_plugin(data, OWNER, au(9, 4, 7), at=2)
        keys = [r.key for r in project_records(out) if r.owner == OWNER and r.key < 10]
        self.assertEqual(keys, sorted(keys))

    def test_at_end_plus_one_is_an_append(self):
        data = _project(native(OWNER, 4, 1))
        out, _ = add_plugin(data, OWNER, au(9, 4, 7), at=2)
        self.assertEqual(_keys(out), [4, 5])

    def test_an_empty_slot_takes_the_plug_in_and_nothing_moves(self):
        data = _project(native(OWNER, 4, 1))
        out, report = add_plugin(data, OWNER, au(9, 4, 7), at=3)
        self.assertEqual((_keys(out), _indexes(out), report["moved"], report["position"]), ([4, 6], [0, 2], [], 3))

    def test_slot_zero_is_refused(self):
        with self.assertRaises(ValueError):
            add_plugin(_project(native(OWNER, 4, 1)), OWNER, au(9, 4, 7), at=0)


class GapTest(unittest.TestCase):
    """A chain need not start at slot 1: Logic's own saves carry a lone plug-in at key 6, slot 3.
    A slot is its mixer position, empty slots counted — the number automation names it by."""

    def test_append_follows_the_last_key(self):
        data = _project(native(OWNER, 6, 1))
        out, report = add_plugin(data, OWNER, au(9, 4, 7))
        self.assertEqual((_keys(out), _indexes(out), report["moved"]), ([6, 7], [2, 3], []))

    def test_an_empty_first_slot_takes_the_plug_in_and_the_lone_one_stays(self):
        data = _project(native(OWNER, 6, 1))
        out, report = add_plugin(data, OWNER, au(9, 4, 7), at=1)
        self.assertEqual((_keys(out), _indexes(out), report["moved"]), ([4, 6], [0, 2], []))
        self.assertEqual(_marker(channel_slots(out, OWNER)[1].raw), _marker(native(OWNER, 6, 1)))

    def test_the_lone_plug_ins_own_slot_moves_it_down(self):
        data = _project(native(OWNER, 6, 1))
        out, report = add_plugin(data, OWNER, au(9, 4, 7), at=3)
        self.assertEqual((_keys(out), _indexes(out), report["moved"]), ([6, 7], [2, 3], [(6, 7)]))
        self.assertEqual(_marker(channel_slots(out, OWNER)[1].raw), _marker(native(OWNER, 6, 1)))


class StampTest(unittest.TestCase):
    def test_a_native_donor_takes_the_channels_width(self):
        data = _project(fmt=STEREO)
        out, _ = add_plugin(data, OWNER, native(9, 4, 7, fmt=MONO))
        self.assertEqual(channel_slots(out, OWNER)[0].raw[HEADER + 84], STEREO)

    def test_an_au_donor_of_the_other_width_is_refused_on_an_audio_channel(self):
        data = _project(fmt=STEREO)
        with self.assertRaises(ValueError) as e:
            add_plugin(data, OWNER, au(9, 4, 7, fmt=MONO))
        self.assertIn("stereo", str(e.exception))

    def test_id_offsets_give_the_copy_its_own_id(self):
        donor = au(9, 4, 7)
        end = len(donor) - HEADER
        out, _ = add_plugin(_project(), OWNER, donor, id_offsets=tuple(range(end - TAIL, end - TAIL + 4)))
        got = channel_slots(out, OWNER)[0].raw
        self.assertNotEqual(got[-TAIL:], donor[-TAIL:])
        self.assertEqual(got[HEADER + 200:-TAIL], donor[HEADER + 200:-TAIL])

    def test_without_offsets_the_id_is_copied(self):
        donor = au(9, 4, 7)
        out, report = add_plugin(_project(), OWNER, donor)
        self.assertEqual(channel_slots(out, OWNER)[0].raw[-TAIL:], donor[-TAIL:])
        self.assertEqual(report["ids"], "verbatim")

    def test_bypass(self):
        out, _ = add_plugin(_project(), OWNER, au(9, 4, 7), bypass=True)
        self.assertEqual(channel_slots(out, OWNER)[0].raw[HEADER + 112], 1)

    def test_the_owner_is_restamped(self):
        out, _ = add_plugin(_project(), OWNER, au(9, 4, 7))
        self.assertEqual(struct.unpack_from("<H", channel_slots(out, OWNER)[0].raw, 14)[0], OWNER)


class SettingsTest(unittest.TestCase):
    """`--set NAME=VALUE`: the donor's floats dialled by name on the way in."""

    def _donor(self) -> bytes:
        from _fixtures import chunk
        from _records import rec
        from test_transplant_ids import _widths
        p = bytearray(300)
        p[6] = 0
        _widths(p, MONO)
        body = chunk(999, [0.0, -20.0, 2.0, 0.0, 0.0, 0.0])
        return rec(b"UCuA", 9, 4, bytes(p) + body + bytes(20), 5)

    def _table(self):
        from logicxkit.logic.services.plugin_params import Table
        return Table.from_dict({"type": 999, "name": "Test Comp", "floats": 6, "params": [
            {"index": 1, "name": "Threshold", "unit": "dB", "min": -60, "max": 0},
            {"index": 2, "name": "Ratio", "min": 1, "max": 30},
            {"index": 3, "name": "Auto Gain", "choices": ["Off", "On"]}]})

    def test_named_values_land_in_the_new_slot(self):
        from logicxkit.logic._binary import find_blocks, read_block_floats
        out, _ = add_plugin(_project(), OWNER, self._donor(), settings={"threshold": -12, "Auto Gain": "On"},
                            table=self._table())
        raw = channel_slots(out, OWNER)[0].raw
        idx, type_id, n = find_blocks(raw[HEADER:])[0]
        self.assertEqual((type_id, read_block_floats(raw[HEADER:], idx, n)[:4]), (999, [0.0, -12.0, 2.0, 1.0]))

    def test_a_value_off_the_measured_range_is_refused_before_anything_is_written(self):
        with self.assertRaises(ValueError):
            add_plugin(_project(), OWNER, self._donor(), settings={"Threshold": 5}, table=self._table())
        with self.assertRaises(ValueError):
            add_plugin(_project(), OWNER, self._donor(), settings={"Threshold": -12})


class OldBaseTest(unittest.TestCase):
    """A project whose slots start at key 2: the index is key minus 2."""

    @staticmethod
    def _old_slot(owner: int, key: int, n: int) -> bytes:
        from test_transplant import OldSlotBaseTest
        return OldSlotBaseTest._old_slot(owner, key, b"S%d" % n, chunk_too=True)

    def test_append_and_index_follow_the_old_base(self):
        data = proj(mono_chan(OWNER, "Audio 3"), self._old_slot(OWNER, 2, 1), self._old_slot(OWNER, 3, 2), ref(OWNER, 13),
                    mono_chan(5, "Audio 5"), self._old_slot(5, 2, 3), ref(5, 13))
        out, report = add_plugin(data, OWNER, au(9, 4, 7), at=1)
        self.assertEqual(_keys(out), [2, 3, 4])
        self.assertEqual(_indexes(out), [0, 1, 2])
        self.assertEqual(report["moved"], [(2, 3), (3, 4)])


class SideChainTest(unittest.TestCase):
    """The slot listens to the source asked for; a donor's own side chain (a channel of the
    project it was saved from) never comes along."""

    def test_the_added_slot_carries_the_side_chain_asked_for(self):
        from logicxkit.logic.services.sidechain import SideChain, side_chain
        data = _project(native(OWNER, 4, 8))
        out, report = add_plugin(data, OWNER, au(9, 4, 7), side_chain=SideChain(0x45, 1))
        added = channel_slots(out, OWNER)[-1].raw
        self.assertEqual(side_chain(added[HEADER:]), SideChain(0x45, 1))
        self.assertEqual(report["side_chain"], "Bus 2")

    def test_a_donors_own_side_chain_is_cleared(self):
        from logicxkit.logic.services.sidechain import SideChain, side_chain, with_side_chain
        data = _project(native(OWNER, 4, 8))
        donor = with_side_chain(au(9, 4, 7), SideChain(0x40, 3))
        out, report = add_plugin(data, OWNER, donor)
        self.assertIsNone(side_chain(channel_slots(out, OWNER)[-1].raw[HEADER:]))
        self.assertIsNone(report["side_chain"])

if __name__ == "__main__":
    unittest.main()
