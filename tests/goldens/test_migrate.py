"""`logic migrate` held to Logic's re-save of a migrated legacy session."""

import unittest

import _goldens
from logicxkit.logic.services.insert import project_records, slot_index_base
from logicxkit.logic.services.project import project_metadata
from logicxkit.logic.services.slots import is_plugin_slot, property_key_base
from logicxkit.logic.services.stacks import read_tracks
from logicxkit.logic.services.validate import validate_project
from logicxkit.logicx import project_data


def _slots(data: bytes) -> int:
    base, first = property_key_base(data), slot_index_base(data)
    return sum(1 for r in project_records(data) if is_plugin_slot(r, base, first))


@_goldens.needs("legacy-migrate-fixed-mine", "legacy-migrate-fixed-logic")
class LogicResavedTest(unittest.TestCase):
    def test_logic_kept_every_row_and_every_plug_in_of_the_migrated_session(self):
        want = _goldens.fact("legacy-migrate-fixed-mine", "rows")
        self.assertEqual(len(want), 57)
        for key in ("legacy-migrate-fixed-mine", "legacy-migrate-fixed-logic"):
            path = _goldens.path(key)
            data, count = project_data(path), project_metadata(path).get("tracks")
            self.assertEqual(validate_project(data), [])
            self.assertEqual([[t["name"], t.get("label")] for t in read_tracks(data, count)], want)
            self.assertEqual(_slots(data), _goldens.fact("legacy-migrate-fixed-mine", "plugin_slots"))

    def test_the_third_send_moved_the_session_to_base_4(self):
        data = project_data(_goldens.path("legacy-migrate-fixed-mine"))
        self.assertEqual(slot_index_base(data), _goldens.fact("legacy-migrate-fixed-mine", "slot_base"))


@_goldens.needs("legacy-migrate-keyed-mine", "legacy-migrate-idswap-mine")
class MisKeyedInstrumentTest(unittest.TestCase):
    """Two files alike but for two fresh ids: Logic opened one and refused the other."""

    def test_the_gate_refuses_both_whichever_logic_opens(self):
        for key in ("legacy-migrate-keyed-mine", "legacy-migrate-idswap-mine"):
            owner = _goldens.fact(key, "owner")
            problems = validate_project(project_data(_goldens.path(key)))
            self.assertIn(f"channel {owner} key 4: slot index 0, expected 2 for this project's numbering", problems)
            self.assertIn(f"channel {owner} key 15: keyed archive 2, expected at key 13", problems)
        self.assertEqual((_goldens.fact("legacy-migrate-keyed-mine", "opens"),
                          _goldens.fact("legacy-migrate-idswap-mine", "opens")), (False, True))


if __name__ == "__main__":
    unittest.main()
