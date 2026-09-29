"""The slot writers carry the automation that names a slot by its insert number: on Logic's own
`autoset-resave-logic` (Audio 2: Compressor, Noise Gate, Pro-C 2 in slots 1-3, a lane on each),
a plug-in put in front moves every lane down one insert, a removal drops its slot's lanes and
moves the later ones up. An instrument channel's slot 1 is its instrument. Skips without the
public corpus."""

import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.add_plugin import add_plugin
from logicxkit.logic.services.automation import read_automation
from logicxkit.logic.services.insert_lanes import channel_object, move_lanes
from logicxkit.logic.services.plugin_library import find_donor, load_library
from logicxkit.logic.services.remove_plugin import remove_plugin
from logicxkit.logic.services.transplant import channel_slots, slot_at, slot_class_version
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

KEY, INST = "autoset-resave-logic", "tracks-instrument-logic"


def _lanes(data: bytes, owner: int) -> dict[tuple[int, int], int]:
    """(insert, parameter) -> points, on the channel's own folder."""
    obj = channel_object(data, owner)
    return {(lane.slot, lane.param_index): len(lane.points) for a in read_automation(data)
            if a.track_object == obj for lane in a.lanes if lane.slot}


def _donor(data: bytes, name: str):
    return find_donor(load_library([PACKAGED / "donors"]), name, width=None, version=slot_class_version(data))


@_goldens.needs(KEY)
class LanesFollowTheSlotsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = project_data(_goldens.path(KEY))
        cls.owner = owner_by_label(cls.data, "Audio 2")
        cls.before = _lanes(cls.data, cls.owner)

    def test_the_golden_has_a_lane_on_each_slot(self):
        self.assertEqual(sorted(self.before), [(1, 0), (1, 13), (2, 4), (3, 1)])

    def test_a_plug_in_in_front_moves_every_lane_down_one(self):
        gain = _donor(self.data, "Gain")
        out, report = add_plugin(self.data, self.owner, gain.raw, at=1, type_id=gain.type_id)
        self.assertEqual(_lanes(out, self.owner), {(s + 1, p): n for (s, p), n in self.before.items()})
        self.assertEqual(report["lanes_moved"], sum(self.before.values()))

    def test_an_append_moves_nothing(self):
        gain = _donor(self.data, "Gain")
        out, report = add_plugin(self.data, self.owner, gain.raw, type_id=gain.type_id)
        self.assertEqual((_lanes(out, self.owner), report["lanes_moved"]), (self.before, 0))

    def test_a_removal_drops_its_slots_lanes_and_moves_the_rest_up(self):
        out, report = remove_plugin(self.data, self.owner, 1)
        self.assertEqual(_lanes(out, self.owner), {(1, 4): self.before[(2, 4)], (2, 1): self.before[(3, 1)]})
        self.assertEqual(report["lanes_dropped"], self.before[(1, 0)] + self.before[(1, 13)])

    def test_the_last_slots_removal_moves_nothing(self):
        out, report = remove_plugin(self.data, self.owner, 3)
        self.assertEqual(_lanes(out, self.owner), {k: n for k, n in self.before.items() if k[0] != 3})
        self.assertEqual(report["lanes_moved"], 0)

    def test_an_empty_slot_is_refused_by_name(self):
        with self.assertRaises(ValueError) as e:
            remove_plugin(self.data, self.owner, 5)
        self.assertIn("slot(s) 1, 2, 3", str(e.exception))

    def test_a_flagged_point_keeps_its_flag_when_it_moves(self):
        flagged = [p.flagged for a in read_automation(self.data) for lane in a.lanes for p in lane.points]
        out, _ = move_lanes(self.data, self.owner, {1: 2, 2: 3, 3: 4})
        self.assertEqual(sorted(flagged), sorted(p.flagged for a in read_automation(out) for lane in a.lanes for p in lane.points))

    def test_a_lane_past_insert_15_is_refused(self):
        with self.assertRaises(ValueError):
            move_lanes(self.data, self.owner, {3: 16})


@_goldens.needs(INST)
class InstrumentSlotTest(unittest.TestCase):
    """Logic numbers an instrument channel's instrument as insert 1 and its first Audio FX as
    insert 2: slot 1 is the instrument's."""

    @classmethod
    def setUpClass(cls):
        cls.data = project_data(_goldens.path(INST))
        cls.owner = owner_by_label(cls.data, "Inst 1")
        cls.comp = _donor(cls.data, "Compressor")

    def test_an_effect_is_refused_in_front_of_the_instrument(self):
        with self.assertRaises(ValueError) as e:
            add_plugin(self.data, self.owner, self.comp.raw, at=1, type_id=self.comp.type_id)
        self.assertIn("instrument", str(e.exception))

    def test_an_append_lands_behind_the_instrument(self):
        out, report = add_plugin(self.data, self.owner, self.comp.raw, type_id=self.comp.type_id)
        self.assertEqual(report["position"], 2)
        self.assertEqual(slot_at(out, self.owner, 1).raw, slot_at(self.data, self.owner, 1).raw)

    def test_removing_the_instrument_moves_no_effect_into_its_slot(self):
        out, _ = add_plugin(self.data, self.owner, self.comp.raw, type_id=self.comp.type_id)
        out, report = remove_plugin(out, self.owner, 1)
        self.assertEqual((report["moved"], slot_at(out, self.owner, 1)), ([], None))
        self.assertIsNotNone(slot_at(out, self.owner, 2))

    def test_an_instrument_is_refused_on_an_audio_channel(self):
        klopf = _donor(self.data, "Klopfgeist")
        with self.assertRaises(ValueError):
            add_plugin(self.data, owner_by_label(self.data, "Audio 1"), klopf.raw, type_id=klopf.type_id)

    def test_the_channels_slots_keep_their_order(self):
        out, _ = add_plugin(self.data, self.owner, self.comp.raw, type_id=self.comp.type_id)
        keys = [r.key for r in channel_slots(out, self.owner)]
        self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
