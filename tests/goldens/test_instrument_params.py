"""The parameter tables of Logic's instruments and MIDI effects against the saves they were
measured from (`instrument-params-<name>-defaults` and `-spots`): each plug-in has a table, the
table reads both saves back to the numbers Logic's Controls view showed, and a named float
changes only when its row was moved. Skips without the public corpus."""

import unittest

import _goldens
from _instparams import CHUNKED, TEXT, _close, _slot_of
from logicxkit.logic.services.mixer.plugin_params import decode_payload, load_tables, table_for
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED


@_goldens.needs(*(k for pair in TEXT for k in pair))
class TextStateTest(unittest.TestCase):
    """Alchemy and Sample Alchemy keep their state as text: the table reads a key's first field,
    times its scale, back to the number Logic showed, before and after."""

    def test_the_text_tables_read_both_saves_back(self):
        self.assertTrue(TEXT)
        tables = load_tables([PACKAGED / "logic"])
        for defaults, spots in TEXT:
            label = _goldens.fact(defaults, "channel")
            payloads = [_slot_of(project_data(_goldens.path(k)), label, _goldens.fact(defaults, "plugin")) for k in (defaults, spots)]
            table = table_for(tables, _goldens.fact(defaults, "type"), _goldens.fact(defaults, "variant"))
            self.assertEqual((table.state, table.name), ("text", _goldens.fact(defaults, "plugin")))
            moved = _goldens.fact(spots, "moved")
            for p in table.params:
                if p.evidence != "value" or p.name not in moved:
                    continue
                with self.subTest(f"{spots} {p.name}"):
                    d0, d1 = decode_payload(table, payloads[0]), decode_payload(table, payloads[1])
                    for got, want in ((d0[p.name], moved[p.name]["before"]), (d1[p.name], moved[p.name]["after"])):
                        if isinstance(want, (int, float)):
                            got = {"Off": 0.0, "On": 1.0}.get(got, got)
                            self.assertTrue(_close(got, want), f"{p.name}: {got!r} vs {want!r}")


@_goldens.needs(*(k for pair in CHUNKED for k in pair))
class ChunkedStateTest(unittest.TestCase):
    """The sampler instruments and the small utilities keep a state no table reads yet; their
    pairs are staged as measurements, and this says what each pair is."""

    def test_each_pair_names_its_state_and_its_moved_rows(self):
        self.assertTrue(CHUNKED)
        for defaults, spots in CHUNKED:
            with self.subTest(defaults):
                self.assertIn(_goldens.fact(defaults, "maker"), ("EMAG", "CLEM"))
                self.assertGreaterEqual(_goldens.fact(defaults, "rows"), 1)
                self.assertTrue(_goldens.fact(spots, "moved"))


if __name__ == "__main__":
    unittest.main()
