"""Where a spec's relative paths land — `strip_root`, else `LOGICXKIT_STRIP_ROOT`, else Logic's
own library, never the cwd — and which preset names and settings paths are allowed."""

import os
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from logicxkit.logic.services.library import (
    DEFAULT,
    ENV,
    USER_DATA_ENV,
    logic_user_data,
    resolve,
    strip_library,
)


class StripLibraryTest(unittest.TestCase):
    def test_the_default_is_logics_own_library(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV, None)
            self.assertEqual(strip_library(), DEFAULT)

    def test_the_env_override_wins_and_expands_a_tilde(self):
        with mock.patch.dict(os.environ, {ENV: "~/staged/strips"}):
            self.assertEqual(strip_library(), Path.home() / "staged/strips")


class ResolveTest(unittest.TestCase):
    def test_an_absolute_path_ignores_every_root(self):
        with mock.patch.dict(os.environ, {ENV: "/env/root"}):
            self.assertEqual(resolve("/x/y.cst", "/spec/root"), Path("/x/y.cst"))

    def test_a_relative_path_takes_the_specs_root_first(self):
        with mock.patch.dict(os.environ, {ENV: "/env/root"}):
            self.assertEqual(resolve("Track/K.cst", "/spec/root"), Path("/spec/root/Track/K.cst"))

    def test_without_a_specs_root_it_falls_back_to_the_library(self):
        with mock.patch.dict(os.environ, {ENV: "/env/root"}):
            self.assertEqual(resolve("Track/K.cst"), Path("/env/root/Track/K.cst"))

    def test_a_relative_path_never_resolves_against_the_cwd(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV, None)
            got = resolve("Track/K.cst")
        self.assertEqual(got, DEFAULT / "Track/K.cst")
        self.assertFalse(str(got).startswith(str(Path.cwd())), got)

    def test_a_tilde_in_the_spec_is_expanded_not_joined(self):
        self.assertEqual(resolve("~/K.cst", "/spec/root"), Path.home() / "K.cst")


class SpecResolutionTest(unittest.TestCase):
    """load_spec and template_path_for hang relative values off the same root."""

    def test_output_dir_and_template_resolve_against_the_specs_root(self):
        import json
        import tempfile
        from logicxkit.logic.services.spec import load_spec, template_path_for
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.json"
            p.write_text(json.dumps({"strip_root": "/root", "output_dir": "Track/Out",
                                     "template": "Track/T.cst", "presets": {}}))
            spec = load_spec(p)
            self.assertEqual(spec["_output_dir"], Path("/root/Track/Out"))
            self.assertEqual(spec["_template_path"], Path("/root/Track/T.cst"))
            self.assertEqual(template_path_for(spec, {}), Path("/root/Track/T.cst"))
            self.assertEqual(template_path_for(spec, {"template": "/abs.cst"}), Path("/abs.cst"))

    def test_planned_pst_paths_hang_off_logics_user_folder_not_the_strip_library(self):
        """`Plug-In Settings` is a SIBLING of `Channel Strip Settings`, so a .pst spec cannot
        resolve against the strip root."""
        from logicxkit.logic.services.pst import plan_psts
        spec = {"output_dir": "Plug-In Settings", "presets": {"P": {"eq": {"hpf": {"freq": 30}}}}}
        with mock.patch.dict(os.environ, {USER_DATA_ENV: "/amapps", ENV: "/amapps/Channel Strip Settings"}):
            dests = [dest for _n, dest, _v in plan_psts(spec)]
        self.assertTrue(dests)
        for d in dests:
            self.assertTrue(str(d).startswith("/amapps/Plug-In Settings/"), d)
            self.assertNotIn("Channel Strip Settings", str(d))

    def test_an_absolute_pst_output_dir_still_wins(self):
        from logicxkit.logic.services.pst import plan_psts
        spec = {"output_dir": "/abs/out", "presets": {"P": {"eq": {"hpf": {"freq": 30}}}}}
        for _n, dest, _v in plan_psts(spec):
            self.assertTrue(str(dest).startswith("/abs/out/"), dest)

    def test_a_graft_resolves_both_donors_against_the_root(self):
        from logicxkit.logic.services.spec import resolve_base
        asked = []
        def load(path):
            asked.append(path)
            raise RuntimeError("stop after resolving")
        spec = {"strip_root": "/root"}
        preset = {"graft": {"routing_from": "a.cst", "chain_from": "/abs/b.cst"}}
        with self.assertRaises(RuntimeError):
            resolve_base(spec, preset, load)
        self.assertEqual(asked[0], Path("/root/a.cst"))


