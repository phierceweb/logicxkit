"""Packaged natives placed at the other width and copies given their own ids, as Logic re-saved
them: an Expander re-stamped onto a stereo channel and a Fuzz-Wah's one build on a mono channel
kept byte for byte; two Channel EQs with stamped ids kept, where one id on both was reassigned.
Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic._binary import find_blocks
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.binding import channels
from logicxkit.logic.services.stream import HEADER
from logicxkit.logic.services.slot_width import slot_format
from logicxkit.logic.services.transplant import ID_TAIL, ID_WINDOW, channel_slots, slot_at
from logicxkit.logicx import project_data

TOKEN = slice(HEADER + 76, HEADER + 78)          # a per-plug-in token Logic recomputes on load (the logic README)


def _slot(key: str) -> bytes:
    facts = _goldens.entry(key)["facts"]
    data = project_data(_goldens.path(key))
    return slot_at(data, owner_by_label(data, facts["channel"]), facts["slot"]).raw


def _eq_ids(key: str) -> dict[str, bytes]:
    data = project_data(_goldens.path(key))
    return {c.label: r.raw[HEADER:][-ID_WINDOW:-ID_TAIL] for o, c in channels(data).items() for r in channel_slots(data, o)
            if (b := find_blocks(r.raw[HEADER:])) and b[0][1] == 236}


class OtherWidthTest(unittest.TestCase):
    @_goldens.needs("addplugin-expander-stereo-mine", "addplugin-expander-stereo-logic",
                    "addplugin-fuzzwah-mono-mine", "addplugin-fuzzwah-mono-logic")
    def test_logic_kept_the_placed_slots(self):
        for mine, logic in (("addplugin-expander-stereo-mine", "addplugin-expander-stereo-logic"),
                            ("addplugin-fuzzwah-mono-mine", "addplugin-fuzzwah-mono-logic")):
            with self.subTest(mine):
                self.assertEqual(slot_format(_slot(mine)), _goldens.fact(mine, "width"))
                self.assertEqual(_slot(mine), _slot(logic))


class OwnIdsTest(unittest.TestCase):
    @_goldens.needs("addplugin-ids-mine", "addplugin-ids-logic", "addplugin-ids-shared-mine", "addplugin-ids-shared-logic")
    def test_stamped_ids_are_kept_and_a_shared_one_is_reassigned(self):
        mine, logic = _eq_ids("addplugin-ids-mine"), _eq_ids("addplugin-ids-logic")
        self.assertEqual(len(set(mine.values())), 2)
        self.assertEqual(mine, logic)
        shared, fixed = _eq_ids("addplugin-ids-shared-mine"), _eq_ids("addplugin-ids-shared-logic")
        self.assertEqual(len(set(shared.values())), 1)
        reassigned = _goldens.fact("addplugin-ids-shared-logic", "reassigned")
        self.assertNotEqual(fixed[reassigned], shared[reassigned])
        self.assertEqual({k: v for k, v in fixed.items() if k != reassigned}, {k: v for k, v in shared.items() if k != reassigned})


if __name__ == "__main__":
    unittest.main()
