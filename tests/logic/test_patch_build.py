"""`build_patch` and `logic patch --build`: a bundle only from a real strip, assembled beside its
destination so a refusal or a failure leaves the output directory as it was."""

import io
import plistlib
import shutil
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from _records import proj, rec
from test_patch import cst

from logicxkit import cli
from logicxkit.logic import _patch_cmd
from logicxkit.logic.services.mixer.patch import ReplacedBundleLeft, build_patch, read_patch

_real_rmtree = shutil.rmtree


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


def refuse_old(path, *args, **kwargs):
    if Path(path).name.endswith(".patch-old"):
        raise PermissionError("operation not permitted")
    return _real_rmtree(path, *args, **kwargs)


class BuildPatchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.strip = self.tmp / "Kick.cst"
        self.strip.write_bytes(cst("Kick"))
        self.out = self.tmp / "patches"
        self.out.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_built_patch_is_the_saved_shape(self):
        out = build_patch(self.strip, name="Kick Chain", out_dir=self.tmp / "new")
        self.assertEqual(out, self.tmp / "new" / "Kick Chain.patch")
        self.assertEqual((out / "#Root.cst").read_bytes(), self.strip.read_bytes())
        pl = plistlib.loads((out / "data.plist").read_bytes())
        (ch,) = pl["channels"]
        self.assertEqual((pl["VersionPatches"], ch["Channel_name"], ch["Filename"], ch["Root"]), (40014, "Kick Chain", "#Root.cst", True))
        self.assertEqual(len(ch["UUID"]), 36)
        p = read_patch(out)
        self.assertEqual(([c.name for c in p.channels], p.channels[0].plugins), (["Kick Chain"], ["Channel EQ"]))
        self.assertEqual(sorted(x.name for x in out.parent.iterdir()), ["Kick Chain.patch"])

    def test_an_existing_patch_is_kept_unless_overwrite(self):
        build_patch(self.strip, name="Kick Chain", out_dir=self.out)
        with self.assertRaisesRegex(FileExistsError, "overwrite"):
            build_patch(self.strip, name="Kick Chain", out_dir=self.out)
        build_patch(self.strip, name="Kick Chain", out_dir=self.out, overwrite=True)

    def test_a_missing_strip_is_refused_before_anything_is_made(self):
        before = snapshot(self.out)
        for missing in (self.tmp / "missing.cst", self.tmp):
            with self.assertRaisesRegex(ValueError, "not a file"):
                build_patch(missing, name="P", out_dir=self.out)
        with self.assertRaises(ValueError):
            build_patch(self.tmp / "missing.cst", name="P", out_dir=self.tmp / "never")
        self.assertEqual(snapshot(self.out), before)
        self.assertFalse((self.tmp / "never").exists())

    def test_a_file_that_is_not_a_strip_is_refused_and_nothing_is_left(self):
        real = cst("Kick")
        bad = {"text": b"not a cst\n", "empty": b"", "truncated": real[:-10], "no terminator": real[:-50],
               "half": real[:len(real) // 2], "trailing junk": real + b"junk", "two terminators": real[-50:] * 2,
               "project data": proj(rec(b"OCuA", 3, 0xFFFF, bytes(200)), rec(b"UCuA", 3, 2, bytes(64)))}
        for label, data in bad.items():
            with self.subTest(label):
                self.strip.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "not a Logic channel strip"):
                    build_patch(self.strip, name="P", out_dir=self.out)
                self.assertEqual(snapshot(self.out), {})

    def test_zero_padding_after_the_terminator_is_accepted(self):
        self.strip.write_bytes(cst("Kick") + b"\0")
        self.assertTrue(build_patch(self.strip, name="P", out_dir=self.out).is_dir())

    def test_a_name_that_is_not_a_plain_file_name_is_refused(self):
        for name in ("", ".", "..", "a/b", "a\\b"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "plain file name"):
                build_patch(self.strip, name=name, out_dir=self.out)
        self.assertEqual(snapshot(self.tmp / "patches"), {})

    def test_overwrite_with_a_bad_strip_keeps_the_old_bundle_byte_for_byte(self):
        build_patch(self.strip, name="P", out_dir=self.out)
        before = snapshot(self.out)
        self.strip.write_bytes(b"not a cst\n")
        with self.assertRaises(ValueError):
            build_patch(self.strip, name="P", out_dir=self.out, overwrite=True)
        self.assertEqual(snapshot(self.out), before)

    def test_overwrite_with_a_good_strip_replaces_the_bundle(self):
        old = build_patch(self.strip, name="P", out_dir=self.out)
        old_uuid = plistlib.loads((old / "data.plist").read_bytes())["channels"][0]["UUID"]
        (old / "stale").write_bytes(b"x")
        fresh = cst("Snare")[:-50] + rec(b"UCuA", 0, 9, bytes(8)) + cst("Snare")[-50:]
        self.strip.write_bytes(fresh)
        new = build_patch(self.strip, name="P", out_dir=self.out, overwrite=True)
        self.assertEqual(sorted(p.name for p in new.iterdir()), ["#Root.cst", "data.plist"])
        self.assertEqual((new / "#Root.cst").read_bytes(), fresh)
        self.assertNotEqual(plistlib.loads((new / "data.plist").read_bytes())["channels"][0]["UUID"], old_uuid)
        self.assertEqual([p.name for p in self.out.iterdir()], ["P.patch"])

    def test_a_failed_write_leaves_no_bundle_and_no_temporary_directory(self):
        with mock.patch("logicxkit.logic.services.mixer.patch.plistlib.dumps", side_effect=OSError("disk full")), \
             self.assertRaisesRegex(OSError, "disk full"):
            build_patch(self.strip, name="P", out_dir=self.out)
        self.assertEqual(snapshot(self.out), {})

    def test_a_failed_move_restores_the_old_bundle(self):
        build_patch(self.strip, name="P", out_dir=self.out)
        before = snapshot(self.out)
        real_rename, calls = Path.rename, []

        def rename(src, dst):
            calls.append((src, dst))
            if len(calls) == 2:
                raise OSError("move failed")
            return real_rename(src, dst)

        with mock.patch.object(Path, "rename", rename), self.assertRaisesRegex(OSError, "move failed"):
            build_patch(self.strip, name="P", out_dir=self.out, overwrite=True)
        self.assertEqual(snapshot(self.out), before)

    def test_a_replaced_bundle_that_cannot_be_removed_is_reported(self):
        build_patch(self.strip, name="P", out_dir=self.out)
        self.strip.write_bytes(cst("Snare"))
        with mock.patch("logicxkit.logic.services.mixer.patch.shutil.rmtree", side_effect=refuse_old), \
                self.assertRaises(ReplacedBundleLeft) as caught:
            build_patch(self.strip, name="P", out_dir=self.out, overwrite=True)
        (left,) = [p for p in self.out.iterdir() if p.name.endswith(".patch-old")]
        self.assertEqual((caught.exception.dest, caught.exception.leftover), (self.out / "P.patch", left))
        self.assertIn(str(left), str(caught.exception))
        self.assertEqual((self.out / "P.patch" / "#Root.cst").read_bytes(), cst("Snare"))


