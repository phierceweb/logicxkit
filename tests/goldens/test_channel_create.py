"""Channel records past a session's count: fresh audio channels held against Logic's own
three adds, and Input N channels written from that layout."""

import struct
import unittest

from logicxkit.logic.services.addtrack import add_track
from logicxkit.logic.services.binding import bound_objects, channels
from logicxkit.logic.services.channel_alloc import (
    COUNT_CLASS_AT,
    COUNT_TOTAL_AT,
    is_channel_count,
    is_mixer_record,
    new_audio_channel,
)
from logicxkit.logic.services.inputs_create import ensure_inputs, mono_inputs
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.integrity import require_no_regression
from logicxkit.logic.services.routing import set_input
from logicxkit.logic.services.sends import read_sends, send_base
from logicxkit.logicx import project_data
from _data import needs

import _goldens

BASE, THREE = _goldens.path("upgraded-baseline-logic"), _goldens.path("upgraded-three-audio-logic")
LEGACY = _goldens.path("legacy-song")
LEGACY_INPUTS = _goldens.fact("legacy-song", "inputs")


def labels(data, lo, hi):
    ch = channels(data)
    return {o: (c.label, c.in_use, c.size) for o, c in sorted(ch.items()) if lo <= o <= hi}


def count_words(data):
    r = next(r for r in project_records(data) if is_channel_count(r))
    p = r.raw[HEADER:]
    return struct.unpack_from("<H", p, COUNT_TOTAL_AT)[0], {k: struct.unpack_from("<H", p, at)[0] for k, at in COUNT_CLASS_AT.items()}, len(p)


@unittest.skipUnless(BASE and THREE, "no Logic add pair")
@needs("logic", "audio-channel-12.3.1.json")
class LogicAddsTest(unittest.TestCase):
    def test_fresh_record_equals_logics(self):
        logic = next(r for r in project_records(project_data(THREE)) if is_mixer_record(r) and r.owner == 27).raw
        p = logic[HEADER:]
        ours = new_audio_channel(number=28, owner=27, object_uuid=p[-48:-32], output_uuid=p[-32:-16], input_uuid=p[-16:])
        self.assertEqual(ours, logic)

    def test_three_adds_land_where_logic_put_them(self):
        data = project_data(BASE)
        after = bound_objects(data)[26]                      # the track on Audio 27
        for name in ("Audio 28", "Audio 29", "Audio 30"):
            data, info = add_track(data, name=name, after=after, kind="audio", new_channel=True)
            after = info["object_id"] if "object_id" in info else after
        require_no_regression(project_data(BASE), data)
        logic = project_data(THREE)
        self.assertEqual(labels(data, 26, 34), labels(logic, 26, 34))
        self.assertEqual(count_words(data), count_words(logic))

    def test_a_fourth_add_goes_before_the_bare_stubs(self):
        data = project_data(THREE)                           # Audio 31 and 32 are bare, unused stubs
        after = bound_objects(data)[26]
        before = count_words(data)
        data, _ = add_track(data, name="Audio 31", after=after, kind="audio", new_channel=True)
        self.assertEqual(count_words(data)[1]["Audio"], before[1]["Audio"] + 1)
        got = labels(data, 30, 34)
        self.assertEqual(got[30][:2], ("Audio 31", True))
        self.assertEqual([got[o][0] for o in (31, 32, 33, 34)], ["Audio 32", "Audio 33", "Audio 34", "Input 1"])


@unittest.skipUnless(LEGACY, "no legacy song golden")
class InputsTest(unittest.TestCase):
    def setUp(self):
        self.song = LEGACY
        self.data = project_data(self.song)
        self.assertEqual(len(mono_inputs(self.data)), LEGACY_INPUTS)

    def test_inputs_appear_after_the_last_and_sends_keep_their_buses(self):
        """Logic's re-save of six made inputs kept the send words as they were (`117`)."""
        have = mono_inputs(self.data)[-1][0]
        after = ensure_inputs(self.data, have + 6)
        require_no_regression(self.data, after)
        new = mono_inputs(after)
        self.assertEqual([n for n, _o in new][-7:], list(range(have, have + 7)))
        self.assertEqual([o for _n, o in new][-7:], list(range(new[-7][1], new[-7][1] + 7)))
        self.assertEqual(send_base(after), send_base(self.data))
        before_sends = {o: [x.bus for x in v] for o, v in read_sends(self.data).items()}
        after_sends = {o: [x.bus for x in v] for o, v in read_sends(after).items()}
        self.assertEqual(sorted(before_sends.values()), sorted(after_sends.values()))
        total, classes, size = count_words(after)
        t0, c0, s0 = count_words(self.data)
        self.assertEqual((total, size), (t0 + 6, s0 + 24))
        self.assertEqual(classes, c0)

    def test_pairs_and_later_channels_move_up_together(self):
        after = ensure_inputs(self.data, mono_inputs(self.data)[-1][0] + 1)
        ch0, ch1 = channels(self.data), channels(after)
        first_pair0 = next(o for o, c in sorted(ch0.items()) if c.label == "Input 1-2")
        self.assertEqual(ch1[first_pair0 + 1].label, "Input 1-2")
        self.assertEqual(sum(1 for c in ch1.values() if c.label == "Output 1-2"), 1)

    def test_enough_already_is_a_no_op(self):
        self.assertEqual(ensure_inputs(self.data, 3), self.data)

    def test_a_track_can_then_take_the_new_input(self):
        wanted = mono_inputs(self.data)[-1][0] + 1
        after = ensure_inputs(self.data, wanted)
        owner = next(o for o, c in channels(after).items() if c.label == f"Input {wanted}")
        track = next(o for o, c in channels(after).items() if c.label == "Audio 1")
        routed = set_input(after, track, owner)
        p = next(r for r in project_records(routed) if is_mixer_record(r) and r.owner == track).raw
        self.assertEqual(p[-16:], channels(after)[owner].uuid)


if __name__ == "__main__":
    unittest.main()
