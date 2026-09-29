"""What Logic's Automation Event List named, for lanes the slot writers placed or moved: a lane's
insert is the mixer slot, empty slots counted — insert 1 names nothing where the chain starts at
slot 4, insert 4 names the Pro-Q 4 there — and an instrument channel's instrument is insert 1.
Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.automation import read_automation
from logicxkit.logic.services.insert_lanes import channel_object
from logicxkit.logic.services.transplant import slot_at
from logicxkit.logicx import project_data


def _lanes(key: str, channel: str) -> dict[int, list[int]]:
    """insert -> the parameter indices of its lanes, on the channel's folder."""
    data = project_data(_goldens.path(key))
    obj = channel_object(data, owner_by_label(data, channel))
    out: dict[int, list[int]] = {}
    for a in read_automation(data):
        if a.track_object == obj:
            for lane in a.lanes:
                if lane.slot:
                    out.setdefault(lane.slot, []).append(lane.param_index)
    return {k: sorted(v) for k, v in out.items()}


def _named(key: str) -> dict[int, str]:
    """parameter index -> the name Logic's list gave it (one lane per index here)."""
    return {num: name for _bar, num, _val, name in _goldens.fact(key, "event_list")}


class InsertIsTheMixerSlotTest(unittest.TestCase):
    @_goldens.needs("slots-insert1-logic", "slots-insert4-mine")
    def test_insert_1_names_nothing_and_insert_4_the_pro_q_4_in_slot_4(self):
        self.assertEqual(set(_named("slots-insert1-logic").values()), {""})
        self.assertEqual(_named("slots-insert4-mine"), {1: "Band 1 Enabled", 26: "Band 2 Gain", 48: "Band 3 Frequency"})
        data = project_data(_goldens.path("slots-insert4-mine"))
        self.assertIsNotNone(slot_at(data, owner_by_label(data, "Audio 2"), 4))
        self.assertEqual(_lanes("slots-insert4-mine", "Audio 2"), {4: [1, 26, 48]})

    @_goldens.needs("slots-replace4-mine", "slots-replace4-logic")
    def test_a_translated_replace_carries_the_lanes_onto_the_same_insert(self):
        self.assertEqual(_lanes("slots-replace4-mine", "Audio 2"), {4: [0, 10, 17]})
        self.assertEqual(_lanes("slots-replace4-logic", "Audio 2"), {4: [0, 10, 17]})
        self.assertEqual(_named("slots-replace4-logic"), {0: "Low Cut On/Off", 10: "Peak 1 Gain", 17: "Peak 3 Frequency"})


class LanesFollowTheirPlugInsTest(unittest.TestCase):
    @_goldens.needs("slots-front-mine", "slots-front-logic")
    def test_a_plug_in_put_in_front_leaves_every_lane_on_its_own_plug_in(self):
        want = {int(k): v for k, v in _goldens.fact("slots-front-mine", "lanes").items()}
        self.assertEqual(_lanes("slots-front-mine", "Audio 2"), want)
        self.assertEqual(_lanes("slots-front-logic", "Audio 2"), want)
        names = {(num, name) for _b, num, _v, name in _goldens.fact("slots-front-logic", "event_list")}
        self.assertEqual(names, {(0, "Threshold"), (13, "Auto Release"), (4, "Hold"), (1, "Threshold")})

    @_goldens.needs("slots-remove-mine", "slots-remove-logic")
    def test_a_removal_takes_its_lanes_and_leaves_the_rest_on_their_plug_ins(self):
        want = {int(k): v for k, v in _goldens.fact("slots-remove-mine", "lanes").items()}
        self.assertEqual(_lanes("slots-remove-mine", "Audio 2"), want)
        self.assertEqual(_lanes("slots-remove-logic", "Audio 2"), want)
        self.assertEqual(_named("slots-remove-logic"), {4: "Hold", 1: "Threshold"})


class InstrumentChannelTest(unittest.TestCase):
    @_goldens.needs("slots-inst-mine", "slots-inst-logic")
    def test_the_instrument_is_insert_1_and_the_first_audio_effect_insert_2(self):
        self.assertEqual(_lanes("slots-inst-mine", "Inst 1"), {1: [0], 2: [0], 3: [1]})
        rows = _goldens.fact("slots-inst-logic", "event_list")
        by_val = {val: name for _b, _num, val, name in rows}
        self.assertEqual((by_val[32], by_val[64], by_val[76]), ("Level", "Threshold", ""))   # 0.25 on 1, 0.5 on 2, 0.6 on 3


class NamedTrackTest(unittest.TestCase):
    @_goldens.needs("slots-named-mine", "slots-named-logic")
    def test_the_lane_written_by_track_name_kept_its_insert(self):
        self.assertEqual(_lanes("slots-named-mine", "Inst 1"), {2: [0]})
        self.assertEqual(_lanes("slots-named-logic", "Inst 1"), {2: [0]})


if __name__ == "__main__":
    unittest.main()
