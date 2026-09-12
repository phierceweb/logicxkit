"""A send's level, against Logic's own drags of the send knob on a blank project."""

import unittest

import _goldens
from logicxkit.logic.services.sends import read_sends
from logicxkit.logicx import project_data

KEYS = ["send-bus-1-logic", "send-level-1-logic", "send-level-2-logic"]


@_goldens.needs(*KEYS)
class SendLevelTest(unittest.TestCase):
    def test_each_save_reads_the_level_the_knob_was_dragged_to(self):
        for key in KEYS:
            (send,) = read_sends(project_data(_goldens.path(key)))[_goldens.fact(key, "owner")]
            with self.subTest(key=key):
                self.assertEqual(send.bus, _goldens.fact(key, "bus"))
                self.assertEqual(send.level, _goldens.fact(key, "level_byte"))
                self.assertEqual(int(send.level_exact), send.level)


@_goldens.needs("send-two-base-3-logic")
class SlotBaseFollowsSendsTest(unittest.TestCase):
    """Two sends on a blank project moved its slot base to 3; the channels' own base word says
    so unanimously, and the reader must follow it rather than a vote over slot-shaped records."""

    def test_the_slot_base_is_the_channels_word(self):
        from logicxkit.logic.services.insert import slot_index_base
        self.assertEqual(slot_index_base(project_data(_goldens.path("send-two-base-3-logic"))),
                         _goldens.fact("send-two-base-3-logic", "slot_base"))


if __name__ == "__main__":
    unittest.main()
