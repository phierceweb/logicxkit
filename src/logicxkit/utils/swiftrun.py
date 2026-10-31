"""Run a vendored Swift script, compiled once per script and toolchain and the binary reused.

Shared by the AU host (``auprobe.swift``, ``aulatency.swift``), WindowImage OCR (``vision_ocr.swift``)
and the audio envelopes (``bandrms.swift``).

The scripts live inside the package (``logicxkit/native/``) and are declared as package data,
so they resolve the same way from a checkout and from an installed wheel. The binaries live in
the temp directory under ``logicxkit-swift/``, named by the script and a hash of its text and the
compiler's version; without ``swiftc`` the script runs JIT through ``swift``.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

COMPILE_TIMEOUT = 300
LOAD_KILL = 1.0                         # a SIGKILL this soon is the loader's: a damaged binary
UNUSED_FOR = 7 * 24 * 3600              # a build no run has used this long is pruned
_HUNG: set[str] = set()                 # binaries whose compile did not finish this process
_DROPPED: set[str] = set()              # binaries dropped this process: a cause that persists would rebuild them every call


class SwiftRunError(RuntimeError):
    """The swift toolchain or the script itself is missing (callers wrap their own types)."""


def native_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "native"


def cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "logicxkit-swift"


def swift_available() -> bool:
    """A toolchain to run a script with: `swift` for a JIT run, or `swiftc` to build it."""
    return shutil.which("swift") is not None or shutil.which("swiftc") is not None


@functools.cache
def _toolchain(swiftc: str) -> str | None:
    """The compiler's version text, or None once it has failed to answer (asked once per process)."""
    try:
        r = subprocess.run([swiftc, "--version"], capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout.strip() else None


def _own(path: Path) -> bool:
    """The path itself, no link, belongs to this user and nobody else may write it (the cache sits
    under the temp dir)."""
    st = path.lstat()
    return not stat.S_ISLNK(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o022


def compiled(script: Path, swiftc: str) -> tuple[Path | None, subprocess.CompletedProcess | None]:
    """The script's binary, compiled on first use; (None, the failed compile) when swiftc refused
    it; (None, None) when the toolchain or the compile did not answer in time, for a JIT run."""
    version = _toolchain(swiftc)
    if version is None:
        return None, None
    digest = hashlib.sha256(script.read_bytes() + version.encode()).hexdigest()[:16]
    binary = cache_dir() / f"{script.stem}-{digest}"
    if binary.name in _HUNG or binary.name in _DROPPED:
        return None, None
    binary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not _own(binary.parent):                               # a cache others may write: nothing in it is run
        return None, None
    if binary.is_symlink():
        binary.unlink()                                       # a link in the user's own cache: removed unfollowed, rebuilt
    if binary.exists():
        if not binary.is_file():                                  # something else at the path: left alone, the script run JIT
            return None, None
        if _own(binary):
            os.utime(binary)                                  # its last use, so another install's prune keeps it
            return binary, None
        if binary.stat().st_uid != os.getuid():               # another user's: left alone, the script run JIT
            return None, None
        binary.unlink()                                       # the user's own with loose bits (a wide umask): rebuilt
    with tempfile.TemporaryDirectory(dir=binary.parent) as work:
        built = Path(work) / script.stem
        try:
            r = subprocess.run([swiftc, "-O", str(script), "-o", str(built)],
                               capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
        except subprocess.TimeoutExpired:
            _HUNG.add(binary.name)                            # the caller runs the script JIT, this time and after
            return None, None
        if r.returncode != 0:
            r.stderr = f"{script.name}: swiftc failed\n{r.stderr}"
            return None, r
        built.chmod(0o700)
        os.replace(built, binary)      # a rename: a concurrent run sees the whole binary or none
    _prune(binary, script.stem)
    return binary, None


def _prune(binary: Path, stem: str) -> None:
    """The script's other builds no run has used for `UNUSED_FOR` (another install or toolchain may
    still use a recent one) and the work dirs of compiles killed mid-run are removed."""
    older = re.compile(rf"{re.escape(stem)}-[0-9a-f]{{16}}")
    now = time.time()
    cutoff = now - COMPILE_TIMEOUT                              # a younger work dir may be a compile running now
    for p in binary.parent.iterdir():
        try:
            if p != binary and older.fullmatch(p.name) and _own(p) and p.stat().st_mtime < now - UNUSED_FOR:
                p.unlink()
            elif p.name.startswith("tmp") and p.is_dir() and not p.is_symlink() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p)
        except OSError:
            continue                                            # left for the next build to remove


def run_swift(script: Path, args: list[str], timeout: float) -> tuple[int, str, str]:
    swift, swiftc = shutil.which("swift"), shutil.which("swiftc")
    if swift is None and swiftc is None:
        raise SwiftRunError("swift toolchain not available")
    # Without this the toolchain reports the miss as a compiler error naming an internal path.
    if not Path(script).exists():
        raise SwiftRunError(f"swift script not installed: {script}")
    jit = [swift, str(script)] if swift else None
    command = jit
    if swiftc:
        try:
            binary, failed = compiled(Path(script), swiftc)
        except (subprocess.TimeoutExpired, OSError):          # the toolchain hangs or the cache cannot be written: JIT
            binary, failed = None, None
        if failed is not None:
            return failed.returncode, failed.stdout, failed.stderr
        if binary is not None:
            command = [str(binary)]
    if command is None:
        mine = re.compile(rf"{re.escape(Path(script).stem)}-[0-9a-f]{{16}}").fullmatch
        if any(mine(n) for n in _HUNG):
            raise SwiftRunError(f"{Path(script).name}: its compile did not finish in {COMPILE_TIMEOUT} s and there is "
                                "no `swift` to run it; install `swift`, or retry in a new process")
        if any(mine(n) for n in _DROPPED):
            raise SwiftRunError(f"{Path(script).name}: its binary could not run and there is no `swift` to run it; "
                                "install `swift`, or retry in a new process")
        raise SwiftRunError(f"{Path(script).name}: no `swift` to run it and no binary could be built; "
                            f"check what sits under {cache_dir()} or install `swift`")
    name = Path(script).name
    try:
        started = time.monotonic()
        r = subprocess.run([*command, *args], capture_output=True, text=True, timeout=timeout)
        if (command != jit and r.returncode == -signal.SIGKILL and not r.stdout and not r.stderr
                and time.monotonic() - started < LOAD_KILL):
            raise OSError(f"the binary was killed at load: {command[0]}")
    except subprocess.TimeoutExpired:
        raise SwiftRunError(f"{name}: no answer in {timeout:g} s") from None
    except OSError as e:
        if command == jit:
            raise SwiftRunError(f"{name}: {e}") from None
        try:
            Path(command[0]).unlink(missing_ok=True)          # a cached binary that cannot run: dropped, the script run JIT
        except OSError as e2:
            raise SwiftRunError(f"{name}: {e}; and the binary could not be dropped: {e2}") from None
        _DROPPED.add(Path(command[0]).name)
        if jit is None:
            raise SwiftRunError(f"{name}: {e}; the binary is dropped, retry in a new process to rebuild it") from None
        try:
            r = subprocess.run([*jit, *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise SwiftRunError(f"{name}: no answer in {timeout:g} s") from None
        except OSError as e2:
            raise SwiftRunError(f"{name}: {e2}") from None
    return r.returncode, r.stdout, r.stderr
