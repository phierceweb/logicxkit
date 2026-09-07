"""Run a vendored Swift script (JIT via ``swift``, no build step).

Shared by the AU host (``auprobe.swift``) and WindowImage OCR (``vision_ocr.swift``).

The scripts live inside the package (``logicxkit/native/``) and are declared as package data,
so they resolve the same way from a checkout and from an installed wheel.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class SwiftRunError(RuntimeError):
    """The swift toolchain or the script itself is missing (callers wrap their own types)."""


def native_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "native"


def swift_available() -> bool:
    return shutil.which("swift") is not None


def run_swift(script: Path, args: list[str], timeout: float) -> tuple[int, str, str]:
    swift = shutil.which("swift")
    if swift is None:
        raise SwiftRunError("swift toolchain not available")
    # Without this the toolchain reports the miss as a compiler error naming an internal path.
    if not Path(script).exists():
        raise SwiftRunError(f"swift script not installed: {script}")
    r = subprocess.run([swift, str(script), *args],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr
