"""A cached binary that cannot run is dropped and the script run JIT; a cache or binary that is
not the user's own alone is never run; a hung or failed compile is remembered or named."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401  — puts logicxkit on the path

from logicxkit.utils import swiftrun
from logicxkit.utils.swiftrun import run_swift

HELLO = 'print(CommandLine.arguments.dropFirst().joined(separator: " "))\n'


class CachedBinaryFailureTest(unittest.TestCase):
    def setUp(self):
        swiftrun._toolchain.cache_clear()
        self.addCleanup(swiftrun._toolchain.cache_clear)
        swiftrun._HUNG.clear()
        swiftrun._DROPPED.clear()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cache = self.root / "cache"
        self.script = self.root / "hello.swift"
        self.script.write_text(HELLO)
        patches = [mock.patch.object(swiftrun, "cache_dir", return_value=self.cache),
                   mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_a_binary_that_cannot_run_is_dropped_and_the_script_runs_jit(self):
        self.cache.mkdir(mode=0o700)
        version = "Swift 6\n"
        import hashlib
        digest = hashlib.sha256(self.script.read_bytes() + version.encode()).hexdigest()[:16]
        bad = self.cache / f"hello-{digest}"
        bad.write_bytes(b"garbage")
        bad.chmod(0o700)

        def fake_run(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, version, "")
            if cmd[0] == str(bad):
                raise OSError(8, "Exec format error")
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")
        with mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            self.assertEqual(run_swift(self.script, ["a"], 5), (0, "jit\n", ""))
        self.assertFalse(bad.exists())

    def test_a_binary_killed_at_load_is_dropped_and_the_script_runs_jit(self):
        """A damaged or truncated Mach-O execs, and the kernel kills it at once with no output."""
        self.cache.mkdir(mode=0o700)
        version = "Swift 6\n"
        import hashlib
        digest = hashlib.sha256(self.script.read_bytes() + version.encode()).hexdigest()[:16]
        bad = self.cache / f"hello-{digest}"
        bad.write_bytes(b"truncated")
        bad.chmod(0o700)

        def fake_run(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, version, "")
            if cmd[0] == str(bad):
                return swiftrun.subprocess.CompletedProcess(cmd, -9, "", "")
            ran.append(cmd[0])
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")
        ran = []
        with mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            self.assertEqual(run_swift(self.script, ["a"], 5), (0, "jit\n", ""))
            self.assertFalse(bad.exists())
            self.assertEqual(run_swift(self.script, ["a"], 5), (0, "jit\n", ""))
        self.assertEqual(ran, ["/usr/bin/swift"] * 2)              # not rebuilt for the rest of the process

    def test_without_swift_a_binary_killed_at_load_fails_once_and_is_not_rebuilt_this_process(self):
        import hashlib
        self.cache.mkdir(mode=0o700)
        bad = self.cache / f"hello-{hashlib.sha256(self.script.read_bytes() + b'Swift 6\n').hexdigest()[:16]}"
        bad.write_bytes(b"truncated")
        bad.chmod(0o700)
        compiles = []

        def fake_run(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 6\n", "")
            if cmd[1:2] == ["-O"]:
                compiles.append(cmd)
            return swiftrun.subprocess.CompletedProcess(cmd, -9, "", "")
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: None if n == "swift" else f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(swiftrun.SwiftRunError, "killed at load.*retry in a new process"):
                run_swift(self.script, ["a"], 5)
            with self.assertRaisesRegex(swiftrun.SwiftRunError, "hello.swift: its binary could not run.*retry in a new process"):
                run_swift(self.script, ["a"], 5)
        self.assertEqual(compiles, [])

    def test_a_dropped_binary_of_another_script_sharing_the_stem_prefix_is_not_blamed(self):
        with mock.patch.object(swiftrun, "_DROPPED", {"hello-world-0123456789abcdef"}), \
             mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: None if n == "swift" else f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun, "compiled", return_value=(None, None)):
            with self.assertRaisesRegex(swiftrun.SwiftRunError, "hello.swift: no `swift` to run it and no binary"):
                run_swift(self.script, ["a"], 5)

    def _killed(self, out: str, err: str, seconds: float) -> tuple[tuple, bool]:
        """A cached binary that ends by SIGKILL with ``out``/``err`` after ``seconds``: (result, kept)."""
        import hashlib
        self.cache.mkdir(mode=0o700, exist_ok=True)
        good = self.cache / f"hello-{hashlib.sha256(self.script.read_bytes() + b'Swift 6\n').hexdigest()[:16]}"
        good.write_bytes(b"binary")
        good.chmod(0o700)

        def fake_run(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 6\n", "")
            if cmd[0] == str(good):
                return swiftrun.subprocess.CompletedProcess(cmd, -9, out, err)
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")
        clock = iter([0.0, seconds])
        with mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(swiftrun.time, "monotonic", side_effect=lambda: next(clock)):
            return run_swift(self.script, ["a"], 5), good.exists()

    def test_a_binary_killed_after_it_ran_or_said_something_is_kept(self):
        self.assertEqual(self._killed("", "", 5.0), ((-9, "", ""), True))                 # killed mid-run, not at load
        self.assertEqual(self._killed("partial\n", "", 0.1), ((-9, "partial\n", ""), True))

    def test_a_jit_run_killed_returns_its_code(self):
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: None if n == "swiftc" else f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun.subprocess, "run", return_value=swiftrun.subprocess.CompletedProcess([], -9, "", "")):
            self.assertEqual(run_swift(self.script, ["a"], 5), (-9, "", ""))

    def test_a_hung_compile_is_remembered_and_a_failed_one_names_the_script(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 6\n", "")
            if cmd[1:2] == ["-O"]:
                raise swiftrun.subprocess.TimeoutExpired(cmd, 300)
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")
        with mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            for _ in range(2):
                self.assertEqual(run_swift(self.script, ["a"], 5), (0, "jit\n", ""))
        self.assertEqual(sum(c[1:2] == ["-O"] for c in calls), 1)

        def failing(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 7\n", "")
            return swiftrun.subprocess.CompletedProcess(cmd, 1, "", "error: no such module")
        swiftrun._toolchain.cache_clear()
        with mock.patch.object(swiftrun.subprocess, "run", side_effect=failing):
            code, _out, err = run_swift(self.script, ["a"], 5)
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("hello.swift: swiftc failed"), err)

    def test_without_swift_a_hung_compile_is_named_as_one(self):
        def fake_run(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 6\n", "")
            raise swiftrun.subprocess.TimeoutExpired(cmd, 300)
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: None if n == "swift" else f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            for _ in range(2):
                with self.assertRaisesRegex(swiftrun.SwiftRunError, "hello.swift: its compile did not finish in 300 s"):
                    run_swift(self.script, ["a"], 5)


class CacheOwnershipTest(unittest.TestCase):
    """Nothing is run from a cache others may write; the user's own binary with loose bits is rebuilt
    0o700; another user's is left alone; without `swift` the binary still runs."""

    def setUp(self):
        swiftrun._toolchain.cache_clear()
        self.addCleanup(swiftrun._toolchain.cache_clear)
        swiftrun._HUNG.clear()
        swiftrun._DROPPED.clear()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cache = self.root / "cache"
        self.script = self.root / "hello.swift"
        self.script.write_text(HELLO)
        import hashlib
        self.binary = self.cache / f"hello-{hashlib.sha256(self.script.read_bytes() + b'Swift 6\n').hexdigest()[:16]}"
        patch = mock.patch.object(swiftrun, "cache_dir", return_value=self.cache)
        patch.start()
        self.addCleanup(patch.stop)

    def fake_run(self, cmd, **kw):
        if cmd[1:2] == ["--version"]:
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 6\n", "")
        if cmd[1:2] == ["-O"]:
            Path(cmd[-1]).write_bytes(b"built")
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == str(self.binary):
            return swiftrun.subprocess.CompletedProcess(cmd, 0, "ran\n", "")
        return swiftrun.subprocess.CompletedProcess(cmd, 0, "jit\n", "")

    def run_with(self, which):
        with mock.patch.object(swiftrun.shutil, "which", side_effect=which), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=self.fake_run):
            return run_swift(self.script, ["a"], 5)

    def test_a_link_at_the_binarys_path_is_replaced_by_a_build(self):
        self.cache.mkdir(mode=0o700)
        self.binary.symlink_to("/bin/echo")
        self.assertEqual(self.run_with(lambda n: f"/usr/bin/{n}"), (0, "ran\n", ""))
        self.assertFalse(self.binary.is_symlink())
        self.assertTrue(Path("/bin/echo").exists())

    def test_a_cache_others_may_write_runs_nothing_from_it(self):
        self.cache.mkdir()
        self.cache.chmod(0o777)
        self.binary.write_bytes(b"planted")
        self.binary.chmod(0o700)
        self.assertEqual(self.run_with(lambda n: f"/usr/bin/{n}"), (0, "jit\n", ""))
        self.assertTrue(self.binary.exists())

    def test_an_own_binary_with_loose_bits_is_rebuilt_0o700(self):
        self.cache.mkdir(mode=0o700)
        self.binary.write_bytes(b"loose")
        self.binary.chmod(0o777)
        self.assertEqual(self.run_with(lambda n: f"/usr/bin/{n}"), (0, "ran\n", ""))
        self.assertEqual(self.binary.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.binary.read_bytes(), b"built")

    def test_another_users_binary_in_an_own_cache_is_left_alone(self):
        """The directory passes as the user's own; the binary inside it is someone else's."""
        self.cache.mkdir(mode=0o700)
        self.binary.write_bytes(b"theirs")
        self.binary.chmod(0o700)
        other = swiftrun.os.getuid() + 1                      # the directory is held as the user's own; the uid check sees another user
        with mock.patch.object(swiftrun, "_own", side_effect=lambda p: p == self.cache), \
             mock.patch.object(swiftrun.os, "getuid", return_value=other):
            self.assertEqual(self.run_with(lambda n: f"/usr/bin/{n}"), (0, "jit\n", ""))
        self.assertEqual(self.binary.read_bytes(), b"theirs")                     # not dropped, not rebuilt

    def test_a_broken_binary_is_dropped_even_with_no_swift(self):
        self.cache.mkdir(mode=0o700)
        self.binary.write_bytes(b"garbage")
        self.binary.chmod(0o700)

        def fake_run(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 6\n", "")
            raise OSError(8, "Exec format error")
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: "/usr/bin/swiftc" if n == "swiftc" else None), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(swiftrun.SwiftRunError, "the binary is dropped"):
                run_swift(self.script, ["a"], 5)
        self.assertFalse(self.binary.exists())
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: "/usr/bin/swiftc" if n == "swiftc" else None):
            self.assertTrue(swiftrun.swift_available())

    def test_a_cache_reached_through_a_link_runs_nothing(self):
        real = self.root / "real"
        real.mkdir(mode=0o700)
        self.cache.symlink_to(real)
        self.assertEqual(self.run_with(lambda n: f"/usr/bin/{n}"), (0, "jit\n", ""))
        self.assertEqual(list(real.iterdir()), [])

    def test_a_directory_at_the_binarys_path_is_left_alone_and_the_script_runs_jit(self):
        self.cache.mkdir(mode=0o700)
        self.binary.mkdir(mode=0o700)
        self.assertEqual(self.run_with(lambda n: f"/usr/bin/{n}"), (0, "jit\n", ""))
        self.assertTrue(self.binary.is_dir())

    def test_a_binary_that_cannot_run_or_be_dropped_is_the_scripts_error(self):
        self.cache.mkdir(mode=0o700)
        self.binary.write_bytes(b"garbage")
        self.binary.chmod(0o700)

        def fake_run(cmd, **kw):
            if cmd[1:2] == ["--version"]:
                return swiftrun.subprocess.CompletedProcess(cmd, 0, "Swift 6\n", "")
            raise OSError(8, "Exec format error")
        with mock.patch.object(swiftrun.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"), \
             mock.patch.object(swiftrun.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(swiftrun.Path, "unlink", side_effect=OSError(13, "Permission denied")):
            with self.assertRaisesRegex(swiftrun.SwiftRunError, "could not be dropped"):
                run_swift(self.script, ["a"], 5)

    def test_without_swift_the_binary_still_runs(self):
        self.assertEqual(self.run_with(lambda n: "/usr/bin/swiftc" if n == "swiftc" else None), (0, "ran\n", ""))
        with mock.patch.object(swiftrun.shutil, "which", return_value=None):
            with self.assertRaisesRegex(swiftrun.SwiftRunError, "toolchain not available"):
                run_swift(self.script, ["a"], 5)


if __name__ == "__main__":
    unittest.main()
