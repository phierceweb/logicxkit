"""Fail the run if a test opens, lists or shells out to anything under `~/Music`.

Tests measure staged copies under `resources/`; a golden that reads Logic's live library
instead asserts whatever was last saved there. The mixing-console scene is the one exemption.

`open` covers every Python read (`Path.read_bytes`, `plistlib`, `shutil.copy`); `scandir` and
`listdir` cover a glob or rglob over a live directory; `subprocess` covers the tools this repo
shells out to (`cp`, `plutil`, `defaults`, `swift`). A bare `os.stat`/`exists()` is NOT
guarded — it is too hot to wrap, and a test that probes then reads is caught at the read.
"""

from __future__ import annotations

import builtins
import io
import os
import subprocess
from pathlib import Path

from _paths import SCENE

LIVE = Path.home() / "Music"

violations: list[str] = []


class LiveLibraryRead(Exception):
    """A test reached for a file under ~/Music instead of a staged copy."""


def offending(path) -> Path | None:
    """The live-library path a read is aiming at, or None when it is allowed."""
    if not isinstance(path, (str, os.PathLike)):
        return None                                  # a file descriptor, not a path
    p = Path(os.fspath(path))
    if not p.is_absolute():
        p = Path.cwd() / p
    return p if p.is_relative_to(LIVE) and p != SCENE else None


def _refuse(p: Path) -> None:
    violations.append(str(p))
    raise LiveLibraryRead(
        f"{p} is under {LIVE} — tests read staged copies under resources/ "
        "(see tests/_paths.py); only the X32 scene is exempt")


def install() -> None:
    """Patch the ways a test can reach a file, for the session."""
    real_open, real_scandir, real_listdir = io.open, os.scandir, os.listdir
    real_run, real_popen = subprocess.run, subprocess.Popen

    def wrap(real):
        def guarded(target, *args, **kwargs):
            p = offending(target)
            if p is not None:
                _refuse(p)
            return real(target, *args, **kwargs)
        return guarded

    def wrap_spawn(real):
        def guarded(args, *rest, **kwargs):
            for a in ([args] if isinstance(args, (str, os.PathLike)) else list(args or ())):
                p = offending(a)
                if p is not None:
                    _refuse(p)
            return real(args, *rest, **kwargs)
        return guarded

    io.open = builtins.open = wrap(real_open)
    os.scandir, os.listdir = wrap(real_scandir), wrap(real_listdir)
    subprocess.run, subprocess.Popen = wrap_spawn(real_run), wrap_spawn(real_popen)