class BuildCliTest(unittest.TestCase):
    def run_cli(self, *argv) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["logic", "patch", *argv])
        return rc, buf.getvalue()

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp, out = Path(tmp), Path(tmp, "out")
            out.mkdir()
            good, bad = tmp / "good.cst", tmp / "bad.cst"
            good.write_bytes(cst("Kick"))
            bad.write_text("not a cst\n")
            self.assertEqual(self.run_cli("--build", str(bad), "--name", "P", "--out", str(out))[0], 1)
            self.assertEqual(self.run_cli("--build", str(tmp / "missing.cst"), "--name", "P", "--out", str(out))[0], 1)
            self.assertEqual(snapshot(out), {})
            rc, text = self.run_cli("--build", str(good), "--name", "P", "--out", str(out))
            self.assertEqual((rc, "Channel EQ" in text), (0, True))
            self.assertEqual(self.run_cli("--build", str(good), "--name", "P", "--out", str(out))[0], 1)
            self.assertEqual(self.run_cli("--build", str(good), "--name", "P", "--out", str(out), "--overwrite")[0], 0)

    def test_a_leftover_replaced_bundle_exits_1_naming_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            good, out = Path(tmp, "good.cst"), Path(tmp, "out")
            good.write_bytes(cst("Kick"))
            self.assertEqual(self.run_cli("--build", str(good), "--name", "P", "--out", str(out))[0], 0)
            with mock.patch("logicxkit.logic.services.mixer.patch.shutil.rmtree", side_effect=refuse_old):
                rc, text = self.run_cli("--build", str(good), "--name", "P", "--out", str(out), "--overwrite")
            (left,) = [p for p in out.iterdir() if p.name.endswith(".patch-old")]
            self.assertEqual((rc, str(left) in text, "is built" in text), (1, True, True))

    def test_a_bundle_that_does_not_read_back_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp, "good.cst")
            good.write_bytes(cst("Kick"))
            for exc in (ValueError("unreadable"), OSError("gone")):
                with self.subTest(exc=exc), mock.patch.object(_patch_cmd, "read_patch", side_effect=exc):
                    args = Namespace(build=str(good), name="P", out=str(Path(tmp, "out")), install=False, overwrite=True)
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        rc = _patch_cmd.cmd_patch(args)
                    self.assertEqual((rc, str(exc) in buf.getvalue()), (1, True))


if __name__ == "__main__":
    unittest.main()
