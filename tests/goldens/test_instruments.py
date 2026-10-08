"""Logic's built-in instruments, one per save (`instrument-<name>-logic` in the public manifest;
the `plugin` fact is the row chosen in the slot's menu): each slot names its plug-in in its
header, whatever its state, `plugins` lists it by Logic's name, and the writers see an
instrument."""

import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.plugins import is_instrument_plugin, project_plugins
from logicxkit.logic.services.mixer.slot_identity import slot_header
from logicxkit.logic.services.mixer.transplant import channel_slots
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logicx import project_data

KEYS = tuple(k for k in sorted(_goldens.manifest())
             if k.startswith("instrument-") and _goldens.fact(k, "plugin") and _goldens.fact(k, "header"))
MENU_ROWS = 27          # the instruments Logic 12.4's slot menu lists, Drum Machine Designer aside


@_goldens.needs(*KEYS)
class BuiltInInstrumentsTest(unittest.TestCase):
    def _slot(self, key: str) -> bytes:
        data = project_data(_goldens.path(key))
        owner = owner_by_label(data, _goldens.fact(key, "channel"))
        return next(r.raw[HEADER:] for r in channel_slots(data, owner) if r.key == _goldens.fact(key, "key"))

    def test_every_instrument_of_the_slot_menu_has_a_save(self):
        self.assertEqual(len(KEYS), MENU_ROWS)

    def test_the_slot_header_names_the_plug_in(self):
        for key in KEYS:
            with self.subTest(key):
                head, want = slot_header(self._slot(key)), _goldens.fact(key, "header")
                self.assertEqual((head.name, head.maker, head.word, head.code),
                                 (want["name"], want["maker"], want["word"], want["code"]))

    def test_plugins_lists_the_instrument_by_the_menu_rows_name(self):
        for key in KEYS:
            with self.subTest(key):
                refs = [r for r in project_plugins(project_data(_goldens.path(key)))
                        if r.channel == _goldens.fact(key, "channel")]
                self.assertEqual([(r.key, r.name, r.native) for r in refs],
                                 [(_goldens.fact(key, "key"), _goldens.fact(key, "plugin"), True)])

    def test_the_slot_is_an_instrument_to_the_writers(self):
        for key in KEYS:
            with self.subTest(key):
                self.assertTrue(is_instrument_plugin(self._slot(key)))


@_goldens.needs("instrument-control-logic")
class EmptyInstrumentSlotTest(unittest.TestCase):
    def test_a_new_instrument_tracks_slot_is_apples_file_player(self):
        data = project_data(_goldens.path("instrument-control-logic"))
        refs = [r for r in project_plugins(data) if r.channel == _goldens.fact("instrument-control-logic", "channel")]
        self.assertEqual([(r.native, r.component) for r in refs], [(True, ("augn", "afpl", "appl"))])


if __name__ == "__main__":
    unittest.main()
