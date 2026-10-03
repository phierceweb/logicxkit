"""`add-plugin`'s mid-chain insert and append as staged, reproduced from their inputs and held
to Logic's re-saves (2026-09-21). Skips without the public corpus."""

import struct
import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.mixer.plugin_library import find_donor, load_library
from logicxkit.logic.services.mixer.slots import archive_index, property_key_base
from logicxkit.logic.services.mixer.smart_controls import mapping_slots
from logicxkit.logic.services.mixer.transplant import channel_slots, slot_class_version
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

SOURCE = "master-track-limiter-logic"
LIBRARY = [PACKAGED / "donors"]          # the package's own donors: the same on every machine
CASES = (("addplugin-mid-mine", "addplugin-mid-logic", 6), ("addplugin-end-mine", "addplugin-end-logic", None))  # slot 6: the Multipressor's
KEYS = (SOURCE,) + tuple(k for case in CASES for k in case[:2])
LABEL, PLUGIN = "Audio 1", "Channel EQ"


def _slots(data: bytes) -> list[bytes]:
    return [r.raw for r in channel_slots(data, owner_by_label(data, LABEL))]


def _archives(data: bytes) -> list[bytes]:
    owner = owner_by_label(data, LABEL)
    return [r.raw for r in project_records(data) if r.tag == b"UCuA" and r.owner == owner and archive_index(r.raw)]


def _channel_record(data: bytes) -> bytes:
    owner = owner_by_label(data, LABEL)
    return max((r.raw for r in project_records(data) if r.tag == CHANNEL_TAG and r.owner == owner), key=len)


@_goldens.needs(*KEYS)
class ResaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = project_data(_goldens.path(SOURCE))
        cls.donor = find_donor(load_library(LIBRARY), PLUGIN, width=None,
                               version=slot_class_version(cls.source))

    def _ours(self, at):
        out, _ = add_plugin(self.source, owner_by_label(self.source, LABEL), self.donor.raw, at=at,
                            type_id=self.donor.type_id)
        return out

    def test_the_writes_are_reproduced_from_their_inputs(self):
        for mine_key, _logic_key, at in CASES:
            with self.subTest(mine_key):
                self.assertEqual(self._ours(at), project_data(_goldens.path(mine_key)))

    def test_logic_kept_every_slot_as_written(self):
        """Byte for byte, the new slot included: the packaged donor's +76 token came back
        unchanged (another donor's stale one came back as 0 — the logic README)."""
        for mine_key, logic_key, _at in CASES:
            with self.subTest(logic_key):
                mine, logic = project_data(_goldens.path(mine_key)), project_data(_goldens.path(logic_key))
                self.assertEqual(_slots(mine), _slots(logic))

    def test_logic_kept_the_archives_the_channel_record_and_the_layout(self):
        for mine_key, logic_key, _at in CASES:
            with self.subTest(logic_key):
                mine, logic = project_data(_goldens.path(mine_key)), project_data(_goldens.path(logic_key))
                self.assertEqual(_archives(mine), _archives(logic))
                self.assertEqual(_channel_record(mine), _channel_record(logic))
                self.assertEqual(property_key_base(mine), property_key_base(logic))
                facts = _goldens.entry(logic_key)["facts"]
                self.assertEqual([r.key for r in channel_slots(logic, owner_by_label(logic, LABEL))], facts["keys"])
                self.assertEqual(struct.unpack_from("<H", _channel_record(logic), HEADER + 30)[0], facts["shown"])

    def test_the_moved_mappings_point_at_the_moved_plug_in(self):
        logic = project_data(_goldens.path("addplugin-mid-logic"))
        slots = mapping_slots(_archives(logic)[0])
        self.assertTrue(slots)
        self.assertEqual(set(slots), {_goldens.entry("addplugin-mid-logic")["facts"]["mapping_slots"]})


EDIT_KEYS = ("addplugin-mid-mine", "addplugin-remove-mine", "addplugin-remove-logic",
             "addplugin-replace-mine", "addplugin-replace-logic")


@_goldens.needs(*EDIT_KEYS)
class RemoveReplaceTest(unittest.TestCase):
    """One slot out, and another plug-in in its place, from the mid-chain write; held to
    Logic's re-saves (2026-09-22)."""

    @classmethod
    def setUpClass(cls):
        from logicxkit.logic.services.mixer.remove_plugin import remove_plugin
        cls.source = project_data(_goldens.path("addplugin-mid-mine"))
        owner = owner_by_label(cls.source, LABEL)
        cls.removed, _ = remove_plugin(cls.source, owner, 6)            # slot 6: the Channel EQ the mid write put there
        gain = find_donor(load_library(LIBRARY), "Gain", width=None, version=slot_class_version(cls.source))
        cls.replaced, _ = add_plugin(cls.removed, owner, gain.raw, at=6, type_id=gain.type_id)

    def test_the_writes_are_reproduced_from_their_inputs(self):
        self.assertEqual(self.removed, project_data(_goldens.path("addplugin-remove-mine")))
        self.assertEqual(self.replaced, project_data(_goldens.path("addplugin-replace-mine")))

    def test_logic_kept_every_slot_as_written(self):
        for mine_key, logic_key in (("addplugin-remove-mine", "addplugin-remove-logic"),
                                    ("addplugin-replace-mine", "addplugin-replace-logic")):
            with self.subTest(logic_key):
                mine, logic = project_data(_goldens.path(mine_key)), project_data(_goldens.path(logic_key))
                self.assertEqual(_slots(mine), _slots(logic))
                facts = _goldens.entry(logic_key)["facts"]
                self.assertEqual([r.key for r in channel_slots(logic, owner_by_label(logic, LABEL))], facts["keys"])

    def test_the_replaced_slots_mappings_went_and_the_rest_moved_back(self):
        """The mid write mapped every knob to slot index 6 (Multipressor, moved to 7 by the
        insert); after the removal they read 5 again, and the replacement moves them to 6."""
        self.assertEqual(set(mapping_slots(_archives(self.removed)[0])), {5})
        self.assertEqual(set(mapping_slots(_archives(self.replaced)[0])), {6})


if __name__ == "__main__":
    unittest.main()
