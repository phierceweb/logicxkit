"""`logic build` write path: each .cst lands exactly the build_strip bytes (hermetic).

A spec's relative `output_dir` resolves into Logic's own strip library, so the overwrite guard
and the exit code are part of the contract, not conveniences.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from _fixtures import block as _block
from logicxkit.logic import build_strip
from logicxkit.logic.cli import main

_EQ = {"peak1": {"freq": 100, "gain": 3.0, "q": 1.0}}
_COMP = {"circuit": "StudioFET", "threshold": -20, "ratio": 3, "attack": 15, "release": 75}




def _template() -> bytes:
    # 300-byte gap keeps the Compressor block outside identify_plugin's ChanEQ name window
    return _block("ChanEQ", 33) + b"\x00" * 300 + _block("Compressor", 14)


class _BuildCase(unittest.TestCase):
    """Spec fixture + the CLI call, shared by the write and guard cases."""

    def _spec(self, d: str, presets: dict, *, out_sub: str = "out") -> tuple[str, Path, bytes]:
        root = Path(d)
        tpl = root / "template.cst"
        tpl.write_bytes(_template())
        out_dir = root / out_sub
        spec_path = root / "spec.json"
        spec_path.write_text(json.dumps(
            {"template": str(tpl), "output_dir": str(out_dir), "presets": presets}))
        return str(spec_path), out_dir, tpl.read_bytes()

    def _build(self, spec_path: str, *flags: str, rc: int = 0) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["build", spec_path, *flags]), rc)
        return buf.getvalue()


class BuildWriteTest(_BuildCase):
    def test_writes_exact_build_strip_bytes(self):
        presets = {"Kick In": {"eq": _EQ, "comp": _COMP}, "Passthrough": {}}
        with tempfile.TemporaryDirectory() as d:
            spec_path, out_dir, tpl_bytes = self._spec(d, presets)
            out = self._build(spec_path)
            for name, preset in presets.items():
                with self.subTest(preset=name):
                    self.assertIn(f"OK  {name}.cst", out)
                    self.assertEqual((out_dir / f"{name}.cst").read_bytes(),
                                     build_strip(tpl_bytes, preset))
            self.assertEqual((out_dir / "Passthrough.cst").read_bytes(), tpl_bytes)

    def test_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            spec_path, out_dir, _ = self._spec(d, {"A": {"eq": _EQ}, "B": {"comp": _COMP}})
            self._build(spec_path)
            self.assertEqual(sorted(p.name for p in out_dir.iterdir()), ["A.cst", "B.cst"])

    def test_creates_missing_output_dir(self):
        """The atomic write needs an existing parent — cmd_build must make one."""
        with tempfile.TemporaryDirectory() as d:
            spec_path, out_dir, tpl_bytes = self._spec(d, {"A": {"eq": _EQ}},
                                                       out_sub="fresh/nested/out")
            self.assertFalse(out_dir.exists())
            self._build(spec_path)
            self.assertEqual((out_dir / "A.cst").read_bytes(),
                             build_strip(tpl_bytes, {"eq": _EQ}))

    def test_failed_preset_keeps_prior_file_and_drops_no_temp_file(self):
        """Even told to overwrite, a preset that cannot be assembled leaves the old file."""
        with tempfile.TemporaryDirectory() as d:
            eq_only = Path(d) / "eq_only.cst"
            eq_only.write_bytes(_block("ChanEQ", 33))
            spec_path, out_dir, _ = self._spec(
                d, {"A": {"comp": _COMP, "template": str(eq_only)}})
            out_dir.mkdir(parents=True)
            (out_dir / "A.cst").write_bytes(b"PRIOR-GOOD")
            out = self._build(spec_path, "--overwrite", rc=1)
            self.assertIn("!!  A", out)
            self.assertEqual((out_dir / "A.cst").read_bytes(), b"PRIOR-GOOD")
            self.assertEqual([p.name for p in out_dir.iterdir()], ["A.cst"])

    def test_a_failed_preset_is_a_non_zero_exit(self):
        with tempfile.TemporaryDirectory() as d:
            eq_only = Path(d) / "eq_only.cst"
            eq_only.write_bytes(_block("ChanEQ", 33))
            spec_path, _, _ = self._spec(d, {"A": {"comp": _COMP, "template": str(eq_only)}})
            out = self._build(spec_path, rc=1)
            self.assertIn("0 written, 0 skipped, 1 failed", out)


class OverwriteGuardTest(_BuildCase):
    """A relative output_dir is Logic's live library; an existing strip is not collateral."""

    def test_an_existing_strip_is_kept_and_the_run_still_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            spec_path, out_dir, _ = self._spec(d, {"A": {"eq": _EQ}, "B": {"comp": _COMP}})
            out_dir.mkdir(parents=True)
            (out_dir / "A.cst").write_bytes(b"USER-STRIP")
            out = self._build(spec_path)
            self.assertIn("--  A.cst exists", out)
            self.assertIn("1 written, 1 skipped, 0 failed", out)
            self.assertEqual((out_dir / "A.cst").read_bytes(), b"USER-STRIP")
            self.assertTrue((out_dir / "B.cst").exists())

    def test_overwrite_replaces_it(self):
        with tempfile.TemporaryDirectory() as d:
            spec_path, out_dir, tpl_bytes = self._spec(d, {"A": {"eq": _EQ}})
            out_dir.mkdir(parents=True)
            (out_dir / "A.cst").write_bytes(b"USER-STRIP")
            out = self._build(spec_path, "--overwrite")
            self.assertIn("OK  A.cst", out)
            self.assertEqual((out_dir / "A.cst").read_bytes(), build_strip(tpl_bytes, {"eq": _EQ}))

    def test_a_relative_output_dir_resolves_into_the_strip_library(self):
        """The reason the guard exists: nothing in the spec has to name Logic's library."""
        from logicxkit.logic.services.library import strip_library
        from logicxkit.logic.services.spec import load_spec
        with tempfile.TemporaryDirectory() as d:
            spec_path = Path(d) / "rel.json"
            spec_path.write_text(json.dumps(
                {"output_dir": "Track/Somewhere", "presets": {}}))
            self.assertEqual(load_spec(spec_path)["_output_dir"],
                             strip_library() / "Track/Somewhere")


if __name__ == "__main__":
    unittest.main()
