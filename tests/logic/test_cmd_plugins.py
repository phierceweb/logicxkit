"""`logic plugins` keeps Apple's registry scan: used again while the Components folders stay as
they were and the scan is under a day old, run again otherwise or with `--rescan`. A scan that
leaves out a plug-in a Components folder holds is neither kept nor used, and the run says so."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from _cli import run

from logicxkit.logic import _plugins_cmd as cmd

NEUTRON = "neutron-dialled"                      # Audio 2 holds a Pro-C 2 and a Neutron 5
PRO_C, NEUTRON_5 = ("aumf", "FC2p", "FabF"), ("aufx", "ZNN5", "iZtp")
FOLDERS = [["/Library/Audio/Plug-Ins/Components/One.component", 1]]


class KeptScanTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "cache" / "auval-registry.json"
        self.scan = mock.Mock(return_value={PRO_C, NEUTRON_5})
        self.folders, self.declared = list(FOLDERS), {PRO_C, NEUTRON_5}
        for name, value in (("_cache_file", lambda: self.cache), ("_component_folders", lambda: self.folders),
                            ("_declared", lambda: self.declared), ("installed_components", self.scan)):
            patch = mock.patch.object(cmd, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def registry(self, rescan: bool = False):
        return cmd._registry({PRO_C, NEUTRON_5}, rescan=rescan, quiet=True)

    def test_the_second_run_uses_the_kept_scan(self):
        self.assertEqual((self.registry(), self.registry(), self.scan.call_count), ({PRO_C, NEUTRON_5},) * 2 + (1,))
        self.assertAlmostEqual(cmd._kept_scan()[1], time.time(), delta=60)

    def test_a_changed_components_folder_an_old_scan_and_rescan_each_run_it_again(self):
        self.registry()
        self.folders.append(["/Library/Audio/Plug-Ins/Components/Two.component", 2])
        self.registry()
        self.assertEqual(self.scan.call_count, 2)
        kept = json.loads(self.cache.read_text())
        self.cache.write_text(json.dumps({**kept, "at": kept["at"] - cmd.CACHE_AGE - 1}))
        self.registry()
        self.assertEqual(self.scan.call_count, 3)
        self.registry(rescan=True)
        self.assertEqual(self.scan.call_count, 4)

    def test_a_scan_with_no_answer_is_not_kept_and_a_bad_cache_only_costs_the_scan(self):
        self.scan.return_value = None
        self.assertIsNone(self.registry())
        self.assertFalse(self.cache.exists())
        self.scan.return_value = {PRO_C, NEUTRON_5}
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text("not json")
        self.assertEqual(self.registry(), {PRO_C, NEUTRON_5})

    def test_a_cache_that_cannot_be_written_still_answers(self):
        self.cache.parent.write_text("a file where the folder would go")
        self.assertEqual(self.registry(), {PRO_C, NEUTRON_5})

    def test_a_scan_that_leaves_out_a_plug_in_a_components_folder_holds_is_not_kept(self):
        self.scan.return_value = {NEUTRON_5}                      # auval has not listed Pro-C 2 yet
        self.assertEqual((self.registry(), self.cache.exists()), ({NEUTRON_5}, False))
        self.declared = {NEUTRON_5}                               # no bundle holds it: it is missing, and that is kept
        self.assertEqual((self.registry(), self.cache.exists()), ({NEUTRON_5}, True))

    def test_a_kept_scan_without_a_wanted_plug_in_a_components_folder_holds_is_run_again(self):
        self.scan.return_value = {NEUTRON_5}
        self.assertEqual(cmd._registry({NEUTRON_5}, rescan=False, quiet=True), {NEUTRON_5})     # kept: all it was asked for
        self.scan.return_value = {PRO_C, NEUTRON_5}
        self.assertEqual((self.registry(), self.scan.call_count), ({PRO_C, NEUTRON_5}, 2))
        self.assertEqual((self.registry(), self.scan.call_count), ({PRO_C, NEUTRON_5}, 2))

    @_goldens.needs(NEUTRON)
    def test_the_command_says_which_scan_it_used(self):
        bundle = _goldens.path(NEUTRON)
        code, text = run("plugins", bundle)
        self.assertEqual((code, "third-party check from the auval scan of" in text), (0, False), text)
        code, text = run("plugins", bundle)
        self.assertIn("third-party check from the auval scan of", text)
        code, text = run("plugins", bundle, "--rescan")
        self.assertNotIn("third-party check from the auval scan of", text)
        self.assertEqual(self.scan.call_count, 2)

    @_goldens.needs(NEUTRON)
    def test_the_command_says_when_auval_left_out_a_plug_in_that_is_there(self):
        self.scan.return_value = {NEUTRON_5}
        code, text = run("plugins", _goldens.path(NEUTRON))
        self.assertEqual(code, 1, text)
        self.assertIn("auval does not list 1 plug-in(s) that a Components folder holds", text)
        self.assertFalse(self.cache.exists())


class DeclaredTest(unittest.TestCase):
    def test_the_bundles_info_plists_name_what_they_register(self):
        import plistlib
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "One.component" / "Contents"
            bundle.mkdir(parents=True)
            (bundle / "Info.plist").write_bytes(plistlib.dumps(
                {"AudioComponents": [{"type": "aufx", "subtype": "Abcd", "manufacturer": "Efgh", "name": "E: A"}]}))
            (Path(tmp) / "Broken.component").mkdir()
            with mock.patch.object(cmd, "COMPONENT_FOLDERS", (tmp, str(Path(tmp) / "absent"))):
                self.assertEqual(cmd._declared(), {("aufx", "Abcd", "Efgh")})
                self.assertEqual([Path(p).name for p, _t in cmd._component_folders()], ["Broken.component", "One.component"])


if __name__ == "__main__":
    unittest.main()
