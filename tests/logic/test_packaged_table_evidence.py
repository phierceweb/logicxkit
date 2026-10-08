"""What a coded placement in the packaged tables must have had behind it: a word no other row
owns, a linked word included, and the display of the row's own move to check the word against.
ES2's second coded series named Sine Level at MM3 Amount's linked word, its code moving exactly
MM3 Amount's two words; every such row had no display of its own move."""

import json
import unittest

from logicxkit.utils.data import PACKAGED

TABLES = sorted((PACKAGED / "logic").glob("params-*.json"))


def _tables():
    return [json.loads(f.read_text()) for f in TABLES]


class CodedPlacementTest(unittest.TestCase):
    def test_no_coded_row_sits_on_another_rows_linked_word(self):
        on_linked = []
        for t in _tables():
            linked = {w: p["name"] for p in t["params"] for w in p.get("linked") or ()}
            for p in t["params"]:
                if p.get("evidence") == "code" and p.get("offset") is None and p["index"] in linked:
                    on_linked.append(f"{t['name']} {p['name']} at {p['index']}: {linked[p['index']]}'s linked word")
        self.assertEqual(on_linked, [])

    def test_no_coded_row_records_an_empty_display(self):
        """`shown` is kept where the word is not the number shown; the spots display every coded
        row needs is checked against the saves in `test_instrument_params_saves.py`."""
        unchecked = [f"{t['name']} {p['name']}" for t in _tables() for p in t["params"]
                     if p.get("evidence") == "code" and p.get("shown") == ""]
        self.assertEqual(unchecked, [])

    def test_a_code_that_confirms_a_word_keeps_what_was_measured_of_it(self):
        """A drawbar at 0 reads the same as int32 and float, so only the earlier pass knew B3's
        upper drawbars are int32 words; a toggle's names are the row's, not the word's."""
        tables = {t["name"]: t for t in _tables()}
        drawbars = [p for p in tables["Vintage B3"]["params"] if p.get("offset") is None and 99 <= p["index"] <= 107]
        self.assertTrue(drawbars)
        self.assertEqual([p["name"] for p in drawbars if p.get("kind") != "int"], [])
        notes = [p for p in tables["Transposer"]["params"] if p["name"] in ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")]
        self.assertEqual({tuple(p.get("choices") or ()) for p in notes}, {("Off", "On")})


if __name__ == "__main__":
    unittest.main()
