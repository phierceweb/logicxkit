"""Bypassing a channel's slots, held to Logic's re-save of one of ours."""

import unittest
import _goldens
from logicxkit.logic.services.slots import slot_bypassed
from logicxkit.logic.services.stream import project_records
from logicxkit.logic.services.transplant import owner_of
from logicxkit.logicx import project_data


@_goldens.needs("bypass-ours", "bypass-resave-logic")
class LogicResavedBypassTest(unittest.TestCase):
    def test_logic_kept_the_bypass_bits(self):
        ours, logic = (project_data(_goldens.path(k)) for k in ("bypass-ours", "bypass-resave-logic"))
        owner = owner_of(ours, _goldens.fact("bypass-ours", "channel"))
        keys = _goldens.fact("bypass-ours", "bypassed_keys")

        def bypassed(data):
            return {r.key: slot_bypassed(r.raw) for r in project_records(data)
                    if r.tag == b"UCuA" and r.owner == owner and r.key in keys}
        self.assertEqual(bypassed(ours), {k: True for k in keys})
        self.assertEqual(bypassed(ours), bypassed(logic))


if __name__ == "__main__":
    unittest.main()
