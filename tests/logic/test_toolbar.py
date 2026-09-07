"""The toolbar button set: names to ids, and the list Logic writes."""

import plistlib
import tempfile
import unittest
from pathlib import Path

from logicxkit.logic.services.toolbar import (BUTTONS, ORDER, buttons_of, ids_for, read_toolbar, show_toolbar,
                                              toolbar_shown, write_toolbar)


class ToolbarTest(unittest.TestCase):
    def test_ids_are_unique_and_ordered(self):
        self.assertEqual(len(set(BUTTONS.values())), len(BUTTONS))
        self.assertEqual(ORDER, list(BUTTONS.values()))

    def test_round_trip(self):
        want = {name: name in ("Crop", "Zoom", "Bounce") for name in BUTTONS}
        ids = ids_for(want)
        self.assertEqual(ids, [BUTTONS["Bounce"], BUTTONS["Zoom"], BUTTONS["Crop"]])
        self.assertEqual([n for n, on in buttons_of(ids).items() if on], ["Bounce", "Zoom", "Crop"])

    def test_unknown_ids_survive(self):
        state = buttons_of([BUTTONS["Zoom"], 99])
        self.assertTrue(state["Zoom"] and state["button 99"])
        self.assertEqual(ids_for({"Crop": True}, [99, BUTTONS["Zoom"]]), [BUTTONS["Zoom"], BUTTONS["Crop"], 99])

    def test_write_and_row_on_a_bare_plist(self):
        state = {"screensetDictArray": [{"layoutDictArray": [{"docwWindowState": {
            "transportLayoutDict": {}, "actionBarLayoutDict": {"CLgActionBarBtns": [4]}, "transportBarRows": 1}}]}]}
        with tempfile.TemporaryDirectory() as d:
            alt = Path(d)
            (alt / "DisplayState.plist").write_bytes(plistlib.dumps(state, fmt=plistlib.FMT_BINARY))
            write_toolbar(alt, [8, 38])
            show_toolbar(alt, True)
            self.assertEqual(read_toolbar(alt), [8, 38])
            self.assertTrue(toolbar_shown(alt))
            show_toolbar(alt, False)
            self.assertFalse(toolbar_shown(alt))


if __name__ == "__main__":
    unittest.main()
