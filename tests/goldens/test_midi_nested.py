"""How Logic itself pairs nested same-pitch notes on import: the first note-off closes the first
note-on (first in, first out), which is what groovebin's reader does too."""

import unittest
import _goldens
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logicx import project_data


@_goldens.needs("midi-nested-import-logic")
class NestedPairingTest(unittest.TestCase):
    def test_logic_pairs_first_in_first_out(self):
        (region,) = [r for r in read_midi(project_data(_goldens.path("midi-nested-import-logic"))) if r.name == "nested"]
        notes = sorted((e for e in region.events if e.kind == "note"), key=lambda e: e.tick)
        self.assertEqual([n.tick for n in notes], _goldens.fact("midi-nested-import-logic", "starts"))
        self.assertEqual([n.length for n in notes], _goldens.fact("midi-nested-import-logic", "lengths"))
        self.assertEqual([n.length for n in notes], [200, 900])


if __name__ == "__main__":
    unittest.main()