class UserDataTest(unittest.TestCase):
    def test_the_strip_library_sits_inside_logics_user_folder(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV, None), os.environ.pop(USER_DATA_ENV, None)
            self.assertEqual(strip_library(), logic_user_data() / "Channel Strip Settings")
            self.assertEqual(strip_library(), DEFAULT)

    def test_moving_the_user_folder_moves_the_strip_library_with_it(self):
        with mock.patch.dict(os.environ, {USER_DATA_ENV: "/elsewhere"}):
            os.environ.pop(ENV, None)
            self.assertEqual(logic_user_data(), Path("/elsewhere"))
            self.assertEqual(strip_library(), Path("/elsewhere/Channel Strip Settings"))


class ChainConfigRootTest(unittest.TestCase):
    def test_a_chains_strip_without_a_root_falls_back_to_the_library(self):
        from logicxkit.logic import strip_path
        with mock.patch.dict(os.environ, {ENV: "/env/root"}):
            self.assertEqual(strip_path({}, {"strip": "Track/K.cst"}), Path("/env/root/Track/K.cst"))


class PrefsPlistTest(unittest.TestCase):
    def test_the_default_is_the_domains_own_file(self):
        from logicxkit.logic.services.prefs import DOMAIN, ENV_PLIST, PREFS_DIR, prefs_plist
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_PLIST, None)
            self.assertEqual(prefs_plist(), PREFS_DIR / f"{DOMAIN}.plist")
            self.assertEqual(prefs_plist("com.x.scratch"), PREFS_DIR / "com.x.scratch.plist")

    def test_the_override_replaces_logics_file_but_not_a_scratch_domains(self):
        from logicxkit.logic.services.prefs import ENV_PLIST, PREFS_DIR, prefs_plist
        with mock.patch.dict(os.environ, {ENV_PLIST: "/tmp/copy.plist"}):
            self.assertEqual(prefs_plist(), Path("/tmp/copy.plist"))
            self.assertEqual(prefs_plist("com.x.scratch"), PREFS_DIR / "com.x.scratch.plist")


class PresetNameTest(unittest.TestCase):
    BAD = ("../escaped", "sub/dir", "/abs/path", "..", ".", "", "back\\slash")

    def _spec(self, tmp: Path, name: str) -> dict:
        return {"output_dir": str(tmp / "out"),
                "presets": {name: {"eq": {"peak1": {"freq": 100, "gain": 3.0, "q": 1.0}}}}}

    def test_a_strip_spec_refuses_a_name_that_is_not_a_plain_file_name(self):
        import json
        import tempfile
        from logicxkit.logic.services.spec import load_spec
        for name in self.BAD:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                spec = Path(tmp) / "spec.json"
                spec.write_text(json.dumps(self._spec(Path(tmp), name)))
                with self.assertRaisesRegex(ValueError, "plain file name"):
                    load_spec(spec)

    def test_a_settings_spec_refuses_one_too(self):
        from logicxkit.logic.services.pst import plan_psts
        for name in self.BAD:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "plain file name"):
                plan_psts(self._spec(Path("/tmp/logicxkit-never-written"), name))

    def test_an_ordinary_name_still_plans(self):
        from logicxkit.logic.services.pst import plan_psts
        ((name, dest, _values),) = plan_psts(self._spec(Path("/tmp/x"), "Kick - Tight 2"))
        self.assertEqual(dest.name, "Kick - Tight 2.pst")


if __name__ == "__main__":
    unittest.main()
