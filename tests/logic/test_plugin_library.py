"""The plug-in library: Logic's own plug-ins as `harvest_donors` files them, third-party ones
harvested per (component, width, class version) with their instance-id offsets measured from a
second instance, and one lookup by name over both."""

import json
import tempfile
import unittest
from pathlib import Path

from _records import proj
from logicxkit.logic.services.mixer.donors import harvest_donors
from logicxkit.logic.services.mixer.plugin_library import Donor, find_donor, harvest_au, load_library
from test_transplant_ids import MONO, STEREO, TAIL, au, mono_chan, native, ref

COMPONENT = ("aufx", "Aln2", "Srdx")


def _project() -> bytes:
    """Two mono instances of one AU (ids differ), one stereo, and a Channel EQ."""
    return proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10),
                mono_chan(2, "Audio 2"), au(2, 4, 2), ref(2, 10),
                mono_chan(3, "Audio 3", STEREO), au(3, 4, 3, fmt=STEREO), ref(3, 10),
                mono_chan(4, "Audio 4"), native(4, 4, 9), ref(4, 10))


class HarvestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_file_per_component_width_and_version(self):
        keys = harvest_au(_project(), self.lib)
        self.assertEqual(keys, ["au-Srdx-Aln2-mono-v5", "au-Srdx-Aln2-stereo-v5"])
        self.assertTrue((self.lib / "au-Srdx-Aln2-mono-v5.slot").exists())
        manifest = json.loads((self.lib / "manifest.json").read_text())
        self.assertEqual(manifest["au-Srdx-Aln2-mono-v5"]["component"], list(COMPONENT))
        self.assertEqual(manifest["au-Srdx-Aln2-mono-v5"]["width"], MONO)
        self.assertEqual(manifest["au-Srdx-Aln2-stereo-v5"]["width"], STEREO)

    def test_id_offsets_come_from_another_instance_of_the_plugin(self):
        harvest_au(_project(), self.lib)
        manifest = json.loads((self.lib / "manifest.json").read_text())
        mono, stereo = manifest["au-Srdx-Aln2-mono-v5"], manifest["au-Srdx-Aln2-stereo-v5"]
        end = mono["bytes"]
        self.assertTrue(mono["id_offsets"])
        self.assertTrue(all(end - TAIL <= o < end - 4 for o in mono["id_offsets"]))
        self.assertEqual(stereo["id_offsets"], mono["id_offsets"], "the same plug-in, whatever its width")

    def test_a_lone_instance_has_no_offsets_to_measure(self):
        harvest_au(proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10)), self.lib)
        manifest = json.loads((self.lib / "manifest.json").read_text())
        self.assertEqual(manifest["au-Srdx-Aln2-mono-v5"]["id_offsets"], [])

    def test_a_name_is_kept(self):
        harvest_au(_project(), self.lib, name="Auto-Align 2")
        manifest = json.loads((self.lib / "manifest.json").read_text())
        self.assertEqual(manifest["au-Srdx-Aln2-mono-v5"]["plugin"], "Auto-Align 2")

    def test_a_bare_name_with_several_plugins_is_refused_and_a_coded_one_lands(self):
        two = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10),
                   mono_chan(2, "Audio 2"), au(2, 4, 2, subtype="Xyz2"), ref(2, 10))
        with self.assertRaises(ValueError) as cm:
            harvest_au(two, self.lib, name="Auto-Align 2")
        self.assertIn("--as Xyz2=Auto-Align 2", str(cm.exception))
        harvest_au(two, self.lib, name="Xyz2=Other")
        manifest = json.loads((self.lib / "manifest.json").read_text())
        self.assertEqual((manifest["au-Srdx-Xyz2-mono-v5"]["plugin"], manifest["au-Srdx-Aln2-mono-v5"]["plugin"]),
                         ("Other", "Srdx/Aln2"))

    def test_an_existing_donor_is_kept(self):
        harvest_au(_project(), self.lib)
        first = (self.lib / "au-Srdx-Aln2-mono-v5.slot").read_bytes()
        self.assertEqual(harvest_au(_project(), self.lib), [])
        self.assertEqual((self.lib / "au-Srdx-Aln2-mono-v5.slot").read_bytes(), first)

    def test_refresh_replaces_an_existing_donor(self):
        (self.lib).mkdir(exist_ok=True)
        (self.lib / "au-Srdx-Aln2-mono-v5.slot").write_bytes(b"stale")
        self.assertNotIn("au-Srdx-Aln2-mono-v5", harvest_au(_project(), self.lib))
        self.assertIn("au-Srdx-Aln2-mono-v5", harvest_au(_project(), self.lib, refresh=True))
        self.assertNotEqual((self.lib / "au-Srdx-Aln2-mono-v5.slot").read_bytes(), b"stale")
        (self.lib / "236-v5.slot").write_bytes(b"stale")
        self.assertIn("236-v5", harvest_donors(_project(), self.lib, {236: "Channel EQ"}, refresh=True))
        self.assertNotEqual((self.lib / "236-v5.slot").read_bytes(), b"stale")

    def test_native_slots_are_not_taken(self):
        harvest_au(_project(), self.lib)
        self.assertFalse((self.lib / "236-v5.slot").exists())


class LookupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        harvest_donors(_project(), self.lib, {236: "Channel EQ"})
        harvest_au(_project(), self.lib, name="Auto-Align 2")
        self.donors = load_library([self.lib])

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_kinds_load(self):
        self.assertEqual(sorted(d.key for d in self.donors),
                         ["236-v5", "au-Srdx-Aln2-mono-v5", "au-Srdx-Aln2-stereo-v5"])
        native_donor = next(d for d in self.donors if d.kind == "native")
        self.assertEqual((native_donor.type_id, native_donor.name, native_donor.width), (236, "Channel EQ", None))

    def test_by_name_code_and_type_id(self):
        for name in ("Auto-Align 2", "auto-align 2", "Srdx/Aln2"):
            self.assertEqual(find_donor(self.donors, name, width=MONO, version=5).key, "au-Srdx-Aln2-mono-v5")
        self.assertEqual(find_donor(self.donors, "236", width=STEREO, version=5).key, "236-v5")
        self.assertEqual(find_donor(self.donors, "channel eq", width=MONO, version=5).key, "236-v5")

    def test_the_width_picks_the_au_donor(self):
        self.assertEqual(find_donor(self.donors, "Srdx/Aln2", width=STEREO, version=5).key, "au-Srdx-Aln2-stereo-v5")

    def test_a_missing_width_names_the_ones_there_are(self):
        donors = [d for d in self.donors if d.key != "au-Srdx-Aln2-stereo-v5"]
        with self.assertRaises(LookupError) as e:
            find_donor(donors, "Srdx/Aln2", width=STEREO, version=5)
        self.assertIn("mono", str(e.exception))

    def test_an_unknown_name_lists_the_library(self):
        with self.assertRaises(LookupError) as e:
            find_donor(self.donors, "Space Designer", width=MONO, version=5)
        self.assertIn("Auto-Align 2", str(e.exception))
        self.assertIn("Channel EQ", str(e.exception))

    def test_a_native_whose_record_differs_by_width_is_filed_per_width_and_picked_by_it(self):
        """DeEsser 2 and Expander: the stereo record is longer than the mono one, so neither
        can be re-stamped to the other width; both are filed, fixed, and the width picks."""
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            from _records import rec
            from logicxkit.logic.services.stream.stream import HEADER
            mono = proj(mono_chan(1, "Audio 1"), native(1, 4, 1), ref(1, 10))
            payload = native(2, 4, 2, fmt=STEREO)[HEADER:]
            longer = rec(b"UCuA", 2, 4, payload[:-20] + bytes(64) + payload[-20:], 5)
            stereo = proj(mono_chan(2, "Audio 2", STEREO), longer, ref(2, 10))
            first = harvest_donors(mono, lib, {236: "Channel EQ"})
            second = harvest_donors(stereo, lib, {236: "Channel EQ"})
            self.assertEqual((first, second), (["236-v5"], ["236-stereo-v5"]))
            manifest = json.loads((lib / "manifest.json").read_text())
            self.assertTrue(manifest["236-v5"]["fixed_width"] and manifest["236-stereo-v5"]["fixed_width"])
            donors = load_library([lib])
            self.assertEqual(find_donor(donors, "Channel EQ", width=MONO, version=5).key, "236-v5")
            self.assertEqual(find_donor(donors, "Channel EQ", width=STEREO, version=5).key, "236-stereo-v5")

    def test_a_native_of_the_same_length_at_both_widths_stays_one_donor_for_any_width(self):
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            harvest_donors(proj(mono_chan(1, "Audio 1"), native(1, 4, 1), ref(1, 10)), lib)
            self.assertEqual(harvest_donors(proj(mono_chan(2, "Audio 2", STEREO), native(2, 4, 2, fmt=STEREO), ref(2, 10)), lib), [])
            donor = find_donor(load_library([lib]), "Channel EQ", width=STEREO, version=5)
            self.assertEqual((donor.key, donor.width), ("236-v5", None))

    def test_a_native_without_a_manifest_name_is_still_named(self):
        with tempfile.TemporaryDirectory() as td:
            harvest_donors(_project(), Path(td))
            donors = load_library([Path(td)])
            self.assertEqual(find_donor(donors, "Channel EQ", width=MONO, version=5).key, "236-v5")

    def test_the_donor_carries_its_offsets(self):
        donor = find_donor(self.donors, "Auto-Align 2", width=MONO, version=5)
        self.assertIsInstance(donor, Donor)
        self.assertTrue(donor.id_offsets)
        self.assertEqual(donor.component, COMPONENT)


if __name__ == "__main__":
    unittest.main()
