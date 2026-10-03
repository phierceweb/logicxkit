"""Parameter tables for Logic's own plug-ins: name -> float index, measured, one JSON per type
in the package data; `decode` reads a float block by name and `encode` patches one."""

import json
import tempfile
import unittest
from pathlib import Path

from _fixtures import chunk
from logicxkit.logic.services.mixer.plugin_params import Table, decode, load_table, load_tables, set_by_name, table_for

TABLE = {"type": 999, "name": "Test Comp", "floats": 6, "opaque": [0],
         "params": [{"index": 1, "name": "Threshold", "unit": "dB", "min": -60, "max": 0, "default": -20},
                    {"index": 2, "name": "Ratio", "unit": ":1", "min": 1, "max": 30, "default": 2},
                    {"index": 3, "name": "Auto Gain", "unit": "", "min": 0, "max": 1, "default": 0,
                     "choices": ["Off", "On"]}],
         "evidence": "a synthetic table"}


class LoadTest(unittest.TestCase):
    def test_a_table_loads_by_type_and_name(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "params-999.json").write_text(json.dumps(TABLE))
            tables = load_tables([Path(td)])
            self.assertEqual(sorted(tables), [999])
            table = tables[999]
            self.assertIsInstance(table, Table)
            self.assertEqual((table.name, table.floats, table.index("Ratio")), ("Test Comp", 6, 2))
            self.assertEqual(load_table(999, [Path(td)]).name, "Test Comp")

    def test_a_name_is_matched_loosely(self):
        table = Table.from_dict(TABLE)
        self.assertEqual(table.index("ratio"), 2)
        self.assertEqual(table.index("auto_gain"), 3)
        with self.assertRaises(KeyError):
            table.index("Attack")


class DecodeTest(unittest.TestCase):
    def test_floats_read_back_by_name(self):
        table = Table.from_dict(TABLE)
        self.assertEqual(decode(table, [0.0, -18.5, 4.0, 1.0, 7.0, 8.0]),
                         {"Threshold": -18.5, "Ratio": 4.0, "Auto Gain": "On"})

    def test_a_short_block_reads_what_it_has(self):
        table = Table.from_dict(TABLE)
        self.assertEqual(decode(table, [0.0, -18.5]), {"Threshold": -18.5})


class EncodeTest(unittest.TestCase):
    def test_a_value_lands_at_its_index_in_the_chunk(self):
        table = Table.from_dict(TABLE)
        raw = chunk(999, [0.0] * 6)
        out = set_by_name(table, raw, {"ratio": 3.5, "Auto Gain": "On"})
        from logicxkit.logic._binary import find_blocks, read_block_floats
        idx, type_id, n = find_blocks(out)[0]
        self.assertEqual((type_id, read_block_floats(out, idx, n)[1:4]), (999, [0.0, 3.5, 1.0]))

    def test_out_of_range_and_unknown_names_are_refused(self):
        table = Table.from_dict(TABLE)
        raw = chunk(999, [0.0] * 6)
        with self.assertRaises(ValueError):
            set_by_name(table, raw, {"Threshold": 5})
        with self.assertRaises(KeyError):
            set_by_name(table, raw, {"Attack": 5})

    def test_a_choice_by_name_or_number(self):
        table = Table.from_dict(TABLE)
        raw = chunk(999, [0.0] * 6)
        from logicxkit.logic._binary import find_blocks, read_block_floats
        for value in ("On", 1, "1"):
            out = set_by_name(table, raw, {"Auto Gain": value})
            idx, _t, n = find_blocks(out)[0]
            self.assertEqual(read_block_floats(out, idx, n)[3], 1.0)



class VariantTest(unittest.TestCase):
    """One block type, several plug-ins: a table names its variant base and is found by it."""

    def _tables(self, td):
        for stem, type_id, variant, name in (("params-147", 147, 216, "Echo"), ("params-147v200", 147, 200, "Tape Delay"),
                                             ("params-150", 150, None, "SilverVerb")):
            d = {"type": type_id, "name": name, "floats": 4, "params": [{"index": 1, "name": "Dry"}]}
            if variant is not None:
                d["variant"] = variant
            (Path(td) / f"{stem}.json").write_text(json.dumps(d))
        return load_tables([Path(td)])

    def test_keys_by_type_and_by_type_and_variant(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._tables(td)
            self.assertEqual({k: v.name for k, v in t.items()},
                             {147: "Echo", (147, 216): "Echo", (147, 200): "Tape Delay", 150: "SilverVerb"})

    def test_table_for_takes_the_variant_first_then_the_type(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._tables(td)
            self.assertEqual(table_for(t, 147, 200).name, "Tape Delay")
            self.assertEqual(table_for(t, 147, 216).name, "Echo")
            self.assertEqual(table_for(t, 147, None).name, "Echo")        # a record without a variant (v2): the type's
            self.assertIsNone(table_for(t, 147, 999))                      # a member of the family with no table yet
            self.assertEqual(table_for(t, 150, 249).name, "SilverVerb")    # a table naming no variant serves every record
            self.assertIsNone(table_for(t, 151, 1))


if __name__ == "__main__":
    unittest.main()
