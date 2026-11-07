"""A chain written past the shown slots raises every channel record's shown-slot count as Logic's
re-save does, so the slots past the old count are read as slots: `slider-midpoints-raw` put five
plug-ins on the blank's Stereo Out with the count left at 2, and Logic's re-save made it 6."""

import struct
import unittest

import _goldens
from logicxkit.logicx import project_data
from logicxkit.logic.services.mixer.insert import insert_slots
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.mixer.slots import SHOWN_AT
from logicxkit.logic.services.mixer.transplant import channel_slots, owner_of, slot_at
from logicxkit.logic.services.stream.stream import HEADER, project_records

BASE, RESAVE = "blank-base", "slider-midpoints-resave-logic"


def shown(data: bytes) -> set[int]:
    return {struct.unpack_from("<H", r.raw, HEADER + SHOWN_AT)[0] for r in project_records(data)
            if r.tag == CHANNEL_TAG and len(r.raw) - HEADER >= SHOWN_AT + 2}


@_goldens.needs(BASE, RESAVE)
class ChainShownSlotsTest(unittest.TestCase):
    def setUp(self):
        self.resave = project_data(_goldens.path(RESAVE))
        self.owner = owner_of(self.resave, "Output 1-2")
        slots = channel_slots(self.resave, self.owner)
        self.written = insert_slots(project_data(_goldens.path(BASE)),
                                    {self.owner: [(r.raw, r.key, None, None) for r in slots]})

    def test_the_count_is_logics(self):
        self.assertEqual(shown(self.written), shown(self.resave))

    def test_every_slot_is_read_back(self):
        self.assertEqual([r.key for r in channel_slots(self.written, self.owner)],
                         [r.key for r in channel_slots(self.resave, self.owner)])
        self.assertIsNotNone(slot_at(self.written, self.owner, 5))


if __name__ == "__main__":
    unittest.main()
