"""A one-sided range's word end — "Off", "mono", "inf", "Mute", "Click", "Paradise", "Fix", "∞" —
pinned by a save with the slider at that end: the table's `named` entry turns the stored float back
into the word the Controls view showed, and writing the word after a number puts that float back. One public save per
end (`*-word-*` keys; facts name the table, the parameter and the word)."""

import unittest

import _goldens

from logicxkit.logic.services.mixer.plugin_params import decode_payload, load_tables, set_by_name, table_of
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logicx import project_data


def word_keys() -> list[str]:
    return sorted(k for k, e in _goldens.manifest().items() if isinstance(e, dict) and "-word-" in k and "shown" in e.get("facts", {}))


def slot_of(data: bytes, channel: str, table_name: str, tables: dict):
    """The slot on ``channel`` whose table is ``table_name``: an audio effect's, an instrument's or a
    MIDI effect's (`slot_payloads` lists all three)."""
    for ref, payload in slot_payloads(data):
        table = table_of(tables, payload) if ref.channel == channel else None
        if table is not None and table.name == table_name:
            return table, payload
    raise AssertionError(f"no {table_name} slot on {channel}")


class WordEndsTest(unittest.TestCase):
    def test_each_word_end_decodes_to_its_word_and_writes_back(self):
        keys = [k for k in word_keys() if _goldens.path(k) is not None]
        if not keys:
            self.skipTest("no word-end saves on this machine")
        self.assertEqual(len(keys), 28)                    # the one-sided ranges `test_instrument_ranges` pins
        tables = load_tables()
        for key in keys:
            with self.subTest(key=key):
                facts = _goldens.manifest()[key]["facts"]
                table, payload = slot_of(project_data(_goldens.path(key)), facts["channel"], facts["table"], tables)
                shown = decode_payload(table, payload)[facts["param"]]
                self.assertEqual(shown, facts["shown"])
                param = next(p for p in table.params if p.name == facts["param"])
                other = param.max if facts["side"] == "min" else param.min          # the closed end: a number
                moved = set_by_name(table, payload, {facts["param"]: other})
                self.assertNotEqual(moved, payload)
                self.assertEqual(set_by_name(table, moved, {facts["param"]: facts["shown"]}), payload)


if __name__ == "__main__":
    unittest.main()
