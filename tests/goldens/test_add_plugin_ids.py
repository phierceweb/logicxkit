"""Every copy `add-plugin` makes of a packaged native carries its own instance id, stamped at the
offsets `bin/regen_data.py` measured between two of Logic's instances. Logic gives a second
holder of one id a fresh one on load, so a copied id shows up as a change on the first re-save.
Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic._add_plugin_cmd import _offsets
from logicxkit.logic._binary import find_blocks
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.add_plugin import add_plugin
from logicxkit.logic.services.binding import channels
from logicxkit.logic.services.insert import HEADER
from logicxkit.logic.services.plugin_library import find_donor, load_library
from logicxkit.logic.services.transplant import ID_TAIL, ID_WINDOW, channel_slots, slot_class_version
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

KEY = "autoset-resave-logic"


def _eq_ids(data: bytes) -> list[bytes]:
    return [r.raw[HEADER:][-ID_WINDOW:-ID_TAIL] for o in channels(data) for r in channel_slots(data, o)
            if (b := find_blocks(r.raw[HEADER:])) and b[0][1] == 236]


@_goldens.needs(KEY)
class FreshIdTest(unittest.TestCase):
    def test_two_copies_of_a_packaged_native_carry_their_own_ids(self):
        data = project_data(_goldens.path(KEY))
        eq = find_donor(load_library([PACKAGED / "donors"]), "Channel EQ", width=None, version=slot_class_version(data))
        self.assertTrue(eq.id_offsets)
        for label in ("Audio 1", "Audio 2"):
            data, report = add_plugin(data, owner_by_label(data, label), eq.raw, id_offsets=_offsets(data, eq),
                                      type_id=eq.type_id)
            self.assertEqual(report["ids"], "stamped")
        ids = _eq_ids(data)
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.assertNotIn(eq.raw[HEADER:][-ID_WINDOW:-ID_TAIL], ids)


@_goldens.needs("addplugin-ids-shared-mine", "addplugin-ids-shared-logic")
class LogicsOwnIdTest(unittest.TestCase):
    """Two Channel EQs written with one id came back from Logic with a fresh id on one of them:
    the bytes Logic rewrote hold every offset the packaged donor stamps (it rewrote one more, 419)."""

    def test_the_packaged_offsets_are_bytes_logic_gives_a_fresh_id(self):
        eq = next(d for d in load_library([PACKAGED / "donors"]) if d.key == "236-v5")

        def differing(key: str) -> set[int]:
            data = project_data(_goldens.path(key))
            a, b = (r.raw[HEADER:] for o in channels(data) for r in channel_slots(data, o)
                    if (blocks := find_blocks(r.raw[HEADER:])) and blocks[0][1] == 236)
            return {i for i in range(len(a) - ID_WINDOW, len(a) - ID_TAIL) if a[i] != b[i]}

        self.assertEqual(differing("addplugin-ids-shared-mine"), set())
        self.assertLessEqual(set(eq.id_offsets), differing("addplugin-ids-shared-logic"))


if __name__ == "__main__":
    unittest.main()
