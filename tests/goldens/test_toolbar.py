"""The toolbar ids against Logic's own saves."""

import unittest

import _goldens
from logicxkit.logic.services.toolbar import (BUTTONS, ORDER, alternative_dirs, buttons_of, ids_for, read_toolbar,
                                              toolbar_shown)

ALL, REST = _goldens.path("toolbar-all-logic"), _goldens.path("toolbar-rest-logic")
BASE, OURS = _goldens.path("changes-base"), _goldens.path("toolbar-ours-logic")


@unittest.skipUnless(ALL and REST, "no toolbar saves")
class GoldenToolbarTest(unittest.TestCase):
    def test_every_button_on_is_the_whole_table_in_logics_order(self):
        ids = read_toolbar(alternative_dirs(ALL)[0])
        self.assertEqual(ids, ORDER)
        self.assertTrue(all(buttons_of(ids).values()))

    def test_the_rest_reads_as_the_fourteen(self):
        ids = read_toolbar(alternative_dirs(REST)[0])
        state = buttons_of(ids)
        self.assertEqual(sum(state.values()), _goldens.fact("toolbar-rest-logic", "buttons"))
        self.assertEqual(ids, ids_for({n: on for n, on in state.items() if n in BUTTONS}))


BITS = [_goldens.path(f"toolbar-bit{n}-logic") for n in range(5)]
# Customize Toolbar's boxes down the left column, then the right — the order the bit saves count in
COLUMNS = ["Bounce", "Export", "Import Audio", "Groups", "Group Clutch", "Automation Quick Access", "Learn",
           "Articulation", "Track Zoom", "Note Repeat", "Spot Erase", "Split by Playhead", "Split by Locators", "Crop",
           "Stretch to Locators", "Remove Silence", "Join", "Bounce Regions", "Move to Track", "Move to Playhead",
           "Nudge Value", "Lock/Unlock SMPTE", "Repeat Section", "Cut Section", "Insert Section", "Insert Silence",
           "Shuffle", "Previous/Next Marker", "Set Locators", "Zoom", "Colors"]


@unittest.skipUnless(all(BITS), "no toolbar bit saves")
class BitSavesTest(unittest.TestCase):
    """Five saves, each showing the boxes whose position down the popover's columns has one
    bit set: together they pin every id to its name."""

    def test_every_id_is_pinned_by_its_position_bits(self):
        self.assertEqual(sorted(COLUMNS), sorted(BUTTONS))
        for n, save in enumerate(BITS):
            ids = read_toolbar(alternative_dirs(save)[0])
            shown = {name for name, on in buttons_of(ids).items() if on}
            self.assertEqual(shown, {name for i, name in enumerate(COLUMNS) if i >> n & 1}, f"bit {n}")


@unittest.skipUnless(BASE and OURS, "no toolbar re-save")
class ReSavedToolbarTest(unittest.TestCase):
    """Logic re-saved our write (+Crop +Bounce -Colors over changes-base) with the list unchanged."""

    def test_logic_kept_our_list(self):
        want = buttons_of(read_toolbar(alternative_dirs(BASE)[0]))
        want.update({n: True for n in _goldens.fact("toolbar-ours-logic", "shown")})
        want.update({n: False for n in _goldens.fact("toolbar-ours-logic", "hidden")})
        ours = ids_for({n: on for n, on in want.items() if n in BUTTONS})
        self.assertEqual(read_toolbar(alternative_dirs(OURS)[0]), ours)
        self.assertEqual(len(ours), _goldens.fact("toolbar-ours-logic", "buttons"))

    def test_the_row_flag(self):
        self.assertFalse(toolbar_shown(alternative_dirs(BASE)[0]))
        self.assertTrue(toolbar_shown(alternative_dirs(OURS)[0]))


if __name__ == "__main__":
    unittest.main()
