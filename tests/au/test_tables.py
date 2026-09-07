"""Checked-in AU parameter tables (data/*.json) and the value-naming join."""
import unittest

from logicxkit.au.services.tables import ffp_identity, join_values, load_table
from _data import needs


@needs("au")
class TestLoadTable(unittest.TestCase):
    def test_proc2_table_present_with_named_params(self):
        t = load_table("FabF", "FC2p")
        self.assertIsNotNone(t)
        by_id = {p["id"]: p for p in t["params"]}
        self.assertEqual(by_id[1]["name"], "Threshold")
        self.assertEqual(by_id[2]["name"], "Ratio")

    def test_proq4_table_present(self):
        t = load_table("FabF", "FQ4p")
        self.assertIsNotNone(t)
        by_id = {p["id"]: p for p in t["params"]}
        self.assertEqual(by_id[2]["name"], "Band 1 Frequency")

    def test_unknown_plugin_returns_none(self):
        self.assertIsNone(load_table("Nope", "XXXX"))


class TestFfpIdentity(unittest.TestCase):
    def test_ffp_magic_maps_to_fabfilter_subtype(self):
        self.assertEqual(ffp_identity("FC2p"), ("FabF", "FC2p"))


class TestJoinValues(unittest.TestCase):
    def test_positional_join_names_and_flags_changed(self):
        table = {"params": [
            {"id": 0, "name": "A", "unit": "generic", "min": 0, "max": 1, "default": 0.5},
            {"id": 1, "name": "B", "unit": "dB", "min": -60, "max": 0, "default": -18.0},
        ]}
        rows = join_values(table, [(0, 0.5), (1, -6.0)])
        self.assertEqual(rows[0]["name"], "A")
        self.assertFalse(rows[0]["changed"])
        self.assertTrue(rows[1]["changed"])
        self.assertEqual(rows[1]["unit"], "dB")

    def test_ids_missing_from_table_still_reported(self):
        rows = join_values({"params": []}, [(7, 1.0)])
        self.assertEqual(rows[0]["name"], "param7")
        self.assertIsNone(rows[0]["changed"])


if __name__ == "__main__":
    unittest.main()
