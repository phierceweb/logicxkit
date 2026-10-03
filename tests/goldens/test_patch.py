"""A patch bundle Logic itself saved from the Library, read back, and one built from its strip."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.logic.services.mixer.patch import ROOT_STRIP, build_patch, read_patch


@_goldens.needs("patch-audio-1-logic")
class LogicSavedPatchTest(unittest.TestCase):
    def test_the_saved_patch_reads_its_strip_and_plugins(self):
        p = read_patch(_goldens.path("patch-audio-1-logic"))
        facts = _goldens.entry("patch-audio-1-logic")["facts"]
        (ch,) = p.channels
        self.assertEqual((len(p.channels), ch.strip, ch.plugins), (facts["channels"], facts["strip"], facts["plugins"]))
        self.assertEqual(ch.name, facts["name"])

    def test_its_strip_builds_and_a_truncated_copy_is_refused(self):
        real = (_goldens.path("patch-audio-1-logic") / ROOT_STRIP).read_bytes()
        facts = _goldens.entry("patch-audio-1-logic")["facts"]
        with tempfile.TemporaryDirectory() as tmp:
            strip, out = Path(tmp, "real.cst"), Path(tmp, "out")
            strip.write_bytes(real)
            built = build_patch(strip, name="Built", out_dir=out)
            self.assertEqual(((built / ROOT_STRIP).read_bytes() == real, read_patch(built).channels[0].plugins), (True, facts["plugins"]))
            for cut in (len(real) - 1, len(real) - 50, len(real) // 2, 36):
                with self.subTest(cut=cut):
                    strip.write_bytes(real[:cut])
                    with self.assertRaisesRegex(ValueError, "not a Logic channel strip"):
                        build_patch(strip, name="Cut", out_dir=out)
            self.assertEqual([p.name for p in out.iterdir()], ["Built.patch"])


@_goldens.needs("patch-built-loaded-logic")
class BuiltPatchLoadedTest(unittest.TestCase):
    """A patch `logic patch --build` wrote, chosen from Logic's Library: the channel got the strip."""

    def test_logic_loaded_every_insert_of_the_built_patch(self):
        from logicxkit.logic.services.mixer.plugins import project_plugins
        from logicxkit.logicx import project_data
        facts = _goldens.entry("patch-built-loaded-logic")["facts"]
        names = [r.name for r in project_plugins(project_data(_goldens.path("patch-built-loaded-logic"))) if r.channel == facts["channel"]]
        self.assertEqual(names, facts["inserts"])

    def test_project_data_is_not_a_strip(self):
        from logicxkit.logicx.container import first_alternative
        bundle = _goldens.path("patch-built-loaded-logic")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "not a Logic channel strip"):
            build_patch(bundle / "Alternatives" / first_alternative(bundle) / "ProjectData", name="P", out_dir=Path(tmp))


if __name__ == "__main__":
    unittest.main()
