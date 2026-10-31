"""A Swift script is compiled once and its binary reused; an edit compiles anew, a compile error
comes back as the script's failure, and without `swiftc` or an answer from it the script runs JIT."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401  — puts logicxkit on the path

from logicxkit.utils import swiftrun
from logicxkit.utils.swiftrun import run_swift

HELLO = 'print(CommandLine.arguments.dropFirst().joined(separator: " "))\n'


@unittest.skipUnless(shutil.which("swiftc"), "no swift toolchain")
class SwiftCacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cache = self.root / "cache"
        patch = mock.patch.object(swiftrun, "cache_dir", return_value=self.cache)
        patch.start()
        self.addCleanup(patch.stop)
        self.script = self.root / "hello.swift"
        self.script.write_text(HELLO)

    def binaries(self) -> list[str]:
        return sorted(p.name for p in self.cache.iterdir() if p.is_file())

    def test_the_second_run_reuses_the_first_ones_binary(self):
        self.assertEqual(run_swift(self.script, ["a", "b"], 30), (0, "a b\n", ""))
        built = self.binaries()
        self.assertEqual(len(built), 1)
        with mock.patch.object(swiftrun.subprocess, "run", wraps=swiftrun.subprocess.run) as calls:
            self.assertEqual(run_swift(self.script, ["c"], 30), (0, "c\n", ""))
        self.assertEqual(calls.call_count, 1)                                     # the binary alone, no compile
        self.assertEqual(self.binaries(), built)
        import os
        import time
        os.utime(self.cache / built[0], (0, 0))
        run_swift(self.script, ["d"], 30)
        self.assertGreater((self.cache / built[0]).stat().st_mtime, time.time() - 60)    # its use, for another install's prune

    def test_an_edited_script_is_compiled_anew_and_a_build_unused_for_a_week_removed(self):
        import os
        import time
        run_swift(self.script, [], 30)
        old = self.binaries()
        self.script.write_text(HELLO.replace('" "', '"-"'))
        self.assertEqual(run_swift(self.script, ["a", "b"], 30), (0, "a-b\n", ""))
        self.assertEqual(len(self.binaries()), 2)                               # another install may still run it
        week = time.time() - swiftrun.UNUSED_FOR - 60
        os.utime(self.cache / old[0], (week, week))
        self.script.write_text(HELLO.replace('" "', '"+"'))
        run_swift(self.script, [], 30)
        self.assertNotIn(old[0], self.binaries())
        self.assertEqual(len(self.binaries()), 2)
        others = ["hello2-0123456789abcdef", "hello_x-0123456789abcdef", "hello-fedcba9876543210"]
        for name in others:
            (self.cache / name).write_bytes(b"other")
            (self.cache / name).chmod(0o700 if name != others[-1] else 0o777)        # the last a build, not the user's own alone
            os.utime(self.cache / name, (week, week))
        self.script.write_text(HELLO)
        run_swift(self.script, [], 30)
        self.assertEqual([b for b in self.binaries() if b in others], sorted(others))

    def test_a_killed_compiles_work_dir_is_removed_once_it_is_stale(self):
        import os
        import time
        self.cache.mkdir(mode=0o700)
        stale, running = self.cache / "tmpstale", self.cache / "tmprunning"
        for d in (stale, running):
            d.mkdir()
            (d / "hello").write_bytes(b"half")
        then = time.time() - swiftrun.COMPILE_TIMEOUT - 60
        os.utime(stale, (then, then))
        run_swift(self.script, [], 30)
        self.assertFalse(stale.exists())
        self.assertTrue(running.exists())

    def test_a_compile_error_is_the_scripts_failure_and_leaves_no_binary(self):
        self.script.write_text("let x: Int = \"no\"\n")
        code, _out, err = run_swift(self.script, [], 30)
        self.assertNotEqual(code, 0)
        self.assertIn("error", err)
        self.assertEqual(self.binaries(), [])

    def test_without_swiftc_the_script_runs_jit(self):
        which = shutil.which
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: None if n == "swiftc" else which(n)):
            self.assertEqual(run_swift(self.script, ["jit"], 60), (0, "jit\n", ""))
        self.assertFalse(self.cache.exists())


class ToolchainFailureTest(unittest.TestCase):
    """When the toolchain does not answer, the script runs JIT and the failure is remembered."""

    def setUp(self):
        swiftrun._toolchain.cache_clear()
        self.addCleanup(swiftrun._toolchain.cache_clear)

    def test_a_version_timeout_is_asked_once_and_the_run_goes_jit(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[1:2] == ["--version"]:
                raise swiftrun.subprocess.TimeoutExpired(cmd, kw.get("timeout", 60))
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun.Path, "exists", return_value=True), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            for _ in range(2):
                self.assertEqual(run_swift(Path("/x/hello.swift"), ["a"], 5), (0, "jit\n", ""))
        self.assertEqual(sum(c[1:2] == ["--version"] for c in calls), 1)
        self.assertEqual([c[0] for c in calls if c[1:2] != ["--version"]], ["/usr/bin/swift", "/usr/bin/swift"])

    def test_a_blank_version_answer_builds_nothing_and_the_run_goes_jit(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "  \n", "")
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "hello.swift"
        script.write_text(HELLO)
        with mock.patch.object(swiftrun, "cache_dir", return_value=Path(tmp.name) / "cache"), \
             mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            self.assertEqual(run_swift(script, ["a"], 5), (0, "jit\n", ""))
        self.assertEqual([c[0] for c in calls if c[1:2] != ["--version"]], ["/usr/bin/swift"])

    def test_a_failed_version_answer_builds_nothing_and_the_run_goes_jit(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 1, "Swift 6\n", "no toolchain selected")
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "hello.swift"
        script.write_text(HELLO)
        with mock.patch.object(swiftrun, "cache_dir", return_value=Path(tmp.name) / "cache"), \
             mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            self.assertEqual(run_swift(script, ["a"], 5), (0, "jit\n", ""))
        self.assertEqual([c[0] for c in calls if c[1:2] != ["--version"]], ["/usr/bin/swift"])

    def test_a_compile_timeout_falls_back_to_jit(self):
        def fake_run(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 6\n", "")
            if cmd[1:2] == ["-O"]:
                raise swiftrun.subprocess.TimeoutExpired(cmd, kw.get("timeout", 300))
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "hello.swift"
        script.write_text(HELLO)
        with mock.patch.object(swiftrun, "cache_dir", return_value=Path(tmp.name) / "cache"), \
             mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            self.assertEqual(run_swift(script, ["a"], 5), (0, "jit\n", ""))

    def test_a_run_timeout_is_the_scripts_error(self):
        def fake_run(cmd, **kw):
            raise swiftrun.subprocess.TimeoutExpired(cmd, kw.get("timeout", 5))
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: "/usr/bin/swift" if n == "swift" else None), \
             mock.patch.object(swiftrun.Path, "exists", return_value=True), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(swiftrun.SwiftRunError, "no answer in 5 s"):
                run_swift(Path("/x/hello.swift"), ["a"], 5)


if __name__ == "__main__":
    unittest.main()
